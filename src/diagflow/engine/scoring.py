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


def score_capacity(candidate: CandidateDiagnostician, weights: dict) -> ScoreComponent:
    """
    Priority b: Score based on remaining daily quota.

    Score = remaining_slots / total_quota
    At quota → 0.0, fully available → 1.0
    Over quota → 0.0 (should have been filtered, but defensive)
    """
    pts_max = float(weights.get("pts_capacity", 0.1))
    
    if candidate.daily_quota <= 0:
        actual_pts = 0.0
        raw = 0.0
    else:
        remaining = max(0, candidate.daily_quota - candidate.current_day_count)
        raw = remaining / candidate.daily_quota
        actual_pts = raw * pts_max

    return ScoreComponent(
        rule_name="capacity",
        display_name="Χωρητικότητα",
        raw_score=raw,
        weight=pts_max,
        weighted_score=actual_pts,
        explanation=(
            f"Υπόλοιπο: {max(0, candidate.daily_quota - candidate.current_day_count)}"
            f"/{candidate.daily_quota} εξετάσεις"
        ),
    )


def score_partnership(candidate: CandidateDiagnostician, exam: ExamContext, weights: dict) -> ScoreComponent:
    """
    Priority c: Score based on issuing doctor partnership.

    If the issuing doctor has a preferred diagnostician and this candidate matches,
    they get a full score.
    """
    pts_max = float(weights.get("pts_partnership", 0.35))
    
    if candidate.is_partnership_exclusive:
        actual_pts = pts_max
        explanation = (
            f"⚡ Αποκλειστική συνεργασία ιατρού '{exam.issuing_doctor_name}' → "
            f"{candidate.name}"
        )
    elif candidate.is_partnership_match:
        actual_pts = pts_max
        explanation = (
            f"Προτίμηση ιατρού '{exam.issuing_doctor_name}' → "
            f"{candidate.name}"
        )
    else:
        actual_pts = 0.0
        explanation = f"Δεν υπάρχει συνεργασία με τον ιατρό '{exam.issuing_doctor_name}'"

    raw = actual_pts / pts_max if pts_max > 0 else 0.0

    return ScoreComponent(
        rule_name="partnership",
        display_name="Συνεργασία Ιατρού",
        raw_score=raw,
        weight=pts_max,
        weighted_score=actual_pts,
        explanation=explanation,
    )


def score_skills_weighted(candidate: CandidateDiagnostician, exam: ExamContext, weights: dict) -> ScoreComponent:
    """
    Skills weighted bonus (after passing the hard skills filter).

    Candidates with high proficiency get a bonus here.
    Candidates with no skill data (who passed the hard filter) get a neutral 0.3.
    This is separate from the hard skills filter — it rewards expertise.
    """
    exam_type = exam.exam_name if exam.exam_name else (f"{exam.body_part} ({exam.modality})" if exam.body_part else exam.modality)
    
    pts_max = float(weights.get("pts_skills_pref", 0.20))
    pts_neut = float(weights.get("pts_skills_neut", 0.10))
    pts_none = float(weights.get("pts_skills_none", 0.06))
    
    if candidate.has_skill_match and candidate.has_skill_data:
        if candidate.skill_proficiency >= 1.0:
            actual_pts = pts_max
            explanation = f"Προτιμά να διαγνώσει '{exam_type}'"
        else:
            actual_pts = pts_neut
            explanation = f"Μπορεί να διαγνώσει '{exam_type}' (Ουδέτερο)"
    else:
        actual_pts = pts_none
        explanation = f"Δεν υπάρχουν δεδομένα εξειδίκευσης για '{exam_type}' (ουδέτερο)"

    raw = actual_pts / pts_max if pts_max > 0 else 0.0

    return ScoreComponent(
        rule_name="skills",
        display_name="Εξειδίκευση",
        raw_score=raw,
        weight=pts_max,
        weighted_score=actual_pts,
        explanation=explanation,
    )


def score_lab_preference(candidate: CandidateDiagnostician, exam: ExamContext, weights: dict) -> ScoreComponent:
    """
    Priority e: Weighted score for lab preference (NOT a hard filter).

    Diagnosticians who explicitly prefer this lab get full score.
    If they have no preference or it doesn't match, they get a neutral/low score,
    so they are not excluded but ranked lower if someone else prefers this lab.
    """
    pts_max = float(weights.get("pts_lab_pref", 0.15))
    pts_neut = float(weights.get("pts_lab_neut", 0.075))
    pts_other = float(weights.get("pts_lab_other", 0.015))
    
    preferred_lab_id = getattr(candidate, "preferred_lab_id", "")
    
    if preferred_lab_id and str(preferred_lab_id) == str(exam.lab_id):
        actual_pts = pts_max
        explanation = f"Προτιμά τις εξετάσεις από '{exam.lab_name}'"
    elif preferred_lab_id:
        actual_pts = pts_other
        explanation = f"Δεν είναι το προτιμώμενο εργαστήριό του/της (προτιμά άλλο)"
    else:
        actual_pts = pts_neut
        explanation = f"Δεν έχει συγκεκριμένη προτίμηση εργαστηρίου (ουδέτερο)"

    raw = actual_pts / pts_max if pts_max > 0 else 0.0

    return ScoreComponent(
        rule_name="lab_preference",
        display_name="Προτίμηση Εργαστηρίου",
        raw_score=raw,
        weight=pts_max,
        weighted_score=actual_pts,
        explanation=explanation,
    )


def score_patient_history(
    candidate: CandidateDiagnostician, exam: ExamContext, weights: dict
) -> ScoreComponent:
    """
    Priority f: Score based on continuity of care.

    If this diagnostician has handled this patient's past similar exams,
    they get a bonus for consistency.
    """
    pts_max = float(weights.get("pts_history", 0.20))
    
    if candidate.has_patient_history:
        actual_pts = pts_max
        explanation = (
            f"Ο/Η {candidate.name} έχει αξιολογήσει εξέταση "
            f"αυτού του ασθενή στο παρελθόν"
        )
    else:
        actual_pts = 0.0
        explanation = "Δεν υπάρχει ιστορικό με αυτόν τον ασθενή"

    raw = actual_pts / pts_max if pts_max > 0 else 0.0

    return ScoreComponent(
        rule_name="patient_history",
        display_name="Ιστορικό Ασθενή",
        raw_score=raw,
        weight=pts_max,
        weighted_score=actual_pts,
        explanation=explanation,
    )



def compute_candidate_score(
    candidate: CandidateDiagnostician,
    exam: ExamContext,
    weights: dict,
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
        score_skills_weighted(candidate, exam, weights),
        score_patient_history(candidate, exam, weights),
        score_partnership(candidate, exam, weights),
        score_lab_preference(candidate, exam, weights),
        score_capacity(candidate, weights),
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

    Load-balancing / near-tie handling:
      Candidates whose score is within `settings.score_tie_tolerance` of the top score
      are placed in a "near-tie group". Within this group, ranking is determined by
      workload (fewest exams today first), then quota size, then random jitter.
      Candidates clearly outside the tolerance are ranked strictly by score as normal.

    This prevents the same diagnostician from receiving all proposals when multiple
    equally-good candidates exist (e.g., 28% vs 27% should rotate, not always pick 28%).
    """
    import math
    import random
    from diagflow.db.diagflow_db import get_system_weights
    
    weights = get_system_weights()
    scored_pairs = []
    
    for c in candidates:
        candidate_score = compute_candidate_score(c, exam, weights)
        scored_pairs.append((c, candidate_score))

    # First pass: find the top raw score to determine the near-tie boundary
    if not scored_pairs:
        return []

    top_score = max(pair[1].total_score for pair in scored_pairs)
    tolerance = settings.score_tie_tolerance

    def sort_key(pair: tuple[CandidateDiagnostician, "CandidateScore"]) -> tuple:
        candidate, score = pair
        is_near_tie = (top_score - score.total_score) <= tolerance

        if is_near_tie:
            # Within the near-tie group: sort by workload, then random
            # Negate current_day_count so fewer exams = higher sort priority (reverse=True)
            return (
                1,                            # Group 0 = near-tie (sorts higher with reverse=True)
                -candidate.current_day_count, # Fewest exams today first
                candidate.daily_quota,        # Larger quota = more capacity
                random.random(),              # Random jitter for final tie-break
            )
        else:
            # Outside the tolerance: rank strictly by score
            return (
                0,                            # Group 1 = strict (sorts lower)
                score.total_score,            # Higher score wins
                -candidate.current_day_count,
                candidate.daily_quota,
            )

    scored_pairs.sort(key=sort_key, reverse=True)

    scores = [pair[1] for pair in scored_pairs]

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
