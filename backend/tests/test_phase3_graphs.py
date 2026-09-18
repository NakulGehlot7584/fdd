"""Phase 3 Graph and Evidence Visualization Backend Tests.

Validates:
1. Graph category availability and canonical role mapping.
2. Multi-axis telemetry series, units ('in. w.c.', '°F', '%', 'ppm', '0/1'), and step rendering.
3. Rule-specific graph series including diagnostic and canonical context roles for audited rules.
4. Downsampling with boundary (index 0, N-1) and episode boundary preservation.
5. Null telemetry handling without crashing or hallucinating numbers.
6. Fault timeline lane structuring and severity sorting.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.fdd.graphs import (
    ROLE_METADATA,
    build_fault_timeline,
    build_rule_graph,
    build_telemetry_graph,
    get_available_graph_categories,
    select_plot_indices,
)
from app.fdd.models import (
    FaultEpisode,
    RuleDefinition,
    RuleExecutionResult,
    RuleExecutionStatus,
    RuleFinding,
)

client = TestClient(app)

SAMPLE_PARQUET = Path(r"D:\fdd\data\historian\building=DEFAULT_BUILDING\equipment=AHU-HPE-01\history.parquet")


# ---------------------------------------------------------------------------
# 1. Role Metadata and Category Availability Tests
# ---------------------------------------------------------------------------

def test_canonical_role_metadata_units_and_axes():
    """Verify that all canonical roles have correct engineering units and Y-axis assignments."""
    # Temperatures -> °F, y1, line
    for temp_role in ["sat", "sat_sp", "rat", "mat", "oa_t", "chw_supply_t", "chw_return_t", "zone_t"]:
        meta = ROLE_METADATA.get(temp_role)
        assert meta is not None, f"Missing metadata for {temp_role}"
        assert meta["unit"] == "°F"
        assert meta["y_axis"] == "y1"
        assert meta["chart_type"] == "line"

    # Valve positions and modulations -> %, y2, line
    for pct_role in ["clg_valve_pct", "clg_valve_fbk", "htg_valve_pct", "oa_damper_pct"]:
        meta = ROLE_METADATA.get(pct_role)
        assert meta is not None, f"Missing metadata for {pct_role}"
        assert meta["unit"] == "%"
        assert meta["y_axis"] == "y2"
        assert meta["chart_type"] == "line"

    # Static pressures -> in. w.c., y3, line
    for press_role in ["duct_static", "duct_static_sp"]:
        meta = ROLE_METADATA.get(press_role)
        assert meta is not None, f"Missing metadata for {press_role}"
        assert meta["unit"] == "in. w.c."
        assert meta["y_axis"] == "y3"
        assert meta["chart_type"] == "line"

    # CO2 -> ppm, y3, line
    for co2_role in ["co2", "co2_sp"]:
        meta = ROLE_METADATA.get(co2_role)
        assert meta is not None, f"Missing metadata for {co2_role}"
        assert meta["unit"] == "ppm"
        assert meta["y_axis"] == "y3"
        assert meta["chart_type"] == "line"

    # Binary fan commands/status -> 0/1, y4, step
    for bin_role in ["fan_cmd", "fan_status"]:
        meta = ROLE_METADATA.get(bin_role)
        assert meta is not None, f"Missing metadata for {bin_role}"
        assert meta["unit"] == "0/1"
        assert meta["y_axis"] == "y4"
        assert meta["chart_type"] == "step"


def test_category_availability_canonical_and_aliases():
    """Verify category discovery correctly identifies both canonical and legacy alias roles."""
    roles = {
        "sat", "sat_sp", "clg_valve_pct", "duct_static", "duct_static_sp",
        "fan_cmd", "zone_t", "zone_h", "co2"
    }
    cats = get_available_graph_categories(roles)
    cat_map = {c.category_id: c for c in cats}

    assert "all_telemetry" in cat_map
    assert cat_map["all_telemetry"].is_available is True

    assert "temperature_dynamics" in cat_map
    assert cat_map["temperature_dynamics"].is_available is True
    assert "sat" in cat_map["temperature_dynamics"].available_roles
    assert "zone_t" in cat_map["temperature_dynamics"].available_roles

    assert "airside" in cat_map
    assert cat_map["airside"].is_available is True
    assert "duct_static" in cat_map["airside"].available_roles
    assert "fan_cmd" in cat_map["airside"].available_roles

    assert "hydronic" in cat_map
    assert cat_map["hydronic"].is_available is True
    assert "clg_valve_pct" in cat_map["hydronic"].available_roles

    assert "zone_comfort" in cat_map
    assert cat_map["zone_comfort"].is_available is True
    assert "co2" in cat_map["zone_comfort"].available_roles
    assert "zone_h" in cat_map["zone_comfort"].available_roles


# ---------------------------------------------------------------------------
# 2. Downsampling and Boundary Preservation Tests
# ---------------------------------------------------------------------------

def test_select_plot_indices_preserves_endpoints_and_fault_episodes():
    """select_plot_indices strictly preserves index 0, index N-1, and preserved fault boundaries."""
    n_samples = 10000
    preserved = [450, 451, 452, 2300, 2301, 8999]
    selected = select_plot_indices(n_samples, max_points=1000, preserved_indices=preserved)

    # Monotonically increasing
    assert np.all(np.diff(selected) >= 0)
    assert len(selected) <= 1000 + len(preserved)

    # First and last indices preserved
    assert selected[0] == 0
    assert selected[-1] == n_samples - 1

    # All preserved indices are present
    for p in preserved:
        assert p in selected


# ---------------------------------------------------------------------------
# 3. Rule Context Graphs for Audited Rules
# ---------------------------------------------------------------------------

def test_build_rule_graph_for_ahu_satdev_includes_cooling_valve():
    """Rule graph for AHU-SATDEV includes cooling valve and fan command for diagnostic context."""
    rule_def = RuleDefinition(
        rule_id="AHU-SATDEV",
        sql_file="ahu_satdev.sql",
        description="Supply air temperature deviation from setpoint",
        required_roles=["sat", "sat_sp"],
        optional_roles=["fan_status", "fan_cmd"],
        priority="P1",
    )
    graph = build_rule_graph(
        parquet_path=SAMPLE_PARQUET,
        equipment_id="AHU-HPE-01",
        rule_id="AHU-SATDEV",
        rule_def=rule_def,
        episodes=[],
        max_points=5000,
    )
    series_roles = [s.role for s in graph.series]
    # Primary required roles first
    assert "sat" in series_roles
    assert "sat_sp" in series_roles
    # Contextual role clg_valve_pct is present
    assert "clg_valve_pct" in series_roles
    # Verify axes
    sat_s = next(s for s in graph.series if s.role == "sat")
    assert sat_s.unit == "°F"
    assert sat_s.y_axis == "y1"
    clg_s = next(s for s in graph.series if s.role == "clg_valve_pct")
    assert clg_s.unit == "%"
    assert clg_s.y_axis == "y2"


def test_build_rule_graph_for_fc1_includes_airside_context():
    """Rule graph for FC1 includes duct static pressure, setpoint, and fan command."""
    rule_def = RuleDefinition(
        rule_id="FC1",
        sql_file="fc1.sql",
        description="Duct static below setpoint at full fan",
        required_roles=["duct_static", "duct_static_sp", "fan_cmd"],
        priority="P1",
    )
    graph = build_rule_graph(
        parquet_path=SAMPLE_PARQUET,
        equipment_id="AHU-HPE-01",
        rule_id="FC1",
        rule_def=rule_def,
        episodes=[],
        max_points=5000,
    )
    series_roles = [s.role for s in graph.series]
    assert "duct_static" in series_roles
    assert "duct_static_sp" in series_roles
    assert "fan_cmd" in series_roles
    ds_s = next(s for s in graph.series if s.role == "duct_static")
    assert ds_s.unit == "in. w.c."
    assert ds_s.y_axis == "y3"


def test_build_rule_graph_for_cmd1_binary_step():
    """Rule graph for CMD-1 renders fan_cmd and fan_status with step chart type."""
    rule_def = RuleDefinition(
        rule_id="CMD-1",
        sql_file="cmd1.sql",
        description="Supply fan command vs status mismatch",
        required_roles=["fan_cmd", "fan_status"],
        priority="P0",
    )
    graph = build_rule_graph(
        parquet_path=SAMPLE_PARQUET,
        equipment_id="AHU-HPE-01",
        rule_id="CMD-1",
        rule_def=rule_def,
        episodes=[],
        max_points=5000,
    )
    cmd_s = next(s for s in graph.series if s.role == "fan_cmd")
    stat_s = next(s for s in graph.series if s.role == "fan_status")
    assert cmd_s.chart_type == "step"
    assert stat_s.chart_type == "step"
    assert cmd_s.y_axis == "y4"
    assert stat_s.y_axis == "y4"


# ---------------------------------------------------------------------------
# 4. Fault Timeline Lanes and Severity Ordering
# ---------------------------------------------------------------------------

def test_build_fault_timeline_sorts_by_severity():
    """build_fault_timeline sorts lanes strictly by CRITICAL -> HIGH -> MEDIUM -> LOW."""
    def make_res(rule_id: str, severity: str, count: int) -> RuleExecutionResult:
        finding = RuleFinding(
            equipment_id="AHU-01",
            rule_id=rule_id,
            severity=severity,
            description=rule_id,
            fault_detected=True,
            fault_hours=count * 0.25,
            sample_count=count,
            episodes=[
                FaultEpisode(
                    episode_id="ep1",
                    start="2026-07-16T10:00:00",
                    end="2026-07-16T10:15:00",
                    samples=count,
                    duration_hours=count * 0.25,
                    summary=f"{count*0.25:.2f}h",
                )
            ],
        )
        return RuleExecutionResult(
            rule_id=rule_id,
            status=RuleExecutionStatus.FAULT_DETECTED,
            findings=[finding],
        )

    results = [
        make_res("MED_RULE", "MEDIUM", 4),
        make_res("CRIT_RULE", "CRITICAL", 2),
        make_res("HIGH_RULE", "HIGH", 3),
    ]

    timeline = build_fault_timeline("AHU-01", results)
    lane_ids = [lane.rule_id for lane in timeline.lanes]
    assert lane_ids == ["CRIT_RULE", "HIGH_RULE", "MED_RULE"]
    assert timeline.total_fault_hours == 0.5 + 0.75 + 1.0
    assert timeline.total_episodes == 3


# ---------------------------------------------------------------------------
# 5. Integration API Tests with Sample Datasets and Null Handling
# ---------------------------------------------------------------------------

def test_api_graph_endpoints_on_sample_ahu():
    """Live API integration: test graph categories, telemetry graph, rule graph, and timeline."""
    eq_id = "AHU-HPE-01"
    
    # 1. Available categories
    resp = client.get(f"/api/graphs/available/{eq_id}")
    assert resp.status_code == 200
    cat_data = resp.json()
    assert len(cat_data) >= 4

    # 2. Telemetry graph
    resp = client.get(f"/api/graphs/telemetry/{eq_id}?max_points=500")
    assert resp.status_code == 200
    telemetry = resp.json()
    assert len(telemetry["series"]) > 0
    first_series = telemetry["series"][0]
    assert "timestamps" in first_series
    assert len(first_series["timestamps"]) <= 500

    # 3. Rule graph for FC1
    resp = client.get(f"/api/graphs/rule/{eq_id}/FC1?max_points=500")
    assert resp.status_code == 200
    r_graph = resp.json()
    assert "FC1" in r_graph["graph_id"]
    assert len(r_graph["series"]) > 0

    # 4. Fault timeline
    resp = client.get(f"/api/graphs/timeline/{eq_id}")
    assert resp.status_code == 200
    timeline = resp.json()
    assert len(timeline["lanes"]) > 0


def test_api_null_telemetry_dataset_handling():
    """Datasets with 100% null columns (e.g. F5_AHU02_SOUTH_AHU_Month SAT) must not crash."""
    eq_id = "F5_AHU02_SOUTH_AHU_Month"
    
    # 1. Available categories should succeed
    resp = client.get(f"/api/graphs/available/{eq_id}")
    assert resp.status_code == 200

    # 2. Telemetry graph should succeed and preserve nulls
    resp = client.get(f"/api/graphs/telemetry/{eq_id}?max_points=500")
    assert resp.status_code == 200
    telemetry = resp.json()
    sat_series = next((s for s in telemetry["series"] if s["role"] == "sat"), None)
    if sat_series:
        # SAT in this dataset is completely null
        assert all(v is None for v in sat_series["values"])

    # 3. Rule graph for AHU-SATDEV should return empty episodes rather than crashing
    resp = client.get(f"/api/graphs/rule/{eq_id}/AHU-SATDEV")
    assert resp.status_code == 200
    r_graph = resp.json()
    assert r_graph["fault_episodes"] == []
