"""
DiagFlow — API Route Definitions

REST endpoints for the secretariat review dashboard:
- GET  /api/exams/pending         — List pending exams
- GET  /api/exams/assigned        — List assigned exams (today)
- POST /api/assignments/suggest   — Generate assignment suggestion
- POST /api/assignments/confirm   — Confirm a suggestion
- POST /api/assignments/override  — Override a suggestion
- GET  /api/diagnosticians        — List all diagnosticians
- GET  /api/pamakristos/oncall    — Get today's on-call
- POST /api/pamakristos/oncall    — Set on-call manually

Admin endpoints (backed by diagflow.db — persistent):
- POST /api/admin/auth/login
- GET/POST        /api/admin/diagnosticians
- PUT/DELETE      /api/admin/diagnosticians/{id}
- GET/POST/DELETE /api/admin/partnerships
- GET/POST/DELETE /api/admin/doctors
- GET/POST        /api/admin/availability
- GET/POST/DELETE /api/admin/skills
"""

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel

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
import diagflow.db.diagflow_db as cfg_db

router = APIRouter()

# ── In-memory suggestion cache (for confirm/override flow) ──
_suggestion_cache: dict = {}

# ── Admin session store ──
_admin_sessions: set[str] = set()


# ─────────────────────────────────────────────────────
#  Admin Auth
# ─────────────────────────────────────────────────────

class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    token: str
    username: str


@router.post("/admin/auth/login", response_model=AdminLoginResponse)
async def admin_login(request: AdminLoginRequest):
    """Authenticate admin user. Returns a session token."""
    if request.username == "admin" and request.password == "admin1234":
        import secrets
        token = secrets.token_hex(16)
        _admin_sessions.add(token)
        return AdminLoginResponse(token=token, username=request.username)
    raise HTTPException(status_code=401, detail="Λάθος στοιχεία σύνδεσης")


def _require_admin(x_admin_token: str = Header(default="")):
    """Dependency: require a valid admin token."""
    if not x_admin_token or x_admin_token not in _admin_sessions:
        raise HTTPException(status_code=403, detail="Απαιτείται σύνδεση διαχειριστή")
    return x_admin_token


# ─────────────────────────────────────────────────────
#  Exams
# ─────────────────────────────────────────────────────

@router.get("/exams/pending")
async def get_pending_exams(
    svc: AssignmentService = Depends(get_assignment_service),
):
    """Fetch all pending (unassigned) exams from Slis / mock DB."""
    return svc.get_pending_exams()


@router.get("/exams/assigned")
async def get_assigned_exams(
    svc: AssignmentService = Depends(get_assignment_service),
):
    """Fetch assigned exams from Slis / mock DB."""
    return svc.get_assigned_exams()


# ─────────────────────────────────────────────────────
#  Assignment Engine
# ─────────────────────────────────────────────────────

@router.post("/assignments/suggest", response_model=SuggestionResponse)
async def suggest_assignment(
    request: SuggestAssignmentRequest,
    assign_svc: AssignmentService = Depends(get_assignment_service),
    diag_svc: DiagnosticianService = Depends(get_diagnostician_service),
):
    """Generate an assignment suggestion for a specific exam."""
    pending = assign_svc.get_pending_exams()
    exam_data = next((e for e in pending if e["exam_id"] == request.exam_id), None)

    if not exam_data:
        raise HTTPException(status_code=404, detail=f"Exam {request.exam_id} not found")

    exam = ExamContext(
        exam_id=exam_data["exam_id"],
        patient_id=exam_data["patient_id"],
        patient_name=exam_data.get("patient_name", ""),
        modality=exam_data["modality"],
        body_part=exam_data["body_part"],
        exam_code=str(exam_data.get("examnumcode", "")),
        lab_id=exam_data["lab_id"],
        lab_name=exam_data["lab_name"],
        issuing_doctor_id=exam_data["issuing_doctor_id"],
        issuing_doctor_name=exam_data["issuing_doctor_name"],
        comments=exam_data.get("comments", ""),
        is_pamakristos="PAM" in exam_data.get("lab_id", "").upper(),
    )

    candidates = await diag_svc.get_candidates_for_exam(
        exam_id=exam.exam_id,
        modality=exam.modality,
        body_part=exam.body_part,
        lab_id=exam.lab_id,
        issuing_doctor_id=exam.issuing_doctor_id,
        patient_id=exam.patient_id,
        exam_code=exam.exam_code,
    )

    comment_analysis = None
    suggestion = await assign_svc.suggest_assignment(exam, candidates, comment_analysis)

    if not suggestion:
        raise HTTPException(
            status_code=422,
            detail="No eligible diagnosticians found after applying all rules. Manual assignment required.",
        )

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
    _suggestion_cache.pop(request.exam_id, None)

    return AssignmentConfirmation(
        exam_id=request.exam_id,
        diagnostician_id=request.override_diagnostician_id,
        was_overridden=True,
        status="overridden",
        timestamp=result["decision_timestamp"],
    )


# ─────────────────────────────────────────────────────
#  Diagnosticians (public read)
# ─────────────────────────────────────────────────────

@router.get("/diagnosticians", response_model=list[DiagnosticianResponse])
async def list_diagnosticians(
    svc: DiagnosticianService = Depends(get_diagnostician_service),
):
    """List all active diagnosticians."""
    return await svc.get_all_diagnosticians()


# ─────────────────────────────────────────────────────
#  Παμμακάριστος
# ─────────────────────────────────────────────────────

@router.get("/pamakristos/oncall")
async def get_pamakristos_oncall(
    scheduler: PamakristosScheduler = Depends(get_pamakristos_scheduler),
):
    return await scheduler.get_oncall_diagnostician()


@router.get("/pamakristos/schedule")
async def get_pamakristos_weekly_schedule(
    scheduler: PamakristosScheduler = Depends(get_pamakristos_scheduler),
):
    return await scheduler.get_weekly_schedule()


@router.post("/pamakristos/oncall")
async def set_pamakristos_oncall(
    request: SetOncallRequest,
    scheduler: PamakristosScheduler = Depends(get_pamakristos_scheduler),
):
    target_date = date.fromisoformat(request.date)
    return await scheduler.set_oncall_diagnostician(target_date, request.diagnostician_id)


# ─────────────────────────────────────────────────────
#  Admin — Diagnosticians  (diagflow.db — persistent)
# ─────────────────────────────────────────────────────

class DiagnosticianCreateRequest(BaseModel):
    name: str
    active: bool = True
    can_ct: bool = True
    can_mri: bool = True
    daily_quota: int = 15


@router.get("/admin/diagnosticians")
async def admin_list_diagnosticians(_: str = Depends(_require_admin)):
    return cfg_db.get_all_diagnosticians()


@router.post("/admin/diagnosticians")
async def admin_create_diagnostician(
    req: DiagnosticianCreateRequest,
    _: str = Depends(_require_admin),
):
    return cfg_db.create_diagnostician(
        name=req.name,
        active=req.active,
        can_ct=req.can_ct,
        can_mri=req.can_mri,
        daily_quota=req.daily_quota,
    )


@router.put("/admin/diagnosticians/{diag_id}")
async def admin_update_diagnostician(
    diag_id: int,
    req: DiagnosticianCreateRequest,
    _: str = Depends(_require_admin),
):
    record = cfg_db.update_diagnostician(
        diag_id=diag_id,
        name=req.name,
        active=req.active,
        can_ct=req.can_ct,
        can_mri=req.can_mri,
        daily_quota=req.daily_quota,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Ο ακτινοδιαγνώστης δεν βρέθηκε")
    return record


@router.delete("/admin/diagnosticians/{diag_id}")
async def admin_delete_diagnostician(diag_id: int, _: str = Depends(_require_admin)):
    if not cfg_db.delete_diagnostician(diag_id):
        raise HTTPException(status_code=404, detail="Ο ακτινοδιαγνώστης δεν βρέθηκε")
    return {"deleted": diag_id}


# ─────────────────────────────────────────────────────
#  Admin — Partnerships  (diagflow.db — persistent)
# ─────────────────────────────────────────────────────

class PartnershipCreateRequest(BaseModel):
    issuing_doctor_id: str
    issuing_doctor_name: str
    preferred_diagnostician_id: int
    priority: int = 1
    exclusive: bool = False


@router.get("/admin/partnerships")
async def admin_list_partnerships(_: str = Depends(_require_admin)):
    return cfg_db.get_all_partnerships()


@router.post("/admin/partnerships")
async def admin_create_partnership(
    req: PartnershipCreateRequest,
    _: str = Depends(_require_admin),
):
    return cfg_db.create_partnership(
        issuing_doctor_id=req.issuing_doctor_id,
        issuing_doctor_name=req.issuing_doctor_name,
        preferred_diagnostician_id=req.preferred_diagnostician_id,
        priority=req.priority,
        exclusive=req.exclusive,
    )


@router.delete("/admin/partnerships/{part_id}")
async def admin_delete_partnership(part_id: int, _: str = Depends(_require_admin)):
    if not cfg_db.delete_partnership(part_id):
        raise HTTPException(status_code=404, detail="Η σύμπραξη δεν βρέθηκε")
    return {"deleted": part_id}


# ─────────────────────────────────────────────────────
#  Admin — Doctors  (diagflow.db — persistent)
# ─────────────────────────────────────────────────────

class DoctorCreateRequest(BaseModel):
    id: str = ""
    name: str
    specialty: str = ""


@router.get("/admin/doctors")
async def admin_list_doctors(_: str = Depends(_require_admin)):
    return cfg_db.get_all_doctors()


@router.post("/admin/doctors")
async def admin_create_doctor(req: DoctorCreateRequest, _: str = Depends(_require_admin)):
    import secrets
    doc_id = req.id if req.id else f"DR-{secrets.token_hex(4).upper()}"
    return cfg_db.upsert_doctor(doctor_id=doc_id, name=req.name, specialty=req.specialty)


@router.delete("/admin/doctors/{doctor_id}")
async def admin_delete_doctor(doctor_id: str, _: str = Depends(_require_admin)):
    if not cfg_db.delete_doctor(doctor_id):
        raise HTTPException(status_code=404, detail="Ο γιατρός δεν βρέθηκε")
    return {"deleted": doctor_id}


# ─────────────────────────────────────────────────────
#  Admin — Availability  (diagflow.db — persistent)
# ─────────────────────────────────────────────────────

class AvailabilitySetRequest(BaseModel):
    diagnostician_id: int
    date: str
    status: str = "available"
    is_pamakristos_oncall: bool = False
    notes: str = ""


@router.get("/admin/availability")
async def admin_list_availability(_: str = Depends(_require_admin)):
    return cfg_db.get_all_availability()


@router.post("/admin/availability")
async def admin_set_availability(
    req: AvailabilitySetRequest,
    _: str = Depends(_require_admin),
):
    return cfg_db.upsert_availability(
        diagnostician_id=req.diagnostician_id,
        date=req.date,
        status=req.status,
        is_pamakristos_oncall=req.is_pamakristos_oncall,
        notes=req.notes,
    )


# ─────────────────────────────────────────────────────
#  Admin — Skills  (diagflow.db — persistent)
# ─────────────────────────────────────────────────────

class SkillSetRequest(BaseModel):
    diagnostician_id: int
    exam_code: str
    is_preferred: bool = False


class SkillDeleteRequest(BaseModel):
    skill_id: int


@router.get("/admin/skills")
async def admin_list_skills(
    diagnostician_id: int | None = None,
    _: str = Depends(_require_admin),
):
    return cfg_db.get_skills(diagnostician_id)


@router.post("/admin/skills")
async def admin_set_skill(req: SkillSetRequest, _: str = Depends(_require_admin)):
    return cfg_db.upsert_skill(
        diagnostician_id=req.diagnostician_id,
        exam_code=req.exam_code,
        is_preferred=req.is_preferred,
    )


@router.delete("/admin/skills/{skill_id}")
async def admin_delete_skill(skill_id: int, _: str = Depends(_require_admin)):
    if not cfg_db.delete_skill(skill_id):
        raise HTTPException(status_code=404, detail="Η δεξιότητα δεν βρέθηκε")
    return {"deleted": skill_id}


# ─────────────────────────────────────────────────────
#  Admin — Παμμακάριστος on-call override
# ─────────────────────────────────────────────────────

class OncallSetRequest(BaseModel):
    diagnostician_id: int
    date: str


@router.get("/admin/oncall")
async def admin_get_oncall(_: str = Depends(_require_admin)):
    today = str(date.today())
    record = cfg_db.get_oncall_diagnostician(today)
    if record:
        return record
    # Fallback: check scheduler
    return {"diagnostician_id": None, "diagnostician_name": None, "date": today}


@router.post("/admin/oncall")
async def admin_set_oncall(
    req: OncallSetRequest,
    _: str = Depends(_require_admin),
    scheduler: PamakristosScheduler = Depends(get_pamakristos_scheduler),
):
    # Clear any existing on-call for the date first
    existing = cfg_db.get_all_availability()
    for a in existing:
        if a["date"] == req.date and a["is_pamakristos_oncall"]:
            cfg_db.upsert_availability(
                diagnostician_id=a["diagnostician_id"],
                date=req.date,
                status=a["status"],
                is_pamakristos_oncall=False,
                notes=a["notes"] or "",
            )

    record = cfg_db.upsert_availability(
        diagnostician_id=req.diagnostician_id,
        date=req.date,
        status="available",
        is_pamakristos_oncall=True,
    )
    scheduler.set_manual_override_from_admin(record)
    return record
