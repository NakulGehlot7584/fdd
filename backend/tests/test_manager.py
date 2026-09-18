import pytest
from pathlib import Path
from app.datasets.manager import DatasetManager

TEST_CSV = Path(r"D:\openfdd-test-data\ahu_01_sample_sensor_data.csv")

def test_dataset_manager_lifecycle():
    manager = DatasetManager()
    assert len(manager.list_datasets()) == 0

    info = manager.add_csv(TEST_CSV)
    assert info.file_name == "ahu_01_sample_sensor_data.csv"
    assert info.dataset_id is not None
    assert len(manager.list_datasets()) == 1

    # Idempotent re-registration of same path
    info2 = manager.add_csv(TEST_CSV)
    assert info2.dataset_id == info.dataset_id
    assert len(manager.list_datasets()) == 1

    # Lookup
    fetched = manager.get_dataset(info.dataset_id)
    assert fetched is not None
    assert fetched.dataset_id == info.dataset_id

    result = manager.get_dataset_result(info.dataset_id)
    assert result is not None
    assert result.file_name == "ahu_01_sample_sensor_data.csv"

    # Removal
    removed = manager.remove_dataset(info.dataset_id)
    assert removed is True
    assert len(manager.list_datasets()) == 0
    assert manager.get_dataset(info.dataset_id) is None
