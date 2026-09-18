"""
Comprehensive test suite for Arrow + Parquet Historian Storage.

Test Requirements Covered:
1. Canonical DataFrame -> historian write
2. Historian file/storage creation
3. Historian read-back
4. Schema correctness
5. timestamp_utc preservation
6. equipment_id preservation
7. canonical role preservation
8. numeric value preservation
9. multiple equipment partitioning
10. multiple imports / duplicate behavior
11. time range preservation
12. existing project test CSV
"""

from __future__ import annotations

from datetime import datetime
import io
from pathlib import Path
import tempfile
import polars as pl
import pyarrow as pa
import pytest

from app.historian import (
    HistorianService,
    HistorianStorage,
    get_equipment_meta,
    read_all_telemetry,
    read_equipment_arrow_table,
    read_equipment_telemetry,
    write_canonical_telemetry_to_historian,
)
from app.mapping.mapper import map_columns
from app.transformation.canonical import (
    transform_csv_canonical,
    transform_to_canonical,
)
from app.datasets.manager import DatasetManager


@pytest.fixture
def temp_storage():
    """Create a temporary HistorianStorage instance isolated to a temp directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = HistorianStorage(root_dir=tmpdir)
        yield storage


# ============================================================
# TEST 1 & 2: WRITE CANONICAL TELEMETRY TO HISTORIAN & FILE CREATION
# ============================================================

def test_canonical_df_to_historian_write(temp_storage):
    """
    Test that a CanonicalTransformResult writes into partitioned Parquet storage.
    """
    csv_data = """timestamp,equipment_id,supply_air_temp_c,fan_status
2026-07-01 12:00:00,AHU_01,20.0,1.0
2026-07-01 12:15:00,AHU_01,21.0,1.0
2026-07-01 12:30:00,AHU_01,22.0,0.0
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)
    can_res = transform_to_canonical(raw_df=df, mapping_result=mapping)

    written_meta = write_canonical_telemetry_to_historian(
        canonical_result=can_res,
        storage=temp_storage,
        building_id="BLDG_100",
    )

    assert len(written_meta) == 1
    meta = written_meta[0]
    assert meta.building_id == "BLDG_100"
    assert meta.equipment_id == "AHU_01"
    assert meta.row_count == 3
    assert "sat" in meta.telemetry_roles
    assert "fan_status" in meta.telemetry_roles

    # Verify physical file existence
    pq_path = temp_storage.get_parquet_path("BLDG_100", "AHU_01")
    meta_path = temp_storage.get_meta_path("BLDG_100", "AHU_01")
    assert pq_path.is_file()
    assert meta_path.is_file()


# ============================================================
# TEST 3 & 4: HISTORIAN READ-BACK & SCHEMA CORRECTNESS
# ============================================================

def test_historian_read_back_and_schema(temp_storage):
    """
    Test reading back telemetry from Parquet and checking schema data types.
    """
    csv_data = """timestamp,equipment_id,supply_air_temp_c,duct_static_pressure_pa
2026-07-01 12:00:00,AHU_01,20.0,250.0
2026-07-01 12:15:00,AHU_01,21.0,250.0
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)
    can_res = transform_to_canonical(raw_df=df, mapping_result=mapping)

    write_canonical_telemetry_to_historian(
        can_res,
        storage=temp_storage,
        building_id="BLDG_100",
    )

    # Read back into Polars DataFrame
    read_df = read_equipment_telemetry("BLDG_100", "AHU_01", storage=temp_storage)
    assert read_df.height == 2
    assert "timestamp_utc" in read_df.columns
    assert "equipment_id" in read_df.columns
    assert "sat" in read_df.columns
    assert "duct_static" in read_df.columns

    # Read back into PyArrow Table
    arrow_table = read_equipment_arrow_table("BLDG_100", "AHU_01", storage=temp_storage)
    assert isinstance(arrow_table, pa.Table)
    assert arrow_table.num_rows == 2
    schema = arrow_table.schema

    # Check Arrow schema types
    assert schema.field("timestamp_utc").type == pa.timestamp("us")
    assert schema.field("equipment_id").type == pa.string()
    assert schema.field("sat").type == pa.float64()
    assert schema.field("duct_static").type == pa.float64()


# ============================================================
# TEST 5, 6, 7 & 8: VALUE & EXTENT PRESERVATION
# ============================================================

def test_value_and_metadata_preservation(temp_storage):
    """
    Test timestamp_utc, equipment_id, canonical roles, and numeric values are preserved exactly.
    """
    csv_data = """timestamp,equipment_id,Supply Air Temp (°C),Supply Fan Status,Occupancy Mode
2026-07-01 00:00:00,AHU_NORTH,20.0,1.0,occupied
2026-07-01 01:00:00,AHU_NORTH,25.0,0.0,unoccupied
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)
    can_res = transform_to_canonical(raw_df=df, mapping_result=mapping)

    write_canonical_telemetry_to_historian(
        can_res,
        storage=temp_storage,
        building_id="BLDG_MAIN",
    )

    read_df = read_equipment_telemetry("BLDG_MAIN", "AHU_NORTH", storage=temp_storage)

    # 5. timestamp_utc preservation
    assert str(read_df["timestamp_utc"][0]) == "2026-07-01 00:00:00"
    assert str(read_df["timestamp_utc"][1]) == "2026-07-01 01:00:00"

    # 6. equipment_id preservation
    assert read_df["equipment_id"].to_list() == ["AHU_NORTH", "AHU_NORTH"]

    # 7. canonical roles preservation
    assert "sat" in read_df.columns
    assert "fan_status" in read_df.columns
    assert "occ_mode" in read_df.columns

    # 8. numeric values preservation (20°C -> 68°F, 25°C -> 77°F)
    assert pytest.approx(read_df["sat"][0], 0.01) == 68.0
    assert pytest.approx(read_df["sat"][1], 0.01) == 77.0
    assert read_df["fan_status"].to_list() == [1.0, 0.0]
    assert read_df["occ_mode"].to_list() == ["occupied", "unoccupied"]


# ============================================================
# TEST 9: MULTIPLE EQUIPMENT PARTITIONING
# ============================================================

def test_multiple_equipment_partitioning(temp_storage):
    """
    Test that a single CSV containing multiple equipment IDs writes distinct partition directories.
    """
    csv_data = """timestamp,equipment_id,supply_air_temp_c
2026-07-01 00:00:00,AHU_01,20.0
2026-07-01 00:15:00,AHU_01,20.5
2026-07-01 00:00:00,AHU_02,22.0
2026-07-01 00:15:00,AHU_02,22.5
2026-07-01 00:00:00,AHU_03,24.0
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)
    can_res = transform_to_canonical(raw_df=df, mapping_result=mapping)

    service = HistorianService(storage=temp_storage)
    written = service.ingest_canonical_result(can_res, building_id="CAMPUS_01")

    assert len(written) == 3
    equip_ids = {m.equipment_id for m in written}
    assert equip_ids == {"AHU_01", "AHU_02", "AHU_03"}

    # Verify separate queries
    df_1 = service.get_telemetry("CAMPUS_01", "AHU_01")
    df_2 = service.get_telemetry("CAMPUS_01", "AHU_02")
    df_3 = service.get_telemetry("CAMPUS_01", "AHU_03")

    assert df_1.height == 2
    assert df_2.height == 2
    assert df_3.height == 1


# ============================================================
# TEST 10: MULTIPLE IMPORTS / IDEMPOTENT RE-IMPORT BEHAVIOR
# ============================================================

def test_duplicate_reimport_behavior(temp_storage):
    """
    Test that re-importing the same dataset updates partition atomically without file corruption.
    """
    csv_data = """timestamp,equipment_id,supply_air_temp_c
2026-07-01 00:00:00,AHU_REIMPORT,20.0
2026-07-01 00:15:00,AHU_REIMPORT,20.5
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)
    can_res = transform_to_canonical(raw_df=df, mapping_result=mapping)

    service = HistorianService(storage=temp_storage)

    # First import
    service.ingest_canonical_result(can_res, building_id="BLDG_X")
    summary1 = service.get_summary()
    assert summary1.total_rows == 2

    # Re-import identical data
    service.ingest_canonical_result(can_res, building_id="BLDG_X")
    summary2 = service.get_summary()
    assert summary2.total_rows == 2
    assert summary2.total_equipment == 1

    df_read = service.get_telemetry("BLDG_X", "AHU_REIMPORT")
    assert df_read.height == 2


# ============================================================
# TEST 11: TIME RANGE PRESERVATION & FILTERING
# ============================================================

def test_time_range_filtering(temp_storage):
    """
    Test that time range is tracked in metadata and filtering by start/end time works.
    """
    csv_data = """timestamp,equipment_id,supply_air_temp_c
2026-07-01 00:00:00,AHU_TIME,20.0
2026-07-01 01:00:00,AHU_TIME,21.0
2026-07-01 02:00:00,AHU_TIME,22.0
2026-07-01 03:00:00,AHU_TIME,23.0
2026-07-01 04:00:00,AHU_TIME,24.0
"""
    df = pl.read_csv(io.StringIO(csv_data))
    mapping = map_columns(df.columns)
    can_res = transform_to_canonical(raw_df=df, mapping_result=mapping)

    service = HistorianService(storage=temp_storage)
    service.ingest_canonical_result(can_res, building_id="BLDG_TIME")

    meta = get_equipment_meta("BLDG_TIME", "AHU_TIME", storage=temp_storage)
    assert meta is not None
    assert "2026-07-01 00:00:00" in meta.min_timestamp
    assert "2026-07-01 04:00:00" in meta.max_timestamp

    # Query with time filter
    filtered_df = service.get_telemetry(
        "BLDG_TIME",
        "AHU_TIME",
        start_time="2026-07-01 01:00:00",
        end_time="2026-07-01 03:00:00",
    )
    assert filtered_df.height == 3
    assert filtered_df["timestamp_utc"].min() == datetime(2026, 7, 1, 1, 0, 0)
    assert filtered_df["timestamp_utc"].max() == datetime(2026, 7, 1, 3, 0, 0)


# ============================================================
# TEST 12: REAL PROJECT TEST CSV TO HISTORIAN ROUNDTRIP
# ============================================================

def test_real_project_csv_historian_roundtrip(temp_storage):
    """
    Test real CSV dataset (ahu_multi_point_sample.csv) roundtrip through Historian.
    """
    sample_path = Path(r"D:\fdd\test_data\ahu_multi_point_sample.csv")
    assert sample_path.exists()

    can_res = transform_csv_canonical(sample_path)
    service = HistorianService(storage=temp_storage)

    written = service.ingest_canonical_result(
        can_res,
        building_id="BUILDING_OFFICE",
    )

    assert len(written) == 1
    meta = written[0]
    assert meta.equipment_id == "AHU-HPE-01"
    assert meta.row_count == 96
    assert len(meta.telemetry_roles) > 10

    # Read back
    read_df = service.get_telemetry("BUILDING_OFFICE", "AHU-HPE-01")
    assert read_df.height == 96
    assert "sat" in read_df.columns
    assert "rat" in read_df.columns
    assert "duct_static" in read_df.columns
    assert "co2" in read_df.columns

    # Check DatasetManager integration
    manager = DatasetManager(historian=service)
    ds_info = manager.add_csv(sample_path)
    ingest_meta = manager.ingest_to_historian(ds_info.dataset_id, building_id="BUILDING_OFFICE")
    assert len(ingest_meta) == 1
    assert ingest_meta[0].equipment_id == "AHU-HPE-01"
