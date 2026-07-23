"""
DiagFlow — Scoring Tests

Tests that the weighted scoring logic produces correct scores.
"""

from diagflow.engine.scoring import (
    compute_candidate_score,
    score_all_candidates,
    score_capacity,
    score_partnership,
    score_patient_history,
    score_skills_weighted,
)
from diagflow.engine.filters import CandidateDiagnostician, ExamContext


class TestCapacityScoring:
    """Tests for the capacity scoring component."""

    def test_full_capacity_scores_high(self, sample_exam, sample_candidates):
        """Diagnostician with lots of remaining capacity should score high."""
        candidate = sample_candidates[1]  # Κωνσταντίνου: 3/12 used
        result = score_capacity(candidate)
        assert result.raw_score == pytest.approx(0.75, abs=0.01)

    def test_near_quota_scores_low(self, sample_exam):
        """Diagnostician near their quota should score low."""
        candidate = CandidateDiagnostician(
            id=99, name="Full", daily_quota=10, current_day_count=9
        )
        result = score_capacity(candidate)
        assert result.raw_score == pytest.approx(0.1, abs=0.01)

    def test_at_quota_scores_zero(self, sample_exam):
        """Diagnostician at their quota should score 0."""
        candidate = CandidateDiagnostician(
            id=99, name="Maxed", daily_quota=10, current_day_count=10
        )
        result = score_capacity(candidate)
        assert result.raw_score == 0.0


class TestSkillsScoring:
    """Tests for the skills scoring component."""

    def test_skilled_candidate_scores_proficiency(self, sample_exam, sample_candidates):
        """Candidate with matching skill should score their proficiency level."""
        candidate = sample_candidates[0]  # Νάτσικα: abdomen MRI, proficiency 1.0
        result = score_skills_weighted(candidate, sample_exam)
        assert result.raw_score == 1.0

    def test_no_skill_data_scores_neutral(self, sample_exam, sample_candidates):
        """Candidate without skill data should get a neutral 0.3 score."""
        candidate = CandidateDiagnostician(id=99, name="NoData")
        result = score_skills_weighted(candidate, sample_exam)
        assert result.raw_score == 0.3


class TestPartnershipScoring:
    """Tests for the partnership scoring component."""

    def test_partnership_match_scores_positive(self, sample_exam, sample_candidates):
        """Candidate matching the issuing doctor's preference should score high."""
        candidate = sample_candidates[2]  # Παπαδόπουλος: partnership match
        result = score_partnership(candidate, sample_exam)
        assert result.raw_score > 0.0

    def test_no_partnership_scores_zero(self, sample_exam, sample_candidates):
        """Candidate without partnership match should score 0."""
        candidate = sample_candidates[0]  # Νάτσικα: no partnership
        result = score_partnership(candidate, sample_exam)
        assert result.raw_score == 0.0


class TestPatientHistoryScoring:
    """Tests for the patient history scoring component."""

    def test_patient_history_scores_positive(self, sample_exam, sample_candidates):
        """Candidate with patient history should get a bonus."""
        candidate = sample_candidates[0]  # Νάτσικα: 3 past exams
        result = score_patient_history(candidate, sample_exam)
        assert result.raw_score > 0.0

    def test_no_history_scores_zero(self, sample_exam, sample_candidates):
        """Candidate without patient history should score 0."""
        candidate = sample_candidates[1]  # Κωνσταντίνου: no history
        result = score_patient_history(candidate, sample_exam)
        assert result.raw_score == 0.0


class TestCompositeScoring:
    """Tests for the full composite scoring."""

    def test_scores_are_sorted_descending(self, sample_exam, sample_candidates):
        """score_all_candidates should return results sorted highest first."""
        # Only use available, eligible candidates
        eligible = [c for c in sample_candidates if c.is_available and c.can_mri and c.accepts_lab]
        scores = score_all_candidates(eligible, sample_exam)

        for i in range(len(scores) - 1):
            assert scores[i].total_score >= scores[i + 1].total_score

    def test_scores_have_correct_ranks(self, sample_exam, sample_candidates):
        """Candidates should have rank 1, 2, 3... after scoring."""
        eligible = [c for c in sample_candidates if c.is_available and c.can_mri and c.accepts_lab]
        scores = score_all_candidates(eligible, sample_exam)

        for i, score in enumerate(scores):
            assert score.rank == i + 1

    def test_scores_are_bounded(self, sample_exam, sample_candidates):
        """All scores should be between 0 and 1."""
        eligible = [c for c in sample_candidates if c.is_available and c.can_mri and c.accepts_lab]
        scores = score_all_candidates(eligible, sample_exam)

        for score in scores:
            assert 0.0 <= score.total_score <= 1.0


# Need to import pytest for approx
import pytest
