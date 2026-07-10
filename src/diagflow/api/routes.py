"""
DiagFlow — API Route Definitions

REST endpoints for the secretariat review dashboard:
- GET  /api/exams/pending — List pending exams
- POST /api/assignments/suggest — Generate assignment suggestion
- POST /api/assignments/confirm — Confirm a suggestion
- POST /api/assignments/override — Override a suggestion
- GET  /api/diagnosticians — List all diagnosticians
- GET  /api/pamakristos/oncall — Get today's on-call
- POST /api/pamakristos/oncall — Set on-call manually
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from diagflow.api.dependencies import (
    get_assignment_service,
    get_diagnostician_service,
    get_pamakristos_scheduler,
)
from diagflow.api.schemas import (
    AssignmentConfirmation,
    ConfirmAssignmentRequest,
    DiagnosticianResponse,
    ExamResponse,
    OverrideAssignmentRequest,
    SetOncallRequest,
    SuggestAssignmentRequest,
    SuggestionResponse,
)
from diagflow.engine.filters import ExamContext
from diagflow.services.assignment import AssignmentService
from diagflow.services.comment_parser import parse_comment
from diagflow.services.diagnostician import DiagnosticianService
from diagflow.services.pamakristos import PamakristosScheduler

router = APIRouter()

# ── In-memory suggestion cache (for confirm/override flow) ──
# In production, this would be stored in the DB or Redis
_suggestion_cache: dict = {}


@router.get("/exams/pending", response_model=list[ExamResponse])
async def get_pending_exams(
    svc: AssignmentService = Depends(get_assignment_service),
):
    """Fetch all pending (unassigned) exams from Slis."""
    exams = await svc.get_pending_exams()
    return [ExamResponse(**exam) for exam in exams]


@router.post("/assignments/suggest", response_model=SuggestionResponse)
async def suggest_assignment(
    request: SuggestAssignmentRequest,
    assign_svc: AssignmentService = Depends(get_assignment_service),
    diag_svc: DiagnosticianService = Depends(get_diagnostician_service),
):
    """
    Generate an assignment suggestion for a specific exam.

    Runs the full rule engine pipeline:
    1. Parse comments (keyword + LLM)
    2. Load candidates
    3. Apply hard filters
    4. Compute weighted scores
    5. Run solver
    6. Return suggestion with full transparency
    """
    # Fetch exam data
    pending = await assign_svc.get_pending_exams()
    exam_data = next((e for e in pending if e["exam_id"] == request.exam_id), None)

    if not exam_data:
        raise HTTPException(status_code=404, detail=f"Exam {request.exam_id} not found")

    exam = ExamContext(
        exam_id=exam_data["exam_id"],
        patient_id=exam_data["patient_id"],
        patient_name=exam_data.get("patient_name", ""),
        modality=exam_data["modality"],
        body_part=exam_data["body_part"],
        lab_id=exam_data["lab_id"],
        lab_name=exam_data["lab_name"],
        issuing_doctor_id=exam_data["issuing_doctor_id"],
        issuing_doctor_name=exam_data["issuing_doctor_name"],
        comments=exam_data.get("comments", ""),
        is_pamakristos="PAM" in exam_data.get("lab_id", "").upper(),
    )

    # Load candidates
    candidates = await diag_svc.get_candidates_for_exam(
        exam_id=exam.exam_id,
        modality=exam.modality,
        body_part=exam.body_part,
        lab_id=exam.lab_id,
        issuing_doctor_id=exam.issuing_doctor_id,
        patient_id=exam.patient_id,
    )

    # Parse comments
    diagnostician_names = [c.name for c in candidates]
    comment_analysis = await parse_comment(exam.comments, diagnostician_names)

    # Run the pipeline
    suggestion = await assign_svc.suggest_assignment(exam, candidates, comment_analysis)

    if not suggestion:
        raise HTTPException(
            status_code=422,
            detail="No eligible diagnosticians found after applying all rules. Manual assignment required.",
        )

    # Cache the suggestion for confirm/override
    _suggestion_cache[exam.exam_id] = suggestion

    return SuggestionResponse(
        exam_id=suggestion.exam_id,
        patient_id=suggestion.patient_id,
        exam_summary=suggestion.exam_summary,
        suggested_diagnostician_id=suggestion.suggested_diagnostician_id,
        suggested_diagnostician_name=suggestion.suggested_diagnostician_name,
        confidence_score=suggestion.confidence_score,
        score_breakdown=suggestion.score_breakdown,
        alternatives=suggestion.alternatives,
        rules_fired=suggestion.rules_fired,
        solver_status=suggestion.solver_status,
        is_direct_assignment=suggestion.is_direct_assignment,
        direct_assignment_reason=suggestion.direct_assignment_reason,
        pipeline_timestamp=suggestion.pipeline_timestamp,
    )


@router.post("/assignments/confirm", response_model=AssignmentConfirmation)
async def confirm_assignment(
    request: ConfirmAssignmentRequest,
    svc: AssignmentService = Depends(get_assignment_service),
):
    """Confirm the suggested assignment (no override)."""
    suggestion = _suggestion_cache.get(request.exam_id)
    if not suggestion:
        raise HTTPException(
            status_code=404,
            detail=f"No pending suggestion for exam {request.exam_id}. Generate a suggestion first.",
        )

    result = await svc.confirm_assignment(
        exam_id=request.exam_id,
        diagnostician_id=request.diagnostician_id,
        suggestion=suggestion,
    )

    # Remove from cache after confirmation
    _suggestion_cache.pop(request.exam_id, None)

    return AssignmentConfirmation(
        exam_id=request.exam_id,
        diagnostician_id=request.diagnostician_id,
        was_overridden=False,
        status="confirmed",
        timestamp=result["decision_timestamp"],
    )


@router.post("/assignments/override", response_model=AssignmentConfirmation)
async def override_assignment(
    request: OverrideAssignmentRequest,
    svc: AssignmentService = Depends(get_assignment_service),
):
    """Override the suggested assignment with a different diagnostician."""
    suggestion = _suggestion_cache.get(request.exam_id)
    if not suggestion:
        raise HTTPException(
            status_code=404,
            detail=f"No pending suggestion for exam {request.exam_id}. Generate a suggestion first.",
        )

    result = await svc.override_assignment(
        exam_id=request.exam_id,
        original_diagnostician_id=request.original_diagnostician_id,
        override_diagnostician_id=request.override_diagnostician_id,
        reason=request.reason,
        suggestion=suggestion,
    )

    # Remove from cache after override
    _suggestion_cache.pop(request.exam_id, None)

    return AssignmentConfirmation(
        exam_id=request.exam_id,
        diagnostician_id=request.override_diagnostician_id,
        was_overridden=True,
        status="overridden",
        timestamp=result["decision_timestamp"],
    )


@router.get("/diagnosticians", response_model=list[DiagnosticianResponse])
async def list_diagnosticians(
    svc: DiagnosticianService = Depends(get_diagnostician_service),
):
    """List all diagnosticians with their current status."""
    return await svc.get_all_diagnosticians()


@router.get("/pamakristos/oncall")
async def get_pamakristos_oncall(
    scheduler: PamakristosScheduler = Depends(get_pamakristos_scheduler),
):
    """Get today's Παμακάριστος on-call diagnostician."""
    return await scheduler.get_oncall_diagnostician()


@router.get("/pamakristos/schedule")
async def get_pamakristos_weekly_schedule(
    scheduler: PamakristosScheduler = Depends(get_pamakristos_scheduler),
):
    """Get the weekly Παμακάριστος on-call schedule."""
    return await scheduler.get_weekly_schedule()


@router.post("/pamakristos/oncall")
async def set_pamakristos_oncall(
    request: SetOncallRequest,
    scheduler: PamakristosScheduler = Depends(get_pamakristos_scheduler),
):
    """Manually set the Παμακάριστος on-call diagnostician for a date."""
    target_date = date.fromisoformat(request.date)
    return await scheduler.set_oncall_diagnostician(target_date, request.diagnostician_id)
