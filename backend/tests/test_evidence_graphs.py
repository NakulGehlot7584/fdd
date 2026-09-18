"""Comprehensive unit and integration tests for Milestone 7:
Fault Episodes, Grounded Diagnostics, Dynamic Graph Payloads, and REST APIs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.fdd.episodes import extract_fault_episodes
from app.fdd.diagnostics import build_grounded_diagnostic, get_diagnostic_meta
from app.fdd.graphs import (
    build_fault_timeline,
    build_rule_graph,
    build_telemetry_graph,
    get_available_graph_categories,
    select_plot_indices,
)
from app.fdd.models import (
    FaultEpisode,
    RuleExecutionResult,
    RuleExecutionStatus,
    RuleFinding,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# 1. Episode Segmentation Tests
# ---------------------------------------------------------------------------

def test_extract_fault_episodes_single_and_consecutive():
    """Single sample and contiguous consecutive samples create properly bounded episodes."""
    base = datetime(2026, 7, 16, 10, 0, 0)
    
    # 1 sample
    summary, eps = extract_fault_episodes([base], poll_seconds=300.0)
    assert summary["episode_count"] == 1
    assert summary["sample_count"] == 1
    assert summary["total_fault_hours"] == round(300.0 / 3600.0, 4)
    assert eps[0].start == base.isoformat()
    assert eps[0].end == base.isoformat()
    assert eps[0].samples == 1

    # 6 contiguous samples (every 5 minutes = 300s)
    consec = [base + timedelta(minutes=5 * i) for i in range(6)]
    summary, eps = extract_fault_episodes(consec, poll_seconds=300.0)
    assert summary["episode_count"] == 1
    assert summary["sample_count"] == 6
    assert summary["total_fault_hours"] == round(6 * 300.0 / 3600.0, 4)
    assert eps[0].start == consec[0].isoformat()
    assert eps[0].end == consec[-1].isoformat()
    assert eps[0].samples == 6


def test_extract_fault_episodes_gaps_and_transitions():
    """Gaps exceeding max(poll_seconds * 2.5, 600s) cleanly segment into distinct episodes."""
    base = datetime(2026, 7, 16, 8, 0, 0)
    poll_sec = 300.0  # gap threshold is max(750s, 600s) = 750s (12.5 min)

    # Episode 1: 3 samples (8:00, 8:05, 8:10)
    ep1 = [base + timedelta(minutes=5 * i) for i in range(3)]
    
    # Gap of 2 hours (8:10 to 10:10)
    gap_start = base + timedelta(hours=2, minutes=10)
    # Episode 2: 4 samples (10:10, 10:15, 10:20, 10:25)
    ep2 = [gap_start + timedelta(minutes=5 * i) for i in range(4)]

    # Gap of 45 minutes (10:25 to 11:10)
    gap2_start = ep2[-1] + timedelta(minutes=45)
    # Episode 3: 2 samples (11:10, 11:15)
    ep3 = [gap2_start, gap2_start + timedelta(minutes=5)]

    all_ts = ep1 + ep2 + ep3
    summary, eps = extract_fault_episodes(all_ts, poll_seconds=poll_sec)

    assert summary["episode_count"] == 3
    assert summary["sample_count"] == 9
    assert summary["total_fault_hours"] == round(9 * 300.0 / 3600.0, 4)
    assert len(eps) == 3

    assert eps[0].samples == 3
    assert eps[0].start == ep1[0].isoformat()
    assert eps[0].end == ep1[-1].isoformat()

    assert eps[1].samples == 4
    assert eps[1].start == ep2[0].isoformat()
    assert eps[1].end == ep2[-1].isoformat()

    assert eps[2].samples == 2
    assert eps[2].start == ep3[0].isoformat()
    assert eps[2].end == ep3[-1].isoformat()


def test_extract_fault_episodes_empty_and_unordered():
    """Empty lists return zeroed summaries, and unordered inputs are sorted correctly."""
    # Empty
    summary, eps = extract_fault_episodes([], poll_seconds=300.0)
    assert summary["episode_count"] == 0
    assert summary["total_fault_hours"] == 0.0
    assert len(eps) == 0

    # Unordered
    base = datetime(2026, 7, 16, 12, 0, 0)
    t1 = base + timedelta(minutes=5)
    t2 = base + timedelta(minutes=10)
    t3 = base + timedelta(minutes=0)
    summary, eps = extract_fault_episodes([t1, t2, t3], poll_seconds=300.0)
    assert summary["episode_count"] == 1
    assert summary["sample_count"] == 3
    assert eps[0].start == t3.isoformat()
    assert eps[0].end == t2.isoformat()


# ---------------------------------------------------------------------------
# 2. Diagnostic Grounding & Evidence Tests
# ---------------------------------------------------------------------------

def test_grounded_diagnostic_satdev():
    """Diagnostic engine computes observed numerical delta and reports confirmed evidence."""
    base = datetime(2026, 7, 16, 14, 0, 0)
    ts = [base + timedelta(minutes=5 * i) for i in range(5)]
    _, eps = extract_fault_episodes(ts, poll_seconds=300.0)

    record = build_grounded_diagnostic(
        rule_id="AHU-SATDEV",
        equipment_id="AHU_UNIT_1",
        metrics={"fault_hours": 0.4167},
        episodes=eps,
        telemetry_summary={"sat": {"mean": 64.8}, "sat_sp": {"mean": 55.0}},
        available_roles={"sat", "sat_sp", "fan_cmd"},
    )

    assert record.rule_id == "AHU-SATDEV"
    assert record.fault_detected is True
    assert record.severity == "HIGH"
    assert len(record.possible_causes) >= 3
    assert len(record.recommended_checks) >= 3
    assert len(record.evidence) >= 2

    # Verify primary grounded evidence
    prim_ev = record.evidence[0]
    assert prim_ev.confidence == "CONFIRMED"
    assert "+9.8" in prim_ev.evidence_text
    assert prim_ev.observed_values["sat_mean"] == 64.8
    assert prim_ev.observed_values["sat_sp_mean"] == 55.0

    # Verify missing context notice
    warn_ev = record.evidence[1]
    assert warn_ev.confidence == "LIMITED"
    assert "[CANNOT BE FULLY CORROBORATED]" in warn_ev.evidence_text
    assert any(r in warn_ev.missing_context_roles for r in ["clg_valve_pct", "htg_valve_pct", "clg_vlv", "htg_vlv"])


def test_grounded_diagnostic_fan_command_status_mismatch():
    """CMD-1 rule correctly asserts fan command ON vs fan status OFF evidence."""
    base = datetime(2026, 7, 16, 9, 0, 0)
    ts = [base + timedelta(minutes=5 * i) for i in range(3)]
    _, eps = extract_fault_episodes(ts, poll_seconds=300.0)

    record = build_grounded_diagnostic(
        rule_id="CMD-1",
        equipment_id="AHU_02",
        metrics={"fault_hours": 0.25},
        episodes=eps,
        telemetry_summary={"fan_cmd": {"mean": 1.0}, "fan_status": {"mean": 0.0}},
        available_roles={"fan_cmd", "fan_status"},
    )

    assert record.fault_detected is True
    assert record.severity == "CRITICAL"
    ev = record.evidence[0]
    assert ev.confidence == "CONFIRMED"
    assert "Supply fan command is ON (1)" in ev.evidence_text
    assert "status feedback indicates OFF (0)" in ev.evidence_text


def test_grounded_diagnostic_healthy_rule():
    """Rules with 0 fault hours produce valid non-fault diagnostic records."""
    record = build_grounded_diagnostic(
        rule_id="FC1",
        equipment_id="AHU_HEALTHY",
        metrics={"fault_hours": 0.0},
        episodes=[],
        telemetry_summary={},
        available_roles={"duct_static", "duct_static_sp", "fan_cmd"},
    )

    assert record.fault_detected is False
    assert record.total_fault_hours == 0.0
    assert len(record.episodes) == 0


# ---------------------------------------------------------------------------
# 3. Dynamic Graph Engine & Downsampling Tests
# ---------------------------------------------------------------------------

def test_downsampling_preserves_endpoints_and_fault_boundaries():
    """Downsampler strictly retains index 0, index N-1, and designated episode boundaries."""
    n_total = 12000
    max_pts = 400
    preserved = [125, 126, 4500, 4510, 11980]

    chosen = select_plot_indices(n_total, max_points=max_pts, preserved_indices=preserved)

    assert len(chosen) <= max_pts
    assert 0 in chosen
    assert n_total - 1 in chosen
    for p in preserved:
        assert p in chosen
    # Monotonically increasing
    assert (np.diff(chosen) > 0).all()


def test_downsampling_under_cap_retains_all_points():
    """Downsampler retains 100% of points when total samples <= max_points."""
    n = 250
    chosen = select_plot_indices(n, max_points=1000)
    assert len(chosen) == 250
    assert np.array_equal(chosen, np.arange(n))


def test_available_graph_categories():
    """Category availability matches available canonical columns."""
    # Only temperature points
    cats1 = get_available_graph_categories(["sat", "sat_sp", "rat"])
    cat_map1 = {c.category_id: c.is_available for c in cats1}
    assert cat_map1["all_telemetry"] is True
    assert cat_map1["temperature_dynamics"] is True
    assert cat_map1["airside"] is False
    assert cat_map1["hydronic"] is False

    # Airside points added
    cats2 = get_available_graph_categories(["sat", "sat_sp", "duct_static", "fan_cmd"])
    cat_map2 = {c.category_id: c.is_available for c in cats2}
    assert cat_map2["temperature_dynamics"] is True
    assert cat_map2["airside"] is True
    assert cat_map2["hydronic"] is False


def test_build_fault_timeline_lanes():
    """Composite fault timeline groups findings into sorted swimlanes."""
    base = datetime(2026, 7, 16, 10, 0, 0)
    ep1 = FaultEpisode(
        episode_id="ep_001",
        start=base.isoformat(),
        end=(base + timedelta(hours=1)).isoformat(),
        samples=12,
        duration_hours=1.0,
    )
    ep2 = FaultEpisode(
        episode_id="ep_002",
        start=(base + timedelta(hours=3)).isoformat(),
        end=(base + timedelta(hours=4)).isoformat(),
        samples=12,
        duration_hours=1.0,
    )

    finding1 = RuleFinding(
        equipment_id="AHU_01",
        rule_id="CMD-1",
        severity="P0",
        description="Fan command mismatch",
        fault_detected=True,
        fault_hours=2.0,
        episodes=[ep1, ep2],
    )
    res1 = RuleExecutionResult(
        rule_id="CMD-1",
        status=RuleExecutionStatus.FAULT_DETECTED,
        findings=[finding1],
    )

    finding2 = RuleFinding(
        equipment_id="AHU_01",
        rule_id="AHU-SATDEV",
        severity="P1",
        description="SAT deviation",
        fault_detected=True,
        fault_hours=1.0,
        episodes=[ep1],
    )
    res2 = RuleExecutionResult(
        rule_id="AHU-SATDEV",
        status=RuleExecutionStatus.FAULT_DETECTED,
        findings=[finding2],
    )

    timeline = build_fault_timeline(
        equipment_id="AHU_01",
        rule_results=[res2, res1],
        building_id="BLDG_TEST",
    )

    assert timeline.equipment_id == "AHU_01"
    assert timeline.total_fault_hours == 3.0
    assert timeline.total_episodes == 3
    assert len(timeline.lanes) == 2
    assert timeline.lanes[0].rule_id == "CMD-1"  # P0 precedes P1


# ---------------------------------------------------------------------------
# 4. REST API Endpoint Integration Tests
# ---------------------------------------------------------------------------

def test_api_list_available_graphs():
    """GET /api/graphs/available/{equipment_id} returns valid category list."""
    response = client.get("/api/graphs/available/AHU-HPE-01?building_id=REAL_VERIFY")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 3
    cat_ids = [c["category_id"] for c in data]
    assert "all_telemetry" in cat_ids
    assert "temperature_dynamics" in cat_ids


def test_api_get_telemetry_graph():
    """GET /api/graphs/telemetry/{equipment_id} returns multi-axis timeseries."""
    response = client.get(
        "/api/graphs/telemetry/AHU-HPE-01?building_id=REAL_VERIFY&max_points=50"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["equipment_id"] == "AHU-HPE-01"
    assert "series" in data
    assert len(data["series"]) > 0
    first_s = data["series"][0]
    assert "timestamps" in first_s
    assert "values" in first_s
    assert "unit" in first_s
    assert "y_axis" in first_s
    assert len(first_s["timestamps"]) <= 50


def test_api_get_rule_investigation_graph():
    """GET /api/graphs/rule/{equipment_id}/{rule_id} returns focused graph with episodes."""
    response = client.get(
        "/api/graphs/rule/AHU-HPE-01/AHU-SATDEV?building_id=REAL_VERIFY&max_points=100"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["equipment_id"] == "AHU-HPE-01"
    assert "fault_episodes" in data
    assert isinstance(data["fault_episodes"], list)
    assert len(data["fault_episodes"]) > 0
    ep0 = data["fault_episodes"][0]
    assert "start" in ep0
    assert "end" in ep0
    assert "duration_hours" in ep0


def test_api_get_fault_timeline():
    """GET /api/graphs/timeline/{equipment_id} returns composite swimlanes."""
    response = client.get(
        "/api/graphs/timeline/AHU-HPE-01?building_id=REAL_VERIFY&rule_ids=AHU-SATDEV"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["equipment_id"] == "AHU-HPE-01"
    assert "lanes" in data
    assert len(data["lanes"]) > 0
    assert data["total_fault_hours"] > 0
    assert data["total_episodes"] > 0


def test_api_get_equipment_faults_endpoint():
    """GET /api/fdd/faults/{equipment_id} returns enriched diagnostic records."""
    response = client.get(
        "/api/fdd/faults/AHU-HPE-01?building_id=REAL_VERIFY&rule_ids=AHU-SATDEV"
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    rec = data[0]
    assert rec["rule_id"] == "AHU-SATDEV"
    assert rec["fault_detected"] is True
    assert len(rec["episodes"]) > 0
    assert len(rec["evidence"]) > 0
    assert len(rec["possible_causes"]) > 0
    assert len(rec["recommended_checks"]) > 0


def test_api_get_single_rule_fault_endpoint():
    """GET /api/fdd/faults/{equipment_id}/{rule_id} returns single rule diagnostic."""
    response = client.get(
        "/api/fdd/faults/AHU-HPE-01/AHU-SATDEV?building_id=REAL_VERIFY"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["rule_id"] == "AHU-SATDEV"
    assert data["equipment_id"] == "AHU-HPE-01"
    assert data["fault_detected"] is True
    assert data["severity"] == "HIGH"
    assert data["total_fault_hours"] > 0
