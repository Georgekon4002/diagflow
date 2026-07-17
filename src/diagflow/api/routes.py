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

Admin endpoints (all with mock data until DB is ready):
- POST /api/admin/auth/login
- GET/POST /api/admin/diagnosticians
- PUT  /api/admin/diagnosticians/{id}
- GET/POST /api/admin/partnerships
- GET/POST /api/admin/doctors
- GET/POST /api/admin/availability
- GET/POST /api/admin/skills
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

router = APIRouter()

# ── In-memory suggestion cache (for confirm/override flow) ──
# In production, this would be stored in the DB or Redis
_suggestion_cache: dict = {}

# ── Admin session store (simple token-based, mock) ──
# In production, use JWT or a real session mechanism
_admin_sessions: set[str] = set()

# ── Mock admin state (persisted in memory during server lifetime) ──
_mock_diagnosticians: list[dict] = [
    {"id": 1, "name": "Νάτσικα Α.", "active": True, "can_ct": True, "can_mri": True, "daily_quota": 15},
    {"id": 2, "name": "Κωνσταντίνου Β.", "active": True, "can_ct": True, "can_mri": True, "daily_quota": 12},
    {"id": 3, "name": "Παπαδόπουλος Γ.", "active": True, "can_ct": True, "can_mri": True, "daily_quota": 18},
    {"id": 4, "name": "Λιάκος Δ.", "active": True, "can_ct": True, "can_mri": False, "daily_quota": 10},
    {"id": 5, "name": "Δημητρίου Ε.", "active": True, "can_ct": True, "can_mri": True, "daily_quota": 14},
    {"id": 6, "name": "Αντωνίου Ζ.", "active": False, "can_ct": True, "can_mri": True, "daily_quota": 16},
]

_mock_partnerships: list[dict] = [
    {"id": 1, "issuing_doctor_id": "DR-101", "issuing_doctor_name": "Παπαδόπουλος Ν.", "preferred_diagnostician_id": 3, "preferred_diagnostician_name": "Παπαδόπουλος Γ.", "priority": 5, "exclusive": True},
    {"id": 2, "issuing_doctor_id": "DR-205", "issuing_doctor_name": "Ιωάννου Ε.", "preferred_diagnostician_id": 2, "preferred_diagnostician_name": "Κωνσταντίνου Β.", "priority": 4, "exclusive": False},
]

_mock_doctors: list[dict] = [
    {"id": "DR-101", "name": "Παπαδόπουλος Ν.", "specialty": "Ορθοπεδική"},
    {"id": "DR-205", "name": "Ιωάννου Ε.", "specialty": "Καρδιολογία"},
    {"id": "DR-310", "name": "Βασιλείου Κ.", "specialty": "Νευρολογία"},
    {"id": "DR-PAM-01", "name": "Εφημερία Παμμακάριστου", "specialty": "Εφημερία"},
]

_mock_availability: list[dict] = [
    {"id": 1, "diagnostician_id": 6, "diagnostician_name": "Αντωνίου Ζ.", "date": str(date.today()), "status": "on_leave", "is_pamakristos_oncall": False, "notes": "Άδεια"},
]

_mock_skills: list[dict] = [
    {"id": 1, "diagnostician_id": 1, "diagnostician_name": "Νάτσικα Α.", "exam_code": "21100", "exam_title": "MRI Κοιλίας", "modality": "MRI", "is_preferred": True},
    {"id": 2, "diagnostician_id": 1, "diagnostician_name": "Νάτσικα Α.", "exam_code": "22140", "exam_title": "CT Θώρακα", "modality": "CT", "is_preferred": False},
    {"id": 3, "diagnostician_id": 2, "diagnostician_name": "Κωνσταντίνου Β.", "exam_code": "22140", "exam_title": "CT Θώρακα", "modality": "CT", "is_preferred": True},
    {"id": 4, "diagnostician_id": 3, "diagnostician_name": "Παπαδόπουλος Γ.", "exam_code": "21063", "exam_title": "MRI Εγκεφάλου", "modality": "MRI", "is_preferred": True},
]

_mock_oncall: dict = {"diagnostician_id": 3, "diagnostician_name": "Παπαδόπουλος Γ.", "date": str(date.today())}

_mock_assigned_exams: list[dict] = [
    {
        "exam_id": "EX-2026-A01", "patient_id": "PT-1001", "patient_name": "Σοφία Μ.",
        "modality": "CT", "body_part": "chest", "lab_id": "LAB-KIF", "lab_name": "Κηφισιά",
        "issuing_doctor_id": "DR-101", "issuing_doctor_name": "Παπαδόπουλος Ν.",
        "request_date": "2026-07-14", "status": "assigned",
        "assigned_diagnostician_id": 1, "assigned_diagnostician_name": "Νάτσικα Α.",
        "assigned_at": "2026-07-14T09:15:00",
    },
    {
        "exam_id": "EX-2026-A02", "patient_id": "PT-2002", "patient_name": "Νίκος Α.",
        "modality": "MRI", "body_part": "neuro", "lab_id": "LAB-MAR", "lab_name": "Μαρούσι",
        "issuing_doctor_id": "DR-310", "issuing_doctor_name": "Βασιλείου Κ.",
        "request_date": "2026-07-14", "status": "assigned",
        "assigned_diagnostician_id": 3, "assigned_diagnostician_name": "Παπαδόπουλος Γ.",
        "assigned_at": "2026-07-14T10:30:00",
    },
    {
        "exam_id": "EX-2026-A03", "patient_id": "PT-3003", "patient_name": "Ελένη Τ.",
        "modality": "CT", "body_part": "abdomen", "lab_id": "LAB-GLY", "lab_name": "Γλυφάδα",
        "issuing_doctor_id": "DR-205", "issuing_doctor_name": "Ιωάννου Ε.",
        "request_date": "2026-07-13", "status": "assigned",
        "assigned_diagnostician_id": 2, "assigned_diagnostician_name": "Κωνσταντίνου Β.",
        "assigned_at": "2026-07-13T14:45:00",
    },
]


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
    # Simple hardcoded credentials for demo
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
    """
    Generate an assignment suggestion for a specific exam.

    Runs the full rule engine pipeline:
    1. Load candidates
    2. Apply hard filters (availability, skills)
    3. Compute weighted scores (capacity, partnership, lab, history)
    4. Run solver
    5. Return suggestion with full transparency (including eliminated candidates)
    """
    # Fetch exam data
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

    # Load candidates
    candidates = await diag_svc.get_candidates_for_exam(
        exam_id=exam.exam_id,
        modality=exam.modality,
        body_part=exam.body_part,
        lab_id=exam.lab_id,
        issuing_doctor_id=exam.issuing_doctor_id,
        patient_id=exam.patient_id,
        exam_code=exam.exam_code,
    )

    # Parse comments [DISABLED — passing None]
    comment_analysis = None
    # Uncomment when re-enabling comment parsing:
    # diagnostician_names = [c.name for c in candidates]
    # comment_analysis = await parse_comment(exam.comments, diagnostician_names)

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


# ─────────────────────────────────────────────────────
#  Diagnosticians (public read, admin write)
# ─────────────────────────────────────────────────────

@router.get("/diagnosticians", response_model=list[DiagnosticianResponse])
async def list_diagnosticians(
    svc: DiagnosticianService = Depends(get_diagnostician_service),
):
    """List all diagnosticians with their current status."""
    return await svc.get_all_diagnosticians()


# ─────────────────────────────────────────────────────
#  Παμμακάριστος
# ─────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────
#  Admin — Diagnosticians
# ─────────────────────────────────────────────────────

class DiagnosticianCreateRequest(BaseModel):
    name: str
    active: bool = True
    can_ct: bool = True
    can_mri: bool = True
    daily_quota: int = 15


@router.get("/admin/diagnosticians")
async def admin_list_diagnosticians(_: str = Depends(_require_admin)):
    return _mock_diagnosticians


@router.post("/admin/diagnosticians")
async def admin_create_diagnostician(
    req: DiagnosticianCreateRequest,
    _: str = Depends(_require_admin),
):
    new_id = max((d["id"] for d in _mock_diagnosticians), default=0) + 1
    record = {"id": new_id, **req.model_dump()}
    _mock_diagnosticians.append(record)
    return record


@router.put("/admin/diagnosticians/{diag_id}")
async def admin_update_diagnostician(
    diag_id: int,
    req: DiagnosticianCreateRequest,
    _: str = Depends(_require_admin),
):
    for i, d in enumerate(_mock_diagnosticians):
        if d["id"] == diag_id:
            _mock_diagnosticians[i] = {"id": diag_id, **req.model_dump()}
            return _mock_diagnosticians[i]
    raise HTTPException(status_code=404, detail="Ο ακτινοδιαγνώστης δεν βρέθηκε")


# ─────────────────────────────────────────────────────
#  Admin — Partnerships
# ─────────────────────────────────────────────────────

class PartnershipCreateRequest(BaseModel):
    issuing_doctor_id: str
    issuing_doctor_name: str
    preferred_diagnostician_id: int
    preferred_diagnostician_name: str
    priority: int = 1
    exclusive: bool = False


@router.get("/admin/partnerships")
async def admin_list_partnerships(_: str = Depends(_require_admin)):
    return _mock_partnerships


@router.post("/admin/partnerships")
async def admin_create_partnership(
    req: PartnershipCreateRequest,
    _: str = Depends(_require_admin),
):
    new_id = max((p["id"] for p in _mock_partnerships), default=0) + 1
    record = {"id": new_id, **req.model_dump()}
    _mock_partnerships.append(record)
    return record


@router.delete("/admin/partnerships/{part_id}")
async def admin_delete_partnership(part_id: int, _: str = Depends(_require_admin)):
    global _mock_partnerships
    _mock_partnerships = [p for p in _mock_partnerships if p["id"] != part_id]
    return {"deleted": part_id}


# ─────────────────────────────────────────────────────
#  Admin — Doctors
# ─────────────────────────────────────────────────────

class DoctorCreateRequest(BaseModel):
    name: str
    specialty: str = ""


@router.get("/admin/doctors")
async def admin_list_doctors(_: str = Depends(_require_admin)):
    return _mock_doctors


@router.post("/admin/doctors")
async def admin_create_doctor(req: DoctorCreateRequest, _: str = Depends(_require_admin)):
    new_id = f"DR-{len(_mock_doctors) + 1:03d}"
    record = {"id": new_id, **req.model_dump()}
    _mock_doctors.append(record)
    return record


# ─────────────────────────────────────────────────────
#  Admin — Availability
# ─────────────────────────────────────────────────────

class AvailabilitySetRequest(BaseModel):
    diagnostician_id: int
    diagnostician_name: str
    date: str  # ISO date string
    status: str = "available"  # available, on_leave, half_day
    is_pamakristos_oncall: bool = False
    notes: str = ""


@router.get("/admin/availability")
async def admin_list_availability(_: str = Depends(_require_admin)):
    return _mock_availability


@router.post("/admin/availability")
async def admin_set_availability(
    req: AvailabilitySetRequest,
    _: str = Depends(_require_admin),
):
    # Remove existing record for same diagnostician+date
    global _mock_availability
    _mock_availability = [
        a for a in _mock_availability
        if not (a["diagnostician_id"] == req.diagnostician_id and a["date"] == req.date)
    ]
    new_id = max((a["id"] for a in _mock_availability), default=0) + 1
    record = {"id": new_id, **req.model_dump()}
    _mock_availability.append(record)
    return record


# ─────────────────────────────────────────────────────
#  Admin — Skills
# ─────────────────────────────────────────────────────

class SkillSetRequest(BaseModel):
    diagnostician_id: int
    diagnostician_name: str
    exam_code: str
    exam_title: str
    modality: str
    is_preferred: bool


@router.get("/admin/skills")
async def admin_list_skills(_: str = Depends(_require_admin)):
    return _mock_skills


@router.post("/admin/skills")
async def admin_set_skill(req: SkillSetRequest, _: str = Depends(_require_admin)):
    global _mock_skills
    # Replace existing
    _mock_skills = [
        s for s in _mock_skills
        if not (s["diagnostician_id"] == req.diagnostician_id
                and s["exam_code"] == req.exam_code
                and s["modality"] == req.modality)
    ]
    new_id = max((s["id"] for s in _mock_skills), default=0) + 1
    record = {"id": new_id, **req.model_dump()}
    _mock_skills.append(record)
    return record


# ─────────────────────────────────────────────────────
#  Admin — Παμμακάριστος on-call override
# ─────────────────────────────────────────────────────

class OncallSetRequest(BaseModel):
    diagnostician_id: int
    diagnostician_name: str
    date: str


@router.get("/admin/oncall")
async def admin_get_oncall(_: str = Depends(_require_admin)):
    return _mock_oncall


@router.post("/admin/oncall")
async def admin_set_oncall(
    req: OncallSetRequest,
    _: str = Depends(_require_admin),
    scheduler: PamakristosScheduler = Depends(get_pamakristos_scheduler),
):
    global _mock_oncall
    _mock_oncall = req.model_dump()
    scheduler.set_manual_override_from_admin(_mock_oncall)
    return _mock_oncall
