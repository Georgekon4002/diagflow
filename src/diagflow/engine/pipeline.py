"""
DiagFlow — Assignment Pipeline Orchestrator

This is the main entry point for the rule engine. It orchestrates:
1. Loading exam and candidate data
2. [DISABLED] Parsing comments via LLM (code preserved, not active)
3. Running hard filters
4. Computing weighted scores
5. Running the solver (greedy or CP-SAT)
6. Producing a suggestion with full audit trail

The pipeline is designed to work with mock data during development
and real Slis data once DB access is available.

Key behavior: Diagnosticians eliminated by hard filters are NOT hidden.
They are included in the alternatives list with a red indicator and
the reason for their elimination, so the user can still manually
override and choose them if needed.
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
    get_elimination_reason,
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

    # Alternative candidates (includes hard-filtered ones with elimination reason)
    # Format: {id, name, score, eliminated, elimination_reason}
    alternatives: list[dict]

    # Audit trail
    rules_fired: list[str]
    filter_results: dict  # Candidate ID → filter results
    solver_status: str
    pipeline_timestamp: str


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
    ) -> AssignmentSuggestion | None:
        """
        Run the full assignment pipeline for a single exam.

        Args:
            exam: The exam to assign
            candidates: All potentially eligible diagnosticians

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

        # ── Step 0.5: Exclusive Partnerships ──
        exclusive_partner = next((c for c in candidates if c.is_partnership_exclusive), None)
        if exclusive_partner:
            logger.info(
                "exclusive_partnership_match",
                exam_id=exam.exam_id,
                diagnostician=exclusive_partner.name,
            )
            
            # Generate alternatives so the user can override if needed
            filtered_candidates, filter_results = apply_hard_filters(candidates, exam)
            scored_candidates = []
            if filtered_candidates:
                scored_candidates = score_all_candidates(filtered_candidates, exam)
                
            alternatives = self._build_alternatives(
                exclusive_partner.id,
                scored_candidates,
                candidates,
                filter_results,
            )
            
            return self._build_exclusive_assignment_suggestion(exam, exclusive_partner, alternatives, scored_candidates)

        # ── Step 1: Hard filters ──
        filtered_candidates, filter_results = apply_hard_filters(candidates, exam)

        if not filtered_candidates:
            logger.warning(
                "no_candidates_after_filters",
                exam_id=exam.exam_id,
                message="All candidates were filtered out. Manual assignment required.",
            )
            return None

        # ── Step 2: Weighted scoring (on passed candidates only) ──
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

        # ── Step 5: Build alternatives list ──
        # Include ALL candidates: scored alternatives + hard-filtered (eliminated) ones
        # So the UI can show eliminated candidates with a red box and reason
        alternatives = self._build_alternatives(
            best.diagnostician_id,
            scored_candidates,
            candidates,
            filter_results,
        )

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

    def _build_alternatives(
        self,
        suggested_id: int,
        scored_candidates: list[CandidateScore],
        all_candidates: list[CandidateDiagnostician],
        filter_results: dict[int, list[FilterResult]],
    ) -> list[dict]:
        """
        Build the alternatives list for the UI.

        Includes:
          1. Top scored candidates (not the suggestion, not eliminated) — up to 3
          2. Eliminated candidates — with red indicator and reason

        This allows the secretariat to still manually select an eliminated
        diagnostician if there is a valid business reason.
        """
        result = []

        # ── Part 1: Scored (non-eliminated) alternatives ──
        for cs in scored_candidates:
            if cs.diagnostician_id == suggested_id:
                continue  # Skip the suggestion itself
            result.append({
                "id": cs.diagnostician_id,
                "name": cs.diagnostician_name,
                "score": round(cs.total_score, 3),
                "eliminated": False,
                "elimination_reason": None,
            })

        # ── Part 2: Hard-filtered (eliminated) candidates ──
        scored_ids = {cs.diagnostician_id for cs in scored_candidates}
        for candidate in all_candidates:
            if candidate.id == suggested_id:
                continue
            if candidate.id in scored_ids:
                continue  # Already in the scored list
            reason = get_elimination_reason(candidate.id, filter_results)
            result.append({
                "id": candidate.id,
                "name": candidate.name,
                "score": 0.0,
                "eliminated": True,
                "elimination_reason": reason or "Εξαιρέθηκε από φίλτρο",
            })

        return result

    def _build_exclusive_assignment_suggestion(
        self,
        exam: ExamContext,
        candidate: CandidateDiagnostician,
        alternatives: list[dict] | None = None,
        scored_candidates: list[CandidateScore] | None = None,
    ) -> AssignmentSuggestion:
        """Build a suggestion for an exclusive partnership assignment."""
        exam_summary = (
            f"{exam.modality} {exam.body_part} — "
            f"Dr. {exam.issuing_doctor_name} — "
            f"Lab {exam.lab_name}"
        )

        candidate_score = None
        if scored_candidates:
            candidate_score = next((s for s in scored_candidates if s.diagnostician_id == candidate.id), None)

        if candidate_score:
            confidence_score = round(candidate_score.total_score, 3)
            score_breakdown = [
                {
                    "rule": comp.rule_name,
                    "display_name": comp.display_name,
                    "raw_score": round(comp.raw_score, 3),
                    "weight": comp.weight,
                    "weighted_score": round(comp.weighted_score, 3),
                    "explanation": comp.explanation,
                }
                for comp in candidate_score.components
            ]
            rules_fired = [comp.rule_name for comp in candidate_score.components if comp.weighted_score > 0]
            if "exclusive_partnership" not in rules_fired:
                rules_fired.append("exclusive_partnership")
        else:
            confidence_score = 1.0
            score_breakdown = [
                {
                    "rule": "exclusive_partnership",
                    "display_name": "Αποκλειστική Συνεργασία",
                    "raw_score": 1.0,
                    "weight": 1.0,
                    "weighted_score": 1.0,
                    "explanation": f"Απευθείας ανάθεση λόγω αποκλειστικής συνεργασίας με τον ιατρό {exam.issuing_doctor_name}.",
                }
            ]
            rules_fired = ["exclusive_partnership"]

        return AssignmentSuggestion(
            exam_id=exam.exam_id,
            patient_id=exam.patient_id,
            exam_summary=exam_summary,
            suggested_diagnostician_id=candidate.id,
            suggested_diagnostician_name=candidate.name,
            confidence_score=confidence_score,
            score_breakdown=score_breakdown,
            alternatives=alternatives or [],
            rules_fired=rules_fired,
            filter_results={},
            solver_status="EXCLUSIVE_ASSIGNMENT",
            pipeline_timestamp=datetime.now().isoformat(),
        )
