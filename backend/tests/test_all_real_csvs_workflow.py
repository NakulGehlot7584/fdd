"""End-to-End Validation of All Real CSV Datasets in test_data/.

Tests Phases 7, 8, 9, 10 on:
1. ahu_multi_point_sample.csv
2. F5_AHU01_NORTH_AHU_Month.csv
3. F5_AHU02_SOUTH_AHU_Month.csv
4. F2_AHU02_North.csv
"""

from __future__ import annotations

import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TEST_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "test_data"


def test_workflow_all_real_datasets():
    csv_files = [
        "ahu_multi_point_sample.csv",
        "F5_AHU01_NORTH_AHU_Month.csv",
        "F5_AHU02_SOUTH_AHU_Month.csv",
        "F2_AHU02_North.csv",
    ]

    for csv_name in csv_files:
        csv_path = TEST_DATA_DIR / csv_name
        assert csv_path.exists(), f"File {csv_name} not found"

        print(f"\n--- Testing Dataset: {csv_name} ({csv_path.stat().st_size / 1024:.1f} KB) ---")

        with open(csv_path, "rb") as f:
            file_bytes = f.read()

        # Step 1: Upload CSV
        res_upload = client.post(
            "/api/datasets/upload",
            files=[("files", (csv_name, io.BytesIO(file_bytes), "text/csv"))],
        )
        assert res_upload.status_code == 201, f"Upload failed for {csv_name}: {res_upload.text}"
        ds_summary = res_upload.json()["datasets"][0]
        dataset_id = ds_summary["dataset_id"]
        assert ds_summary["row_count"] > 0
        assert ds_summary["column_count"] > 0
        if csv_name == "F2_AHU02_North.csv":
            # Grounded real data check: F2 contains 44 duplicate timestamps
            assert ds_summary["preflight_valid"] is False
        else:
            assert ds_summary["preflight_valid"] is True

        # Step 2: Detail & Column Profiling & Canonical Mapping
        res_detail = client.get(f"/api/datasets/{dataset_id}")
        assert res_detail.status_code == 200
        detail = res_detail.json()
        assert detail["mapped_column_count"] > 0
        assert detail["mapping_coverage"] > 0.0

        # Step 3: Canonical Telemetry
        res_canon = client.get(f"/api/datasets/{dataset_id}/canonical")
        assert res_canon.status_code == 200
        canon = res_canon.json()
        assert len(canon["preview_rows"]) > 0

        # Step 4: Resolve Equipment ID in Historian
        res_hist_eq = client.get("/api/historian/equipment")
        assert res_hist_eq.status_code == 200
        eq_list = res_hist_eq.json()
        matching_eq = next(
            (e for e in eq_list if csv_name in e.get("parquet_file", "") or e["equipment_id"] in [dataset_id, csv_path.stem]),
            eq_list[0],
        )
        eq_id = matching_eq["equipment_id"]

        # Step 5: Check Available Graph Categories
        res_avail = client.get(f"/api/graphs/available/{eq_id}")
        assert res_avail.status_code == 200
        avail_cats = res_avail.json()
        assert len(avail_cats) > 0
        print(f"  Available Graph Categories for {eq_id}: {[c['category_id'] for c in avail_cats if c['is_available']]}")

        # Step 6: Test Telemetry Graphs for Available Categories
        for c in avail_cats:
            if c["is_available"]:
                res_tel = client.get(f"/api/graphs/telemetry/{eq_id}?category={c['category_id']}&max_points=500")
                assert res_tel.status_code == 200
                tel_payload = res_tel.json()
                assert len(tel_payload["series"]) > 0

        # Step 7: Execute Rules with Overrides (Phase 3 & 8)
        res_exec = client.post(
            f"/api/fdd/execute/{eq_id}",
            json={
                "parameter_overrides": {
                    "AHU-SATDEV": {"sat_dev_err": 3.5, "confirm_seconds": 600},
                    "FC13-SAT-HIGH": {"sat_err": 1.0, "confirm_seconds": 600},
                }
            },
        )
        assert res_exec.status_code == 200
        summary = res_exec.json()
        assert summary["total_catalog_rules"] == 66
        assert summary["applicable_rules"] == 45
        assert summary["non_applicable_rules"] == 21
        assert summary["total_rules_evaluated"] == 45
        # Dynamic equation: Total evaluated = rules_succeeded + rules_skipped + rules_failed
        assert summary["total_rules_evaluated"] == summary["rules_succeeded"] + summary["rules_skipped"] + summary["rules_failed"]
        print(
            f"  FDD Results for {eq_id}: Total={summary['total_rules_evaluated']}, "
            f"Run={summary['rules_succeeded']}, Faulted={summary['rules_faulted']}, "
            f"Passed={summary['rules_no_fault']}, Skipped={summary['rules_skipped']}"
        )

        # Verify SKIPPED_MISSING_ROLES correctly identifies missing roles
        for r in summary["results"]:
            if r["status"] == "SKIPPED_MISSING_ROLES":
                assert len(r["missing_roles"]) > 0

        # Step 8: Test Faults & Diagnostic Evidence Grounding (Phase 9)
        res_faults = client.get(f"/api/fdd/faults/{eq_id}")
        assert res_faults.status_code == 200
        fault_records = res_faults.json()
        print(f"  Detected Fault Findings for {eq_id}: {len(fault_records)}")

        for fault in fault_records:
            assert fault["rule_id"]
            assert fault["rule_name"]
            assert fault["severity"] in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
            assert "evidence" in fault
            assert "possible_causes" in fault
            assert "recommended_checks" in fault
            # Evidence must be grounded
            for ev in fault["evidence"]:
                assert len(ev["evidence_text"]) > 0
                assert ev["confidence"] in ["CONFIRMED", "SUPPORTED", "LIMITED"]

            # Step 9: Test Rule-Specific Graph for each fault (Phase 10)
            res_rgraph = client.get(f"/api/graphs/rule/{eq_id}/{fault['rule_id']}?max_points=500")
            assert res_rgraph.status_code == 200
            rg_payload = res_rgraph.json()
            assert len(rg_payload["series"]) > 0

        # Step 10: Test Fault Timeline (Phase 10)
        res_timeline = client.get(f"/api/graphs/timeline/{eq_id}")
        assert res_timeline.status_code == 200
        tl_payload = res_timeline.json()
        assert "lanes" in tl_payload

        # Step 11: Cleanup Dataset
        res_del = client.delete(f"/api/datasets/{dataset_id}")
        assert res_del.status_code == 200
        assert res_del.json()["removed"] is True
