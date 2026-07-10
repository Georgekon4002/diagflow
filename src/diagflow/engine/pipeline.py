"""
DiagFlow — Assignment Pipeline Orchestrator

This is the main entry point for the rule engine. It orchestrates:
1. Loading exam and candidate data
2. Parsing comments via LLM
3. Running hard filters
4. Computing weighted scores
5. Running the solver (greedy or CP-SAT)
6. Producing a suggestion with full audit trail

The pipeline is designed to work with mock data during development
and real Slis data once DB access is available.
"""

import json
from dataclasses import dataclass, asdict
from datetime import date, datetime

import structlog

from diagflow.engine.filters import (
    CandidateDiagnostician,
    ExamContext,
    FilterResult,
    apply_hard_filters,
)
from diagflow.engine.scoring import CandidateScore, score_all_candidates
from diagflow.engine.solver import SolverResult, solve_single_assignment

logger = structlog.get_logger(__name__)


@dataclass
class AssignmentSuggestion:
    """
    The final output of the pipeline — a complete assignment suggestion
    with full transparency into why this diagnostician was chosen.
    """

    exam_id: str
    patient_id: str
    exam_summary: str  # e.g., "MRI Abdomen — Dr. Παπαδόπουλος — Lab Κηφισιάς"

    # Suggestion
    suggested_diagnostician_id: int
    suggested_diagnostician_name: str
    confidence_score: float  # 0.0 to 1.0

    # Scoring breakdown (for UI display)
    score_breakdown: list[dict]  # List of {rule, score, weight, explanation}

    # Alternative candidates (top 3 for the override dropdown)
    alternatives: list[dict]  # List of {id, name, score}

    # Audit trail
    rules_fired: list[str]
    filter_results: dict  # Candidate ID → filter results
    solver_status: str
    pipeline_timestamp: str

    # Comment analysis
    comment_raw: str
    comment_parsed: str  # JSON from LLM analysis

    # Direct assignment (if comments specify a specific diagnostician)
    is_direct_assignment: bool = False
    direct_assignment_reason: str = ""


class AssignmentPipeline:
    """
    Main pipeline orchestrator.

    Usage:
        pipeline = AssignmentPipeline()
        suggestion = pipeline.run(exam, candidates)
    """

    def __init__(self):
        """Initialize the pipeline."""
        self._comment_parser = None  # Lazy-loaded

    def run(
        self,
        exam: ExamContext,
        candidates: list[CandidateDiagnostician],
        comment_analysis: dict | None = None,
    ) -> AssignmentSuggestion | None:
        """
        Run the full assignment pipeline for a single exam.

        Args:
            exam: The exam to assign
            candidates: All potentially eligible diagnosticians
            comment_analysis: Pre-parsed comment analysis (from LLM service)
                              Format: {"exclude": ["name1"], "assign": "name2" or null, "reasoning": "..."}

        Returns:
            AssignmentSuggestion with the proposed assignment, or None if no candidates remain
        """
        logger.info(
            "pipeline_start",
            exam_id=exam.exam_id,
            modality=exam.modality,
            body_part=exam.body_part,
            candidates=len(candidates),
        )

        # ── Step 0: Apply comment analysis results to candidates ──
        direct_assignment = None
        comment_parsed_str = ""

        if comment_analysis:
            comment_parsed_str = json.dumps(comment_analysis, ensure_ascii=False)
            direct_assignment = self._apply_comment_analysis(
                candidates, comment_analysis, exam
            )

        if direct_assignment:
            # Comment specified a direct assignment — skip the engine
            return self._build_direct_assignment_suggestion(
                exam, direct_assignment, comment_parsed_str
            )

        # ── Step 1: Hard filters ──
        filtered_candidates, filter_results = apply_hard_filters(candidates, exam)

        if not filtered_candidates:
            logger.warning(
                "no_candidates_after_filters",
                exam_id=exam.exam_id,
                message="All candidates were filtered out. Manual assignment required.",
            )
            return None

        # ── Step 2: Weighted scoring ──
        scored_candidates = score_all_candidates(filtered_candidates, exam)

        # ── Step 3: Solver (greedy for single exam) ──
        solver_result: SolverResult = solve_single_assignment(exam, scored_candidates)

        if not solver_result.assignments:
            return None

        # ── Step 4: Build suggestion ──
        best = solver_result.assignments[0]
        best_score = next(
            (s for s in scored_candidates if s.diagnostician_id == best.diagnostician_id),
            scored_candidates[0],
        )

        # Build score breakdown for UI
        score_breakdown = [
            {
                "rule": comp.rule_name,
                "display_name": comp.display_name,
                "raw_score": round(comp.raw_score, 3),
                "weight": comp.weight,
                "weighted_score": round(comp.weighted_score, 3),
                "explanation": comp.explanation,
            }
            for comp in best_score.components
        ]

        # Top 3 alternatives (excluding the suggested one)
        alternatives = [
            {
                "id": s.diagnostician_id,
                "name": s.diagnostician_name,
                "score": round(s.total_score, 3),
            }
            for s in scored_candidates[1:4]
        ]

        # Rules that contributed positively
        rules_fired = [
            comp.rule_name
            for comp in best_score.components
            if comp.weighted_score > 0
        ]

        exam_summary = (
            f"{exam.modality} {exam.body_part} — "
            f"Dr. {exam.issuing_doctor_name} — "
            f"Lab {exam.lab_name}"
        )

        suggestion = AssignmentSuggestion(
            exam_id=exam.exam_id,
            patient_id=exam.patient_id,
            exam_summary=exam_summary,
            suggested_diagnostician_id=best.diagnostician_id,
            suggested_diagnostician_name=best.diagnostician_name,
            confidence_score=round(best.score, 3),
            score_breakdown=score_breakdown,
            alternatives=alternatives,
            rules_fired=rules_fired,
            filter_results={
                str(k): [asdict(r) for r in v] for k, v in filter_results.items()
            },
            solver_status=solver_result.solver_status,
            pipeline_timestamp=datetime.now().isoformat(),
            comment_raw=exam.comments,
            comment_parsed=comment_parsed_str,
        )

        logger.info(
            "pipeline_complete",
            exam_id=exam.exam_id,
            suggested=best.diagnostician_name,
            score=f"{best.score:.3f}",
            rules_fired=rules_fired,
            solver_status=solver_result.solver_status,
        )

        return suggestion

    def _apply_comment_analysis(
        self,
        candidates: list[CandidateDiagnostician],
        analysis: dict,
        exam: ExamContext,
    ) -> CandidateDiagnostician | None:
        """
        Apply LLM comment analysis results to candidates.

        Returns a CandidateDiagnostician if a direct assignment was specified,
        otherwise returns None and modifies candidates in-place.
        """
        # Handle exclusions
        excluded_names = analysis.get("exclude", [])
        for candidate in candidates:
            for excluded in excluded_names:
                if excluded.lower() in candidate.name.lower():
                    candidate.is_excluded_by_comment = True
                    logger.info(
                        "comment_exclusion_applied",
                        candidate=candidate.name,
                        excluded_name=excluded,
                        exam_id=exam.exam_id,
                    )

        # Handle direct assignment
        assign_to = analysis.get("assign")
        if assign_to:
            for candidate in candidates:
                if assign_to.lower() in candidate.name.lower():
                    candidate.is_directly_assigned_by_comment = True
                    logger.info(
                        "comment_direct_assignment",
                        candidate=candidate.name,
                        exam_id=exam.exam_id,
                    )
                    return candidate

        return None

    def _build_direct_assignment_suggestion(
        self,
        exam: ExamContext,
        candidate: CandidateDiagnostician,
        comment_parsed: str,
    ) -> AssignmentSuggestion:
        """Build a suggestion for a comment-directed assignment."""
        exam_summary = (
            f"{exam.modality} {exam.body_part} — "
            f"Dr. {exam.issuing_doctor_name} — "
            f"Lab {exam.lab_name}"
        )

        return AssignmentSuggestion(
            exam_id=exam.exam_id,
            patient_id=exam.patient_id,
            exam_summary=exam_summary,
            suggested_diagnostician_id=candidate.id,
            suggested_diagnostician_name=candidate.name,
            confidence_score=1.0,
            score_breakdown=[
                {
                    "rule": "comment_exclusion",
                    "display_name": "Σχόλια / Παρατηρήσεις",
                    "raw_score": 1.0,
                    "weight": 1.0,
                    "weighted_score": 1.0,
                    "explanation": f"Απευθείας ανάθεση βάσει σχολίου: '{exam.comments[:80]}'",
                }
            ],
            alternatives=[],
            rules_fired=["comment_exclusion"],
            filter_results={},
            solver_status="DIRECT_ASSIGNMENT",
            pipeline_timestamp=datetime.now().isoformat(),
            comment_raw=exam.comments,
            comment_parsed=comment_parsed,
            is_direct_assignment=True,
            direct_assignment_reason=f"Απευθείας ανάθεση στον/στην {candidate.name} βάσει σχολίου",
        )
