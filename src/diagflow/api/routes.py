"""
DiagFlow — API Route Definitions

REST endpoints for the secretariat review dashboard:
- GET  /api/exams/pending         — List pending exams
- GET  /api/exams/assigned        — List assigned exams (not yet synced to Slis)
- POST /api/assignments/suggest   — Generate assignment suggestion
- POST /api/assignments/confirm   — Confirm a suggestion
- POST /api/assignments/override  — Override a suggestion
- GET  /api/diagnosticians        — List all diagnosticians
- GET  /api/pamakristos/oncall    — Get today's on-call
- POST /api/pamakristos/oncall    — Set on-call manually

Slis Sync endpoints:
- POST /api/slis/pull             — Pull/refresh exam data from Slis (on-demand)
- POST /api/slis/push-all         — Push ALL assigned-not-yet-synced exams to Slis
- POST /api/slis/push-selected    — Push selected exams (by exammoreid list) to Slis

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
    BulkConfirmRequest,
    BulkOverrideRequest,
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
from diagflow.services.diagnostician import DiagnosticianService
from diagflow.services.pamakristos import PamakristosScheduler
import diagflow.db.diagflow_db as cfg_db

router = APIRouter()

# ── In-memory suggestion cache (for confirm/override flow) ──
_suggestion_cache: dict = {}

# ── Session suggestion counter — tracks how many times each diagnostician has been
#    suggested since the last data reset. Used as a virtual workload offset so the
#    load-balancing tie-breaker works across sequential API calls in the same session.
#    Keys: diagnostician_id (int), Values: count (int)
_session_suggestion_counts: dict[int, int] = {}

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
        assigned = assign_svc.get_assigned_exams()
        exam_data = next((e for e in assigned if e["exam_id"] == request.exam_id), None)

    if not exam_data:
        raise HTTPException(status_code=404, detail=f"Exam {request.exam_id} not found")

    exam = ExamContext(
        exam_id=exam_data["exam_id"],
        patient_id=exam_data["patient_id"],
        patient_name=exam_data.get("patient_name", ""),
        modality=exam_data["modality"],
        body_part=exam_data["body_part"],
        exam_code=str(exam_data.get("examnumcode", "")),
        exam_name=exam_data.get("examname", ""),
        lab_id=exam_data["lab_id"],
        lab_name=exam_data["lab_name"],
        issuing_doctor_id=exam_data["issuing_doctor_id"],
        issuing_doctor_name=exam_data["issuing_doctor_name"],
        comments=exam_data.get("comments", ""),
        is_pamakristos="ΠΑΜΜΑΚΑΡΙΣΤΟΣ" in exam_data.get("issuing_doctor_name", "").upper(),
    )

    candidates = await diag_svc.get_candidates_for_exam(
        exam_id=exam.exam_id,
        modality=exam.modality,
        body_part=exam.body_part,
        lab_id=exam.lab_id,
        lab_name=exam.lab_name,
        issuing_doctor_id=exam.issuing_doctor_id,
        patient_id=exam.patient_id,
        exam_code=exam.exam_code,
    )

    # Apply session-level virtual workload so back-to-back suggestions spread across
    # near-tied candidates instead of always picking the same person.
    for c in candidates:
        c.current_day_count += _session_suggestion_counts.get(c.id, 0)

    suggestion = await assign_svc.suggest_assignment(exam, candidates)

    if not suggestion:
        raise HTTPException(
            status_code=422,
            detail="No eligible diagnosticians found after applying all rules. Manual assignment required.",
        )

    # Increment the session counter for the suggested diagnostician
    if suggestion.suggested_diagnostician_id:
        diag_id = suggestion.suggested_diagnostician_id
        _session_suggestion_counts[diag_id] = _session_suggestion_counts.get(diag_id, 0) + 1

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


@router.post("/assignments/bulk-confirm", response_model=list[AssignmentConfirmation])
async def bulk_confirm_assignments(
    request: BulkConfirmRequest,
    svc: AssignmentService = Depends(get_assignment_service),
):
    """Confirm suggested assignments for multiple exams."""
    results = []
    for exam_id in request.exam_ids:
        suggestion = _suggestion_cache.get(exam_id)
        if not suggestion:
            continue
            
        result = await svc.confirm_assignment(
            exam_id=exam_id,
            diagnostician_id=suggestion.suggested_diagnostician_id,
            suggestion=suggestion,
        )
        _suggestion_cache.pop(exam_id, None)
        
        results.append(
            AssignmentConfirmation(
                exam_id=exam_id,
                diagnostician_id=suggestion.suggested_diagnostician_id,
                was_overridden=False,
                status="confirmed",
                timestamp=result["decision_timestamp"],
            )
        )
    return results


@router.post("/assignments/bulk-override", response_model=list[AssignmentConfirmation])
async def bulk_override_assignments(
    request: BulkOverrideRequest,
    svc: AssignmentService = Depends(get_assignment_service),
):
    """Override suggested assignments for multiple exams."""
    results = []
    for exam_id in request.exam_ids:
        suggestion = _suggestion_cache.get(exam_id)
        original_diagnostician_id = suggestion.suggested_diagnostician_id if suggestion else 0

        result = await svc.override_assignment(
            exam_id=exam_id,
            original_diagnostician_id=original_diagnostician_id,
            override_diagnostician_id=request.override_diagnostician_id,
            reason=request.reason,
            suggestion=suggestion,
        )
        _suggestion_cache.pop(exam_id, None)

        results.append(
            AssignmentConfirmation(
                exam_id=exam_id,
                diagnostician_id=request.override_diagnostician_id,
                was_overridden=True,
                status="overridden",
                timestamp=result["decision_timestamp"],
            )
        )
    return results


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
async def get_pamakristos_weekly_schedule():
    weekly = cfg_db.get_pamakristos_weekly_schedule_db()
    day_names = {0: "Δευτέρα", 1: "Τρίτη", 2: "Τετάρτη", 3: "Πέμπτη", 4: "Παρασκευή", 5: "Σάββατο", 6: "Κυριακή"}
    return [
        {
            "weekday": item["weekday"],
            "day_name": day_names.get(item["weekday"], ""),
            "diagnostician_id": item["diagnostician_id"],
            "diagnostician_name": item["diagnostician_name"],
        }
        for item in weekly
    ]


@router.post("/pamakristos/oncall")
async def set_pamakristos_oncall(
    request: SetOncallRequest,
    scheduler: PamakristosScheduler = Depends(get_pamakristos_scheduler),
):
    target_date = date.fromisoformat(request.date)
    return await scheduler.set_oncall_diagnostician(target_date, request.diagnostician_id)


class WeeklyScheduleItem(BaseModel):
    weekday: int
    diagnostician_id: int


@router.get("/admin/pamakristos/weekly-schedule")
async def admin_get_weekly_schedule(_: str = Depends(_require_admin)):
    weekly = cfg_db.get_pamakristos_weekly_schedule_db()
    day_names = {0: "Δευτέρα", 1: "Τρίτη", 2: "Τετάρτη", 3: "Πέμπτη", 4: "Παρασκευή", 5: "Σάββατο", 6: "Κυριακή"}
    return [
        {
            "weekday": item["weekday"],
            "day_name": day_names.get(item["weekday"], ""),
            "diagnostician_id": item["diagnostician_id"],
            "diagnostician_name": item["diagnostician_name"],
        }
        for item in weekly
    ]


@router.post("/admin/pamakristos/weekly-schedule")
async def admin_update_weekly_schedule(
    items: list[WeeklyScheduleItem],
    _: str = Depends(_require_admin),
):
    cfg_db.update_pamakristos_weekly_schedule_db([item.model_dump() for item in items])
    return {"status": "ok", "updated": len(items)}


# ─────────────────────────────────────────────────────
#  Admin — Diagnosticians  (diagflow.db — persistent)
# ─────────────────────────────────────────────────────

@router.get("/admin/exam-categories")
async def admin_get_exam_categories(
    svc: AssignmentService = Depends(get_assignment_service),
    _: str = Depends(_require_admin)
):
    return svc.get_exam_categories()

class DiagnosticianCreateRequest(BaseModel):
    name: str
    active: bool = True
    can_ct: bool = True
    can_mri: bool = True
    quota_monday: int = 15
    quota_tuesday: int = 15
    quota_wednesday: int = 15
    quota_thursday: int = 15
    quota_friday: int = 15
    quota_saturday: int = 0
    quota_sunday: int = 0
    preferred_lab_id: int | None = None


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
        quota_monday=req.quota_monday,
        quota_tuesday=req.quota_tuesday,
        quota_wednesday=req.quota_wednesday,
        quota_thursday=req.quota_thursday,
        quota_friday=req.quota_friday,
        quota_saturday=req.quota_saturday,
        quota_sunday=req.quota_sunday,
        preferred_lab_id=req.preferred_lab_id,
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
        quota_monday=req.quota_monday,
        quota_tuesday=req.quota_tuesday,
        quota_wednesday=req.quota_wednesday,
        quota_thursday=req.quota_thursday,
        quota_friday=req.quota_friday,
        quota_saturday=req.quota_saturday,
        quota_sunday=req.quota_sunday,
        preferred_lab_id=req.preferred_lab_id,
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
    is_active: bool = True

class PartnershipUpdateRequest(BaseModel):
    exclusive: bool | None = None
    is_active: bool | None = None


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
        is_active=req.is_active,
    )


@router.patch("/admin/partnerships/{part_id}")
async def admin_update_partnership(
    part_id: int,
    req: PartnershipUpdateRequest,
    _: str = Depends(_require_admin),
):
    record = cfg_db.update_partnership(
        part_id=part_id,
        exclusive=req.exclusive,
        is_active=req.is_active,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Η σύμπραξη δεν βρέθηκε")
    return record


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
def admin_list_doctors(
    q: str = "",
    skip: int = 0,
    limit: int = 50,
    _: str = Depends(_require_admin)
):
    return cfg_db.get_all_doctors(q=q, skip=skip, limit=limit)


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


# ─────────────────────────────────────────────────────
#  Slis Sync Endpoints
# ─────────────────────────────────────────────────────

class PushSelectedRequest(BaseModel):
    exammoreid_list: list[int]


@router.post("/slis/pull")
async def slis_pull():
    """
    Pull fresh exam data from Slis (or refresh the mock DB).
    Runs automatically on startup; can also be triggered via the
    'Ανανέωση' button on the frontend.
    """
    from diagflow.services.slis_sync import pull_from_slis
    # Reset the session suggestion counter so load-balancing starts fresh
    # with the new batch of exams.
    _session_suggestion_counts.clear()
    result = pull_from_slis()
    return {
        "status": "ok",
        "pulled": result.get("pulled", 0),
        "expired": result.get("expired", 0),
        "total_pending": result.get("total_pending", 0),
    }


@router.post("/slis/push-all")
async def slis_push_all():
    """
    Push ALL assigned-but-not-yet-synced exams to Slis in one operation.
    After a successful push the exam's slis_synced_at is set and it will
    be removed from the Assigned tab.
    """
    from diagflow.services.slis_sync import push_all_to_slis
    result = push_all_to_slis()
    return result


@router.post("/slis/push-selected")
async def slis_push_selected(req: PushSelectedRequest):
    """
    Push a specific list of exams (by exammoreid) to Slis.
    Used when the user selects individual rows in the Assigned tab.
    """
    from diagflow.services.slis_sync import push_selected_to_slis
    result = push_selected_to_slis(req.exammoreid_list)
    return result


@router.post("/admin/sync-diagnosticians")
async def admin_sync_diagnosticians(_: str = Depends(_require_admin)):
    """Manual trigger to pull diagnosticians from Slis DB into diagflow.db."""
    from diagflow.services.slis_sync import sync_diagnosticians
    result = sync_diagnosticians()
    return result


@router.post("/admin/sync-doctors")
async def admin_sync_doctors(_: str = Depends(_require_admin)):
    """Manual trigger to pull doctors from Slis DB into diagflow.db."""
    from diagflow.services.slis_sync import sync_doctors
    result = sync_doctors()
    return result
