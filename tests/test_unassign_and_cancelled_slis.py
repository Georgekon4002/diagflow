"""
Test suite for Unassign endpoints and Cancelled/Deleted exam handling in DiagFlow.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from diagflow.main import app
from diagflow.services.slis_sync import push_exam_to_slis, push_selected_to_slis
import diagflow.db.diagflow_db as cfg_db

client = TestClient(app)

def test_push_exam_cancelled_in_slis_mssql_mode():
    """Verify that if an exam was cancelled/deleted in Slis (exammore has no row), push_exam_to_slis auto-purges it."""
    with patch("diagflow.services.slis_sync.settings.use_mock_slis_db", False):
        with patch("diagflow.services.slis_sync.settings.slis_db_connection_string", "mssql+pyodbc://fake"):
            with patch("sqlalchemy.create_engine") as mock_engine:
                mock_conn = MagicMock()
                mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn

                # 1. UPDATE exammore returns rowcount = 0
                mock_update_result = MagicMock()
                mock_update_result.rowcount = 0

                # 2. SELECT diagnostisid FROM exammore returns None (exam not found/deleted)
                mock_select_result = MagicMock()
                mock_select_result.fetchone.return_value = None

                mock_conn.execute.side_effect = [mock_update_result, mock_select_result]

                with patch("diagflow.db.diagflow_db.delete_local_assignment") as mock_delete:
                    res = push_exam_to_slis(exammoreid=20697971, diagnostician_id=1, diagnostician_name="ΔΟΚΙΜΗ")

                    assert res["success"] is False
                    assert res.get("cancelled_in_slis") is True
                    assert "ακυρωθεί/διαγραφεί" in res["error"]
                    mock_delete.assert_called_once_with(20697971)


def test_push_exam_conflict_in_mssql_mode_uses_local_diag_lookup():
    """Verify that when a conflict exists in Slis, it looks up diagnostician name locally without querying invalid table."""
    with patch("diagflow.services.slis_sync.settings.use_mock_slis_db", False):
        with patch("diagflow.services.slis_sync.settings.slis_db_connection_string", "mssql+pyodbc://fake"):
            with patch("sqlalchemy.create_engine") as mock_engine:
                mock_conn = MagicMock()
                mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn

                # 1. UPDATE exammore returns rowcount = 0
                mock_update_result = MagicMock()
                mock_update_result.rowcount = 0

                # 2. SELECT diagnostisid returns (105,)
                mock_select_result = MagicMock()
                mock_select_result.fetchone.return_value = (105,)

                mock_conn.execute.side_effect = [mock_update_result, mock_select_result]

                with patch("diagflow.db.diagflow_db.get_diagnostician", return_value={"name": "ΝΙΚΟΣ ΠΑΠΑΔΑΚΗΣ"}):
                    res = push_exam_to_slis(exammoreid=20697971, diagnostician_id=1, diagnostician_name="ΔΟΚΙΜΗ")

                    assert res["success"] is False
                    assert res.get("conflict") is True
                    assert "ΝΙΚΟΣ ΠΑΠΑΔΑΚΗΣ" in res["error"]


def test_push_exam_cancelled_in_mock_mode():
    """Verify that if an exam is not found in mock_slis.db, it is recognized as cancelled and purged."""
    with patch("diagflow.services.slis_sync.settings.use_mock_slis_db", True):
        with patch("diagflow.services.slis_sync._get_db") as mock_get_db:
            mock_con = MagicMock()
            mock_con.execute.return_value.fetchone.return_value = None
            mock_get_db.return_value = mock_con

            with patch("diagflow.db.diagflow_db.delete_local_assignment") as mock_delete:
                res = push_exam_to_slis(exammoreid=88888, diagnostician_id=1, diagnostician_name="ΔΟΚΙΜΗ")

                assert res["success"] is False
                assert res.get("cancelled_in_slis") is True
                mock_delete.assert_called_once_with(88888)


def test_unassign_endpoints():
    """Test POST /api/assignments/unassign, POST /api/assignments/bulk-unassign, and DELETE /api/assignments/{id}."""
    with patch("diagflow.db.diagflow_db.delete_local_assignment", return_value=True) as mock_del:
        # 1. POST /api/assignments/unassign
        resp1 = client.post("/api/assignments/unassign", json={"exam_id": "12345"})
        assert resp1.status_code == 200
        assert resp1.json() == {"success": True, "exam_id": "12345"}
        mock_del.assert_called_with(12345)

        # 2. DELETE /api/assignments/{id}
        resp2 = client.delete("/api/assignments/12345")
        assert resp2.status_code == 200
        assert resp2.json() == {"success": True, "exam_id": "12345"}

        # 3. POST /api/assignments/bulk-unassign
        resp3 = client.post("/api/assignments/bulk-unassign", json={"exam_ids": ["12345", "67890"]})
        assert resp3.status_code == 200
        assert resp3.json()["success"] is True
        assert resp3.json()["unassigned_count"] == 2
        assert resp3.json()["unassigned_ids"] == [12345, 67890]


def test_dismissed_auto_assignment_not_reassigned():
    """Verify that when an exam is unassigned, it is added to dismissed list and does not get auto-reassigned."""
    from diagflow.services.assignment import _get_pending_exams_from_db

    # 1. Delete local assignment (records in dismissed_auto_assignments)
    cfg_db.delete_local_assignment(777777)
    dismissed = cfg_db.get_dismissed_auto_assignments()
    assert 777777 in dismissed

    # 2. When _get_pending_exams_from_db runs, verify auto-assignment is skipped for this exam
    with patch("diagflow.services.assignment.settings.use_mock_slis_db", True):
        with patch("diagflow.services.assignment._get_mock_db") as mock_get_db:
            mock_con = MagicMock()
            # Simulate exam matching exclusive doctor 'DOC99'
            mock_con.execute.return_value.fetchall.return_value = [{
                "exammoreid": 777777,
                "extracode": "999",
                "category": "MRI",
                "examname": "MRI BRAIN",
                "examnumcode": "1001",
                "fname": "ΓΕΩΡΓΙΟΣ",
                "lname": "ΠΑΠΑΔΟΠΟΥΛΟΣ",
                "wcode": "DOC99",
                "wname": "ΙΑΤΡΟΣ",
                "labcodeid": 1,
            }]
            mock_get_db.return_value = mock_con

            with patch("diagflow.db.diagflow_db.get_exclusive_partnerships", return_value={"DOC99": {"preferred_diagnostician_id": 1, "preferred_diagnostician_name": "DIAG"}}):
                with patch("diagflow.db.diagflow_db.upsert_local_assignment") as mock_upsert:
                    pending = _get_pending_exams_from_db()
                    # Verify upsert_local_assignment was NOT called because it was dismissed
                    mock_upsert.assert_not_called()
                    # Verify exam is returned in pending list instead
                    assert len(pending) == 1
                    assert pending[0]["exammoreid"] == 777777

    # 3. Clean up
    cfg_db.remove_dismissed_auto_assignment(777777)
    assert 777777 not in cfg_db.get_dismissed_auto_assignments()


def test_unassign_mssql_mode_never_crashes():
    """Verify that unassigning in MSSQL mode executes proper T-SQL and handles table creation gracefully without 500 errors."""
    with patch("diagflow.db.diagflow_db.settings.use_mock_slis_db", False):
        with patch("diagflow.db.diagflow_db._conn") as mock_conn_ctx:
            mock_con = MagicMock()
            mock_conn_ctx.return_value.__enter__.return_value = mock_con
            mock_con.execute.return_value.rowcount = 1

            # Delete assignment
            res = cfg_db.delete_local_assignment(20697971)
            assert res is True
            # Verify proper delete was executed on df_local_assignments
            mock_con.execute.assert_any_call("DELETE FROM df_local_assignments WHERE exammoreid = ?", (20697971,))


