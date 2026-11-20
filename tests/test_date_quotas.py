"""
DiagFlow — Date-Based Quotas Unit Tests

Tests that candidate evaluation and scoring correctly select weekday-specific quotas
and evaluate counts based on the exam date.
"""

from datetime import date
import pytest
from unittest.mock import patch, MagicMock

from diagflow.engine.filters import CandidateDiagnostician, ExamContext
from diagflow.services.diagnostician import DiagnosticianService


@pytest.mark.anyio
async def test_candidate_quota_by_exam_weekday():
    """Verify that candidate evaluation selects the correct weekday quota for the exam date."""
    svc = DiagnosticianService()

    # 2026-08-28 is Friday; 2026-08-27 is Thursday; 2026-08-29 is Saturday
    mock_diags = [
        {
            "id": 1,
            "name": "Διαγνώστης Α.",
            "active": True,
            "can_ct": True,
            "can_mri": True,
            "quota_monday": 10,
            "quota_tuesday": 10,
            "quota_wednesday": 10,
            "quota_thursday": 14,
            "quota_friday": 18,
            "quota_saturday": 0,
            "quota_sunday": 0,
            "daily_quota": 10,
        }
    ]

    with patch("diagflow.db.diagflow_db.get_all_diagnosticians", return_value=mock_diags), \
         patch("diagflow.db.diagflow_db.get_absent_diagnostician_ids", return_value=set()), \
         patch("diagflow.db.diagflow_db.get_daily_assignment_counts", return_value={1: {"total": 4, "mri": 2, "ct": 2}}), \
         patch("diagflow.db.diagflow_db.get_all_skills_grouped", return_value={}), \
         patch("diagflow.db.diagflow_db.get_partnerships_by_doctor", return_value=[]):

        # Test Thursday exam
        cands_thursday = await svc.get_candidates_for_exam(
            exam_id="1001",
            modality="MRI",
            body_part="Abdomen",
            lab_id="1",
            issuing_doctor_id="DOC1",
            patient_id="PAT1",
            exam_date="2026-08-27",
        )
        assert len(cands_thursday) == 1
        assert cands_thursday[0].daily_quota == 14
        assert cands_thursday[0].current_day_count == 4

        # Test Friday exam
        cands_friday = await svc.get_candidates_for_exam(
            exam_id="1002",
            modality="MRI",
            body_part="Abdomen",
            lab_id="1",
            issuing_doctor_id="DOC1",
            patient_id="PAT1",
            exam_date="2026-08-28",
        )
        assert len(cands_friday) == 1
        assert cands_friday[0].daily_quota == 18

        # Test Saturday exam
        cands_saturday = await svc.get_candidates_for_exam(
            exam_id="1003",
            modality="MRI",
            body_part="Abdomen",
            lab_id="1",
            issuing_doctor_id="DOC1",
            patient_id="PAT1",
            exam_date="2026-08-29",
        )
        assert len(cands_saturday) == 1
        assert cands_saturday[0].daily_quota == 0


def test_dashboard_and_counts_by_date_consistency_by_exam_date():
    """
    Verify that counts are grouped strictly by examination date (visitdate) and NOT
    assignment date (assigned_at), and that get_dashboard_data() and
    get_all_assignment_counts_by_date() return identical counts & weekday quotas.
    """
    import diagflow.db.diagflow_db as cfg_db

    # Create a dedicated test diagnostician with distinct weekday quotas:
    # 2026-11-17 = Tuesday (quota 12), 2026-11-18 = Wednesday (quota 16), 2026-11-20 = Friday (quota 20)
    diag = cfg_db.create_diagnostician(
        name="TEST_DATE_QUOTA_DIAG",
        active=True,
        can_ct=True,
        can_mri=True,
        quota_monday=10,
        quota_tuesday=12,
        quota_wednesday=16,
        quota_thursday=14,
        quota_friday=20,
        quota_saturday=0,
        quota_sunday=0,
    )
    diag_id = diag["id"]

    try:
        # Stage two exams conducted on 2026-11-17 (assigned on 2026-11-20)
        cfg_db.upsert_local_assignment(
            exammoreid=990001,
            diagnostician_id=diag_id,
            diagnostician_name=diag["name"],
            assigned_at="2026-11-20T10:00:00",
            modality="ΜΑΓΝΗΤΙΚΗ",  # Greek modality must normalize to MRI
            extracode="ORD-17A",
            visitdate="2026-11-17",
        )
        cfg_db.upsert_local_assignment(
            exammoreid=990002,
            diagnostician_id=diag_id,
            diagnostician_name=diag["name"],
            assigned_at="2026-11-20T10:05:00",
            modality="ΑΞΟΝΙΚΗ",  # Greek modality must normalize to CT
            extracode="ORD-17B",
            visitdate="17/11/2026",  # DD/MM/YYYY must normalize to 2026-11-17
        )
        # Log one pushed exam conducted on 2026-11-18 (assigned on 2026-11-20)
        cfg_db.log_assignment(
            exammoreid=990003,
            diagnostician_id=diag_id,
            assigned_at="2026-11-20T11:00:00",
            modality="MRI",
            extracode="ORD-18A",
            visitdate="2026-11-18 09:30:00",
        )

        # 1. Verify get_all_assignment_counts_by_date groups by exam date, NOT assigned_at (2026-11-20)
        counts_by_date = cfg_db.get_all_assignment_counts_by_date()
        assert counts_by_date[diag_id].get("2026-11-17") == 2
        assert counts_by_date[diag_id].get("2026-11-18") == 1
        assert counts_by_date[diag_id].get("2026-11-20", 0) == 0

        # 2. Verify Dashboard for 2026-11-17 (Tuesday)
        dash_17 = cfg_db.get_dashboard_data("2026-11-17")
        card_17 = next((d for d in dash_17 if d["diagnostician_id"] == diag_id), None)
        assert card_17 is not None
        assert len(card_17["assigned_exam_ids"]) == 2
        assert card_17["daily_quota"] == 12  # Tuesday quota, NOT today's weekday
        assert card_17["modality_counts"]["MRI"] == 1
        assert card_17["modality_counts"]["CT"] == 1

        # 3. Verify Dashboard for 2026-11-18 (Wednesday)
        dash_18 = cfg_db.get_dashboard_data("2026-11-18")
        card_18 = next((d for d in dash_18 if d["diagnostician_id"] == diag_id), None)
        assert card_18 is not None
        assert len(card_18["assigned_exam_ids"]) == 1
        assert card_18["daily_quota"] == 16  # Wednesday quota

        # 4. Verify Dashboard for 2026-11-20 (assignment date) has NO card for this doctor
        dash_20 = cfg_db.get_dashboard_data("2026-11-20")
        card_20 = next((d for d in dash_20 if d["diagnostician_id"] == diag_id), None)
        assert card_20 is None

        # 5. Verify daily counts used by engine match dashboard exactly
        daily_17 = cfg_db.get_daily_assignment_counts("2026-11-17")
        assert daily_17[diag_id] == {"total": 2, "mri": 1, "ct": 1}
        daily_18 = cfg_db.get_daily_assignment_counts("2026-11-18")
        assert daily_18[diag_id] == {"total": 1, "mri": 1, "ct": 0}
    finally:
        cfg_db.delete_local_assignment(990001, record_dismissed=False)
        cfg_db.delete_local_assignment(990002, record_dismissed=False)
        with cfg_db._conn() as con:
            con.execute("DELETE FROM assignment_log WHERE exammoreid IN (990001, 990002, 990003)")
        cfg_db.delete_diagnostician(diag_id)


def test_get_table_columns_uses_information_schema_in_mssql_mode():
    """Verify _get_table_columns queries INFORMATION_SCHEMA.COLUMNS on MSSQL instead of SQLite PRAGMA."""
    import diagflow.db.diagflow_db as cfg_db

    mock_con = MagicMock()
    mock_con.mode = "mssql"
    mock_con.execute.return_value.fetchall.return_value = [
        {"name": "exammoreid"},
        {"name": "diagnostician_id"},
        {"name": "VISITDATE"},
    ]

    cols = cfg_db._get_table_columns(mock_con, "df_local_assignments")
    assert "visitdate" in cols
    assert "exammoreid" in cols
    executed_sql = mock_con.execute.call_args[0][0]
    assert "INFORMATION_SCHEMA.COLUMNS" in executed_sql
    assert "PRAGMA" not in executed_sql


def test_session_virtual_counts_scoped_by_exam_date():
    """Verify virtual session suggestion counts do not bleed across different exam dates or double-count."""
    from diagflow.api import routes

    routes._session_suggestions_by_exam.clear()
    try:
        routes._session_suggestions_by_exam["101"] = (7, "2026-11-17")
        routes._session_suggestions_by_exam["102"] = (7, "2026-11-17")
        routes._session_suggestions_by_exam["103"] = (7, "2026-11-18")

        # On 2026-11-17: 2 virtual suggestions for diag 7 (1 if excluding exam 101)
        assert routes._get_session_virtual_count(7, "2026-11-17") == 2
        assert routes._get_session_virtual_count(7, "2026-11-17", exclude_exam_id="101") == 1

        # On 2026-11-18: only 1 virtual suggestion (17/11 suggestions do NOT bleed over)
        assert routes._get_session_virtual_count(7, "2026-11-18") == 1

        # On 2026-11-19: 0 virtual suggestions
        assert routes._get_session_virtual_count(7, "2026-11-19") == 0

        # Clearing exam 101 decrements 2026-11-17 count to 1
        routes._clear_session_suggestion("101")
        assert routes._get_session_virtual_count(7, "2026-11-17") == 1
    finally:
        routes._session_suggestions_by_exam.clear()


def test_update_diagnostician_quota_from_999_to_4_and_back():
    """
    Regression test: updating a diagnostician's quota from 999 to 4 (and back to 999)
    must succeed even if legacy DB data had a non-0/1 truthy integer (like 999) in can_mri.
    """
    from fastapi.testclient import TestClient
    from diagflow.main import app
    from diagflow.api import routes
    import diagflow.db.diagflow_db as cfg_db

    diag = cfg_db.create_diagnostician(
        name="TEST_INF_QUOTA_DIAG",
        active=True,
        can_ct=True,
        can_mri=True,
        quota_monday=999,
        quota_tuesday=999,
        quota_wednesday=999,
        quota_thursday=999,
        quota_friday=999,
        quota_saturday=0,
        quota_sunday=0,
    )
    diag_id = diag["id"]

    # Simulate legacy corrupted non-0/1 boolean integer in DB
    with cfg_db._conn() as con:
        con.execute("UPDATE diagnosticians SET can_mri = 999 WHERE id = ?", (diag_id,))

    token = "test-admin-token-quota"
    routes._admin_sessions[token] = {"id": 1, "username": "admin", "role": "admin"}
    client = TestClient(app)

    try:
        # Reading from DB normalizes boolean flags cleanly
        loaded = cfg_db.get_diagnostician(diag_id)
        assert loaded is not None
        assert loaded["can_mri"] is True

        # Updating quota from 999 -> 4 (even if payload contains legacy can_mri=999) succeeds
        resp1 = client.put(
            f"/api/admin/diagnosticians/{diag_id}",
            headers={"X-Admin-Token": token},
            json={
                "name": "TEST_INF_QUOTA_DIAG",
                "active": 1,
                "can_ct": 1,
                "can_mri": 999,
                "quota_monday": 4,
                "quota_tuesday": 999,
                "quota_wednesday": 999,
                "quota_thursday": 999,
                "quota_friday": 999,
                "quota_saturday": 0,
                "quota_sunday": 0,
                "preferred_lab_id": None,
            },
        )
        assert resp1.status_code == 200
        assert resp1.json()["quota_monday"] == 4

        # Updating quota back 4 -> 999 (infinite) succeeds
        resp2 = client.put(
            f"/api/admin/diagnosticians/{diag_id}",
            headers={"X-Admin-Token": token},
            json={
                "name": "TEST_INF_QUOTA_DIAG",
                "active": True,
                "can_ct": True,
                "can_mri": True,
                "quota_monday": 999,
                "quota_tuesday": 999,
                "quota_wednesday": 999,
                "quota_thursday": 999,
                "quota_friday": 999,
                "quota_saturday": 0,
                "quota_sunday": 0,
                "preferred_lab_id": None,
            },
        )
        assert resp2.status_code == 200
        assert resp2.json()["quota_monday"] == 999
    finally:
        routes._admin_sessions.pop(token, None)
        cfg_db.delete_diagnostician(diag_id)
