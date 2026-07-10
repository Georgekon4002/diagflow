"""
DiagFlow — Hard Filter Implementations

Hard filters produce a pass/fail result. Any diagnostician failing
a hard filter is removed from the candidate pool entirely.

Filter order (by priority):
1. Comment exclusions (LLM-parsed)
2. Availability (on leave, day off)
2. Modality (CT/MRI capability)
5. Lab preference
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

    # Lab preference
    accepts_lab: bool = True

    # Partnership
    is_partnership_match: bool = False
    partnership_priority: int = 0

    # Patient history
    has_patient_history: bool = False
    patient_history_count: int = 0

    # Comment analysis results
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
    Priority 1: Check if the candidate is excluded by parsed comments.

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
    Priority 2: Check if the diagnostician is available today.
    """
    if not candidate.is_available:
        return FilterResult(
            passed=False,
            rule_name="availability",
            reason=f"Ο/Η {candidate.name} δεν είναι διαθέσιμος/η σήμερα",
        )
    return FilterResult(
        passed=True,
        rule_name="availability",
        reason="Διαθέσιμος/η",
    )


def filter_by_modality(
    candidate: CandidateDiagnostician,
    exam: ExamContext,
) -> FilterResult:
    """
    Priority 2: Check if the diagnostician can handle this exam's modality.
    """
    modality = exam.modality.upper()

    if modality == "CT" and not candidate.can_ct:
        return FilterResult(
            passed=False,
            rule_name="modality_filter",
            reason=f"Ο/Η {candidate.name} δεν αξιολογεί αξονικές τομογραφίες (CT)",
        )
    if modality == "MRI" and not candidate.can_mri:
        return FilterResult(
            passed=False,
            rule_name="modality_filter",
            reason=f"Ο/Η {candidate.name} δεν αξιολογεί μαγνητικές τομογραφίες (MRI)",
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
    Priority 5: Check if the diagnostician accepts work from this lab.

    If the diagnostician has no lab preferences set, they accept all labs.
    """
    if not candidate.accepts_lab:
        return FilterResult(
            passed=False,
            rule_name="lab_preference",
            reason=(
                f"Ο/Η {candidate.name} δεν δέχεται εξετάσεις "
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
    Apply all hard filters to the candidate list.

    Returns:
        - Filtered list of candidates that passed all hard filters
        - Dictionary mapping candidate IDs to their filter results (for audit)
    """
    all_filters = [
        filter_by_comment_exclusion,
        filter_by_availability,
        filter_by_modality,
        filter_by_lab_preference,
    ]

    passed_candidates: list[CandidateDiagnostician] = []
    all_results: dict[int, list[FilterResult]] = {}

    for candidate in candidates:
        results: list[FilterResult] = []
        passed_all = True

        for filter_fn in all_filters:
            result = filter_fn(candidate, exam)
            results.append(result)
            if not result.passed:
                passed_all = False
                logger.info(
                    "candidate_filtered_out",
                    candidate=candidate.name,
                    rule=result.rule_name,
                    reason=result.reason,
                    exam_id=exam.exam_id,
                )
                break  # No need to check remaining filters

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
