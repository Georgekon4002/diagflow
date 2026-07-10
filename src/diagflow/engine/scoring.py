"""
DiagFlow — Weighted Scoring Logic

Computes a composite score for each candidate diagnostician.
Each scoring factor produces a 0.0–1.0 normalized score,
which is then multiplied by its configurable weight.

Scoring factors:
3. Capacity (remaining quota ratio)
4. Skills (body-part/modality proficiency match)
6. Partnership (issuing doctor preference)
7. Patient history (continuity of care)
+ Subcategory load penalty (soft load-balancing)
"""

from dataclasses import dataclass

import structlog

from diagflow.config import settings
from diagflow.engine.filters import CandidateDiagnostician, ExamContext

logger = structlog.get_logger(__name__)


@dataclass
class ScoreComponent:
    """A single component of the composite score."""

    rule_name: str
    display_name: str
    raw_score: float  # 0.0 to 1.0
    weight: float
    weighted_score: float  # raw_score * weight
    explanation: str


@dataclass
class CandidateScore:
    """Complete scoring result for a candidate."""

    diagnostician_id: int
    diagnostician_name: str
    total_score: float
    components: list[ScoreComponent]
    rank: int = 0  # Populated after sorting


def score_capacity(candidate: CandidateDiagnostician) -> ScoreComponent:
    """
    Priority 3: Score based on remaining daily quota.

    Score = remaining_slots / total_quota
    At quota → 0.0, fully available → 1.0
    Over quota → 0.0 (should have been filtered, but defensive)
    """
    if candidate.daily_quota <= 0:
        raw = 0.0
    else:
        remaining = max(0, candidate.daily_quota - candidate.current_day_count)
        raw = remaining / candidate.daily_quota

    return ScoreComponent(
        rule_name="capacity",
        display_name="Χωρητικότητα",
        raw_score=raw,
        weight=settings.weight_capacity,
        weighted_score=raw * settings.weight_capacity,
        explanation=(
            f"Υπόλοιπο: {max(0, candidate.daily_quota - candidate.current_day_count)}"
            f"/{candidate.daily_quota} εξετάσεις"
        ),
    )


def score_skills(candidate: CandidateDiagnostician, exam: ExamContext) -> ScoreComponent:
    """
    Priority 4: Score based on body-part/modality skill match.

    Uses the proficiency_level from diagnostician_skills table.
    Exact match = proficiency (0.0-1.0), no skill data = 0.3 (neutral default).
    """
    if candidate.has_skill_match:
        raw = candidate.skill_proficiency
        explanation = (
            f"Εξειδίκευση στο '{exam.body_part}' ({exam.modality}): "
            f"{candidate.skill_proficiency:.0%}"
        )
    else:
        raw = 0.3  # Neutral — no data doesn't mean they can't do it
        explanation = f"Δεν υπάρχουν δεδομένα εξειδίκευσης για '{exam.body_part}'"

    return ScoreComponent(
        rule_name="skills",
        display_name="Εξειδίκευση",
        raw_score=raw,
        weight=settings.weight_skills,
        weighted_score=raw * settings.weight_skills,
        explanation=explanation,
    )


def score_partnership(candidate: CandidateDiagnostician, exam: ExamContext) -> ScoreComponent:
    """
    Priority 6: Score based on issuing doctor partnership.

    If the issuing doctor has a preferred diagnostician and this candidate matches,
    they get a full score. Higher partnership priority = higher score.
    """
    if candidate.is_partnership_match:
        # Normalize priority to 0.0–1.0 (assuming priority 1-5 scale)
        raw = min(1.0, candidate.partnership_priority / 5.0) if candidate.partnership_priority > 0 else 1.0
        explanation = (
            f"Προτίμηση ιατρού '{exam.issuing_doctor_name}' → "
            f"{candidate.name} (προτεραιότητα: {candidate.partnership_priority})"
        )
    else:
        raw = 0.0
        explanation = f"Δεν υπάρχει συνεργασία με τον ιατρό '{exam.issuing_doctor_name}'"

    return ScoreComponent(
        rule_name="partnership",
        display_name="Συνεργασία Ιατρού",
        raw_score=raw,
        weight=settings.weight_partnership,
        weighted_score=raw * settings.weight_partnership,
        explanation=explanation,
    )


def score_patient_history(
    candidate: CandidateDiagnostician, exam: ExamContext
) -> ScoreComponent:
    """
    Priority 7: Score based on continuity of care.

    If this diagnostician has handled this patient's past similar exams,
    they get a bonus for consistency.
    """
    if candidate.has_patient_history:
        # More past assignments = stronger continuity signal, capped at 1.0
        raw = min(1.0, candidate.patient_history_count * 0.3)
        explanation = (
            f"Ο/Η {candidate.name} έχει αξιολογήσει {candidate.patient_history_count} "
            f"παρόμοιες εξετάσεις αυτού του ασθενή στο παρελθόν"
        )
    else:
        raw = 0.0
        explanation = "Δεν υπάρχει ιστορικό με αυτόν τον ασθενή"

    return ScoreComponent(
        rule_name="patient_history",
        display_name="Ιστορικό Ασθενή",
        raw_score=raw,
        weight=settings.weight_patient_history,
        weighted_score=raw * settings.weight_patient_history,
        explanation=explanation,
    )


def penalty_subcategory_load(
    candidate: CandidateDiagnostician, exam: ExamContext
) -> ScoreComponent:
    """
    Soft load-balancing penalty.

    Grows as the diagnostician's same-day count of the same body-part category
    increases. Uses soft sub-caps if defined, otherwise uses a general formula.

    The penalty is SUBTRACTED from the total score.
    """
    if candidate.subcategory_soft_cap and candidate.subcategory_soft_cap > 0:
        # Penalty based on proximity to soft cap
        ratio = candidate.current_subcategory_count / candidate.subcategory_soft_cap
        raw = min(1.0, ratio)  # 0.0 when no exams, 1.0 when at/over soft cap
        explanation = (
            f"Φόρτος κατηγορίας '{exam.body_part}': "
            f"{candidate.current_subcategory_count}/{candidate.subcategory_soft_cap} "
            f"(ήπιο όριο)"
        )
    elif candidate.current_subcategory_count > 0:
        # General penalty — starts light, grows with each same-category exam
        raw = min(1.0, candidate.current_subcategory_count * 0.15)
        explanation = (
            f"Φόρτος κατηγορίας '{exam.body_part}': "
            f"{candidate.current_subcategory_count} σήμερα "
            f"(χωρίς ήπιο όριο, γενική ποινή)"
        )
    else:
        raw = 0.0
        explanation = f"Καμία εξέταση κατηγορίας '{exam.body_part}' σήμερα"

    return ScoreComponent(
        rule_name="subcategory_load",
        display_name="Ποινή Υποκατηγορίας",
        raw_score=raw,
        weight=settings.weight_subcategory_penalty,
        weighted_score=-(raw * settings.weight_subcategory_penalty),  # Negative = penalty
        explanation=explanation,
    )


def compute_candidate_score(
    candidate: CandidateDiagnostician,
    exam: ExamContext,
) -> CandidateScore:
    """
    Compute the complete composite score for a single candidate.

    Combines all weighted scoring components and applies penalties.
    """
    components = [
        score_capacity(candidate),
        score_skills(candidate, exam),
        score_partnership(candidate, exam),
        score_patient_history(candidate, exam),
        penalty_subcategory_load(candidate, exam),
    ]

    total = sum(c.weighted_score for c in components)

    # Clamp to [0, 1] range
    total = max(0.0, min(1.0, total))

    return CandidateScore(
        diagnostician_id=candidate.id,
        diagnostician_name=candidate.name,
        total_score=total,
        components=components,
    )


def score_all_candidates(
    candidates: list[CandidateDiagnostician],
    exam: ExamContext,
) -> list[CandidateScore]:
    """
    Score all candidates and return sorted by total_score (highest first).

    Also assigns rank numbers (1 = best).
    """
    scores = [compute_candidate_score(c, exam) for c in candidates]
    scores.sort(key=lambda s: s.total_score, reverse=True)

    for i, score in enumerate(scores):
        score.rank = i + 1

    logger.info(
        "scoring_complete",
        exam_id=exam.exam_id,
        candidates_scored=len(scores),
        top_candidate=scores[0].diagnostician_name if scores else "none",
        top_score=f"{scores[0].total_score:.3f}" if scores else "n/a",
    )

    return scores
