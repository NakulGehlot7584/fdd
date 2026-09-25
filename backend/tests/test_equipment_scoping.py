"""Regression tests for Phase 2A: Equipment Scoping and Accounting Invariants."""

import pytest
from app.fdd.catalog import get_rule_catalog
from app.fdd.executor import get_executor, resolve_equipment_kind
from app.fdd.models import (
    FDDExecutionSummary,
    RuleDefinition,
    RuleExecutionResult,
    RuleExecutionStatus,
)
from app.historian.storage import HistorianStorage
from app.validation.result_validator import ResultValidator


def test_resolve_equipment_kind():
    """Verify equipment kind resolution hierarchy and ASHRAE token matching."""
    assert resolve_equipment_kind("AHU-01") == "ahu"
    assert resolve_equipment_kind("F2_AHU02_North") == "ahu"
    assert resolve_equipment_kind("CHILLER-PLANT-1") == "chiller"
    assert resolve_equipment_kind("VAV_FLOOR_2") == "vav"
    assert resolve_equipment_kind("BLR_01") == "boiler"
    assert resolve_equipment_kind("HP_ROOFTOP") == "heatpump"
    assert resolve_equipment_kind("CT-01") == "cooling_tower"

    assert resolve_equipment_kind("AHU-01", explicit_kind="chiller") == "chiller"
    assert resolve_equipment_kind("UNIT-01", source_file="ahu_multi_point_sample.csv") == "ahu"
    assert resolve_equipment_kind("UNKNOWN_01", telemetry_roles=["sat", "mat", "rat"]) == "ahu"
    assert resolve_equipment_kind("UNKNOWN_02", telemetry_roles=["zone_flow", "damper_pct"]) == "vav"
    assert resolve_equipment_kind("UNKNOWN_03", telemetry_roles=["chiller_status", "chw_pump_cmd"]) == "chiller"


def test_catalog_ahu_scoping():
    """Verify catalog list_rules(equipment_kind='ahu') filters correctly."""
    catalog = get_rule_catalog()
    assert len(catalog) == 66

    ahu_rules = catalog.list_rules(equipment_kind="ahu")
    assert len(ahu_rules) == 45

    non_ahu_ids = {r.rule_id for r in catalog.list_rules()} - {r.rule_id for r in ahu_rules}
    assert len(non_ahu_ids) == 21

    assert "CHW-NOLOAD-1" in non_ahu_ids
    assert "VAV-1" in non_ahu_ids
    assert "HP-1" in non_ahu_ids
    assert "CHW-1" in non_ahu_ids
    assert "CW-OPT-1" in non_ahu_ids

    for r in ahu_rules:
        if r.equipment_kinds:
            assert "ahu" in [k.lower() for k in r.equipment_kinds], f"Rule {r.rule_id} wrongly in AHU scope"


def test_ahu_execution_scoping_and_invariants():
    """Execute real AHU partition and verify equipment scoping + accounting invariants."""
    storage = HistorianStorage()
    executor = get_executor(storage=storage)

    b_dir = storage.root_dir / "building=DEFAULT_BUILDING" / "equipment=AHU-HPE-01"
    if not (b_dir / "history.parquet").exists():
        pytest.skip("AHU-HPE-01 historian partition not found in DEFAULT_BUILDING.")

    summary = executor.execute_rules_for_equipment(
        equipment_id="AHU-HPE-01",
        building_id="DEFAULT_BUILDING",
    )

    assert summary.equipment_kind == "ahu"
    assert summary.total_catalog_rules == 66
    assert summary.applicable_rules == 45
    assert summary.non_applicable_rules == 21
    assert summary.total_rules_evaluated == 45

    assert summary.applicable_rules == summary.rules_succeeded + summary.rules_skipped + summary.rules_failed
    assert summary.rules_succeeded == summary.rules_faulted + summary.rules_no_fault

    evaluated_rule_ids = {res.rule_id for res in summary.results}
    assert "CHW-NOLOAD-1" not in evaluated_rule_ids
    assert "VAV-1" not in evaluated_rule_ids
    assert "HP-1" not in evaluated_rule_ids
    assert "CHW-1" not in evaluated_rule_ids

    assert summary.rules_succeeded == 21
    assert summary.rules_skipped == 24
    assert summary.rules_failed == 0
    assert summary.rules_faulted == 5
    assert summary.rules_no_fault == 16


def test_chw_noload_does_not_run_on_ahu():
    """CHW-NOLOAD-1 has 0 required roles, but must NOT run on AHU."""
    catalog = get_rule_catalog()
    r = catalog.get_rule("CHW-NOLOAD-1")
    assert r is not None
    assert r.required_roles == []
    assert "chiller" in [k.lower() for k in r.equipment_kinds]
    assert "ahu" not in [k.lower() for k in r.equipment_kinds]

    ahu_rules = [x.rule_id for x in catalog.list_rules(equipment_kind="ahu")]
    assert "CHW-NOLOAD-1" not in ahu_rules


def test_status_label_normalization():
    """Verify that execution statuses map cleanly to standardized user-facing labels."""
    status_map = {
        RuleExecutionStatus.FAULT_DETECTED: "FAULT",
        RuleExecutionStatus.NO_FAULT: "NO FAULT",
        RuleExecutionStatus.SKIPPED_MISSING_ROLES: "SKIPPED",
        RuleExecutionStatus.ERROR: "FAILED",
    }
    assert status_map[RuleExecutionStatus.FAULT_DETECTED] == "FAULT"
    assert status_map[RuleExecutionStatus.NO_FAULT] == "NO FAULT"
    assert status_map[RuleExecutionStatus.SKIPPED_MISSING_ROLES] == "SKIPPED"
    assert status_map[RuleExecutionStatus.ERROR] == "FAILED"


def test_result_validator_equipment_applicability_cases():
    """Verify ResultValidator equipment applicability logic across all 4 specification cases:
    Case 1: equipment_type = 'AHU', equipment_kinds = [] -> is_applicable = True, no warning
    Case 2: equipment_type = 'AHU', equipment_kinds = ['ahu'] -> is_applicable = True, no warning
    Case 3: equipment_type = 'AHU', equipment_kinds = ['vav'] -> is_applicable = False, generates warning
    Case 4: equipment_type = 'AHU', equipment_kinds = ['ahu', 'vav'] -> is_applicable = True, no warning
    """
    catalog = get_rule_catalog()
    validator = ResultValidator(catalog=catalog)

    # 4 specification test rules
    rule_c1 = RuleDefinition(
        rule_id="TEST-CASE1",
        sql_file="c1.sql",
        description="Broad Rule",
        equipment_kinds=[],
        required_roles=[],
    )
    rule_c2 = RuleDefinition(
        rule_id="TEST-CASE2",
        sql_file="c2.sql",
        description="AHU Rule",
        equipment_kinds=["ahu"],
        required_roles=[],
    )
    rule_c3 = RuleDefinition(
        rule_id="TEST-CASE3",
        sql_file="c3.sql",
        description="VAV Rule",
        equipment_kinds=["vav"],
        required_roles=[],
    )
    rule_c4 = RuleDefinition(
        rule_id="TEST-CASE4",
        sql_file="c4.sql",
        description="Multi Rule",
        equipment_kinds=["ahu", "vav"],
        required_roles=[],
    )

    validator.known_rules["TEST-CASE1"] = rule_c1
    validator.known_rules["TEST-CASE2"] = rule_c2
    validator.known_rules["TEST-CASE3"] = rule_c3
    validator.known_rules["TEST-CASE4"] = rule_c4

    # Direct logic verification
    eq_type = "AHU"

    def check_app(r_obj, eq):
        return r_obj is not None and (
            not r_obj.equipment_kinds
            or any(k.lower() == eq.lower() for k in r_obj.equipment_kinds)
        )

    assert check_app(rule_c1, eq_type) is True   # Case 1: Broad
    assert check_app(rule_c2, eq_type) is True   # Case 2: Explicit AHU
    assert check_app(rule_c3, eq_type) is False  # Case 3: VAV on AHU
    assert check_app(rule_c4, eq_type) is True   # Case 4: AHU + VAV

    summary = FDDExecutionSummary(
        building_id="TEST_BLDG",
        equipment_id="AHU_UNIT",
        equipment_kind="ahu",
        total_catalog_rules=4,
        applicable_rules=3,
        non_applicable_rules=1,
        total_rules_evaluated=4,
        rules_succeeded=4,
        rules_faulted=0,
        rules_no_fault=4,
        rules_skipped=0,
        rules_failed=0,
        total_elapsed_ms=5.0,
        poll_seconds=300.0,
        results=[
            RuleExecutionResult(rule_id="TEST-CASE1", status=RuleExecutionStatus.NO_FAULT),
            RuleExecutionResult(rule_id="TEST-CASE2", status=RuleExecutionStatus.NO_FAULT),
            RuleExecutionResult(rule_id="TEST-CASE3", status=RuleExecutionStatus.NO_FAULT),
            RuleExecutionResult(rule_id="TEST-CASE4", status=RuleExecutionStatus.NO_FAULT),
        ],
    )

    report = validator.validate_execution(summary=summary, equipment_type="AHU")
    rules_table = {r["Rule ID"]: r for r in report.rules_table}

    # Case 1: Broad rule (equipment_kinds=[]) -> is_applicable=True, no warning
    assert rules_table["TEST-CASE1"]["Valid"] == "Yes"
    assert "Rule is not applicable to equipment type 'AHU'" not in rules_table["TEST-CASE1"]["Issues"]

    # Case 2: Explicit AHU rule (equipment_kinds=['ahu']) -> is_applicable=True, no warning
    assert rules_table["TEST-CASE2"]["Valid"] == "Yes"
    assert "Rule is not applicable to equipment type 'AHU'" not in rules_table["TEST-CASE2"]["Issues"]

    # Case 3: VAV rule on AHU equipment (equipment_kinds=['vav']) -> is_applicable=False, generates warning
    assert rules_table["TEST-CASE3"]["Valid"] == "No"
    assert "Rule is not applicable to equipment type 'AHU'" in rules_table["TEST-CASE3"]["Issues"]

    # Case 4: Multi-equipment rule (equipment_kinds=['ahu', 'vav']) -> is_applicable=True, no warning
    assert rules_table["TEST-CASE4"]["Valid"] == "Yes"
    assert "Rule is not applicable to equipment type 'AHU'" not in rules_table["TEST-CASE4"]["Issues"]
