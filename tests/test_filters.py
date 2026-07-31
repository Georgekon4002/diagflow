"""
DiagFlow — Hard Filter Tests

Tests that hard filters correctly remove ineligible candidates.
"""

from diagflow.engine.filters import (
    CandidateDiagnostician,
    ExamContext,
    apply_hard_filters,
    filter_by_availability,
    filter_by_capacity,
    filter_by_comment_exclusion,
    filter_by_lab_preference,
    filter_by_modality,
)


class TestAvailabilityFilter:
    """Tests for the availability hard filter."""

    def test_available_candidate_passes(self, sample_exam, sample_candidates):
        """Available candidates should pass the filter."""
        candidate = sample_candidates[0]  # Candidate 1 — available
        result = filter_by_availability(candidate, sample_exam)
        assert result.passed is True

    def test_unavailable_candidate_fails(self, sample_exam, sample_candidates):
        """Candidates on leave should be filtered out."""
        candidate = sample_candidates[4]  # Candidate 5 — on leave
        result = filter_by_availability(candidate, sample_exam)
        assert result.passed is False
        assert "διαθέσιμος" in result.reason.lower()


class TestModalityFilter:
    """Tests for the modality (CT/MRI) hard filter."""

    def test_mri_capable_passes_mri_exam(self, sample_exam, sample_candidates):
        """Diagnostician who can do MRI should pass MRI exam filter."""
        candidate = sample_candidates[0]  # Candidate 1 — can MRI
        result = filter_by_modality(candidate, sample_exam)  # MRI exam
        assert result.passed is True

    def test_ct_only_fails_mri_exam(self, sample_exam, sample_candidates):
        """CT-only diagnostician should fail MRI exam filter."""
        candidate = sample_candidates[3]  # Candidate 4 — CT only
        result = filter_by_modality(candidate, sample_exam)  # MRI exam
        assert result.passed is False

    def test_ct_capable_passes_ct_exam(self, ct_exam, sample_candidates):
        """CT-capable diagnostician should pass CT exam filter."""
        candidate = sample_candidates[3]  # Candidate 4 — can CT
        result = filter_by_modality(candidate, ct_exam)
        assert result.passed is True


class TestLabPreferenceFilter:
    """Tests for the lab preference hard filter."""

    def test_accepted_lab_passes(self, sample_exam, sample_candidates):
        """Candidates who accept the lab should pass."""
        candidate = sample_candidates[0]  # accepts_lab = True
        result = filter_by_lab_preference(candidate, sample_exam)
        assert result.passed is True

    def test_rejected_lab_fails(self, sample_exam, sample_candidates):
        """Candidates who don't accept the lab should be filtered."""
        candidate = sample_candidates[3]  # accepts_lab = False
        result = filter_by_lab_preference(candidate, sample_exam)
        assert result.passed is False


class TestCommentExclusionFilter:
    """Tests for the comment-based exclusion filter."""

    def test_non_excluded_passes(self, sample_exam, sample_candidates):
        """Candidates not mentioned in exclusion should pass."""
        candidate = sample_candidates[0]
        result = filter_by_comment_exclusion(candidate, sample_exam)
        assert result.passed is True

    def test_excluded_candidate_fails(self, sample_exam, sample_candidates):
        """Candidates marked as excluded should fail."""
        candidate = sample_candidates[0]
        candidate.is_excluded_by_comment = True
        result = filter_by_comment_exclusion(candidate, sample_exam)
        assert result.passed is False


class TestCapacityFilter:
    """Tests for daily capacity hard filter."""

    def test_under_quota_passes(self, sample_exam, sample_candidates):
        """Candidate under quota should pass."""
        candidate = sample_candidates[0]
        candidate.daily_quota = 15
        candidate.current_day_count = 5
        result = filter_by_capacity(candidate, sample_exam)
        assert result.passed is True

    def test_over_quota_fails_with_quota_reason(self, sample_exam, sample_candidates):
        """Candidate who reached or exceeded quota should fail with capacity reason."""
        candidate = sample_candidates[0]
        candidate.daily_quota = 5
        candidate.current_day_count = 6
        result = filter_by_capacity(candidate, sample_exam)
        assert result.passed is False
        assert result.reason == "Έχει συμπληρώσει το ημερήσιο όριο"

    def test_zero_quota_always_fails(self, sample_exam, sample_candidates):
        """Candidate with daily_quota == 0 should always fail, even if count is 0."""
        candidate = sample_candidates[0]
        candidate.daily_quota = 0
        candidate.current_day_count = 0
        result = filter_by_capacity(candidate, sample_exam)
        assert result.passed is False
        assert result.reason == "Δεν είναι διαθέσιμος/η σήμερα"


class TestApplyAllHardFilters:
    """Integration tests for the full hard filter pipeline."""

    def test_filters_remove_ineligible(self, sample_exam, sample_candidates):
        """Full filter pipeline should remove unavailable, wrong modality, and wrong lab."""
        passed, results = apply_hard_filters(sample_candidates, sample_exam)

        # From 5 candidates:
        # - Candidate 1: available, MRI capable, accepts lab → PASS
        # - Candidate 2: available, MRI capable, accepts lab → PASS
        # - Candidate 3: available, MRI capable, accepts lab → PASS
        # - Candidate 4: available, CT only → FAIL (modality) or FAIL (lab)
        # - Candidate 5: on leave → FAIL (availability)
        passed_ids = {c.id for c in passed}
        assert 1 in passed_ids  # Candidate 1
        assert 2 in passed_ids  # Candidate 2
        assert 3 in passed_ids  # Candidate 3
        assert 4 not in passed_ids  # Candidate 4 — filtered
        assert 5 not in passed_ids  # Candidate 5 — filtered

    def test_all_filtered_returns_empty(self, sample_exam):
        """If all candidates are ineligible, return empty list."""
        candidates = [
            CandidateDiagnostician(id=99, name="Test", is_available=False),
        ]
        passed, _ = apply_hard_filters(candidates, sample_exam)
        assert len(passed) == 0
