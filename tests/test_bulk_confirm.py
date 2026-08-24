import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from diagflow.main import app
from diagflow.engine.pipeline import AssignmentSuggestion
from diagflow.api.routes import _suggestion_cache
import diagflow.db.diagflow_db as cfg_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    _suggestion_cache.clear()
    tbl = cfg_db._tbl("local_assignments")
    with cfg_db._conn() as conn:
        conn.execute(f"DELETE FROM {tbl}")
    yield
    _suggestion_cache.clear()
    with cfg_db._conn() as conn:
        conn.execute(f"DELETE FROM {tbl}")


def test_bulk_confirm_with_items_when_cache_empty():
    """Bulk confirm should succeed using explicit items even if _suggestion_cache is completely empty."""
    _suggestion_cache.clear()

    payload = {
        "items": [
            {"exam_id": "90001", "diagnostician_id": 1},
            {"exam_id": "90002", "diagnostician_id": 2},
        ]
    }

    response = client.post("/api/assignments/bulk-confirm", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["exam_id"] == "90001"
    assert data[0]["diagnostician_id"] == 1
    assert data[1]["exam_id"] == "90002"
    assert data[1]["diagnostician_id"] == 2

    # Check local assignments DB
    local = cfg_db.get_all_local_assignments()
    assert 90001 in local
    assert local[90001]["diagnostician_id"] == 1
    assert 90002 in local
    assert local[90002]["diagnostician_id"] == 2


def test_bulk_confirm_with_cached_suggestions():
    """Bulk confirm should succeed and evict cache when suggestions are present."""
    _suggestion_cache["90010"] = AssignmentSuggestion(
        exam_id="90010",
        patient_id="P10",
        exam_summary="MRI Brain",
        suggested_diagnostician_id=3,
        suggested_diagnostician_name="DIAG_3",
        confidence_score=0.95,
        score_breakdown=[],
        alternatives=[],
        rules_fired=[],
        filter_results={},
        solver_status="optimal",
        pipeline_timestamp="2026-08-24T12:00:00",
    )

    payload = {
        "exam_ids": ["90010"]
    }

    response = client.post("/api/assignments/bulk-confirm", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["exam_id"] == "90010"
    assert data[0]["diagnostician_id"] == 3

    assert "90010" not in _suggestion_cache
    assert 90010 not in _suggestion_cache


def test_bulk_confirm_fallback_to_on_the_fly_generation():
    """If cache is empty and no explicit item is provided, on-the-fly suggestion generation should run."""
    _suggestion_cache.clear()

    mock_exam = {
        "exam_id": "90020",
        "exammoreid": 90020,
        "patient_id": "P20",
        "patient_name": "Test Patient",
        "modality": "MRI",
        "category": "MRI",
        "body_part": "BRAIN",
        "examnumcode": "101",
        "examname": "MRI Brain",
        "lab_id": "1",
        "lab_name": "LAB",
        "issuing_doctor_id": "DOC1",
        "issuing_doctor_name": "Dr. Test",
        "comments": "",
        "diagnostis": None,
        "code": "",
    }

    mock_suggestion = AssignmentSuggestion(
        exam_id="90020",
        patient_id="P20",
        exam_summary="MRI Brain",
        suggested_diagnostician_id=4,
        suggested_diagnostician_name="DIAG_4",
        confidence_score=0.9,
        score_breakdown=[],
        alternatives=[],
        rules_fired=[],
        filter_results={},
        solver_status="optimal",
        pipeline_timestamp="2026-08-24T12:00:00",
    )

    with patch("diagflow.services.assignment.AssignmentService.get_pending_exams", return_value=[mock_exam]), \
         patch("diagflow.services.assignment.AssignmentService.get_assigned_exams", return_value=[]), \
         patch("diagflow.api.routes._generate_suggestion_for_exam", new_callable=AsyncMock, return_value=mock_suggestion):

        payload = {
            "exam_ids": ["90020"]
        }
        response = client.post("/api/assignments/bulk-confirm", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["exam_id"] == "90020"
        assert data[0]["diagnostician_id"] == 4
