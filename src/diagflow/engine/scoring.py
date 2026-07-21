"""
DiagFlow — Weighted Scoring Logic

Computes a composite score for each candidate diagnostician.
Each scoring factor produces a 0.0–1.0 normalized score,
which is then multiplied by its configurable weight.

Scoring factors (in priority order per business rules):
  b. Capacity (remaining quota ratio)         — weight_capacity
  c. Partnership (issuing doctor preference)  — weight_partnership
  e. Lab preference (weighted, not hard)      — weight_lab
  f. Patient history (continuity of care)     — weight_patient_history

Note: Skills is a HARD FILTER (handled in filters.py), not a weighted score.
      If a candidate passes the skills hard filter, they get a weighted bonus here too.
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
    Priority b: Score based on remaining daily quota.

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


def score_partnership(candidate: CandidateDiagnostician, exam: ExamContext) -> ScoreComponent:
    """
    Priority c: Score based on issuing doctor partnership.

    If the issuing doctor has a preferred diagnostician and this candidate matches,
    they get a full score.
    """
    if candidate.is_partnership_exclusive:
        raw = 1.0
        explanation = (
            f"⚡ Αποκλειστική συνεργασία ιατρού '{exam.issuing_doctor_name}' → "
            f"{candidate.name}"
        )
    elif candidate.is_partnership_match:
        raw = 1.0
        explanation = (
            f"Προτίμηση ιατρού '{exam.issuing_doctor_name}' → "
            f"{candidate.name}"
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


def score_skills_weighted(candidate: CandidateDiagnostician, exam: ExamContext) -> ScoreComponent:
    """
    Skills weighted bonus (after passing the hard skills filter).

    Candidates with high proficiency get a bonus here.
    Candidates with no skill data (who passed the hard filter) get a neutral 0.3.
    This is separate from the hard skills filter — it rewards expertise.
    """
    if candidate.has_skill_match and candidate.has_skill_data:
        raw = candidate.skill_proficiency # Which is 1.0 if preferred, 0.5 if neutral
        if raw >= 1.0:
            explanation = f"Προτιμά εξετάσεις '{exam.body_part}' ({exam.modality})"
        else:
            explanation = f"Αποδεκτή εξέταση '{exam.body_part}' ({exam.modality}) (Ουδέτερο)"
    else:
        raw = 0.3  # Neutral — no data doesn't mean they can't do it
        explanation = f"Δεν υπάρχουν δεδομένα εξειδίκευσης για '{exam.body_part}' (ουδέτερο)"

    return ScoreComponent(
        rule_name="skills",
        display_name="Εξειδίκευση",
        raw_score=raw,
        weight=settings.weight_skills,
        weighted_score=raw * settings.weight_skills,
        explanation=explanation,
    )


def score_lab_preference(candidate: CandidateDiagnostician, exam: ExamContext) -> ScoreComponent:
    """
    Priority e: Weighted score for lab preference (NOT a hard filter).

    Diagnosticians who explicitly prefer this lab get full score.
    If they have no preference or it doesn't match, they get a neutral/low score,
    so they are not excluded but ranked lower if someone else prefers this lab.
    """
    preferred_lab_id = getattr(candidate, "preferred_lab_id", "")
    
    if preferred_lab_id and preferred_lab_id == str(exam.lab_id):
        raw = 1.0
        explanation = f"Προτιμά τις εξετάσεις από '{exam.lab_name}'"
    elif preferred_lab_id:
        raw = 0.1  # They prefer another lab
        explanation = f"Δεν είναι το προτιμώμενο εργαστήριό του/της (προτιμά άλλο)"
    else:
        raw = 0.5  # No specific preference
        explanation = f"Δεν έχει συγκεκριμένη προτίμηση εργαστηρίου (ουδέτερο)"

    return ScoreComponent(
        rule_name="lab_preference",
        display_name="Προτίμηση Εργαστηρίου",
        raw_score=raw,
        weight=settings.weight_lab,
        weighted_score=raw * settings.weight_lab,
        explanation=explanation,
    )


def score_patient_history(
    candidate: CandidateDiagnostician, exam: ExamContext
) -> ScoreComponent:
    """
    Priority f: Score based on continuity of care.

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



def compute_candidate_score(
    candidate: CandidateDiagnostician,
    exam: ExamContext,
) -> CandidateScore:
    """
    Compute the complete composite score for a single candidate.

    Order matches business rule priority:
      b. Capacity
      c. Partnership
      [d. Skills — hard filter in filters.py, bonus here]
      e. Lab preference (weighted)
      f. Patient history
    """
    components = [
        score_capacity(candidate),
        score_partnership(candidate, exam),
        score_skills_weighted(candidate, exam),
        score_lab_preference(candidate, exam),
        score_patient_history(candidate, exam),
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
