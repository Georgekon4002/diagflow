"""
DiagFlow — Rule Definitions & Registry

Defines all assignment rules with their priority, type (hard/weighted/penalty),
and weight configuration. Rules are registered here and referenced by the
pipeline, filters, and scoring modules.

Rule hierarchy (per business requirements):
  a. Availability          — HARD FILTER, priority 1
  b. Capacity              — WEIGHTED, priority 2
  c. Partnerships          — WEIGHTED, priority 3
  d. Skills                — HARD FILTER, priority 4
  e. Lab preference        — WEIGHTED, priority 5
  f. Patient history       — WEIGHTED, priority 6
  + Subcategory load       — SOFT PENALTY, priority 7
  [disabled] Comments      — Code kept but not active
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
        name="availability",
        display_name="Διαθεσιμότητα",
        rule_type=RuleType.HARD_FILTER,
        priority=1,
        description=(
            "Checks if the diagnostician is working today. "
            "Removes anyone on leave, day off, or otherwise unavailable."
        ),
    ),
    Rule(
        name="skills",
        display_name="Εξειδίκευση (Φίλτρο)",
        rule_type=RuleType.HARD_FILTER,
        priority=4,
        description=(
            "Hard filter on skills: if a diagnostician has a recorded proficiency "
            "of 0 for the exam's body-part/modality, they are eliminated. "
            "If no skill data exists, they pass through and get a neutral score."
        ),
    ),
    # ── Weighted Preferences (produce a score) ──
    Rule(
        name="capacity",
        display_name="Χωρητικότητα",
        rule_type=RuleType.WEIGHTED_PREFERENCE,
        priority=2,
        default_weight=0.30,
        description=(
            "Score based on remaining daily quota. "
            "Higher remaining capacity = higher score. "
            "Diagnosticians at or over their hard quota get score 0."
        ),
    ),
    Rule(
        name="partnership",
        display_name="Συνεργασία Ιατρού",
        rule_type=RuleType.WEIGHTED_PREFERENCE,
        priority=3,
        default_weight=0.25,
        description=(
            "Whether the issuing doctor has a preferred diagnostician. "
            "If matched, gives a significant scoring bonus."
        ),
    ),
    Rule(
        name="lab_preference",
        display_name="Προτίμηση Εργαστηρίου",
        rule_type=RuleType.WEIGHTED_PREFERENCE,
        priority=5,
        default_weight=0.10,
        description=(
            "Weighted score for whether a diagnostician accepts the exam's lab. "
            "Not accepting = score penalty, but not a hard elimination."
        ),
    ),
    Rule(
        name="patient_history",
        display_name="Ιστορικό Ασθενή",
        rule_type=RuleType.WEIGHTED_PREFERENCE,
        priority=6,
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
        priority=7,
        default_weight=0.05,
        description=(
            "Penalty that grows as a diagnostician's same-day count of a "
            "specific body-part category increases. Prevents overloading "
            "with repetitive work even when within hard quota. "
            "E.g., too many abdominal MRIs in one day."
        ),
    ),
    # ── DISABLED: Comment Exclusion ──
    # Code is preserved but not active in the current implementation phase.
    # Re-enable by setting enabled=True once comment parsing is production-ready.
    Rule(
        name="comment_exclusion",
        display_name="Σχόλια / Παρατηρήσεις",
        rule_type=RuleType.HARD_FILTER,
        priority=0,  # Would be highest priority when enabled
        description=(
            "LLM parses free-text comments from the secretariat. "
            "Can exclude specific diagnosticians or force a direct assignment. "
            'Example: "ΟΧΙ ΝΑΤΣΙΚΑ" excludes Νάτσικα from candidates.'
        ),
        enabled=False,  # DISABLED — not active in current implementation phase
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
