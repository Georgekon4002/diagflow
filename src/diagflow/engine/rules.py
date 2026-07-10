"""
DiagFlow — Rule Definitions & Registry

Defines all assignment rules with their priority, type (hard/weighted/penalty),
and weight configuration. Rules are registered here and referenced by the
pipeline, filters, and scoring modules.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RuleType(Enum):
    """Classification of rule behavior."""

    HARD_FILTER = "hard_filter"  # Must satisfy — fail = removed from pool
    WEIGHTED_PREFERENCE = "weighted_preference"  # Produces a score, can trade off
    SOFT_PENALTY = "soft_penalty"  # Load-balancing penalty that grows with usage


@dataclass
class Rule:
    """
    Definition of a single assignment rule.

    Attributes:
        name: Unique identifier for the rule
        display_name: Human-readable name (shown in UI)
        rule_type: Hard filter, weighted preference, or soft penalty
        priority: Lower number = higher priority (evaluated first)
        default_weight: Default weight for scoring (only for WEIGHTED_PREFERENCE)
        description: What this rule does
        enabled: Whether this rule is active
    """

    name: str
    display_name: str
    rule_type: RuleType
    priority: int
    default_weight: float = 0.0
    description: str = ""
    enabled: bool = True


# ──────────────────────────────────────────────────────────────
# Rule Registry — All rules defined here, ordered by priority
# ──────────────────────────────────────────────────────────────

RULES: list[Rule] = [
    # ── Hard Filters (must satisfy) ──
    Rule(
        name="comment_exclusion",
        display_name="Σχόλια / Παρατηρήσεις",
        rule_type=RuleType.HARD_FILTER,
        priority=1,
        description=(
            "LLM parses free-text comments from the secretariat. "
            "Can exclude specific diagnosticians or force a direct assignment. "
            'Example: "ΟΧΙ ΝΑΤΣΙΚΑ" excludes Νάτσικα from candidates.'
        ),
    ),
    Rule(
        name="availability",
        display_name="Διαθεσιμότητα",
        rule_type=RuleType.HARD_FILTER,
        priority=2,
        description=(
            "Checks if the diagnostician is working today. "
            "Removes anyone on leave, day off, or otherwise unavailable."
        ),
    ),
    Rule(
        name="lab_preference",
        display_name="Προτίμηση Εργαστηρίου",
        rule_type=RuleType.HARD_FILTER,
        priority=5,
        description=(
            "Some diagnosticians only accept work from specific labs. "
            "If a diagnostician has lab preferences set and the exam's lab "
            "is not in their accepted list, they are removed."
        ),
    ),
    Rule(
        name="modality_filter",
        display_name="Τύπος Εξέτασης (CT/MRI)",
        rule_type=RuleType.HARD_FILTER,
        priority=2,  # Same priority as availability — both are basic eligibility
        description=(
            "Checks if the diagnostician can handle this modality. "
            "Some can do CT only, MRI only, or both."
        ),
    ),
    # ── Weighted Preferences (produce a score) ──
    Rule(
        name="capacity",
        display_name="Χωρητικότητα",
        rule_type=RuleType.WEIGHTED_PREFERENCE,
        priority=3,
        default_weight=0.30,
        description=(
            "Score based on remaining daily quota. "
            "Higher remaining capacity = higher score. "
            "Diagnosticians at or over their hard quota get score 0."
        ),
    ),
    Rule(
        name="skills",
        display_name="Εξειδίκευση",
        rule_type=RuleType.WEIGHTED_PREFERENCE,
        priority=4,
        default_weight=0.25,
        description=(
            "How well the diagnostician's skills match the exam's body part. "
            "Exact match = 1.0, partial/related match = 0.5, no data = 0.3."
        ),
    ),
    Rule(
        name="partnership",
        display_name="Συνεργασία Ιατρού",
        rule_type=RuleType.WEIGHTED_PREFERENCE,
        priority=6,
        default_weight=0.25,
        description=(
            "Whether the issuing doctor has a preferred diagnostician. "
            "If matched, gives a significant scoring bonus."
        ),
    ),
    Rule(
        name="patient_history",
        display_name="Ιστορικό Ασθενή",
        rule_type=RuleType.WEIGHTED_PREFERENCE,
        priority=7,
        default_weight=0.15,
        description=(
            "Continuity of care — same diagnostician for same patient's "
            "past similar exams. Gives a bonus for consistency."
        ),
    ),
    # ── Soft Penalties (load-balancing) ──
    Rule(
        name="subcategory_load",
        display_name="Ισορροπία Φόρτου Υποκατηγορίας",
        rule_type=RuleType.SOFT_PENALTY,
        priority=8,
        default_weight=0.05,
        description=(
            "Penalty that grows as a diagnostician's same-day count of a "
            "specific body-part category increases. Prevents overloading "
            "with repetitive work even when within hard quota. "
            "E.g., too many abdominal MRIs in one day."
        ),
    ),
]


def get_rules_by_type(rule_type: RuleType) -> list[Rule]:
    """Get all enabled rules of a specific type, sorted by priority."""
    return sorted(
        [r for r in RULES if r.rule_type == rule_type and r.enabled],
        key=lambda r: r.priority,
    )


def get_rule_by_name(name: str) -> Optional[Rule]:
    """Look up a rule by its unique name."""
    for rule in RULES:
        if rule.name == name:
            return rule
    return None


def get_all_enabled_rules() -> list[Rule]:
    """Get all enabled rules, sorted by priority."""
    return sorted([r for r in RULES if r.enabled], key=lambda r: r.priority)
