"""
DiagFlow — Pipeline Integration Tests

End-to-end tests for the full assignment pipeline.
"""

import pytest

from diagflow.engine.pipeline import AssignmentPipeline
from diagflow.engine.filters import CandidateDiagnostician, ExamContext


class TestAssignmentPipeline:
    """Integration tests for the full assignment pipeline."""

    @pytest.fixture
    def pipeline(self):
        return AssignmentPipeline()

    def test_basic_assignment(self, pipeline, sample_exam, sample_candidates):
        """Pipeline should produce a valid suggestion for a normal exam."""
        suggestion = pipeline.run(sample_exam, sample_candidates)

        assert suggestion is not None
        assert suggestion.exam_id == "TEST-001"
        assert suggestion.suggested_diagnostician_id > 0
        assert suggestion.suggested_diagnostician_name != ""
        assert 0.0 <= suggestion.confidence_score <= 1.0
        assert len(suggestion.score_breakdown) > 0
        assert len(suggestion.rules_fired) > 0

    def test_filtered_candidates_not_suggested(self, pipeline, sample_exam, sample_candidates):
        """Unavailable or ineligible candidates should never be suggested."""
        suggestion = pipeline.run(sample_exam, sample_candidates)

        assert suggestion is not None
        # Candidate 4 — CT only, no lab acceptance
        assert suggestion.suggested_diagnostician_id != 4
        # Candidate 5 — on leave
        assert suggestion.suggested_diagnostician_id != 5

    def test_all_filtered_returns_none(self, pipeline, sample_exam):
        """If no candidates remain after filtering, return None."""
        candidates = [
            CandidateDiagnostician(id=99, name="Unavailable", is_available=False),
        ]
        suggestion = pipeline.run(sample_exam, candidates)
        assert suggestion is None

    def test_suggestion_has_alternatives(self, pipeline, sample_exam, sample_candidates):
        """Suggestion should include alternative candidates for the override dropdown."""
        suggestion = pipeline.run(sample_exam, sample_candidates)

        assert suggestion is not None
        # Should have at least one alternative (we have 3 passing candidates)
        assert len(suggestion.alternatives) > 0

    def test_suggestion_has_score_breakdown(self, pipeline, sample_exam, sample_candidates):
        """Suggestion should include detailed score breakdown."""
        suggestion = pipeline.run(sample_exam, sample_candidates)

        assert suggestion is not None
        assert len(suggestion.score_breakdown) >= 5  # scoring components

        for comp in suggestion.score_breakdown:
            assert "rule" in comp
            assert "display_name" in comp
            assert "explanation" in comp
            assert "weighted_score" in comp

    def test_pipeline_timestamp(self, pipeline, sample_exam, sample_candidates):
        """Suggestion should have a valid timestamp for audit."""
        suggestion = pipeline.run(sample_exam, sample_candidates)

        assert suggestion is not None
        assert suggestion.pipeline_timestamp is not None
        assert len(suggestion.pipeline_timestamp) > 0
