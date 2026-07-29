"""
DiagFlow — Auto-Assign and Special Cases Test Suite
"""

import pytest
from unittest.mock import patch, MagicMock

from diagflow.engine.pipeline import AssignmentPipeline
from diagflow.engine.filters import CandidateDiagnostician, ExamContext
from diagflow.services.assignment import _get_pending_exams_from_db


@pytest.fixture
def pipeline():
    return AssignmentPipeline()

@pytest.fixture
def mock_candidates():
    candidates = [
        CandidateDiagnostician(
            id=1,
            name="Available Dr",
            is_available=True,
            daily_quota=10,
            current_day_count=5,
            skill_proficiency=0.5,
            has_skill_data=True,
            has_skill_match=True,
            accepts_lab=False
        ),
        CandidateDiagnostician(
            id=2,
            name="No Skill Data Dr",
            is_available=True,
            daily_quota=10,
            current_day_count=0,
            skill_proficiency=0.0,
            has_skill_data=False,
            has_skill_match=False,
            accepts_lab=True
        ),
        CandidateDiagnostician(
            id=3,
            name="Zero Proficiency Dr",
            is_available=True,
            daily_quota=10,
            current_day_count=0,
            skill_proficiency=0.0,
            has_skill_data=True,
            has_skill_match=False,
            accepts_lab=True
        ),
        CandidateDiagnostician(
            id=4,
            name="Full Dr",
            is_available=True,
            daily_quota=10,
            current_day_count=10,
            skill_proficiency=1.0,
            has_skill_data=True,
            has_skill_match=True,
            accepts_lab=True
        ),
        CandidateDiagnostician(
            id=5,
            name="Partner Dr",
            is_available=True,
            daily_quota=10,
            current_day_count=5,
            skill_proficiency=1.0,
            has_skill_data=True,
            has_skill_match=True,
            accepts_lab=True,
            is_partnership_match=True,
            is_partnership_exclusive=False
        ),
        CandidateDiagnostician(
            id=6,
            name="History Dr",
            is_available=True,
            daily_quota=10,
            current_day_count=5,
            skill_proficiency=0.5,
            has_skill_data=True,
            has_skill_match=True,
            accepts_lab=False,
            has_patient_history=True,
            patient_history_count=2
        ),
        CandidateDiagnostician(
            id=7,
            name="Lab Pref Dr",
            is_available=True,
            daily_quota=10,
            current_day_count=5,
            skill_proficiency=0.5,
            has_skill_data=True,
            has_skill_match=True,
            accepts_lab=True,
        )
    ]
    candidates[-1].preferred_lab_id = "LAB-1"
    return candidates

@pytest.fixture
def mock_exam():
    return ExamContext(
        exam_id="1",
        patient_id="PT1",
        patient_name="Patient",
        modality="MRI",
        body_part="head",
        lab_id="LAB-1",
        lab_name="Lab",
        issuing_doctor_id="DR1",
        issuing_doctor_name="Doctor",
        comments=""
    )


class TestAutoAssignFiltersAndScoring:
    
    def test_skills_hard_filter_eliminates(self, pipeline, mock_exam, mock_candidates):
        # Candidate 3 has skill_data=True but proficiency=0.0 -> Should be eliminated
        result = pipeline.run(mock_exam, mock_candidates)
        assert result is not None
        suggested_ids = [c["id"] for c in result.alternatives] + [result.suggested_diagnostician_id]
        # It's in alternatives but marked as eliminated
        alt_3 = next(c for c in result.alternatives if c["id"] == 3)
        assert alt_3["eliminated"] is True
        
    def test_skills_pass_without_data(self, pipeline, mock_exam, mock_candidates):
        # Candidate 2 has skill_data=False -> Should pass filter
        result = pipeline.run(mock_exam, mock_candidates)
        # Should not be eliminated
        alts = {c["id"]: c for c in result.alternatives}
        if result.suggested_diagnostician_id == 2:
            pass
        else:
            assert alts[2]["eliminated"] is False

    def test_capacity_as_hard_filter(self, pipeline, mock_exam, mock_candidates):
        # Candidate 4 is at quota (10/10) -> Should be eliminated
        result = pipeline.run(mock_exam, mock_candidates)
        alt_4 = next(c for c in result.alternatives if c["id"] == 4)
        assert alt_4["eliminated"] is True

    def test_scoring_order_correctness_and_special_cases(self, pipeline, mock_exam, mock_candidates):
        # Partner Dr vs History Dr vs Lab Pref Dr vs Available Dr
        result = pipeline.run(mock_exam, mock_candidates)
        
        scores = {c["name"]: c["score"] for c in result.alternatives}
        scores[result.suggested_diagnostician_name] = result.confidence_score
        
        # Partnership (Partner Dr) should score highest due to highest weight (0.35)
        assert scores["Partner Dr"] > scores["History Dr"]
        
        # Patient History (History Dr) should score higher than Lab Preference (0.20 vs 0.15)
        assert scores["History Dr"] > scores["Lab Pref Dr"]
        
        # Lab Preference (Lab Pref Dr) should score higher than base Available Dr
        assert scores["Lab Pref Dr"] > scores["Available Dr"]


@patch("diagflow.services.assignment._get_mock_db")
@patch("diagflow.db.diagflow_db.get_exclusive_partnerships")
@patch("diagflow.db.diagflow_db.get_oncall_diagnostician")
@patch("diagflow.db.diagflow_db.get_all_local_assignments")
class TestPamakristosAndExclusiveCases:
    
    def test_pam_general_assigns_to_oncall(self, mock_get_local, mock_get_oncall, mock_get_exclusive, mock_get_db):
        mock_get_local.return_value = {}
        mock_con = MagicMock()
        mock_con.execute.return_value.fetchall.return_value = [{
            "exammoreid": 100,
            "wname": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ ΧΕΙΡΟΥΡΓΟΣ",
            "examnumcode": "12345",
            "wcode": "1"
        }]
        mock_get_db.return_value = mock_con
        
        mock_get_exclusive.return_value = {}
        mock_get_oncall.return_value = {"diagnostician_id": 99, "diagnostician_name": "On Call Dr"}
        
        with patch("diagflow.db.diagflow_db.upsert_local_assignment") as mock_upsert:
            exams = _get_pending_exams_from_db()
            # The exam should be directly assigned, not returned in pending
            assert len(exams) == 0
            assert mock_upsert.called
            args, kwargs = mock_upsert.call_args
            assert args[0] == 100
            assert args[1] == 99
            assert args[2] == "On Call Dr"

    def test_pam_22705_always_assigns_to_mperetis(self, mock_get_local, mock_get_oncall, mock_get_exclusive, mock_get_db):
        mock_get_local.return_value = {}
        mock_con = MagicMock()
        mock_con.execute.return_value.fetchall.return_value = [{
            "exammoreid": 101,
            "wname": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ",
            "examnumcode": "22705",
            "wcode": "1"
        }]
        mock_get_db.return_value = mock_con
        
        mock_get_exclusive.return_value = {}
        
        with patch("diagflow.db.diagflow_db.upsert_local_assignment") as mock_upsert:
            exams = _get_pending_exams_from_db()
            assert len(exams) == 0
            assert mock_upsert.called
            args, kwargs = mock_upsert.call_args
            assert args[0] == 101
            assert args[1] == 59
            assert args[2] == "ΜΠΕΡΕΤΗΣ ΓΕΩΡΓΙΟΣ"
            
    def test_exclusive_partnership_direct_assignment(self, mock_get_local, mock_get_oncall, mock_get_exclusive, mock_get_db):
        mock_get_local.return_value = {}
        mock_con = MagicMock()
        mock_con.execute.return_value.fetchall.return_value = [{
            "exammoreid": 102,
            "wcode": "DOC1",
            "wname": "ΠΑΠΟΥΤΣΗ",
            "examnumcode": "111"
        }]
        mock_get_db.return_value = mock_con
        
        mock_get_exclusive.return_value = {
            "DOC1": {
                "preferred_diagnostician_id": 42,
                "preferred_diagnostician_name": "Exclusive Dr"
            }
        }
        
        with patch("diagflow.db.diagflow_db.upsert_local_assignment") as mock_upsert:
            exams = _get_pending_exams_from_db()
            assert len(exams) == 0
            assert mock_upsert.called
            args, kwargs = mock_upsert.call_args
            assert args[0] == 102
            assert args[1] == 42
            assert args[2] == "Exclusive Dr"
