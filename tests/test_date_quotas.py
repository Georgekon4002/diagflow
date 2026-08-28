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
