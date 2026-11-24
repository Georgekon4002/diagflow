"""
DiagFlow — OR-Tools CP-SAT Solver Wrapper

Uses Google's OR-Tools Constraint Programming SAT solver for batch
optimization of diagnostician assignments. When multiple exams are
pending simultaneously, the solver maximizes total score across all
assignments while respecting hard constraints (quotas, availability).

For single-exam assignments, the simple greedy approach (pick highest score)
is used instead — the solver is overkill for one exam.
"""

from dataclasses import dataclass

import structlog

from diagflow.engine.filters import CandidateDiagnostician, ExamContext
from diagflow.engine.scoring import CandidateScore

logger = structlog.get_logger(__name__)


@dataclass
class SolverAssignment:
    """Result of the solver — a single exam → diagnostician assignment."""

    exam_id: str
    diagnostician_id: int
    diagnostician_name: str
    score: float
    is_optimal: bool  # True if this was the solver's top pick


@dataclass
class SolverResult:
    """Complete result of running the solver on a batch of exams."""

    assignments: list[SolverAssignment]
    solver_status: str  # "OPTIMAL", "FEASIBLE", "INFEASIBLE", "GREEDY"
    solve_time_ms: float


def solve_single_assignment(
    exam: ExamContext,
    scored_candidates: list[CandidateScore],
) -> SolverResult:
    """
    Simple greedy assignment for a single exam.

    Just picks the highest-scoring candidate. No need for OR-Tools
    when there's only one exam to assign.
    """
    if not scored_candidates:
        logger.warning("no_candidates_for_assignment", exam_id=exam.exam_id)
        return SolverResult(
            assignments=[],
            solver_status="INFEASIBLE",
            solve_time_ms=0.0,
        )

    best = scored_candidates[0]  # Already sorted by score (highest first)

    return SolverResult(
        assignments=[
            SolverAssignment(
                exam_id=exam.exam_id,
                diagnostician_id=best.diagnostician_id,
                diagnostician_name=best.diagnostician_name,
                score=best.total_score,
                is_optimal=True,
            )
        ],
        solver_status="GREEDY",
        solve_time_ms=0.0,
    )


def solve_batch_assignment(
    exams: list[ExamContext],
    candidates_per_exam: dict[str, list[CandidateScore]],
    candidate_objects: dict[str, list[CandidateDiagnostician]],
    modality_quotas: list[dict] | None = None,
) -> SolverResult:
    """
    Batch optimization using OR-Tools CP-SAT solver.

    Maximizes total assigned exams + weighted score while respecting:
    - Each exam is assigned to at most one diagnostician (avoids all-or-nothing INFEASIBLE)
    - No diagnostician exceeds their daily hard quota
    - Per-modality daily quotas (CT / MRI+MRA) are respected
    - Same-order exams (matching patient_id + extracode) are assigned to the same diagnostician
      when a common eligible candidate exists
    - Soft workload balancing spreads equally-scored exams across diagnosticians
    """
    import time

    try:
        from ortools.sat.python import cp_model
    except ImportError:
        logger.error(
            "ortools_not_installed",
            message="OR-Tools is required for batch optimization. pip install ortools",
        )
        return _greedy_fallback(exams, candidates_per_exam, candidate_objects, modality_quotas)

    start_time = time.perf_counter()

    model = cp_model.CpModel()

    # ── Decision variables ──
    # x[exam_id][diagnostician_id] = 1 if assigned, 0 otherwise
    x: dict[str, dict[int, cp_model.IntVar]] = {}

    all_diagnostician_ids: set[int] = set()

    for exam in exams:
        exam_scores = candidates_per_exam.get(exam.exam_id, [])
        x[exam.exam_id] = {}

        for cs in exam_scores:
            var_name = f"x_{exam.exam_id}_{cs.diagnostician_id}"
            x[exam.exam_id][cs.diagnostician_id] = model.new_bool_var(var_name)
            all_diagnostician_ids.add(cs.diagnostician_id)

    # ── Constraints ──

    # Each exam is assigned to at most one diagnostician (high assignment reward ensures
    # maximal assignment even when total demand exceeds remaining capacity)
    for exam in exams:
        if x[exam.exam_id]:
            model.add_at_most_one(x[exam.exam_id].values())

    # Build lookups of remaining daily capacity and current counts per diagnostician
    capacity_lookup: dict[int, int] = {}
    cand_info_lookup: dict[int, CandidateDiagnostician] = {}
    for exam in exams:
        cands = candidate_objects.get(exam.exam_id, [])
        for c in cands:
            if c.id not in capacity_lookup:
                remaining = (
                    len(exams)
                    if c.daily_quota == 999
                    else max(0, c.daily_quota - c.current_day_count)
                )
                capacity_lookup[c.id] = remaining
                cand_info_lookup[c.id] = c

    # 1. Total daily quota per diagnostician
    for diag_id in all_diagnostician_ids:
        assignments_for_diag = [
            x[exam.exam_id][diag_id]
            for exam in exams
            if diag_id in x[exam.exam_id]
        ]
        if assignments_for_diag:
            remaining = capacity_lookup.get(diag_id, 0)
            model.add(sum(assignments_for_diag) <= remaining)

    # 2. Per-modality daily quotas (CT / MRI+MRA)
    if modality_quotas:
        for quota in modality_quotas:
            if not quota.get("is_active", True):
                continue
            diag_id = int(quota["diagnostician_id"])
            if diag_id not in all_diagnostician_ids:
                continue
            q_mod = str(quota.get("modality") or "").upper()
            max_cnt = int(quota.get("max_count", 0))
            c_info = cand_info_lookup.get(diag_id)
            cur_mod_cnt = (
                (c_info.current_day_ct_count if q_mod == "CT" else c_info.current_day_mri_count)
                if c_info
                else 0
            )
            rem_mod = max(0, max_cnt - cur_mod_cnt)
            matching_vars = []
            for exam in exams:
                e_mod = (exam.modality or "").upper()
                is_match = (q_mod == "MRI" and e_mod in ("MRI", "MRA")) or (q_mod == e_mod)
                if is_match and diag_id in x[exam.exam_id]:
                    matching_vars.append(x[exam.exam_id][diag_id])
            if matching_vars:
                model.add(sum(matching_vars) <= rem_mod)

    # 3. Same-order (extracode) consistency: keep multi-exam orders on the same diagnostician
    order_groups: dict[tuple[str, str], list[ExamContext]] = {}
    for exam in exams:
        ext = str(getattr(exam, "extracode", "") or "").strip()
        if ext:
            key = (str(exam.patient_id or "").strip(), ext)
            order_groups.setdefault(key, []).append(exam)

    for group_exams in order_groups.values():
        if len(group_exams) < 2:
            continue
        # Only enforce when every exam in the group has decision variables and shares >=1 common candidate
        if not all(x.get(e.exam_id) for e in group_exams):
            continue
        common_diags = set.intersection(*(set(x[e.exam_id].keys()) for e in group_exams))
        if not common_diags:
            continue
        first_exam = group_exams[0]
        for other_exam in group_exams[1:]:
            for diag_id in common_diags:
                model.add(x[first_exam.exam_id][diag_id] == x[other_exam.exam_id][diag_id])
        # Disallow assigning an exam in the group to a non-common doctor if another doctor can take all
        for e in group_exams:
            for diag_id in list(x[e.exam_id].keys()):
                if diag_id not in common_diags:
                    model.add(x[e.exam_id][diag_id] == 0)

    # ── Objective: maximize assigned count + total weighted score - soft load imbalance ──
    ASSIGN_BONUS = 100_000
    SCORE_SCALE = 1000
    LOAD_PENALTY_PER_EXISTING = 2  # Gentle tie-break favoring lower current workload

    objective_terms = []
    for exam in exams:
        exam_scores = candidates_per_exam.get(exam.exam_id, [])
        for cs in exam_scores:
            if cs.diagnostician_id in x[exam.exam_id]:
                scaled_score = round(cs.total_score * SCORE_SCALE)
                c_info = cand_info_lookup.get(cs.diagnostician_id)
                existing_load = c_info.current_day_count if c_info else 0
                coeff = ASSIGN_BONUS + scaled_score - (existing_load * LOAD_PENALTY_PER_EXISTING)
                objective_terms.append(x[exam.exam_id][cs.diagnostician_id] * coeff)

    # Progressive per-doctor batch spread penalty: penalizes peak batch load so tied doctors share work
    max_batch_load = model.new_int_var(0, max(1, len(exams)), "max_batch_load")
    for diag_id in all_diagnostician_ids:
        diag_vars = [x[exam.exam_id][diag_id] for exam in exams if diag_id in x[exam.exam_id]]
        if diag_vars:
            c_info = cand_info_lookup.get(diag_id)
            existing_load = c_info.current_day_count if c_info else 0
            model.add(existing_load + sum(diag_vars) <= max_batch_load + existing_load)
            # Track batch additions to keep peak batch load balanced across tied doctors
            model.add(sum(diag_vars) <= max_batch_load)

    # Small penalty (5 pts) on peak batch load breaks ties evenly without overriding real score gaps
    model.maximize(sum(objective_terms) - max_batch_load * 5)

    # ── Solve ──
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0  # Hard limit for responsiveness

    status = solver.solve(model)
    solve_time = (time.perf_counter() - start_time) * 1000

    # ── Extract results ──
    assignments: list[SolverAssignment] = []

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        status_str = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"

        for exam in exams:
            exam_scores = candidates_per_exam.get(exam.exam_id, [])
            for cs in exam_scores:
                if cs.diagnostician_id in x[exam.exam_id]:
                    if solver.value(x[exam.exam_id][cs.diagnostician_id]):
                        assignments.append(
                            SolverAssignment(
                                exam_id=exam.exam_id,
                                diagnostician_id=cs.diagnostician_id,
                                diagnostician_name=cs.diagnostician_name,
                                score=cs.total_score,
                                is_optimal=(status == cp_model.OPTIMAL),
                            )
                        )
                        break

        logger.info(
            "solver_complete",
            status=status_str,
            exams=len(exams),
            assignments=len(assignments),
            solve_time_ms=f"{solve_time:.1f}",
            objective_value=solver.objective_value,
        )
    else:
        status_str = "INFEASIBLE"
        logger.warning(
            "solver_infeasible",
            exams=len(exams),
            message="No feasible assignment found. Falling back to quota-aware greedy.",
        )
        return _greedy_fallback(exams, candidates_per_exam, candidate_objects, modality_quotas)

    return SolverResult(
        assignments=assignments,
        solver_status=status_str,
        solve_time_ms=solve_time,
    )


def _greedy_fallback(
    exams: list[ExamContext],
    candidates_per_exam: dict[str, list[CandidateScore]],
    candidate_objects: dict[str, list[CandidateDiagnostician]] | None = None,
    modality_quotas: list[dict] | None = None,
) -> SolverResult:
    """Quota-aware greedy fallback when CP-SAT cannot be used."""
    remaining_total: dict[int, int] = {}
    remaining_mod: dict[tuple[int, str], int] = {}

    if candidate_objects:
        for exam in exams:
            for c in candidate_objects.get(exam.exam_id, []):
                if c.id not in remaining_total:
                    remaining_total[c.id] = (
                        999_999 if c.daily_quota == 999 else max(0, c.daily_quota - c.current_day_count)
                    )
        if modality_quotas:
            cand_by_id = {
                c.id: c
                for cands in candidate_objects.values()
                for c in cands
            }
            for q in modality_quotas:
                if not q.get("is_active", True):
                    continue
                did = int(q["diagnostician_id"])
                q_mod = str(q.get("modality") or "").upper()
                c = cand_by_id.get(did)
                cur = (c.current_day_ct_count if q_mod == "CT" else c.current_day_mri_count) if c else 0
                remaining_mod[(did, q_mod)] = max(0, int(q.get("max_count", 0)) - cur)

    assignments = []
    for exam in exams:
        scores = candidates_per_exam.get(exam.exam_id, [])
        e_mod = (exam.modality or "").upper()
        mod_key_name = "MRI" if e_mod in ("MRI", "MRA") else e_mod
        for cs in scores:
            did = cs.diagnostician_id
            if remaining_total and remaining_total.get(did, 0) <= 0:
                continue
            if (did, mod_key_name) in remaining_mod and remaining_mod[(did, mod_key_name)] <= 0:
                continue
            assignments.append(
                SolverAssignment(
                    exam_id=exam.exam_id,
                    diagnostician_id=did,
                    diagnostician_name=cs.diagnostician_name,
                    score=cs.total_score,
                    is_optimal=False,
                )
            )
            if did in remaining_total:
                remaining_total[did] -= 1
            if (did, mod_key_name) in remaining_mod:
                remaining_mod[(did, mod_key_name)] -= 1
            break

    return SolverResult(
        assignments=assignments,
        solver_status="GREEDY",
        solve_time_ms=0.0,
    )
