"""
DiagFlow — Test Configuration

Shared fixtures and test utilities.
"""

import pytest

from diagflow.engine.filters import CandidateDiagnostician, ExamContext


@pytest.fixture
def sample_exam() -> ExamContext:
    """A standard MRI abdomen exam for testing."""
    return ExamContext(
        exam_id="TEST-001",
        patient_id="PT-100",
        patient_name="Test Patient",
        modality="MRI",
        body_part="abdomen",
        lab_id="LAB-KIF",
        lab_name="Κηφισιά",
        issuing_doctor_id="DR-101",
        issuing_doctor_name="Παπαδόπουλος Ν.",
        comments="",
    )


@pytest.fixture
def sample_candidates() -> list[CandidateDiagnostician]:
    """A set of test candidates with varied attributes."""
    return [
        CandidateDiagnostician(
            id=1,
            name="Νάτσικα Α.",
            can_ct=True,
            can_mri=True,
            is_available=True,
            daily_quota=15,
            current_day_count=5,
            skill_proficiency=1.0,
            has_skill_match=True,
            has_skill_data=True,
            accepts_lab=True,
            is_partnership_match=False,
            has_patient_history=True,
            patient_history_count=3,
        ),
        CandidateDiagnostician(
            id=2,
            name="Κωνσταντίνου Β.",
            can_ct=True,
            can_mri=True,
            is_available=True,
            daily_quota=12,
            current_day_count=3,
            skill_proficiency=0.5,
            has_skill_match=True,
            has_skill_data=True,
            accepts_lab=True,
            is_partnership_match=False,
        ),
        CandidateDiagnostician(
            id=3,
            name="Παπαδόπουλος Γ.",
            can_ct=True,
            can_mri=True,
            is_available=True,
            daily_quota=18,
            current_day_count=8,
            skill_proficiency=0.5,
            has_skill_match=False,
            has_skill_data=True,
            accepts_lab=True,
            is_partnership_match=True,
            is_partnership_exclusive=False,
            has_patient_history=True,
            patient_history_count=2,
        ),
        CandidateDiagnostician(
            id=4,
            name="Λιάκος Δ.",
            can_ct=True,
            can_mri=False,  # CT only
            is_available=True,
            daily_quota=10,
            current_day_count=4,
            accepts_lab=False,
        ),
        CandidateDiagnostician(
            id=5,
            name="Αντωνίου Ζ.",
            can_ct=True,
            can_mri=True,
            is_available=False,  # On leave
            daily_quota=16,
            current_day_count=0,
            skill_proficiency=0.85,
            has_skill_match=True,
            accepts_lab=True,
        ),
    ]


@pytest.fixture
def exam_with_exclusion_comment() -> ExamContext:
    """An exam with a comment excluding a diagnostician."""
    return ExamContext(
        exam_id="TEST-002",
        patient_id="PT-200",
        patient_name="Test Patient 2",
        modality="MRI",
        body_part="neuro",
        lab_id="LAB-KIF",
        lab_name="Κηφισιά",
        issuing_doctor_id="DR-101",
        issuing_doctor_name="Παπαδόπουλος Ν.",
        comments="ΟΧΙ ΝΑΤΣΙΚΑ",
    )


@pytest.fixture
def ct_exam() -> ExamContext:
    """A CT chest exam for testing modality filtering."""
    return ExamContext(
        exam_id="TEST-003",
        patient_id="PT-300",
        patient_name="Test Patient 3",
        modality="CT",
        body_part="chest",
        lab_id="LAB-MAR",
        lab_name="Μαρούσι",
        issuing_doctor_id="DR-205",
        issuing_doctor_name="Ιωάννου Ε.",
        comments="",
    )
