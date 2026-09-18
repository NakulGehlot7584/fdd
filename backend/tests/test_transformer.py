import pytest
from pathlib import Path
from app.ingestion.csv.transformer import transform_csv, _infer_source_unit, _is_conversion_required

TEST_CSV = Path(r"D:\openfdd-test-data\ahu_01_sample_sensor_data.csv")

def test_unit_inference():
    assert _infer_source_unit("temp (deg C)") == "°C"
    assert _infer_source_unit("sat_temp_c") == "°C"
    assert _infer_source_unit("zone_temp_f") == "°F"
    assert _infer_source_unit("static_pressure (in_wc)") == "in_wc"
    assert _infer_source_unit("damper_pct") == "%"
    assert _infer_source_unit("co2_ppm") == "ppm"
    assert _infer_source_unit("unlabeled_column") is None

def test_conversion_requirement():
    assert _is_conversion_required("°C", "°F") is True
    assert _is_conversion_required("°F", "°F") is False
    assert _is_conversion_required("Pa", "in_wc") is True
    assert _is_conversion_required(None, "°F") is False

def test_transform_csv_real_data():
    assert TEST_CSV.exists()
    result = transform_csv(TEST_CSV, canonicalize_names=False)
    assert result.file_name == "ahu_01_sample_sensor_data.csv"
    assert result.dataframe.height > 0
    assert result.dataframe.width > 0
    assert result.mapped_column_count > 0
    assert len(result.columns) == result.dataframe.width
    assert result.preflight_report.get("valid") is True
