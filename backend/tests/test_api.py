import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
TEST_CSV = Path(r"D:\openfdd-test-data\ahu_01_sample_sensor_data.csv")

def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_datasets_list_empty_or_valid():
    response = client.get("/api/datasets")
    assert response.status_code == 200
    data = response.json()
    assert "datasets" in data
    assert isinstance(data["datasets"], list)

def test_dataset_upload_and_inspect():
    with open(TEST_CSV, "rb") as f:
        response = client.post(
            "/api/datasets/upload",
            files=[("files", ("ahu_01_sample_sensor_data.csv", f, "text/csv"))],
        )
    assert response.status_code == 201
    data = response.json()
    assert len(data["datasets"]) >= 1
    ds_id = data["datasets"][0]["dataset_id"]

    # Detail
    detail_res = client.get(f"/api/datasets/{ds_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["file_name"] == "ahu_01_sample_sensor_data.csv"
    assert detail["row_count"] > 0
    assert len(detail["columns"]) > 0

    # Columns
    cols_res = client.get(f"/api/datasets/{ds_id}/columns")
    assert cols_res.status_code == 200
    cols = cols_res.json()
    assert "columns" in cols
    assert len(cols["columns"]) == len(detail["columns"])

    # Canonical Telemetry
    can_res = client.get(f"/api/datasets/{ds_id}/canonical")
    assert can_res.status_code == 200
    can_data = can_res.json()
    assert can_data["dataset_id"] == ds_id
    assert can_data["row_count"] > 0
    assert len(can_data["telemetry_roles"]) > 0
    assert "timestamp_utc" in [f["name"] for f in can_data["fields"]]
    assert len(can_data["preview_rows"]) > 0

    # Ingest to Historian
    ingest_res = client.post(f"/api/historian/ingest/{ds_id}?building_id=BLDG_API_TEST")
    assert ingest_res.status_code == 200
    ingest_data = ingest_res.json()
    assert ingest_data["dataset_id"] == ds_id
    assert ingest_data["equipment_written"] >= 1
    assert ingest_data["total_rows"] > 0

    # Historian Summary
    summary_res = client.get("/api/historian/summary")
    assert summary_res.status_code == 200
    summary_data = summary_res.json()
    assert summary_data["total_equipment"] >= 1
    assert summary_data["total_rows"] > 0

    # Historian Equipment List
    equip_res = client.get("/api/historian/equipment")
    assert equip_res.status_code == 200
    equip_data = equip_res.json()
    assert len(equip_data) >= 1
    equip_id = equip_data[0]["equipment_id"]
    bldg_id = equip_data[0]["building_id"]

    # Historian Telemetry Query
    hist_telemetry_res = client.get(f"/api/historian/equipment/{equip_id}?building_id={bldg_id}")
    assert hist_telemetry_res.status_code == 200
    telemetry_data = hist_telemetry_res.json()
    assert telemetry_data["row_count"] > 0
    assert "timestamp_utc" in telemetry_data["columns"]
    assert len(telemetry_data["preview_rows"]) > 0

    # Delete
    del_res = client.delete(f"/api/datasets/{ds_id}")
    assert del_res.status_code == 200
    assert del_res.json()["removed"] is True
