import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_health_check_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_search_endpoint_valid_request():
    payload = {
        "destination": "Paris",
        "check_in": "2026-09-01",
        "check_out": "2026-09-05",
        "guests": 2,
        "rooms": 1
    }
    response = client.post("/search/hotels", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert "request_id" in data
    assert "results" in data
    assert "suppliers_queried" in data
    assert "suppliers_failed" in data
    assert isinstance(data["results"], list)
    assert len(data["results"]) > 0


def test_search_endpoint_validation_checkout_before_checkin():
    payload = {
        "destination": "Paris",
        "check_in": "2026-09-05",
        "check_out": "2026-09-01",  # Invalid! check_out is before check_in
        "guests": 2,
        "rooms": 1
    }
    response = client.post("/search/hotels", json=payload)
    assert response.status_code == 422  # Unprocessable Entity
    data = response.json()
    assert "detail" in data


def test_search_endpoint_validation_invalid_guests_and_rooms():
    payload = {
        "destination": "Paris",
        "check_in": "2026-09-01",
        "check_out": "2026-09-05",
        "guests": 0,  # Invalid! Must be > 0
        "rooms": 0   # Invalid! Must be > 0
    }
    response = client.post("/search/hotels", json=payload)
    assert response.status_code == 422
