import pytest
from fastapi.testclient import TestClient
from app.main import app


def test_threshold_metadata_endpoint():
    """Verify that the /api/fdd/threshold-metadata endpoint returns the verified catalog."""
    client = TestClient(app)
    res = client.get("/api/fdd/threshold-metadata")
    assert res.status_code == 200

    data = res.json()
    assert "categories" in data
    assert len(data["categories"]) == 12
    assert data["total_parameters"] == 93
    assert data["tier_a_count"] == 30
    assert data["tier_b_count"] == 63

    # Check presets
    assert "Standard" in data["presets"]
    assert "Sensitive" in data["presets"]
    assert "Lenient" in data["presets"]

    # Verify category structure
    for cat in data["categories"]:
        assert "name" in cat
        assert "display_order" in cat
        assert "tier" in cat

    # Verify parameter structure
    assert len(data["parameters"]) == 93
    for p in data["parameters"]:
        assert "param_name" in p or "name" in p

