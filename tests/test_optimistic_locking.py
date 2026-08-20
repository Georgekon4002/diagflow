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
