"""Targeted Phase 2 Semantic Validation Tests:
Verifies grounded telemetry, observed values during confirmed fault episodes,
canonical role association, sensor fault identification, and confidence calculation.
"""

from __future__ import annotations

import pytest
from app.datasets.manager import DatasetManager
from app.fdd.executor import get_executor


@pytest.fixture(scope="module")
def executor():
    mgr = DatasetManager()
    return get_executor(storage=mgr.historian.storage)


def test_fc1_grounded_evidence(executor):
    """FC1 evidence must reflect fault-period telemetry (DSP=0.42, SP=1.00, fan=90%), not dataset averages."""
    res = executor.execute_rules_for_equipment("AHU-HPE-01", rule_ids=["FC1"])
    assert len(res.results) == 1
    finding = res.results[0].findings[0]
    assert finding.fault_detected is True
    detail = finding.detail
    assert detail is not None
    assert detail.severity == "HIGH"
    assert detail.total_fault_hours == 1.25

    # Check evidence
    assert len(detail.evidence) >= 1
    ev = detail.evidence[0]
    assert ev.confidence == "CONFIRMED"
    assert "0.42" in ev.evidence_text
    assert "1.00" in ev.evidence_text
    assert "90%" in ev.evidence_text
    assert "deficit" in ev.evidence_text

    obs = ev.observed_values
    assert obs["duct_static_mean"] == pytest.approx(0.422, abs=0.01)
    assert obs["duct_static_sp_mean"] == pytest.approx(1.004, abs=0.01)
    assert obs["fan_cmd_mean"] == pytest.approx(90.0, abs=0.1)
    assert obs["deficit"] < 0

    # No false missing context
    assert len(ev.missing_context_roles) == 0


def test_ahu_satdev_grounded_evidence(executor):
    """AHU-SATDEV evidence must reflect fault-period SAT (64.8 deg F vs 55.4 deg F SP, clg=92%) and no false clg_valve missing context."""
    res = executor.execute_rules_for_equipment("AHU-HPE-01", rule_ids=["AHU-SATDEV"])
    assert len(res.results) == 1
    finding = res.results[0].findings[0]
    assert finding.fault_detected is True
    detail = finding.detail
    assert detail is not None
    assert detail.total_fault_hours == 1.5

    ev = detail.evidence[0]
    assert ev.confidence == "CONFIRMED"
    assert "+9.4" in ev.evidence_text
    assert "Cooling Valve: 92%" in ev.evidence_text

    obs = ev.observed_values
    assert obs["sat_mean"] == pytest.approx(64.76, abs=0.1)
    assert obs["sat_sp_mean"] == pytest.approx(55.4, abs=0.1)
    assert obs["delta_temp"] == pytest.approx(9.36, abs=0.1)
    assert obs["clg_valve_pct_mean"] == pytest.approx(92.0, abs=0.1)

    # clg_valve_pct must NOT be in missing context
    for e in detail.evidence:
        assert "clg_valve_pct" not in e.missing_context_roles
        assert "clg_vlv" not in e.missing_context_roles


def test_cmd1_grounded_evidence(executor):
    """CMD-1 evidence must reflect fault-period fan command (62%) and status (0)."""
    res = executor.execute_rules_for_equipment("AHU-HPE-01", rule_ids=["CMD-1"])
    assert len(res.results) == 1
    finding = res.results[0].findings[0]
    assert finding.fault_detected is True
    detail = finding.detail
    assert detail is not None
    assert detail.severity == "CRITICAL"
    assert detail.total_fault_hours == 1.25

    ev = detail.evidence[0]
    assert ev.confidence == "CONFIRMED"
    assert "62%" in ev.evidence_text
    assert "OFF (0)" in ev.evidence_text

    obs = ev.observed_values
    assert obs["fan_cmd"] == pytest.approx(62.0, abs=0.1)
    assert obs["fan_status"] == pytest.approx(0.0, abs=0.1)
    assert len(ev.missing_context_roles) == 0


def test_sv_flatline_sensor_identification(executor):
    """SV-FLATLINE must identify specific faulted sensors: rat, sat, chw_supply_t, chw_return_t."""
    res = executor.execute_rules_for_equipment("AHU-HPE-01", rule_ids=["SV-FLATLINE"])
    assert len(res.results) == 1
    finding = res.results[0].findings[0]
    assert finding.fault_detected is True
    detail = finding.detail
    assert detail is not None

    ev = detail.evidence[0]
    assert ev.confidence == "CONFIRMED"
    assert "Sensor validation fault detected on:" in ev.evidence_text
    obs = ev.observed_values
    assert "faulted_sensors" in obs
    faulted = obs["faulted_sensors"]
    for expected in ["rat", "sat", "chw_supply_t", "chw_return_t"]:
        assert expected in faulted
        assert expected in ev.evidence_text


def test_sv_stale_sensor_identification(executor):
    """SV-STALE must identify specific stale sensors: rat, sat, chw_supply_t, chw_return_t."""
    res = executor.execute_rules_for_equipment("AHU-HPE-01", rule_ids=["SV-STALE"])
    assert len(res.results) == 1
    finding = res.results[0].findings[0]
    assert finding.fault_detected is True
    detail = finding.detail
    assert detail is not None

    ev = detail.evidence[0]
    assert ev.confidence == "CONFIRMED"
    assert "Sensor validation fault detected on:" in ev.evidence_text
    obs = ev.observed_values
    assert "faulted_sensors" in obs
    faulted = obs["faulted_sensors"]
    for expected in ["rat", "sat", "chw_supply_t", "chw_return_t"]:
        assert expected in faulted
        assert expected in ev.evidence_text


def test_ahu_ducthi_grounded_evidence(executor):
    """AHU-DUCTHI on monthly dataset must reflect elevated duct static pressure during fault."""
    res = executor.execute_rules_for_equipment("F5_AHU01_NORTH_AHU_Month", rule_ids=["AHU-DUCTHI"])
    assert len(res.results) == 1
    finding = res.results[0].findings[0]
    assert finding.fault_detected is True
    detail = finding.detail
    assert detail is not None
    assert detail.severity == "CRITICAL"
    assert detail.total_fault_hours == 3.0

    ev = detail.evidence[0]
    assert ev.confidence == "CONFIRMED"
    assert "exceeding setpoint" in ev.evidence_text
    obs = ev.observed_values
    assert obs["duct_static_mean"] > 1.2
    assert obs["duct_static_sp_mean"] == pytest.approx(0.723, abs=0.01)
    assert len(ev.missing_context_roles) == 0
