import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
CSV1 = Path(r"D:\openfdd-test-data\ahu_01_sample_sensor_data.csv")
CSV2 = Path(r"D:\openfdd-test-data\F2_AHU02_North.csv")

def test_multi_csv_upload():
    with open(CSV1, "rb") as f1, open(CSV2, "rb") as f2:
        response = client.post(
            "/api/datasets/upload",
            files=[
                ("files", (CSV1.name, f1, "text/csv")),
                ("files", (CSV2.name, f2, "text/csv")),
            ],
        )
    assert response.status_code == 201
    data = response.json()
    assert len(data["datasets"]) == 2
    filenames = {d["file_name"] for d in data["datasets"]}
    assert CSV1.name in filenames
    assert CSV2.name in filenames
