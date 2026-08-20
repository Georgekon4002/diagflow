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
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel

from diagflow.config import settings
from diagflow.api.dependencies import (
    get_assignment_service,
    get_diagnostician_service,
    get_pamakristos_scheduler,
)
from diagflow.api.schemas import (
    AdminChangeCredentialsRequest,
    AdminChangeCredentialsResponse,
    AssignmentConfirmation,
    BulkConfirmRequest,
    BulkEligibleRequest,
    BulkEligibleResponse,
    BulkEligibleResponseItem,
    BulkOverrideRequest,
    ConfirmAssignmentRequest,
    DiagnosticianResponse,
    ExamResponse,
    OverrideAssignmentRequest,
    SetOncallRequest,
    SlisReassignRequest,
    SlisSearchRequest,
    SuggestAssignmentRequest,
    SuggestionResponse,
)
from diagflow.engine.filters import ExamContext
from diagflow.engine.pipeline import AssignmentSuggestion
from diagflow.services.assignment import AssignmentService
from diagflow.services.diagnostician import DiagnosticianService
from diagflow.services.pamakristos import PamakristosScheduler
import diagflow.db.diagflow_db as cfg_db
from fastapi import APIRouter, Depends, HTTPException, Header, Request

import asyncio
import hashlib
import hmac
import time
import bcrypt

router = APIRouter()

# ── In-memory suggestion cache (for confirm/override flow) ──
_suggestion_cache: dict = {}

# ── Session suggestion counter — tracks how many times each diagnostician has been
#    suggested since the last data reset. Used as a virtual workload offset so the
#    load-balancing tie-breaker works across sequential API calls in the same session.
#    Keys: diagnostician_id (int), Values: count (int)
_session_suggestion_counts: dict[int, int] = {}

# ── Admin session & rate limit stores ──
_admin_sessions: dict[str, dict] = {}
_failed_login_attempts: dict[str, list[float]] = {}


# ─────────────────────────────────────────────────────
#  Admin Auth
# ─────────────────────────────────────────────────────

class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    token: str
    username: str
    role: str = "admin"


def _require_admin(x_admin_token: str = Header(default="")):
    """Dependency: require a valid admin token."""
    if not x_admin_token or x_admin_token not in _admin_sessions:
        raise HTTPException(status_code=401, detail="Απαιτείται σύνδεση διαχειριστή")
    return _admin_sessions[x_admin_token]

def _require_it_support(session: dict = Depends(_require_admin)):
    """Dependency: require it_support role."""
    if session.get("role") != "it_support":
        raise HTTPException(status_code=403, detail="Απαιτούνται δικαιώματα IT support")
    return session

@router.post("/admin/auth/login", response_model=AdminLoginResponse)
async def admin_login(request: AdminLoginRequest, raw_request: Request):
    """Authenticate admin user with rate limiting and bcrypt password verification.
    
    Includes a transparent SHA-256 → bcrypt migration path: if the stored hash
    is a legacy SHA-256 hex string, the password is verified with SHA-256 and the
    hash is immediately re-stored as bcrypt (cost=12). No admin action required.
    """
    client_ip = raw_request.client.host if raw_request.client else "unknown"
    now = time.time()

    # Rate limiting: allow max 5 failed attempts per 60 seconds per IP
    attempts = [t for t in _failed_login_attempts.get(client_ip, []) if now - t < 60.0]
    _failed_login_attempts[client_ip] = attempts

    if len(attempts) >= 5:
        raise HTTPException(
            status_code=429,
            detail="Πολλές αποτυχημένες προσπάθειες. Παρακαλώ περιμένετε 1 λεπτό."
        )

    user = cfg_db.get_admin_user_by_username(request.username.strip())
    password_bytes = request.password.encode("utf-8")

    username_valid = user is not None
    password_valid = False

    if user:
        db_password_hash = user["password_hash"]
        is_legacy_sha256 = len(db_password_hash) == 64 and not db_password_hash.startswith("$2")

        if is_legacy_sha256:
            input_sha256 = hashlib.sha256(password_bytes).hexdigest()
            if hmac.compare_digest(input_sha256, db_password_hash):
                password_valid = True
                new_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12)).decode()
                cfg_db.update_admin_user(user["id"], password_hash=new_hash)
        else:
            try:
                password_valid = bcrypt.checkpw(password_bytes, db_password_hash.encode("utf-8"))
            except Exception:
                pass
    else:
        # Dummy check to prevent timing attacks
        try:
            bcrypt.checkpw(password_bytes, b"$2b$12$0qxEPV2WtZ00AhsmOgAbJOQuiessOk/m5jq4x55CB/c680fNiW13i")
        except Exception:
            pass

    if not (username_valid and password_valid):
        _failed_login_attempts.setdefault(client_ip, []).append(now)
        await asyncio.sleep(1.0)  # Throttling delay against automated brute-force attacks
        raise HTTPException(status_code=401, detail="Λάθος στοιχεία σύνδεσης")

    if user and not user.get("is_active", 1):
        raise HTTPException(status_code=403, detail="Ο λογαριασμός σας έχει απενεργοποιηθεί")

    # Clear failed attempts on success
    _failed_login_attempts.pop(client_ip, None)

    import secrets
    token = secrets.token_hex(16)
    _admin_sessions[token] = {"id": user["id"], "username": user["username"], "role": user["role"]}
    return AdminLoginResponse(token=token, username=user["username"], role=user["role"])


@router.post("/admin/auth/change-credentials", response_model=AdminChangeCredentialsResponse)
async def change_admin_credentials(
    req: AdminChangeCredentialsRequest,
    session: dict = Depends(_require_admin)
):
    """Update admin username and/or password. New password is stored as bcrypt hash."""
    user = cfg_db.get_admin_user_by_id(session["id"])
    if not user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")
    db_password_hash = user["password_hash"]
    password_bytes = req.old_password.encode("utf-8")

    is_legacy_sha256 = len(db_password_hash) == 64 and not db_password_hash.startswith("$2")
    if is_legacy_sha256:
        old_hash = hashlib.sha256(password_bytes).hexdigest()
        old_password_valid = hmac.compare_digest(old_hash, db_password_hash)
    else:
        try:
            old_password_valid = bcrypt.checkpw(password_bytes, db_password_hash.encode("utf-8"))
        except Exception:
            old_password_valid = False

    if not old_password_valid:
        raise HTTPException(status_code=400, detail="Ο τρέχων κωδικός πρόσβασης είναι λανθασμένος")

    new_hash = (
        bcrypt.hashpw(req.new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()
        if req.new_password and req.new_password.strip()
        else None
    )
    new_user = req.new_username.strip() if req.new_username and req.new_username.strip() else None

    if not new_user and not new_hash:
        raise HTTPException(status_code=400, detail="Δεν δόθηκαν νέα στοιχεία προς ενημέρωση")

    updated_user = cfg_db.update_admin_user(user["id"], username=new_user, password_hash=new_hash)
    if not updated_user:
        raise HTTPException(status_code=500, detail="Αποτυχία ενημέρωσης")
    
    # Update current session username if changed
    if new_user:
        session["username"] = updated_user["username"]

    return AdminChangeCredentialsResponse(
        message="Τα στοιχεία σύνδεσης ενημερώθηκαν επιτυχώς",
        username=updated_user["username"]
    )

# ─────────────────────────────────────────────────────
#  Admin — Users Management (super_admin only)
# ─────────────────────────────────────────────────────

class AdminUserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "admin"

class AdminUserUpdateRequest(BaseModel):
    username: str | None = None
    password: str | None = None
    role: str | None = None
    is_active: bool | None = None

@router.get("/admin/users")
async def get_admin_users(session: dict = Depends(_require_it_support)):
    users = cfg_db.get_all_admin_users()
    # Don't expose password hashes
    for u in users:
        u.pop("password_hash", None)
    return users

@router.post("/admin/users")
async def create_admin_user(req: AdminUserCreateRequest, session: dict = Depends(_require_it_support)):
    existing = cfg_db.get_admin_user_by_username(req.username.strip())
    if existing:
        raise HTTPException(status_code=400, detail="Το όνομα χρήστη υπάρχει ήδη")
    new_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()
    user = cfg_db.create_admin_user(req.username.strip(), new_hash, req.role)
    user.pop("password_hash", None)
    return user

@router.put("/admin/users/{user_id}")
async def update_admin_user(user_id: int, req: AdminUserUpdateRequest, session: dict = Depends(_require_it_support)):
    new_hash = None
    if req.password and req.password.strip():
        new_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()
    
    updated = cfg_db.update_admin_user(
        user_id,
        username=req.username.strip() if req.username else None,
        password_hash=new_hash,
        role=req.role,
        is_active=req.is_active
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")
    updated.pop("password_hash", None)
    return updated

@router.post("/admin/users/{user_id}/reset")
async def reset_admin_user(user_id: int, session: dict = Depends(_require_it_support)):
    target_user = cfg_db.get_admin_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")
    if target_user["role"] == "it_support":
        raise HTTPException(status_code=400, detail="Δεν επιτρέπεται η επαναφορά του it_support")
    
    new_hash = bcrypt.hashpw(b"admin1234", bcrypt.gensalt(rounds=12)).decode()
    updated = cfg_db.update_admin_user(user_id, username="admin", password_hash=new_hash)
    if not updated:
        raise HTTPException(status_code=500, detail="Αποτυχία επαναφοράς")
    return {"message": "Τα στοιχεία επαναφέρθηκαν επιτυχώς σε admin / admin1234"}


@router.post("/admin/users/{user_id}/toggle")
async def toggle_admin_user(user_id: int, session: dict = Depends(_require_it_support)):
    target_user = cfg_db.get_admin_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")
    if target_user["role"] == "it_support":
        raise HTTPException(status_code=400, detail="Δεν επιτρέπεται η αλλαγή του it_support")
    
    new_active = not bool(target_user["is_active"])
    updated = cfg_db.update_admin_user(user_id, is_active=new_active)
    if not updated:
        raise HTTPException(status_code=500, detail="Αποτυχία ενημέρωσης")
    return {"message": "Η κατάσταση του χρήστη ενημερώθηκε", "is_active": updated["is_active"]}

@router.delete("/admin/users/{user_id}")
async def delete_admin_user(user_id: int, session: dict = Depends(_require_it_support)):
    if user_id == session["id"]:
        raise HTTPException(status_code=400, detail="Δεν μπορείτε να διαγράψετε τον εαυτό σας")
    if not cfg_db.delete_admin_user(user_id):
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")
    return {"status": "ok"}


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


class SuggestBatchRequest(BaseModel):
    exam_ids: list[str]


async def _generate_suggestion_for_exam(
    exam_data: dict,
    all_exams: list[dict],
    assign_svc: AssignmentService,
    diag_svc: DiagnosticianService,
) -> AssignmentSuggestion | None:
    """Core suggestion generator with multi-exam order alignment and virtual workload tracking."""
    exam = ExamContext(
        exam_id=exam_data["exam_id"],
        patient_id=exam_data["patient_id"],
        patient_name=exam_data.get("patient_name", ""),
        age=exam_data.get("age"),
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
        oldpers=exam_data.get("oldpers"),
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
        oldpers=exam.oldpers,
    )

    # Apply session-level virtual workload
    for c in candidates:
        c.current_day_count += _session_suggestion_counts.get(c.id, 0)

    # Multi-exam order alignment check (same patient and same order/extracode)
    extracode_val = exam_data.get("extracode")
    patient_id_val = exam_data.get("patient_id")
    order_exams = []
    if extracode_val and patient_id_val:
        order_exams = [
            e for e in all_exams
            if str(e.get("patient_id")) == str(patient_id_val)
            and str(e.get("extracode")) == str(extracode_val)
        ]

    if len(order_exams) > 1:
        from diagflow.engine.filters import apply_hard_filters
        from diagflow.engine.scoring import score_all_candidates

        # 1. Check if another exam in this exact same order already has a cached suggestion or assignment
        existing_order_diag_id = None
        for e_item in order_exams:
            e_item_id = str(e_item["exam_id"])
            if e_item_id == str(exam_data["exam_id"]):
                continue
            cached = _suggestion_cache.get(e_item_id)
            if cached and cached.suggested_diagnostician_id:
                existing_order_diag_id = cached.suggested_diagnostician_id
                break
            elif e_item.get("diagnostis") and str(e_item.get("diagnostis")) not in ('0', '', 'None'):
                existing_order_diag_id = e_item.get("diagnostis")
                break

        best_cand_id = None
        if existing_order_diag_id:
            target_cand = next((c for c in candidates if str(c.id) == str(existing_order_diag_id)), None)
            if target_cand:
                passed_target, _ = apply_hard_filters([target_cand], exam)
                if passed_target:
                    best_cand_id = target_cand.id

        cand_info = {}
        if not best_cand_id:
            order_contexts = []
            for e_dict in order_exams:
                e_ctx = ExamContext(
                    exam_id=e_dict["exam_id"],
                    patient_id=e_dict["patient_id"],
                    patient_name=e_dict.get("patient_name", ""),
                    modality=e_dict["modality"],
                    body_part=e_dict["body_part"],
                    exam_code=str(e_dict.get("examnumcode", "")),
                    exam_name=e_dict.get("examname", ""),
                    lab_id=e_dict["lab_id"],
                    lab_name=e_dict["lab_name"],
                    issuing_doctor_id=e_dict["issuing_doctor_id"],
                    issuing_doctor_name=e_dict["issuing_doctor_name"],
                    comments=e_dict.get("comments", ""),
                    is_pamakristos="ΠΑΜΜΑΚΑΡΙΣΤΟΣ" in e_dict.get("issuing_doctor_name", "").upper(),
                    oldpers=e_dict.get("oldpers"),
                )
                e_cands = await diag_svc.get_candidates_for_exam(
                    exam_id=e_ctx.exam_id,
                    modality=e_ctx.modality,
                    body_part=e_ctx.body_part,
                    lab_id=e_ctx.lab_id,
                    lab_name=e_ctx.lab_name,
                    issuing_doctor_id=e_ctx.issuing_doctor_id,
                    patient_id=e_ctx.patient_id,
                    exam_code=e_ctx.exam_code,
                    oldpers=e_ctx.oldpers,
                )
                for c in e_cands:
                    cand_info[c.id] = c
                order_contexts.append((e_ctx, e_cands))

            cand_totals = {}
            cand_eligible_all = {}
            for ex_ctx, cands in order_contexts:
                passed, _ = apply_hard_filters(cands, ex_ctx)
                passed_ids = {p.id for p in passed}
                for c in cands:
                    if c.id not in cand_eligible_all:
                        cand_eligible_all[c.id] = True
                    if c.id not in passed_ids:
                        cand_eligible_all[c.id] = False
                if passed:
                    scored = score_all_candidates(passed, ex_ctx)
                    for sc in scored:
                        cand_totals[sc.diagnostician_id] = cand_totals.get(sc.diagnostician_id, 0.0) + sc.total_score

            best_total = -1.0
            for c_id, is_elig in cand_eligible_all.items():
                if is_elig:
                    score_val = cand_totals.get(c_id, 0.0)
                    if score_val > best_total:
                        best_total = score_val
                        best_cand_id = c_id
                    elif abs(score_val - best_total) < 1e-6 and best_cand_id:
                        c1 = cand_info.get(c_id)
                        c2 = cand_info.get(best_cand_id)
                        if c1 and c2 and c1.current_day_count < c2.current_day_count:
                            best_cand_id = c_id

        suggestion = await assign_svc.suggest_assignment(exam, candidates)
        if suggestion and best_cand_id:
            best_cand = next((c for c in candidates if c.id == best_cand_id), cand_info.get(best_cand_id))
            if best_cand and suggestion.suggested_diagnostician_id != best_cand_id:
                suggestion.suggested_diagnostician_id = best_cand_id
                suggestion.suggested_diagnostician_name = best_cand.name
                if "Multi-exam Order Alignment" not in suggestion.rules_fired:
                    suggestion.rules_fired.insert(0, "Multi-exam Order Alignment")
    else:
        suggestion = await assign_svc.suggest_assignment(exam, candidates)

    if suggestion:
        if suggestion.suggested_diagnostician_id:
            diag_id = suggestion.suggested_diagnostician_id
            _session_suggestion_counts[diag_id] = _session_suggestion_counts.get(diag_id, 0) + 1

        _suggestion_cache[exam.exam_id] = suggestion
        _suggestion_cache[str(exam.exam_id)] = suggestion

    return suggestion


@router.post("/assignments/suggest-batch")
async def suggest_batch_assignments(
    request: SuggestBatchRequest,
    assign_svc: AssignmentService = Depends(get_assignment_service),
    diag_svc: DiagnosticianService = Depends(get_diagnostician_service),
):
    """Generate assignment suggestions for multiple exams in a single ultra-fast pass."""
    pending = assign_svc.get_pending_exams()
    assigned = assign_svc.get_assigned_exams()
    all_exams = pending + assigned
    exams_map = {str(e["exam_id"]): e for e in all_exams}

    results = {}
    for exam_id_str in request.exam_ids:
        exam_data = exams_map.get(exam_id_str)
        if not exam_data:
            continue

        suggestion = await _generate_suggestion_for_exam(exam_data, all_exams, assign_svc, diag_svc)
        if suggestion:
            results[str(suggestion.exam_id)] = {
                "exam_id": suggestion.exam_id,
                "patient_id": suggestion.patient_id,
                "exam_summary": suggestion.exam_summary,
                "suggested_diagnostician_id": suggestion.suggested_diagnostician_id,
                "suggested_diagnostician_name": suggestion.suggested_diagnostician_name,
                "confidence_score": suggestion.confidence_score,
                "score_breakdown": suggestion.score_breakdown,
                "alternatives": [
                    a if isinstance(a, dict) else {
                        "id": getattr(a, "id", None),
                        "name": getattr(a, "name", ""),
                        "score": getattr(a, "score", 0.0),
                        "eliminated": getattr(a, "eliminated", False),
                        "elimination_reason": getattr(a, "elimination_reason", None),
                    }
                    for a in suggestion.alternatives
                ],
                "rules_fired": suggestion.rules_fired,
                "solver_status": suggestion.solver_status,
                "is_direct_assignment": getattr(suggestion, "is_direct_assignment", False),
                "direct_assignment_reason": getattr(suggestion, "direct_assignment_reason", None),
                "pipeline_timestamp": suggestion.pipeline_timestamp,
            }

    return {"suggestions": results}


@router.post("/assignments/suggest", response_model=SuggestionResponse)
async def suggest_assignment(
    request: SuggestAssignmentRequest,
    assign_svc: AssignmentService = Depends(get_assignment_service),
    diag_svc: DiagnosticianService = Depends(get_diagnostician_service),
):
    """Generate an assignment suggestion for a specific exam."""
    pending = assign_svc.get_pending_exams()
    assigned = assign_svc.get_assigned_exams()
    all_exams = pending + assigned
    exam_data = next((e for e in all_exams if str(e["exam_id"]) == str(request.exam_id)), None)

    if not exam_data:
        raise HTTPException(status_code=404, detail=f"Exam {request.exam_id} not found")

    suggestion = await _generate_suggestion_for_exam(exam_data, all_exams, assign_svc, diag_svc)

    if not suggestion:
        raise HTTPException(
            status_code=422,
            detail="No eligible diagnosticians found after applying all rules. Manual assignment required.",
        )

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
    suggestion = _suggestion_cache.get(request.exam_id) or _suggestion_cache.get(str(request.exam_id))
    if not suggestion:
        from diagflow.engine.pipeline import AssignmentSuggestion
        suggestion = AssignmentSuggestion(
            exam_id=str(request.exam_id),
            patient_id="",
            exam_summary="",
            suggested_diagnostician_id=request.diagnostician_id,
            suggested_diagnostician_name="",
            confidence_score=1.0,
            score_breakdown=[],
            alternatives=[],
            rules_fired=[],
            filter_results={},
            solver_status="fallback",
            pipeline_timestamp=datetime.now().isoformat(),
        )

    result = await svc.confirm_assignment(
        exam_id=request.exam_id,
        diagnostician_id=request.diagnostician_id,
        suggestion=suggestion,
    )
    _suggestion_cache.pop(request.exam_id, None)
    _suggestion_cache.pop(str(request.exam_id), None)

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
    suggestion = _suggestion_cache.get(request.exam_id) or _suggestion_cache.get(str(request.exam_id))
    if not suggestion:
        from diagflow.engine.pipeline import AssignmentSuggestion
        suggestion = AssignmentSuggestion(
            exam_id=str(request.exam_id),
            patient_id="",
            exam_summary="",
            suggested_diagnostician_id=request.original_diagnostician_id or 0,
            suggested_diagnostician_name="",
            confidence_score=1.0,
            score_breakdown=[],
            alternatives=[],
            rules_fired=[],
            filter_results={},
            solver_status="fallback",
            pipeline_timestamp=datetime.now().isoformat(),
        )

    result = await svc.override_assignment(
        exam_id=request.exam_id,
        original_diagnostician_id=request.original_diagnostician_id,
        override_diagnostician_id=request.override_diagnostician_id,
        reason=request.reason,
        suggestion=suggestion,
    )
    _suggestion_cache.pop(request.exam_id, None)
    _suggestion_cache.pop(str(request.exam_id), None)

    return AssignmentConfirmation(
        exam_id=request.exam_id,
        diagnostician_id=request.override_diagnostician_id,
        was_overridden=True,
        status="overridden",
        timestamp=result["decision_timestamp"],
    )


@router.post("/assignments/bulk-eligible-diagnosticians", response_model=BulkEligibleResponse)
async def bulk_eligible_diagnosticians(
    request: BulkEligibleRequest,
    assign_svc: AssignmentService = Depends(get_assignment_service),
    diag_svc: DiagnosticianService = Depends(get_diagnostician_service),
):
    """
    Check eligibility for diagnosticians across a set of exams.
    A diagnostician is only eligible if they are eligible for ALL provided exams.
    """
    if not request.exam_ids:
        return BulkEligibleResponse(diagnosticians=[])

    from diagflow.engine.filters import apply_hard_filters, get_elimination_reason, ExamContext

    all_exams = assign_svc.get_pending_exams() + assign_svc.get_assigned_exams()
    req_ids = {str(x) for x in request.exam_ids}
    selected_exams = [e for e in all_exams if str(e.get("exam_id")) in req_ids or (e.get("exammoreid") and str(e.get("exammoreid")) in req_ids)]

    found_eids = {str(e.get("exam_id")) for e in selected_exams} | {str(e.get("exammoreid")) for e in selected_exams if e.get("exammoreid")}
    missing_ids = list(req_ids - found_eids)

    if missing_ids:
        try:
            from diagflow.services.assignment import _get_mock_db
            con = _get_mock_db()
            placeholders = ",".join("?" * len(missing_ids))
            rows = con.execute(f"SELECT * FROM slis_exams WHERE exammoreid IN ({placeholders})", tuple(missing_ids)).fetchall()
            for r in rows:
                r_dict = dict(r)
                selected_exams.append({
                    "exam_id": str(r_dict.get("exammoreid")),
                    "patient_id": str(r_dict.get("demogid") or r_dict.get("patientid") or ""),
                    "patient_name": f"{r_dict.get('fname', '')} {r_dict.get('lname', '')}".strip() if (r_dict.get('fname') or r_dict.get('lname')) else str(r_dict.get("patient_name") or ""),
                    "modality": str(r_dict.get("category") or r_dict.get("modality") or ""),
                    "body_part": str(r_dict.get("bodypart") or ""),
                    "examnumcode": str(r_dict.get("examnumcode") or ""),
                    "examname": str(r_dict.get("examname") or ""),
                    "lab_id": str(r_dict.get("labid") or ""),
                    "lab_name": str(r_dict.get("labname") or r_dict.get("laboratoryname") or ""),
                    "issuing_doctor_id": str(r_dict.get("doctorid") or ""),
                    "issuing_doctor_name": str(r_dict.get("wname") or r_dict.get("issuing_doctor_name") or ""),
                    "comments": str(r_dict.get("comments") or ""),
                    "oldpers": r_dict.get("oldpers")
                })
        except Exception as ex:
            pass

    if not selected_exams:
        return BulkEligibleResponse(diagnosticians=[])

    # Start with all diagnosticians as eligible
    all_diags = await diag_svc.get_all_diagnosticians()
    eligible_diags = {d["id"]: d for d in all_diags}
    reasons: dict[int, str | None] = {d_id: None for d_id in eligible_diags}
    is_eligible = {d_id: True for d_id in eligible_diags}

    exam_contexts = [
        ExamContext(
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
            oldpers=exam_data.get("oldpers"),
        )
        for exam_data in selected_exams
    ]

    # Pre-fetch candidate evaluations for all selected exams in one batch
    batch_candidates = await diag_svc.get_candidates_for_exams_batch(exam_contexts)

    for exam in exam_contexts:
        candidates = batch_candidates.get(str(exam.exam_id), [])
        if not candidates:
            candidates = await diag_svc.get_candidates_for_exam(
                exam_id=exam.exam_id,
                modality=exam.modality,
                body_part=exam.body_part,
                lab_id=exam.lab_id,
                issuing_doctor_id=exam.issuing_doctor_id,
                patient_id=exam.patient_id,
                exam_code=exam.exam_code,
                lab_name=exam.lab_name,
                oldpers=exam.oldpers,
            )

        # Run filters for this exam
        passed, results_dict = apply_hard_filters(
            candidates=[c for c in candidates if is_eligible[c.id]],
            exam=exam
        )
        passed_ids = {p.id for p in passed}

        for d_id in list(eligible_diags.keys()):
            if is_eligible[d_id] and d_id not in passed_ids:
                is_eligible[d_id] = False
                reasons[d_id] = get_elimination_reason(d_id, results_dict)

    res = [
        BulkEligibleResponseItem(
            diagnostician_id=d_id,
            is_eligible=is_eligible[d_id],
            reject_reason=reasons[d_id]
        )
        for d_id in eligible_diags
    ]
    return BulkEligibleResponse(diagnosticians=res)


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


@router.get("/doctors")
def list_doctors_public(q: str = "", limit: int = 200):
    """Public doctor list/search endpoint for autocompletion."""
    return cfg_db.get_all_doctors(q=q, skip=0, limit=limit)


@router.get("/dashboard")
async def get_dashboard():
    """Get today's assigned exams per diagnostician."""
    dashboard_data = cfg_db.get_dashboard_data()
    
    try:
        from diagflow.services.assignment import _exam_details_cache
        dict_entries = cfg_db.get_exam_dictionary()
        exam_dict_map = {str(e["code"]).strip(): e["name"] for e in dict_entries if e.get("code") and e.get("name")}

        local_assigns = cfg_db.get_all_local_assignments()
        
        for d in dashboard_data:
            d["exam_names"] = {}
            for eid in d.get("assigned_exam_ids", []):
                eid_int = int(eid)
                eid_str = str(eid)
                
                # Check local assignment store first
                loc = local_assigns.get(eid_int) or {}
                name = loc.get("examname")
                
                # Check in-memory cache
                if not name:
                    c_info = _exam_details_cache.get(eid_int) or {}
                    name = c_info.get("examname")
                    if not name and c_info.get("examnumcode"):
                        name = exam_dict_map.get(str(c_info["examnumcode"]).strip())

                # Check mock slis DB if in mock mode
                if not name and settings.use_mock_slis_db:
                    try:
                        from diagflow.services.assignment import _get_mock_db
                        con = _get_mock_db()
                        r = con.execute("SELECT examname, examnumcode FROM slis_exams WHERE exammoreid = ?", (eid_int,)).fetchone()
                        if r:
                            name = (r["examname"] or "").strip() or (exam_dict_map.get(str(r["examnumcode"]).strip()) if r["examnumcode"] else "")
                        con.close()
                    except Exception:
                        pass

                if not name or name.startswith("Εξέταση ") or "Εξέταση 20" in name:
                    # Look up modality to give clean descriptive name
                    mod = loc.get("modality") or "Εξέταση"
                    name = f"{mod} Απεικόνιση"

                d["exam_names"][name] = d["exam_names"].get(name, 0) + 1
    except Exception as e:
        print(f"Failed to process dashboard exam names: {e}")
        
    return dashboard_data

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
async def admin_get_weekly_schedule(_=Depends(_require_admin)):
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
    _=Depends(_require_admin),
):
    cfg_db.update_pamakristos_weekly_schedule_db([item.model_dump() for item in items])
    return {"status": "ok", "updated": len(items)}


# ─────────────────────────────────────────────────────
#  Admin — Diagnosticians  (diagflow.db — persistent)
# ─────────────────────────────────────────────────────

@router.get("/admin/exam-categories")
async def admin_get_exam_categories(_=Depends(_require_admin)):
    items = cfg_db.get_exam_dictionary()
    if not items:
        slis_db_path = Path(settings.mock_slis_db_path)
        if slis_db_path.exists():
            import sqlite3
            with sqlite3.connect(slis_db_path) as con:
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    "SELECT DISTINCT examnumcode AS examnumcode, examname AS name, category FROM slis_exams "
                    "WHERE examnumcode IS NOT NULL AND examnumcode != ''"
                ).fetchall()
                items = [dict(r) for r in rows]
                for item in items:
                    cfg_db.upsert_exam_dictionary_entry(
                        str(item["examnumcode"]), str(item.get("name") or ""), str(item.get("category") or "")
                    )
    return items

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
async def admin_list_diagnosticians(_=Depends(_require_admin)):
    return cfg_db.get_all_diagnosticians()


@router.post("/admin/diagnosticians/sync")
async def admin_sync_diagnosticians(_=Depends(_require_admin)):
    from diagflow.services.slis_sync import sync_diagnosticians
    return sync_diagnosticians()


@router.post("/admin/doctors/sync")
async def admin_sync_doctors(_=Depends(_require_admin)):
    from diagflow.services.slis_sync import sync_doctors
    return sync_doctors()


@router.post("/admin/diagnosticians")
async def admin_create_diagnostician(
    req: DiagnosticianCreateRequest,
    _=Depends(_require_admin),
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
    _=Depends(_require_admin),
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
async def admin_delete_diagnostician(diag_id: int, _=Depends(_require_admin)):
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
async def admin_list_partnerships(_=Depends(_require_admin)):
    return cfg_db.get_all_partnerships()


@router.post("/admin/partnerships")
async def admin_create_partnership(
    req: PartnershipCreateRequest,
    _=Depends(_require_admin),
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
    _=Depends(_require_admin),
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
async def admin_delete_partnership(part_id: int, _=Depends(_require_admin)):
    if not cfg_db.delete_partnership(part_id):
        raise HTTPException(status_code=404, detail="Η σύμπραξη δεν βρέθηκε")
    return {"deleted": part_id}


# ─────────────────────────────────────────────────────
#  Admin — Doctors  (diagflow.db — persistent)
# ─────────────────────────────────────────────────────

class DoctorCreateRequest(BaseModel):
    id: str = ""
    name: str


@router.get("/admin/doctors")
def admin_list_doctors(
    q: str = "",
    skip: int = 0,
    limit: int = 50,
    _=Depends(_require_admin)
):
    return cfg_db.get_all_doctors(q=q, skip=skip, limit=limit)


@router.post("/admin/doctors")
async def admin_create_doctor(req: DoctorCreateRequest, _=Depends(_require_admin)):
    import secrets
    doc_id = req.id if req.id else f"DR-{secrets.token_hex(4).upper()}"
    return cfg_db.upsert_doctor(doctor_id=doc_id, name=req.name)


@router.delete("/admin/doctors/{doctor_id}")
async def admin_delete_doctor(doctor_id: str, _=Depends(_require_admin)):
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
async def admin_list_availability(_=Depends(_require_admin)):
    return cfg_db.get_all_availability()


@router.post("/admin/availability")
async def admin_set_availability(
    req: AvailabilitySetRequest,
    _=Depends(_require_admin),
):
    return cfg_db.upsert_availability(
        diagnostician_id=req.diagnostician_id,
        date=req.date,
        status=req.status,
        is_pamakristos_oncall=req.is_pamakristos_oncall,
        notes=req.notes,
    )


@router.delete("/admin/availability/{diagnostician_id}/{date}")
async def admin_delete_availability(
    diagnostician_id: int,
    date: str,
    _=Depends(_require_admin),
):
    success = cfg_db.delete_availability(diagnostician_id, date)
    return {"success": success, "diagnostician_id": diagnostician_id, "date": date}


# ─────────────────────────────────────────────────────
#  Admin — Skills  (diagflow.db — persistent)
# ─────────────────────────────────────────────────────

class SkillSetRequest(BaseModel):
    diagnostician_id: int
    exam_code: str
    is_preferred: bool = False


class SkillUpdateRequest(BaseModel):
    is_preferred: bool = False


class SkillDeleteRequest(BaseModel):
    skill_id: int


@router.get("/admin/skills")
async def admin_list_skills(
    diagnostician_id: int | None = None,
    _=Depends(_require_admin),
):
    return cfg_db.get_skills(diagnostician_id)


@router.post("/admin/skills")
async def admin_set_skill(req: SkillSetRequest, _=Depends(_require_admin)):
    diag_id = req.diagnostician_id
    code = req.exam_code.strip()

    diag = cfg_db.get_diagnostician(diag_id)
    if not diag:
        raise HTTPException(status_code=404, detail="Ο διαγνώστης δεν βρέθηκε")

    diag_name = diag.get("name", f"ID {diag_id}")
    can_ct = bool(diag.get("can_ct", False))
    can_mri = bool(diag.get("can_mri", False))

    existing = cfg_db.get_skills(diag_id)
    if any(str(s.get("exam_code")).strip() == str(code).strip() for s in existing):
        raise HTTPException(
            status_code=400,
            detail=f"Η δεξιότητα {code} υπάρχει ήδη για τον/την {diag_name}"
        )

    category = ""
    dict_entries = cfg_db.get_exam_dictionary()
    matched = next((e for e in dict_entries if str(e.get("examnumcode") or e.get("code") or "").strip() == str(code).strip()), None)
    if matched:
        category = (matched.get("category") or "").upper().strip()
        name = matched.get("name") or ""
    else:
        name = ""

    if not category:
        name_upper = name.upper()
        if "CT" in name_upper or "ΑΞΟΝ" in name_upper or code.startswith("21"):
            category = "CT"
        elif "MRA" in name_upper or "ΑΓΓΕΙΟ" in name_upper or code.startswith("228"):
            category = "MRA"
        elif "MRI" in name_upper or "ΜΑΓΝΗΤ" in name_upper or code.startswith("22"):
            category = "MRI"
        else:
            category = "CT" if code.startswith("21") else "MRI"

    if category == "CT" and not can_ct:
        raise HTTPException(
            status_code=400,
            detail=f"Ο/Η {diag_name} δεν πραγματοποιεί Αξονικές (CT). Δεν μπορείτε να προσθέσετε τον κωδικό {code}."
        )
    if category in ("MRI", "MRA") and not can_mri:
        raise HTTPException(
            status_code=400,
            detail=f"Ο/Η {diag_name} δεν πραγματοποιεί Μαγνητικές (MRI/MRA). Δεν μπορείτε να προσθέσετε τον κωδικό {code}."
        )

    res = cfg_db.upsert_skill(
        diagnostician_id=diag_id,
        exam_code=code,
        is_preferred=req.is_preferred,
    )
    DiagnosticianService.clear_cache()
    return res


@router.put("/admin/skills/{skill_id}")
async def admin_update_skill(skill_id: int, req: SkillUpdateRequest, _=Depends(_require_admin)):
    if not cfg_db.update_skill_preference(skill_id, req.is_preferred):
        raise HTTPException(status_code=404, detail="Η δεξιότητα δεν βρέθηκε")
    DiagnosticianService.clear_cache()
    return {"id": skill_id, "is_preferred": req.is_preferred}


@router.delete("/admin/skills/{skill_id}")
async def admin_delete_skill(skill_id: int, _=Depends(_require_admin)):
    if not cfg_db.delete_skill(skill_id):
        raise HTTPException(status_code=404, detail="Η δεξιότητα δεν βρέθηκε")
    DiagnosticianService.clear_cache()
    return {"deleted": skill_id}



# ─────────────────────────────────────────────────────
#  Admin — Παμμακάριστος on-call override
# ─────────────────────────────────────────────────────

class OncallSetRequest(BaseModel):
    diagnostician_id: int
    date: str


@router.get("/admin/oncall")
async def admin_get_oncall(_=Depends(_require_admin)):
    today = str(date.today())
    record = cfg_db.get_oncall_diagnostician(today)
    if record:
        return record
    # Fallback: check scheduler
    return {"diagnostician_id": None, "diagnostician_name": None, "date": today}


@router.post("/admin/oncall")
async def admin_set_oncall(
    req: OncallSetRequest,
    _=Depends(_require_admin),
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


@router.get("/admin/pamakristos/overrides")
async def admin_get_pamakristos_overrides(_=Depends(_require_admin)):
    return cfg_db.get_pamakristos_manual_overrides()


@router.delete("/admin/pamakristos/overrides/{avail_id}")
async def admin_delete_pamakristos_override(avail_id: int, _=Depends(_require_admin)):
    success = cfg_db.delete_pamakristos_manual_override(avail_id)
    if not success:
        raise HTTPException(status_code=404, detail="Override not found")
    return {"status": "success", "deleted_id": avail_id}


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


@router.get("/slis/status")
async def slis_status():
    """Return the current Slis DB connection status and error details if any."""
    from diagflow.main import SLIS_STATUS
    return SLIS_STATUS


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


@router.post("/slis/search")
async def slis_search_exams(req: SlisSearchRequest):
    """
    Search exams directly in Slis (production MSSQL or mock DB) by filters.
    Defaults to last 7 days if date range is empty.
    """
    from diagflow.services.slis_sync import search_slis_exams
    return search_slis_exams(
        start_date=req.start_date,
        end_date=req.end_date,
        extracode=req.extracode,
        patient_query=req.patient_query,
        doctor_query=req.doctor_query,
        diagnostician_query=req.diagnostician_query,
    )


@router.post("/slis/reassign")
async def slis_reassign_exam(req: SlisReassignRequest):
    """
    Re-assign an exam to a new diagnostician and immediately update Slis.
    """
    from diagflow.services.slis_sync import push_exam_to_slis
    result = push_exam_to_slis(
        exammoreid=req.exammoreid,
        diagnostician_id=req.diagnostician_id,
        diagnostician_name=req.diagnostician_name,
    )
    return result



@router.post("/admin/sync-diagnosticians")
async def admin_sync_diagnosticians(_=Depends(_require_admin)):
    """Manual trigger to pull diagnosticians from Slis DB into diagflow.db."""
    from diagflow.services.slis_sync import sync_diagnosticians
    result = sync_diagnosticians()
    return result


@router.post("/admin/sync-doctors")
async def admin_sync_doctors(_=Depends(_require_admin)):
    """Manual trigger to pull doctors from Slis DB into diagflow.db."""
    from diagflow.services.slis_sync import sync_doctors
    result = sync_doctors()
    return result

# ─────────────────────────────────────────────────────
#  Admin Advanced Options
# ─────────────────────────────────────────────────────

from diagflow.api.schemas import (
    ExamRoutingRuleCreate, ExamRoutingRuleUpdate, ExamRoutingRuleResponse,
    ExclusiveLabRuleCreate, ExclusiveLabRuleUpdate, ExclusiveLabRuleResponse,
    ModalityQuotaCreate, ModalityQuotaUpdate, ModalityQuotaResponse
)

@router.get('/admin/advanced/exam-routing-rules', response_model=list[ExamRoutingRuleResponse])
async def get_exam_routing_rules(_=Depends(_require_admin)):
    return cfg_db.get_all_exam_routing_rules()

@router.post('/admin/advanced/exam-routing-rules', response_model=ExamRoutingRuleResponse)
async def add_exam_routing_rule(req: ExamRoutingRuleCreate, _=Depends(_require_admin)):
    return cfg_db.create_exam_routing_rule(
        lab_id=req.lab_id,
        issuing_doctor_id=req.issuing_doctor_id,
        issuing_doctor_name=req.issuing_doctor_name,
        is_pamakristos=req.is_pamakristos,
        exam_codes=req.exam_codes,
        diagnostician_id=req.diagnostician_id,
        description=req.description,
        is_active=req.is_active
    )

@router.put('/admin/advanced/exam-routing-rules/{rule_id}', response_model=ExamRoutingRuleResponse)
async def edit_exam_routing_rule(rule_id: int, req: ExamRoutingRuleUpdate, _=Depends(_require_admin)):
    result = cfg_db.update_exam_routing_rule(rule_id, req.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail='Rule not found')
    return result

@router.delete('/admin/advanced/exam-routing-rules/{rule_id}')
async def remove_exam_routing_rule(rule_id: int, _=Depends(_require_admin)):
    success = cfg_db.delete_exam_routing_rule(rule_id)
    if not success:
        raise HTTPException(status_code=404, detail='Rule not found')
    return {'success': True}

@router.get('/admin/advanced/exclusive-lab-rules', response_model=list[ExclusiveLabRuleResponse])
async def get_exclusive_lab_rules(_=Depends(_require_admin)):
    return cfg_db.get_all_exclusive_lab_rules()

@router.post('/admin/advanced/exclusive-lab-rules', response_model=ExclusiveLabRuleResponse)
async def add_exclusive_lab_rule(req: ExclusiveLabRuleCreate, _=Depends(_require_admin)):
    return cfg_db.create_exclusive_lab_rule(
        diagnostician_id=req.diagnostician_id,
        lab_id=req.lab_id,
        lab_name=req.lab_name or '',
        is_active=req.is_active
    )

@router.put('/admin/advanced/exclusive-lab-rules/{rule_id}', response_model=ExclusiveLabRuleResponse)
async def edit_exclusive_lab_rule(rule_id: int, req: ExclusiveLabRuleUpdate, _=Depends(_require_admin)):
    result = cfg_db.update_exclusive_lab_rule(rule_id, req.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail='Rule not found')
    return result

@router.delete('/admin/advanced/exclusive-lab-rules/{rule_id}')
async def remove_exclusive_lab_rule(rule_id: int, _=Depends(_require_admin)):
    success = cfg_db.delete_exclusive_lab_rule(rule_id)
    if not success:
        raise HTTPException(status_code=404, detail='Rule not found')
    return {'success': True}

@router.get('/admin/advanced/modality-quotas', response_model=list[ModalityQuotaResponse])
async def get_modality_quotas(_=Depends(_require_admin)):
    return cfg_db.get_all_modality_quotas()

@router.post('/admin/advanced/modality-quotas', response_model=ModalityQuotaResponse)
async def add_modality_quota(req: ModalityQuotaCreate, _=Depends(_require_admin)):
    return cfg_db.create_modality_quota(
        diagnostician_id=req.diagnostician_id,
        modality=req.modality,
        max_count=req.max_count,
        is_active=req.is_active
    )

@router.put('/admin/advanced/modality-quotas/{rule_id}', response_model=ModalityQuotaResponse)
async def edit_modality_quota(rule_id: int, req: ModalityQuotaUpdate, _=Depends(_require_admin)):
    result = cfg_db.update_modality_quota(rule_id, req.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail='Rule not found')
    return result

@router.delete('/admin/advanced/modality-quotas/{rule_id}')
async def remove_modality_quota(rule_id: int, _=Depends(_require_admin)):
    success = cfg_db.delete_modality_quota(rule_id)
    if not success:
        raise HTTPException(status_code=404, detail='Rule not found')
    return {'success': True}

# ── Scoring System Weights ──────────────────────────────────────────────────────────

from fastapi import Body

@router.get("/assignments/weights")
def get_weights():
    """Retrieve dynamic scoring weights from the DB."""
    from diagflow.db.diagflow_db import get_system_weights
    return get_system_weights()

@router.put("/assignments/weights")
def update_weights(weights: dict = Body(...)):
    """Update dynamic scoring weights."""
    from diagflow.db.diagflow_db import update_system_weights
    import math
    
    # Calculate sum of maximum points from each category
    max_pts = (
        float(weights.get("pts_partnership", 0)) +
        float(weights.get("pts_history", 0)) +
        float(weights.get("pts_skills_pref", 0)) +
        float(weights.get("pts_lab_pref", 0)) +
        float(weights.get("pts_capacity", 0))
    )
    
    if not math.isclose(max_pts, 1.0, abs_tol=0.01):
        raise HTTPException(status_code=400, detail=f"Το άθροισμα των μέγιστων πόντων πρέπει να είναι ακριβώς 100%. (Βρέθηκε {max_pts*100:.1f}%)")
        
    updated = update_system_weights(weights)
    return {"message": "Τα βάρη αποθηκεύτηκαν επιτυχώς", "weights": updated}
