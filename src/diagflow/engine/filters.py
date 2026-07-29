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
from typing import Any, Optional

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
    exam_name: str = ""  # Human readable name of the exam
    lab_id: str = ""
    lab_name: str = ""
    issuing_doctor_id: str = ""
    issuing_doctor_name: str = ""
    comments: str = ""  # Raw free-text from secretariat
    is_pamakristos: bool = False  # Is this from Παμακάριστος hospital?
    request_date: Optional[date] = None
    oldpers: Optional[int] = None  # ID of the diagnostician who diagnosed past exam


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
    daily_quota: int = 0
    current_day_count: int = 0
    current_day_mri_count: int = 0
    current_day_ct_count: int = 0
    skill_proficiency: float = 0.0
    has_skill_match: bool = False
    has_skill_data: bool = False  # True if any skill record exists for this modality/body-part

    # Lab preference
    accepts_lab: bool = True
    preferred_lab_id: Optional[Any] = None

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
            reason="Δεν είναι διαθέσιμος/η σήμερα",
        )
    return FilterResult(
        passed=True,
        rule_name="availability",
        reason="Διαθέσιμος/η",
    )


def filter_by_capacity(
    candidate: CandidateDiagnostician,
    exam: ExamContext,
) -> FilterResult:
    """
    Priority 2: Capacity check.
    Eliminates a candidate if they have reached or exceeded their daily quota.
    """
    if candidate.daily_quota > 0 and candidate.daily_quota != 999 and candidate.current_day_count >= candidate.daily_quota:
        return FilterResult(
            passed=False,
            rule_name="capacity",
            reason="Έχει συμπληρώσει το ημερήσιο όριο",
        )
    if candidate.daily_quota == 0 and candidate.current_day_count > 0:
        return FilterResult(
            passed=False,
            rule_name="capacity",
            reason="Έχει συμπληρώσει το ημερήσιο όριο",
        )
            
    return FilterResult(
        passed=True,
        rule_name="capacity",
        reason=f"Υπόλοιπο χωρητικότητας: {max(0, candidate.daily_quota - candidate.current_day_count)}/{candidate.daily_quota}" if candidate.daily_quota != 999 else "Χωρίς ημερήσιο όριο (999)",
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
    exam_type = exam.exam_name if exam.exam_name else (f"{exam.body_part} ({exam.modality})" if exam.body_part else exam.modality)
    if candidate.has_skill_data and candidate.skill_proficiency == 0.0:
        return FilterResult(
            passed=False,
            rule_name="skills",
            reason=f"Δεν μπορεί να διαγνώσει '{exam_type}'",
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
    is_ct = modality == "CT"
    is_mri = modality == "MRI"

    if is_ct and not candidate.can_ct:
        return FilterResult(
            passed=False,
            rule_name="modality",
            reason="Δεν αξιολογεί CTs",
        )
    if is_mri and not candidate.can_mri:
        return FilterResult(
            passed=False,
            rule_name="modality",
            reason="Δεν αξιολογεί MRIs",
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


def filter_by_web_lab(
    candidate: CandidateDiagnostician,
    exam: ExamContext,
) -> FilterResult:
    """
    WEB (id 222) should ONLY receive exams from ΚΟΛΙΑΤΣΟΥ lab.
    """
    if candidate.id == 222 and (exam.lab_name or "").upper() != "ΚΟΛΙΑΤΣΟΥ":
        return FilterResult(
            passed=False,
            rule_name="web_lab_constraint",
            reason="WEB παίρνει μόνο Κολιάτσου",
        )
    return FilterResult(
        passed=True,
        rule_name="web_lab_constraint",
        reason="WEB constraint passed"
    )


def apply_hard_filters(
    candidates: list[CandidateDiagnostician],
    exam: ExamContext,
) -> tuple[list[CandidateDiagnostician], dict[int, list[FilterResult]]]:
    """
    Apply all active hard filters to the candidate list.

    Active filters (per current business rules):
      1. Availability
      2. Capacity (daily quota limit)
      3. Modality capability (CT/MRI)
      4. Skills (only eliminates if proficiency == 0 AND data exists)
      5. Exclusive Lab Rules (Dynamic)
      6. Modality Quotas (Dynamic)
    """
    import diagflow.db.diagflow_db as cfg_db
    exclusive_rules = cfg_db.get_all_exclusive_lab_rules()
    modality_quotas = cfg_db.get_all_modality_quotas()

    def filter_by_exclusive_lab_dynamic(candidate: CandidateDiagnostician, exam: ExamContext) -> FilterResult:
        for rule in exclusive_rules:
            if not rule.get("is_active", True):
                continue
            if candidate.id == rule["diagnostician_id"]:
                if str(exam.lab_id) != str(rule["lab_id"]):
                    return FilterResult(
                        passed=False,
                        rule_name="exclusive_lab_constraint",
                        reason=f"Αποκλειστικό εργαστήριο ({rule['lab_name']})",
                    )
        return FilterResult(passed=True, rule_name="exclusive_lab_constraint", reason="OK")

    def filter_by_modality_quotas_dynamic(candidate: CandidateDiagnostician, exam: ExamContext) -> FilterResult:
        for quota in modality_quotas:
            if not quota.get("is_active", True):
                continue
            quota_mod = quota["modality"].upper()
            exam_mod = exam.modality.upper()
            
            match = False
            if quota_mod == "MRI" and exam_mod in ("MRI", "MRA"):
                match = True
            elif quota_mod == exam_mod:
                match = True
                
            if candidate.id == quota["diagnostician_id"] and match:
                current_count = candidate.current_day_ct_count if quota_mod == "CT" else candidate.current_day_mri_count
                if current_count >= quota["max_count"]:
                    return FilterResult(
                        passed=False,
                        rule_name="modality_quota",
                        reason=f"Έχει συμπληρώσει το όριο ({quota['max_count']} {quota['modality']}/ημέρα)",
                    )
        return FilterResult(passed=True, rule_name="modality_quota", reason="OK")

    active_filters = [
        filter_by_exclusive_lab_dynamic,
        filter_by_availability,
        filter_by_capacity,
        filter_by_modality_quotas_dynamic,
        filter_by_modality,
        filter_by_skills_hard,
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
