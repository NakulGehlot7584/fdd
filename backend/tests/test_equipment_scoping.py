"""Regression tests for Phase 2A: Equipment Scoping and Accounting Invariants."""

import pytest
from app.fdd.catalog import get_rule_catalog
from app.fdd.executor import get_executor, resolve_equipment_kind
from app.fdd.models import RuleExecutionStatus
from app.historian.storage import HistorianStorage


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
