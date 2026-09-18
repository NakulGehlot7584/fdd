"""Comprehensive API Matrix & A-Z End-to-End Workflow Test.

Exercises every route in FastAPI app across valid, empty, invalid, and missing resource scenarios.
"""

from __future__ import annotations

import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

TEST_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "test_data"


def test_01_health_check():
    """Verify GET /api/health endpoint."""
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_02_threshold_metadata():
    """Verify GET /api/fdd/threshold-metadata endpoint."""
    res = client.get("/api/fdd/threshold-metadata")
    assert res.status_code == 200
    data = res.json()
    assert "categories" in data
    assert len(data["categories"]) == 12
    assert "parameters" in data
    assert data["total_parameters"] == 93
    assert data["tier_a_count"] == 30
    assert data["tier_b_count"] == 63
    assert "presets" in data
    assert "Standard" in data["presets"]
    assert "Sensitive" in data["presets"]
    assert "Lenient" in data["presets"]


def test_03_rules_catalog():
    """Verify GET /api/fdd/rules and GET /api/fdd/rules/{rule_id}."""
    # List all rules
    res = client.get("/api/fdd/rules")
    assert res.status_code == 200
    rules = res.json()
    assert len(rules) == 66

    # List AHU rules
    res_ahu = client.get("/api/fdd/rules?equipment_kind=ahu")
    assert res_ahu.status_code == 200
    ahu_rules = res_ahu.json()
    assert len(ahu_rules) == 45

    # Get valid rule
    res_single = client.get("/api/fdd/rules/AHU-SATDEV")
    assert res_single.status_code == 200
    assert res_single.json()["rule_id"] == "AHU-SATDEV"

    # Get missing rule -> 404
    res_missing = client.get("/api/fdd/rules/NON_EXISTENT_RULE_XYZ")
    assert res_missing.status_code == 404


def test_04_datasets_list_empty():
    """Verify GET /api/datasets."""
    res = client.get("/api/datasets")
    assert res.status_code == 200
    assert "datasets" in res.json()


def test_05_dataset_upload_invalid():
    """Verify POST /api/datasets/upload with non-csv and empty payloads."""
    # Empty files list
    res_empty = client.post("/api/datasets/upload", files=[])
    # FastAPI returns 422 if files field is missing or empty
    assert res_empty.status_code in [400, 422]

    # Non-CSV file
    res_txt = client.post(
        "/api/datasets/upload",
        files=[("files", ("test.txt", io.BytesIO(b"dummy text"), "text/plain"))],
    )
    assert res_txt.status_code == 400
    assert "not a CSV" in res_txt.json()["detail"]


def test_06_real_csv_upload_and_pipeline():
    """Upload real test CSV (ahu_multi_point_sample.csv), verify mapping, ingestion, and execution."""
    sample_csv = TEST_DATA_DIR / "ahu_multi_point_sample.csv"
    assert sample_csv.exists(), f"Sample CSV not found at {sample_csv}"

    with open(sample_csv, "rb") as f:
        file_bytes = f.read()

    # 1. Upload CSV
    res_upload = client.post(
        "/api/datasets/upload",
        files=[("files", ("ahu_multi_point_sample.csv", io.BytesIO(file_bytes), "text/csv"))],
    )
    assert res_upload.status_code == 201
    upload_data = res_upload.json()
    assert len(upload_data["datasets"]) >= 1
    ds = upload_data["datasets"][0]
    dataset_id = ds["dataset_id"]
    assert ds["row_count"] > 0
    assert ds["column_count"] > 0

    # 2. Get Dataset Detail
    res_detail = client.get(f"/api/datasets/{dataset_id}")
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["dataset_id"] == dataset_id
    assert detail["preflight"]["valid"] is True
    assert len(detail["columns"]) > 0

    # 3. Get Dataset Columns
    res_cols = client.get(f"/api/datasets/{dataset_id}/columns")
    assert res_cols.status_code == 200
    assert len(res_cols.json()["columns"]) == detail["column_count"]

    # 4. Get Canonical Telemetry
    res_canon = client.get(f"/api/datasets/{dataset_id}/canonical")
    assert res_canon.status_code == 200
    canon = res_canon.json()
    assert canon["dataset_id"] == dataset_id
    assert len(canon["preview_rows"]) > 0

    # 5. Check Historian Equipment list
    res_hist_eq = client.get("/api/historian/equipment")
    assert res_hist_eq.status_code == 200
    eq_list = res_hist_eq.json()
    assert len(eq_list) >= 1
    # Match by equipment ID or source file
    matching_eq = next((e for e in eq_list if e["equipment_id"] in ["AHU-HPE-01", dataset_id] or "ahu_multi_point_sample.csv" in e.get("parquet_file", "")), eq_list[0])
    eq_id = matching_eq["equipment_id"]

    # 6. Check Historian Summary
    res_hist_sum = client.get("/api/historian/summary")
    assert res_hist_sum.status_code == 200
    assert res_hist_sum.json()["total_equipment"] >= 1

    # 7. Check Historian Telemetry preview using resolved equipment ID
    res_hist_tel = client.get(f"/api/historian/equipment/{eq_id}")
    assert res_hist_tel.status_code == 200
    assert len(res_hist_tel.json()["preview_rows"]) > 0

    # 8. Check Available Graphs
    res_avail_graphs = client.get(f"/api/graphs/available/{eq_id}")
    assert res_avail_graphs.status_code == 200
    graphs_avail = res_avail_graphs.json()
    assert len(graphs_avail) > 0

    # 9. Get Telemetry Graph
    res_graph_tel = client.get(f"/api/graphs/telemetry/{eq_id}")
    assert res_graph_tel.status_code == 200
    tel_graph = res_graph_tel.json()
    assert len(tel_graph["series"]) > 0

    # 10. Execute FDD with overrides
    res_exec = client.post(
        f"/api/fdd/execute/{eq_id}",
        json={
            "parameter_overrides": {
                "AHU-SATDEV": {"sat_dev_err": 4.0, "confirm_seconds": 600},
                "FC13-SAT-HIGH": {"sat_err": 1.5, "confirm_seconds": 600},
            }
        },
    )
    assert res_exec.status_code == 200
    exec_summary = res_exec.json()
    assert exec_summary["total_catalog_rules"] == 66
    assert exec_summary["applicable_rules"] == 45
    assert exec_summary["non_applicable_rules"] == 21
    assert exec_summary["total_rules_evaluated"] == 45
    assert exec_summary["rules_succeeded"] >= 1
    # Check dynamic equation: Total evaluated = rules_succeeded + rules_skipped + rules_failed
    assert exec_summary["total_rules_evaluated"] == exec_summary["rules_succeeded"] + exec_summary["rules_skipped"] + exec_summary["rules_failed"]

    # 11. Retrieve Equipment Faults
    res_faults = client.get(f"/api/fdd/faults/{eq_id}")
    assert res_faults.status_code == 200
    faults = res_faults.json()
    assert isinstance(faults, list)

    # 12. Retrieve Specific Rule Fault
    res_rule_fault = client.get(f"/api/fdd/faults/{eq_id}/AHU-SATDEV")
    assert res_rule_fault.status_code == 200
    detail_rec = res_rule_fault.json()
    assert detail_rec["rule_id"] == "AHU-SATDEV"
    assert "evidence" in detail_rec
    assert "possible_causes" in detail_rec
    assert "recommended_checks" in detail_rec

    # 13. Get Rule-Specific Graph
    res_rule_graph = client.get(f"/api/graphs/rule/{eq_id}/AHU-SATDEV")
    assert res_rule_graph.status_code == 200
    assert len(res_rule_graph.json()["series"]) > 0

    # 14. Get Fault Timeline
    res_timeline = client.get(f"/api/graphs/timeline/{eq_id}")
    assert res_timeline.status_code == 200
    assert "lanes" in res_timeline.json()

    # 15. Delete Dataset and clean up
    res_del = client.delete(f"/api/datasets/{dataset_id}")
    assert res_del.status_code == 200
    assert res_del.json()["removed"] is True


def test_07_edge_cases_missing_entities():
    """Verify 404 responses for nonexistent datasets, equipment, and rules."""
    bogus = "NON_EXISTENT_ID_9999"

    # Dataset details 404
    assert client.get(f"/api/datasets/{bogus}").status_code == 404
    assert client.get(f"/api/datasets/{bogus}/columns").status_code == 404
    assert client.get(f"/api/datasets/{bogus}/canonical").status_code == 404
    assert client.delete(f"/api/datasets/{bogus}").status_code == 404

    # Historian equipment 404
    assert client.get(f"/api/historian/equipment/{bogus}").status_code == 404
    assert client.post(f"/api/historian/ingest/{bogus}").status_code == 404

    # Graphs 404
    assert client.get(f"/api/graphs/available/{bogus}").status_code == 404
    assert client.get(f"/api/graphs/telemetry/{bogus}").status_code == 404
    assert client.get(f"/api/graphs/rule/{bogus}/AHU-SATDEV").status_code == 404
    assert client.get(f"/api/graphs/timeline/{bogus}").status_code == 404

    # FDD execution 404
    assert client.post(f"/api/fdd/execute/{bogus}").status_code == 404
    assert client.get(f"/api/fdd/faults/{bogus}").status_code == 404
