"""Comprehensive tests for Milestone 6: Open-FDD Rule Engine and Apache DataFusion integration."""

from __future__ import annotations

import datetime
from pathlib import Path
import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_dataset_manager
from app.datasets.manager import DatasetManager
from app.fdd.catalog import RuleCatalog, get_rule_catalog
from app.fdd.engine import DataFusionEngine, create_engine
from app.fdd.executor import (
    RuleExecutor,
    derive_window_params,
    get_executor,
    inject_optional_roles_cte,
)
from app.fdd.models import (
    RuleExecutionStatus,
    RuleFinding,
)
from app.historian.storage import HistorianStorage
from app.main import app


@pytest.fixture
def catalog() -> RuleCatalog:
    """Fixture providing the official Open-FDD RuleCatalog."""
    return get_rule_catalog()


@pytest.fixture
def engine() -> DataFusionEngine:
    """Fixture providing an isolated DataFusionEngine."""
    return create_engine()


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient fixture."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Rule Catalog Tests
# ---------------------------------------------------------------------------

def test_rule_catalog_loaded(catalog: RuleCatalog):
    """Test that all official Open-FDD rules are parsed and available."""
    assert len(catalog) >= 60
    assert len(catalog) == 66

    # Verify key rules
    ahu_satdev = catalog.get_rule("AHU-SATDEV")
    assert ahu_satdev is not None
    assert "sat" in ahu_satdev.required_roles
    assert "sat_sp" in ahu_satdev.required_roles
    assert "fan_runtime_hours.sql" in [r.sql_file for r in catalog.list_rules()]


def test_rule_catalog_alias_resolution(catalog: RuleCatalog):
    """Test alias resolution works case-insensitively."""
    rule_direct = catalog.get_rule("FC13-SAT-HIGH")
    rule_alias = catalog.get_rule("FC13")
    assert rule_direct is not None
    assert rule_alias is not None
    assert rule_direct.rule_id == rule_alias.rule_id == "FC13-SAT-HIGH"

    # Case insensitivity
    assert catalog.get_rule("ahu-satdev") is not None
    assert catalog.get_rule("ahu-satdev").rule_id == "AHU-SATDEV"


def test_rule_catalog_equipment_filter(catalog: RuleCatalog):
    """Test listing rules filtered by equipment kind."""
    ahu_rules = catalog.list_rules(equipment_kind="ahu")
    assert len(ahu_rules) > 0
    # Every returned rule should either specify ahu or be general
    for r in ahu_rules:
        if r.equipment_kinds:
            assert "ahu" in [k.lower() for k in r.equipment_kinds]


def test_rule_sql_retrieval(catalog: RuleCatalog):
    """Test retrieving SQL template text."""
    sql = catalog.get_rule_sql("AHU-SATDEV")
    assert "WITH" in sql.upper()
    assert "history" in sql.lower()
    assert "{{CONFIRM_ROWS}}" in sql or "{{POLL_SECONDS}}" in sql


# ---------------------------------------------------------------------------
# 2. DataFusion Engine Tests
# ---------------------------------------------------------------------------

def test_datafusion_arrow_table_registration(engine: DataFusionEngine):
    """Test registering an in-memory PyArrow table and querying via SQL."""
    timestamps = [
        datetime.datetime(2026, 1, 1, 0, 0),
        datetime.datetime(2026, 1, 1, 0, 5),
        datetime.datetime(2026, 1, 1, 0, 10),
    ]
    arrow_table = pa.table({
        "timestamp_utc": pa.array(timestamps),
        "equipment_id": pa.array(["AHU-01", "AHU-01", "AHU-01"]),
        "sat": pa.array([55.0, 56.5, 62.0]),
        "sat_sp": pa.array([55.0, 55.0, 55.0]),
    })

    engine.register_arrow_table("history", arrow_table)
    assert engine.table_exists("history")

    cols = engine.get_table_columns("history")
    assert "sat" in cols
    assert "sat_sp" in cols
    assert "equipment_id" in cols

    # Run SQL
    df = engine.query_to_polars("SELECT equipment_id, AVG(sat) as mean_sat FROM history GROUP BY equipment_id")
    assert len(df) == 1
    assert df["equipment_id"][0] == "AHU-01"
    assert round(df["mean_sat"][0], 2) == 57.83


# ---------------------------------------------------------------------------
# 3. Parameter Substitution and Window Derivation Tests
# ---------------------------------------------------------------------------

def test_derive_window_params():
    """Test rolling window parameter calculation from hourly bounds."""
    params = {
        "POLL_SECONDS": "300",
        "FLATLINE_HOURS": "1.0",
        "STALE_HOURS": "2.0",
    }
    derived = derive_window_params(params, poll_seconds=300.0)
    assert derived["FLATLINE_ROWS"] == "12"
    assert derived["FLATLINE_ROWS_PRECEDING"] == "11"
    assert derived["STALE_ROWS"] == "24"
    assert derived["STALE_ROWS_PRECEDING"] == "23"


def test_substitute_sql_params(catalog: RuleCatalog):
    """Test parameter substitution into SQL template."""
    executor = RuleExecutor(catalog=catalog)
    rule = catalog.get_rule("FAN-RUNTIME-HOURS")
    sql, params = executor.substitute_sql_params(rule.sql_template, rule, poll_seconds=900.0)
    assert "{{POLL_SECONDS}}" not in sql
    assert "900.0" in sql


# ---------------------------------------------------------------------------
# 4. Role Gating & Optional Role Injection Tests
# ---------------------------------------------------------------------------

def test_missing_required_roles_skipped(catalog: RuleCatalog, engine: DataFusionEngine):
    """Test that missing required roles results in SKIPPED_MISSING_ROLES status."""
    # Create table with only timestamp and equipment_id
    arrow_table = pa.table({
        "timestamp_utc": pa.array([datetime.datetime(2026, 1, 1, 0, 0)]),
        "equipment_id": pa.array(["AHU-01"]),
    })
    engine.register_arrow_table("history", arrow_table)

    executor = RuleExecutor(catalog=catalog, engine=engine)
    res = executor.execute_rule("AHU-SATDEV", table_name="history")
    assert res.status == RuleExecutionStatus.SKIPPED_MISSING_ROLES
    assert "sat" in res.missing_roles or "sat_sp" in res.missing_roles
    assert len(res.findings) == 0


def test_optional_roles_injection(catalog: RuleCatalog, engine: DataFusionEngine):
    """Test that missing optional roles are injected as NULL columns via CTE."""
    arrow_table = pa.table({
        "timestamp_utc": pa.array([
            datetime.datetime(2026, 1, 1, 0, 0),
            datetime.datetime(2026, 1, 1, 0, 5),
            datetime.datetime(2026, 1, 1, 0, 10),
        ]),
        "equipment_id": pa.array(["AHU-01", "AHU-01", "AHU-01"]),
        "zone_t": pa.array([71.0, 72.0, 71.5]),
        # Notice occ_mode is absent (optional role for VAV-1)
    })
    engine.register_arrow_table("history", arrow_table)

    executor = RuleExecutor(catalog=catalog, engine=engine)
    res = executor.execute_rule("VAV-1", table_name="history", poll_seconds=300.0)
    # Rule should run without error despite missing optional occ_mode role
    assert res.status in (RuleExecutionStatus.NO_FAULT, RuleExecutionStatus.FAULT_DETECTED)
    assert res.error is None
    assert res.row_count >= 1


# ---------------------------------------------------------------------------
# 5. Fault Detection & No-Fault Evaluation Tests
# ---------------------------------------------------------------------------

def test_rule_execution_detects_real_fault(catalog: RuleCatalog, engine: DataFusionEngine):
    """Test that SAT persistent high deviation is detected as a fault."""
    n_points = 20
    timestamps = [datetime.datetime(2026, 1, 1, 0, 0) + datetime.timedelta(minutes=5 * i) for i in range(n_points)]
    # Create persistent 10 degF SAT deviation above SP
    arrow_table = pa.table({
        "timestamp_utc": pa.array(timestamps),
        "equipment_id": pa.array(["AHU-FAULTY"] * n_points),
        "sat": pa.array([65.0] * n_points),
        "sat_sp": pa.array([55.0] * n_points),
        "fan_cmd": pa.array([100.0] * n_points),
        "fan_status": pa.array([1.0] * n_points),
    })
    engine.register_arrow_table("history", arrow_table)

    executor = RuleExecutor(catalog=catalog, engine=engine)
    res = executor.execute_rule("AHU-SATDEV", table_name="history", poll_seconds=300.0)
    assert res.status == RuleExecutionStatus.FAULT_DETECTED
    assert len(res.findings) > 0
    assert res.findings[0].fault_detected is True
    assert res.findings[0].fault_hours > 0.0


def test_rule_execution_healthy_equipment(catalog: RuleCatalog, engine: DataFusionEngine):
    """Test that equipment tracking setpoint within tolerance evaluates to NO_FAULT."""
    n_points = 20
    timestamps = [datetime.datetime(2026, 1, 1, 0, 0) + datetime.timedelta(minutes=5 * i) for i in range(n_points)]
    # SAT matches setpoint exactly
    arrow_table = pa.table({
        "timestamp_utc": pa.array(timestamps),
        "equipment_id": pa.array(["AHU-HEALTHY"] * n_points),
        "sat": pa.array([55.0] * n_points),
        "sat_sp": pa.array([55.0] * n_points),
        "fan_cmd": pa.array([100.0] * n_points),
        "fan_status": pa.array([1.0] * n_points),
    })
    engine.register_arrow_table("history", arrow_table)

    executor = RuleExecutor(catalog=catalog, engine=engine)
    res = executor.execute_rule("AHU-SATDEV", table_name="history", poll_seconds=300.0)
    assert res.status == RuleExecutionStatus.NO_FAULT
    if res.findings:
        assert res.findings[0].fault_detected is False


def test_raw_vs_confirmed_fault_semantics(catalog: RuleCatalog, engine: DataFusionEngine):
    """Test that confirmation strictly separates raw fault occurrences from confirmed faults.

    Streak of 5 raw faults with confirm_rows=3 must yield:
    - raw_fault_count = 5
    - sample_count = 3 (only samples 3, 4, 5 confirmed)
    - fault_hours = 3 * 300 / 3600 = 0.25h
    - episodes = 1 episode starting at timestamp index 2 (the 3rd sample)
    """
    n_points = 10
    poll_sec = 300.0
    timestamps = [datetime.datetime(2026, 1, 1, 0, 0) + datetime.timedelta(seconds=poll_sec * i) for i in range(n_points)]
    # 2 normal rows, 5 faulted rows (index 2..6), 3 normal rows
    sat_vals = [55.0, 55.0, 65.0, 65.0, 65.0, 65.0, 65.0, 55.0, 55.0, 55.0]

    arrow_table = pa.table({
        "timestamp_utc": pa.array(timestamps),
        "equipment_id": pa.array(["AHU-SEMANTIC"] * n_points),
        "sat": pa.array(sat_vals),
        "sat_sp": pa.array([55.0] * n_points),
        "fan_cmd": pa.array([100.0] * n_points),
        "fan_status": pa.array([1.0] * n_points),
    })
    engine.register_arrow_table("history", arrow_table)

    executor = RuleExecutor(catalog=catalog, engine=engine)
    res = executor.execute_rule(
        "AHU-SATDEV",
        table_name="history",
        poll_seconds=poll_sec,
        parameter_overrides={"confirm_rows": 3, "confirm_seconds": 900},
    )
    assert res.status == RuleExecutionStatus.FAULT_DETECTED
    assert len(res.findings) == 1
    finding = res.findings[0]
    assert finding.raw_fault_count == 5
    assert finding.sample_count == 3
    assert round(finding.fault_hours, 2) == 0.25
    assert len(finding.episodes) == 1
    ep = finding.episodes[0]
    assert ep.samples == 3
    # Index 2 was raw streak sample 1 (00:10:00), index 3 was streak sample 2 (00:15:00)
    # The first confirmed sample (streak_len >= 3) is index 4 (00:20:00)
    assert ep.start == timestamps[4].isoformat()
    assert ep.end == timestamps[6].isoformat() or ep.end == timestamps[6].strftime("%Y-%m-%dT%H:%M:%S")

    # Diagnostic record must also reflect raw and confirmed counts
    assert finding.detail is not None
    assert finding.detail.sample_count == 3
    assert finding.detail.raw_sample_count == 5
    assert round(finding.detail.total_fault_hours, 2) == 0.25


def test_transient_fault_below_persistence_threshold(catalog: RuleCatalog, engine: DataFusionEngine):
    """Test that transient raw fault shorter than persistence threshold is not confirmed.

    Streak of 2 raw faults with confirm_rows=3 must yield:
    - raw_fault_count = 2
    - sample_count = 0
    - fault_detected = False
    - status = NO_FAULT
    """
    n_points = 10
    poll_sec = 300.0
    timestamps = [datetime.datetime(2026, 1, 1, 0, 0) + datetime.timedelta(seconds=poll_sec * i) for i in range(n_points)]
    # 2 normal, 2 faulted, 6 normal
    sat_vals = [55.0, 55.0, 65.0, 65.0, 55.0, 55.0, 55.0, 55.0, 55.0, 55.0]

    arrow_table = pa.table({
        "timestamp_utc": pa.array(timestamps),
        "equipment_id": pa.array(["AHU-TRANSIENT"] * n_points),
        "sat": pa.array(sat_vals),
        "sat_sp": pa.array([55.0] * n_points),
        "fan_cmd": pa.array([100.0] * n_points),
        "fan_status": pa.array([1.0] * n_points),
    })
    engine.register_arrow_table("history", arrow_table)

    executor = RuleExecutor(catalog=catalog, engine=engine)
    res = executor.execute_rule(
        "AHU-SATDEV",
        table_name="history",
        poll_seconds=poll_sec,
        parameter_overrides={"confirm_rows": 3, "confirm_seconds": 900},
    )
    assert res.status == RuleExecutionStatus.NO_FAULT
    assert len(res.findings) == 1
    finding = res.findings[0]
    assert finding.fault_detected is False
    assert finding.raw_fault_count == 2
    assert finding.sample_count == 0
    assert finding.fault_hours is None or finding.fault_hours == 0.0
    assert len(finding.episodes) == 0


# ---------------------------------------------------------------------------
# 6. REST API Endpoint Tests
# ---------------------------------------------------------------------------

def test_api_list_rules(client: TestClient):
    """Test GET /api/fdd/rules returns the full official rule catalog."""
    resp = client.get("/api/fdd/rules")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 66
    rule_ids = [r["rule_id"] for r in data]
    assert "AHU-SATDEV" in rule_ids
    assert "FAN-RUNTIME-HOURS" in rule_ids


def test_api_get_rule_by_id(client: TestClient):
    """Test GET /api/fdd/rules/{rule_id} returns rule details and SQL."""
    resp = client.get("/api/fdd/rules/AHU-SATDEV")
    assert resp.status_code == 200
    data = resp.json()
    assert data["rule_id"] == "AHU-SATDEV"
    assert "sat" in data["required_roles"]
    assert "sql_template" in data
    assert data["sql_template"] is not None


def test_api_get_rule_not_found(client: TestClient):
    """Test GET /api/fdd/rules/{rule_id} returns 404 for unknown rule."""
    resp = client.get("/api/fdd/rules/NONEXISTENT_RULE_XYZ")
    assert resp.status_code == 404


def test_api_execute_equipment(client: TestClient):
    """Test POST /api/fdd/execute/{equipment_id} runs rules on historian partition."""
    resp = client.post(
        "/api/fdd/execute/AHU_01",
        params={"building_id": "BLDG_API_TEST"},
        json={"rule_ids": ["FAN-RUNTIME-HOURS", "AHU-SATDEV"]},
    )
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["equipment_id"] == "AHU_01"
    assert summary["building_id"] == "BLDG_API_TEST"
    assert summary["total_rules_evaluated"] == 2
    assert len(summary["results"]) == 2


def test_api_validation_report(client: TestClient):
    """Test GET /api/fdd/validation-report/{equipment_id} generates execution and evidence audit."""
    resp = client.get(
        "/api/fdd/validation-report/AHU_01",
        params={"building_id": "BLDG_API_TEST"},
    )
    assert resp.status_code == 200
    report = resp.json()
    assert "overall_status" in report
    assert report["overall_status"] in ("VALID", "WARNING", "INVALID")
    assert "rules_validated_count" in report
    assert "rules_table" in report
    assert "findings_table" in report
    assert "reconciliation_table" in report
    assert len(report["rules_table"]) > 0

