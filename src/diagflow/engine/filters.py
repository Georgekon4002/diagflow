"""
DiagFlow — Hard Filter Implementations

Hard filters produce a pass/fail result. Any diagnostician failing
a hard filter is removed from the candidate pool — BUT they are still
returned in the filter_results dict so the UI can show them in the
alternatives list with a red indicator and the elimination reason.

Filter order (by priority):
  1. Availability (on leave, day off)
  4. Skills (zero proficiency recorded for this body-part/modality)

NOTE: comment_exclusion filter code is preserved but NOT called in
apply_hard_filters() during this implementation phase.
Lab preference is now a WEIGHTED score, not a hard filter.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ExamContext:
    """
    All the information about an exam needed for assignment decisions.
    Populated from Slis data before the pipeline runs.
    """

    exam_id: str
    patient_id: str
    patient_name: str = ""
    modality: str = ""  # "CT" or "MRI"
    body_part: str = ""  # e.g., "abdomen", "neuro", "chest", "msk"
    exam_code: str = ""  # Added for skill matching
    lab_id: str = ""
    lab_name: str = ""
    issuing_doctor_id: str = ""
    issuing_doctor_name: str = ""
    comments: str = ""  # Raw free-text from secretariat
    is_pamakristos: bool = False  # Is this from Παμακάριστος hospital?
    request_date: Optional[date] = None


@dataclass
class CandidateDiagnostician:
    """
    A diagnostician being evaluated for assignment.
    Populated from the config tables and enriched during the pipeline.
    """

    id: int
    name: str
    can_ct: bool = True
    can_mri: bool = True

    # Populated during filtering/scoring
    is_available: bool = True
    daily_quota: int = 15
    current_day_count: int = 0
    current_subcategory_count: int = 0  # Same body-part count for today
    subcategory_soft_cap: Optional[int] = None

    # Skills for the exam's body part/modality
    skill_proficiency: float = 0.0
    has_skill_match: bool = False
    has_skill_data: bool = False  # True if any skill record exists for this modality/body-part

    # Lab preference
    accepts_lab: bool = True

    # Partnership
    is_partnership_match: bool = False
    is_partnership_exclusive: bool = False

    # Patient history
    has_patient_history: bool = False
    patient_history_count: int = 0

    # Comment analysis results (code preserved, not active)
    is_excluded_by_comment: bool = False
    is_directly_assigned_by_comment: bool = False


@dataclass
class FilterResult:
    """Result of applying a hard filter to a candidate."""

    passed: bool
    rule_name: str
    reason: str  # Human-readable explanation


def filter_by_comment_exclusion(
    candidate: CandidateDiagnostician,
    exam: ExamContext,
) -> FilterResult:
    """
    [DISABLED] Priority 0: Check if the candidate is excluded by parsed comments.

    This function is preserved for future use but is NOT called by
    apply_hard_filters() in the current implementation phase.
    The actual LLM parsing happens in the comment_parser service before
    this filter runs. This filter just checks the result.
    """
    if candidate.is_excluded_by_comment:
        return FilterResult(
            passed=False,
            rule_name="comment_exclusion",
            reason=f"Εξαιρέθηκε από σχόλιο γραμματείας: '{exam.comments[:80]}...'",
        )
    return FilterResult(
        passed=True,
        rule_name="comment_exclusion",
        reason="Δεν υπάρχει εξαίρεση από σχόλια",
    )


def filter_by_availability(
    candidate: CandidateDiagnostician,
    exam: ExamContext,
) -> FilterResult:
    """
    Priority 1: Check if the diagnostician is available today.
    """
    if not candidate.is_available:
        return FilterResult(
            passed=False,
            rule_name="availability",
            reason="Μη διαθέσιμος σήμερα",
        )
    return FilterResult(
        passed=True,
        rule_name="availability",
        reason="Διαθέσιμος/η",
    )


def filter_by_skills_hard(
    candidate: CandidateDiagnostician,
    exam: ExamContext,
) -> FilterResult:
    """
    Priority 4: Hard filter on skills.

    Eliminates a candidate ONLY if they have an explicit skill record
    for this body-part/modality combination AND the proficiency is 0.

    If no skill data exists, the candidate passes (they get a neutral 0.3
    in the weighted scoring phase, not an elimination).
    """
    if candidate.has_skill_data and candidate.skill_proficiency == 0.0:
        return FilterResult(
            passed=False,
            rule_name="skills",
            reason="Δεν αξιολογεί τη συγκεκριμένη εξέταση",
        )
    return FilterResult(
        passed=True,
        rule_name="skills",
        reason=f"Εξειδίκευση '{exam.body_part}' ({exam.modality}): Αποδεκτή"
    )


def filter_by_modality(
    candidate: CandidateDiagnostician,
    exam: ExamContext,
) -> FilterResult:
    """
    Modality check (CT/MRI capability).
    Kept as a secondary check, used only for informational purposes.
    This is separate from the skills hard filter.
    """
    modality = exam.modality.upper()

    if modality == "CT" and not candidate.can_ct:
        return FilterResult(
            passed=False,
            rule_name="modality_filter",
            reason="Δεν αξιολογεί τη συγκεκριμένη εξέταση",
        )
    if modality == "MRI" and not candidate.can_mri:
        return FilterResult(
            passed=False,
            rule_name="modality_filter",
            reason="Δεν αξιολογεί τη συγκεκριμένη εξέταση",
        )
    return FilterResult(
        passed=True,
        rule_name="modality_filter",
        reason=f"Μπορεί να αξιολογήσει {modality}",
    )


def filter_by_lab_preference(
    candidate: CandidateDiagnostician,
    exam: ExamContext,
) -> FilterResult:
    """
    Lab preference check — informational only.
    Lab is now a WEIGHTED scoring factor, not a hard filter.
    This function is kept for reference but not called in apply_hard_filters().
    """
    if not candidate.accepts_lab:
        return FilterResult(
            passed=False,
            rule_name="lab_preference",
            reason=(
                f"Ο/Η {candidate.name} δεν προτιμά εξετάσεις "
                f"από το εργαστήριο '{exam.lab_name}'"
            ),
        )
    return FilterResult(
        passed=True,
        rule_name="lab_preference",
        reason="Αποδεκτό εργαστήριο",
    )


def apply_hard_filters(
    candidates: list[CandidateDiagnostician],
    exam: ExamContext,
) -> tuple[list[CandidateDiagnostician], dict[int, list[FilterResult]]]:
    """
    Apply all active hard filters to the candidate list.

    Active filters (per current business rules):
      1. Availability
      4. Skills (only eliminates if proficiency == 0 AND data exists)

    Returns:
        - Filtered list of candidates that passed ALL hard filters
        - Dictionary mapping ALL candidate IDs to their filter results
          (including eliminated ones, so the UI can show them in the
           alternatives list with a red indicator and reason)
    """
    active_filters = [
        filter_by_availability,
        filter_by_modality,       # Keep modality as a basic sanity filter
        filter_by_skills_hard,    # New: skills hard filter (priority 4)
        # filter_by_comment_exclusion — DISABLED in this phase
        # filter_by_lab_preference   — Now WEIGHTED, not hard
    ]

    passed_candidates: list[CandidateDiagnostician] = []
    all_results: dict[int, list[FilterResult]] = {}

    for candidate in candidates:
        results: list[FilterResult] = []
        passed_all = True
        elimination_reason: str | None = None

        for filter_fn in active_filters:
            result = filter_fn(candidate, exam)
            results.append(result)
            if not result.passed and passed_all:
                # Record the first (primary) elimination reason but continue
                # collecting all results for the audit trail
                passed_all = False
                elimination_reason = result.reason
                logger.info(
                    "candidate_filtered_out",
                    candidate=candidate.name,
                    rule=result.rule_name,
                    reason=result.reason,
                    exam_id=exam.exam_id,
                )

        all_results[candidate.id] = results
        if passed_all:
            passed_candidates.append(candidate)

    logger.info(
        "hard_filters_complete",
        exam_id=exam.exam_id,
        total_candidates=len(candidates),
        passed=len(passed_candidates),
        filtered_out=len(candidates) - len(passed_candidates),
    )

    return passed_candidates, all_results


def get_elimination_reason(
    candidate_id: int,
    filter_results: dict[int, list[FilterResult]],
) -> str | None:
    """
    Return the first failed filter reason for a candidate, or None if they passed.
    Used by the pipeline to populate the alternatives list with elimination reasons.
    """
    results = filter_results.get(candidate_id, [])
    for result in results:
        if not result.passed:
            return result.reason
    return None
