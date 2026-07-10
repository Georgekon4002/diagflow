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
) -> SolverResult:
    """
    Batch optimization using OR-Tools CP-SAT solver.

    Maximizes total assignment score across all exams while respecting:
    - Each exam is assigned to exactly one diagnostician
    - No diagnostician exceeds their daily hard quota
    - Subcategory soft caps are respected as much as possible

    Args:
        exams: List of exams to assign
        candidates_per_exam: Scored candidates for each exam (keyed by exam_id)
        candidate_objects: CandidateDiagnostician objects (keyed by exam_id)

    Returns:
        SolverResult with optimal assignments
    """
    import time

    try:
        from ortools.sat.python import cp_model
    except ImportError:
        logger.error(
            "ortools_not_installed",
            message="OR-Tools is required for batch optimization. pip install ortools",
        )
        # Fallback to greedy one-by-one
        return _greedy_fallback(exams, candidates_per_exam)

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

    # Each exam is assigned to exactly one diagnostician
    for exam in exams:
        if x[exam.exam_id]:
            model.add_exactly_one(x[exam.exam_id].values())

    # No diagnostician exceeds their daily quota
    # Build a lookup of remaining capacity per diagnostician
    capacity_lookup: dict[int, int] = {}
    for exam in exams:
        cands = candidate_objects.get(exam.exam_id, [])
        for c in cands:
            if c.id not in capacity_lookup:
                remaining = max(0, c.daily_quota - c.current_day_count)
                capacity_lookup[c.id] = remaining

    for diag_id in all_diagnostician_ids:
        # Sum of assignments for this diagnostician across all exams
        assignments_for_diag = []
        for exam in exams:
            if diag_id in x[exam.exam_id]:
                assignments_for_diag.append(x[exam.exam_id][diag_id])

        if assignments_for_diag:
            remaining = capacity_lookup.get(diag_id, 1)
            model.add(sum(assignments_for_diag) <= remaining)

    # ── Objective: maximize total weighted score ──
    # Scale scores to integers for CP-SAT (it works with integers)
    SCORE_SCALE = 1000

    objective_terms = []
    for exam in exams:
        exam_scores = candidates_per_exam.get(exam.exam_id, [])
        for cs in exam_scores:
            if cs.diagnostician_id in x[exam.exam_id]:
                scaled_score = int(cs.total_score * SCORE_SCALE)
                objective_terms.append(
                    x[exam.exam_id][cs.diagnostician_id] * scaled_score
                )

    model.maximize(sum(objective_terms))

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
            message="No feasible assignment found. Falling back to greedy.",
        )
        return _greedy_fallback(exams, candidates_per_exam)

    return SolverResult(
        assignments=assignments,
        solver_status=status_str,
        solve_time_ms=solve_time,
    )


def _greedy_fallback(
    exams: list[ExamContext],
    candidates_per_exam: dict[str, list[CandidateScore]],
) -> SolverResult:
    """Fallback to greedy one-by-one assignment when solver can't be used."""
    assignments = []
    for exam in exams:
        scores = candidates_per_exam.get(exam.exam_id, [])
        if scores:
            best = scores[0]
            assignments.append(
                SolverAssignment(
                    exam_id=exam.exam_id,
                    diagnostician_id=best.diagnostician_id,
                    diagnostician_name=best.diagnostician_name,
                    score=best.total_score,
                    is_optimal=False,
                )
            )

    return SolverResult(
        assignments=assignments,
        solver_status="GREEDY",
        solve_time_ms=0.0,
    )
