"""
Comprehensive test suite for Canonical Data Transformation.

Test Requirements Covered:
A. Normal HVAC CSV: raw columns successfully become canonical roles.
B. Timestamp transformation: timestamp becomes canonical timestamp representation.
C. Unit conversion: detected conversion is applied correctly.
D. Missing values: null/missing telemetry does not crash transformation.
E. Unmapped columns: unmapped source columns remain traceable.
F. Metadata: timestamp/equipment_id are not incorrectly mapped as HVAC telemetry roles.
G. Multiple canonical roles: several mapped columns are transformed correctly together.
H. Existing test CSVs: run transformation against project's existing test data.
"""

from __future__ import annotations

from pathlib import Path
import io
import polars as pl
import pytest

from app.mapping.mapper import map_columns
from app.transformation.canonical import (
    CanonicalTransformResult,
    transform_csv_canonical,
    transform_to_canonical,
)
from app.transformation.units import (
    apply_unit_conversion,
    _celsius_to_fahrenheit,
    _pascal_to_in_wc,
)
from app.ingestion.csv.transformer import transform_csv
from app.datasets.manager import DatasetManager


# ============================================================
# TEST A: NORMAL HVAC CSV TRANSFORMATION
# ============================================================

def test_normal_hvac_csv_transformation():
    """
    Test that a standard HVAC CSV transforms raw columns into canonical roles.
    """
    csv_data = """timestamp,Supply Air Temp (°C),Supply Air Setpoint (°C),Supply Fan Status
2026-07-01 12:00:00,20.0,18.0,1
2026-07-01 12:15:00,21.0,18.0,1
2026-07-01 12:30:00,22.0,18.0,0
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)

    result = transform_to_canonical(
        raw_df=df,
        mapping_result=mapping,
        file_name="ahu_test.csv",
        default_equipment_id="AHU_01",
    )

    assert isinstance(result, CanonicalTransformResult)
    assert "timestamp_utc" in result.canonical_df.columns
    assert "equipment_id" in result.canonical_df.columns
    assert "sat" in result.canonical_df.columns
    assert "sat_sp" in result.canonical_df.columns
    assert "fan_status" in result.canonical_df.columns

    # Verify rows count
    assert result.row_count == 3
    assert result.canonical_df["equipment_id"][0] == "AHU_01"


# ============================================================
# TEST B: TIMESTAMP TRANSFORMATION
# ============================================================

def test_timestamp_canonical_representation():
    """
    Test that timestamp strings (ISO8601, AM/PM, IST/UTC) convert to canonical Datetime.
    """
    csv_data = """timestamp,discharge_temp
01-Jul-26 12:00:00 AM IST,68.0
01-Jul-26 12:15:00 AM IST,68.5
01-Jul-26 12:30:00 AM IST,69.0
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)
    result = transform_to_canonical(raw_df=df, mapping_result=mapping)

    assert "timestamp_utc" in result.canonical_df.columns
    ts_series = result.canonical_df["timestamp_utc"]
    assert ts_series.dtype == pl.Datetime
    assert ts_series.null_count() == 0
    assert str(ts_series[0]) == "2026-07-01 00:00:00"


# ============================================================
# TEST C: UNIT CONVERSIONS APPLIED
# ============================================================

def test_unit_conversion_celsius_to_fahrenheit():
    """
    Test that °C to °F conversion is detected and applied correctly: (C * 9/5) + 32.
    """
    csv_data = """timestamp,Supply Air Temp (°C)
2026-07-01 00:00:00,0.0
2026-07-01 01:00:00,20.0
2026-07-01 02:00:00,100.0
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)
    result = transform_to_canonical(raw_df=df, mapping_result=mapping)

    assert "sat" in result.canonical_df.columns
    sat_values = result.canonical_df["sat"].to_list()

    # 0°C -> 32°F, 20°C -> 68°F, 100°C -> 212°F
    assert pytest.approx(sat_values[0], 0.01) == 32.0
    assert pytest.approx(sat_values[1], 0.01) == 68.0
    assert pytest.approx(sat_values[2], 0.01) == 212.0

    # Verify conversion audit record
    assert len(result.conversions_applied) == 1
    conv = result.conversions_applied[0]
    assert conv.canonical_role == "sat"
    assert conv.source_unit == "°C"
    assert conv.canonical_unit == "°F"


def test_unit_conversion_pascal_to_in_wc():
    """
    Test that Pa to in_wc conversion is applied correctly.
    """
    csv_data = """timestamp,duct_static_pressure (Pa)
2026-07-01 00:00:00,248.84
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)
    result = transform_to_canonical(raw_df=df, mapping_result=mapping)

    assert "duct_static" in result.canonical_df.columns
    val = result.canonical_df["duct_static"][0]
    assert pytest.approx(val, 0.01) == 1.0


# ============================================================
# TEST D: MISSING AND INVALID NUMERIC VALUES
# ============================================================

def test_missing_and_invalid_numeric_values():
    """
    Test that missing values, NaN, sentinels, and invalid strings do not crash transformation.
    """
    csv_data = """timestamp,supply_air_temp_c,fan_status
2026-07-01 00:00:00,22.5,true
2026-07-01 01:00:00,nan,false
2026-07-01 02:00:00,null,0
2026-07-01 03:00:00,N/A,1
2026-07-01 04:00:00,INVALID_TEXT,off
2026-07-01 05:00:00,,on
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)
    result = transform_to_canonical(raw_df=df, mapping_result=mapping)

    assert result.row_count == 6
    sat_series = result.canonical_df["sat"]
    fan_series = result.canonical_df["fan_status"]

    # First row is valid: (22.5 * 9/5) + 32 = 72.5
    assert pytest.approx(sat_series[0], 0.01) == 72.5
    # Subsequent rows with dirty values become null without crashing
    assert sat_series[1] is None
    assert sat_series[2] is None
    assert sat_series[3] is None
    assert sat_series[4] is None
    assert sat_series[5] is None

    # Fan statuses parsed properly: true=1, false=0, 0=0, 1=1, off=0, on=1
    assert fan_series.to_list() == [1.0, 0.0, 0.0, 1.0, 0.0, 1.0]


# ============================================================
# TEST E: UNMAPPED COLUMNS TRACEABILITY
# ============================================================

def test_unmapped_columns_traceability():
    """
    Test that unmapped columns remain fully traceable in transformation schema.
    """
    csv_data = """timestamp,sat_temp,unmapped_maintenance_flag,custom_vendor_code
2026-07-01 00:00:00,65.0,OK,9921
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)
    result = transform_to_canonical(raw_df=df, mapping_result=mapping)

    # Telemetry table contains sat
    assert "sat" in result.canonical_df.columns
    assert "unmapped_maintenance_flag" not in result.canonical_df.columns
    assert "custom_vendor_code" not in result.canonical_df.columns

    # Unmapped channels captured in schema
    unmapped_names = [u.source_column for u in result.schema.unmapped_channels]
    assert "unmapped_maintenance_flag" in unmapped_names
    assert "custom_vendor_code" in unmapped_names

    # Unmapped DataFrame access
    unmapped_df = result.get_unmapped_df()
    assert "unmapped_maintenance_flag" in unmapped_df.columns
    assert "custom_vendor_code" in unmapped_df.columns
    assert unmapped_df["unmapped_maintenance_flag"][0] == "OK"


# ============================================================
# TEST F: METADATA SEPARATION
# ============================================================

def test_metadata_isolation():
    """
    Test that timestamp and equipment_id are treated strictly as metadata,
    never mapped as HVAC telemetry roles.
    """
    csv_data = """timestamp,equipment_id,building_id,supply_air_temp
2026-07-01 00:00:00,AHU-01,BLDG-A,65.0
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)
    result = transform_to_canonical(raw_df=df, mapping_result=mapping)

    # Metadata fields identified
    meta_fields = result.schema.metadata_fields
    meta_names = [m.name for m in meta_fields]
    assert "timestamp_utc" in meta_names
    assert "equipment_id" in meta_names

    # Telemetry roles exclude metadata
    assert "timestamp_utc" not in result.telemetry_roles
    assert "equipment_id" not in result.telemetry_roles
    assert result.telemetry_roles == ["sat"]


# ============================================================
# TEST G: MULTIPLE CANONICAL ROLES COEXISTENCE
# ============================================================

def test_multiple_canonical_roles():
    """
    Test transforming multiple HVAC roles simultaneously with different units and types.
    """
    csv_data = """timestamp,SAT (°C),RAT (°C),OAT (°C),Fan Spd (%),Duct Static (Pa),Cooling Valve (%),CO2 (ppm)
2026-07-01 00:00:00,18.0,24.0,30.0,85.0,250.0,45.0,600.0
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)
    result = transform_to_canonical(raw_df=df, mapping_result=mapping)

    expected_roles = {"sat", "rat", "oa_t", "fan_cmd", "duct_static", "clg_valve_pct", "co2"}
    for role in expected_roles:
        assert role in result.canonical_df.columns

    # SAT: 18°C -> 64.4°F
    assert pytest.approx(result.canonical_df["sat"][0], 0.1) == 64.4
    # RAT: 24°C -> 75.2°F
    assert pytest.approx(result.canonical_df["rat"][0], 0.1) == 75.2
    # OAT: 30°C -> 86.0°F
    assert pytest.approx(result.canonical_df["oa_t"][0], 0.1) == 86.0
    # Fan command: 85%
    assert result.canonical_df["fan_cmd"][0] == 85.0
    # Duct static: 250 Pa -> ~1.003 in_wc
    assert pytest.approx(result.canonical_df["duct_static"][0], 0.01) == 1.0036
    # CO2: 600 ppm
    assert result.canonical_df["co2"][0] == 600.0


# ============================================================
# TEST H: REAL TEST DATASET TRANSFORMATION
# ============================================================

def test_real_dataset_transformation():
    """
    Run canonical transformation against the project's real test data file ahu_multi_point_sample.csv.
    """
    sample_path = Path(r"D:\fdd\test_data\ahu_multi_point_sample.csv")
    assert sample_path.exists(), f"Sample test CSV not found at {sample_path}"

    result = transform_csv_canonical(sample_path)

    assert result.row_count > 0
    assert result.column_count > 0
    assert "timestamp_utc" in result.canonical_df.columns
    assert "equipment_id" in result.canonical_df.columns

    # Check key canonical telemetry columns
    assert "sat" in result.canonical_df.columns
    assert "sat_sp" in result.canonical_df.columns
    assert "rat" in result.canonical_df.columns
    assert "fan_cmd" in result.canonical_df.columns
    assert "fan_status" in result.canonical_df.columns
    assert "duct_static" in result.canonical_df.columns
    assert "co2" in result.canonical_df.columns

    # Check conversions were recorded (e.g. °C -> °F, Pa -> in_wc)
    conv_roles = [c.canonical_role for c in result.conversions_applied]
    assert "sat" in conv_roles
    assert "duct_static" in conv_roles

    # Check DatasetTransformResult to_canonical method
    res = transform_csv(sample_path)
    can_res = res.to_canonical()
    assert can_res.row_count == res.dataframe.height
    assert "sat" in can_res.canonical_df.columns


def test_manager_canonical_integration():
    """
    Test DatasetManager retrieving canonical telemetry for a registered dataset.
    """
    sample_path = Path(r"D:\fdd\test_data\ahu_multi_point_sample.csv")
    manager = DatasetManager()
    info = manager.add_csv(sample_path)

    can_result = manager.get_canonical_telemetry(info.dataset_id)
    assert can_result is not None
    assert can_result.row_count == info.row_count
    assert "timestamp_utc" in can_result.canonical_df.columns
    assert "sat" in can_result.canonical_df.columns
