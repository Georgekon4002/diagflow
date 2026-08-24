"""
Test suite for Optimistic Locking concurrency protection in DiagFlow.
"""
import pytest
from unittest.mock import patch, MagicMock
from diagflow.services.slis_sync import push_exam_to_slis, push_selected_to_slis
import diagflow.db.diagflow_db as cfg_db

def test_optimistic_locking_mock_mode():
    """Verify that assigning an already synced exam with another diagnostician returns a conflict."""
    # When using mock DB, if row is already assigned & synced to Diag 1, trying to push Diag 2 yields conflict
    with patch("diagflow.services.slis_sync.settings.use_mock_slis_db", True):
        with patch("diagflow.services.slis_sync._get_db") as mock_get_db:
            mock_con = MagicMock()
            # Simulate exam already assigned to "ΙΩΑΝΝΗΣ ΠΑΠΑΔΟΠΟΥΛΟΣ" (ID 100) and synced
            mock_con.execute.return_value.fetchone.return_value = {
                "category": "CT",
                "extracode": "2781234",
                "diagnostis": 100,
                "code": "ΙΩΑΝΝΗΣ ΠΑΠΑΔΟΠΟΥΛΟΣ",
                "slis_synced_at": "2026-08-20T10:00:00"
            }
            mock_get_db.return_value = mock_con

            # Try to push assignment for Diag 200 ("ΜΑΡΙΑ ΓΕΩΡΓΙΟΥ")
            res = push_exam_to_slis(exammoreid=9999, diagnostician_id=200, diagnostician_name="ΜΑΡΙΑ ΓΕΩΡΓΙΟΥ")

            assert res["success"] is False
            assert res.get("conflict") is True
            assert "ΙΩΑΝΝΗΣ ΠΑΠΑΔΟΠΟΥΛΟΣ" in res["error"]


def test_reassign_force_override_mock_mode():
    """Verify that when force=True, reassigning an already synced exam in mock mode overrides without conflict."""
    with patch("diagflow.services.slis_sync.settings.use_mock_slis_db", True):
        with patch("diagflow.services.slis_sync._get_db") as mock_get_db:
            mock_con = MagicMock()
            mock_con.execute.return_value.fetchone.return_value = {
                "category": "CT",
                "extracode": "2781234",
                "diagnostis": 100,
                "code": "ΙΩΑΝΝΗΣ ΠΑΠΑΔΟΠΟΥΛΟΣ",
                "slis_synced_at": "2026-08-20T10:00:00"
            }
            mock_get_db.return_value = mock_con

            with patch("diagflow.db.diagflow_db.mark_local_assignment_synced"):
                with patch("diagflow.db.diagflow_db.log_assignment"):
                    res = push_exam_to_slis(
                        exammoreid=9999,
                        diagnostician_id=200,
                        diagnostician_name="ΜΑΡΙΑ ΓΕΩΡΓΙΟΥ",
                        force=True,
                    )

                    assert res["success"] is True
                    assert res["diagnostician_id"] == 200
                    # Ensure update query was executed
                    mock_con.execute.assert_any_call(
                        "UPDATE slis_exams SET diagnostis = ?, code = ?, slis_synced_at = ? WHERE exammoreid = ?",
                        (200, "ΜΑΡΙΑ ΓΕΩΡΓΙΟΥ", res["synced_at"], 9999)
                    )


def test_reassign_force_override_mssql_mode():
    """Verify that when force=True in MSSQL mode, direct UPDATE is executed without optimistic WHERE conditions."""
    with patch("diagflow.services.slis_sync.settings.use_mock_slis_db", False):
        with patch("diagflow.services.slis_sync.settings.slis_db_connection_string", "mssql+pyodbc://fake"):
            with patch("sqlalchemy.create_engine") as mock_engine:
                mock_conn = MagicMock()
                mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn

                mock_update_result = MagicMock()
                mock_update_result.rowcount = 1
                mock_conn.execute.return_value = mock_update_result

                with patch("diagflow.db.diagflow_db.mark_local_assignment_synced"):
                    with patch("diagflow.db.diagflow_db.log_assignment"):
                        res = push_exam_to_slis(
                            exammoreid=20697971,
                            diagnostician_id=200,
                            diagnostician_name="ΜΑΡΙΑ ΓΕΩΡΓΙΟΥ",
                            force=True,
                        )

                        assert res["success"] is True
                        assert res["diagnostician_id"] == 200


def test_slis_reassign_api_endpoint():
    """Verify that POST /api/slis/reassign passes force=True and successfully overrides assignment."""
    from fastapi.testclient import TestClient
    from diagflow.main import app

    client = TestClient(app)
    with patch("diagflow.services.slis_sync.push_exam_to_slis") as mock_push:
        mock_push.return_value = {
            "success": True,
            "exammoreid": 12345,
            "diagnostician_id": 5,
            "diagnostician_name": "ΔΗΜΗΤΡΙΟΣ ΠΑΠΑΔΟΠΟΥΛΟΣ",
        }

        resp = client.post("/api/slis/reassign", json={
            "exammoreid": 12345,
            "diagnostician_id": 5,
            "diagnostician_name": "ΔΗΜΗΤΡΙΟΣ ΠΑΠΑΔΟΠΟΥΛΟΣ",
        })

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        mock_push.assert_called_once_with(
            exammoreid=12345,
            diagnostician_id=5,
            diagnostician_name="ΔΗΜΗΤΡΙΟΣ ΠΑΠΑΔΟΠΟΥΛΟΣ",
            force=True,
        )

