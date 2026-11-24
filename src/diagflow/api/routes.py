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
from typing import Any, Literal
import asyncio
import hashlib
import hmac
import math
import secrets
import sqlite3
import sys
import threading
import time

import bcrypt
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError as SAIntegrityError
import structlog

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
    UnassignRequest,
    BulkUnassignRequest,
    _validate_iso_date_str,
)
from diagflow.engine.filters import ExamContext
from diagflow.engine.pipeline import AssignmentSuggestion
from diagflow.services.assignment import (
    AssignmentService,
    _is_pamakristos_row,
    get_exam_details_cache_snapshot,
)
from diagflow.services.diagnostician import DiagnosticianService
from diagflow.services.pamakristos import PamakristosScheduler
from diagflow.services.slis_sync import normalize_modality
import diagflow.db.diagflow_db as cfg_db

logger = structlog.get_logger()

router = APIRouter()

# ── Thread-safe route state lock ──
_route_state_lock = threading.RLock()

# ── In-memory suggestion cache (bounded, for confirm/override flow) ──
_SUGGESTION_CACHE_MAX = 2000
_suggestion_cache: dict = {}

# ── Session suggestion counter — tracks virtual suggestions per
#    exam_id -> (diag_id, exam_date_str, normalized_modality)
#    so both daily total AND modality quotas work across batch suggestions.
_session_suggestions_by_exam: dict[str, tuple[int, str, str]] = {}


def _get_session_virtual_counts(
    diag_id: int,
    exam_date_str: str,
    exclude_exam_id: str | None = None,
) -> tuple[int, int, int]:
    """Return (total, mri_or_mra, ct) pending virtual suggestions for a doctor on a date."""
    excl = str(exclude_exam_id) if exclude_exam_id is not None else None
    total = 0
    mri = 0
    ct = 0
    with _route_state_lock:
        items = list(_session_suggestions_by_exam.items())
    for eid, entry in items:
        did = entry[0]
        dt_s = entry[1]
        mod = entry[2] if len(entry) >= 3 else ""
        if did == diag_id and dt_s == exam_date_str and (excl is None or eid != excl):
            total += 1
            if mod == "CT":
                ct += 1
            elif mod in ("MRI", "MRA"):
                mri += 1
    return total, mri, ct


def _get_session_virtual_count(
    diag_id: int,
    exam_date_str: str,
    exclude_exam_id: str | None = None,
) -> int:
    """Count pending in-session virtual suggestions for a diagnostician on a specific exam date."""
    return _get_session_virtual_counts(diag_id, exam_date_str, exclude_exam_id=exclude_exam_id)[0]


def _store_suggestion_cache(exam_id: str, suggestion: AssignmentSuggestion) -> None:
    with _route_state_lock:
        if len(_suggestion_cache) >= _SUGGESTION_CACHE_MAX:
            for old_k in list(_suggestion_cache.keys())[: _SUGGESTION_CACHE_MAX // 5]:
                _suggestion_cache.pop(old_k, None)
        _suggestion_cache[exam_id] = suggestion
        _suggestion_cache[str(exam_id)] = suggestion


def _get_cached_suggestion(exam_id: str | int) -> AssignmentSuggestion | None:
    with _route_state_lock:
        s = _suggestion_cache.get(str(exam_id))
        if s is None and str(exam_id).isdigit():
            s = _suggestion_cache.get(int(exam_id))
        return s


def _pop_cached_suggestion(exam_id: str | int) -> None:
    with _route_state_lock:
        _suggestion_cache.pop(str(exam_id), None)
        if str(exam_id).isdigit():
            _suggestion_cache.pop(int(exam_id), None)


def _clear_session_suggestion(exam_id: str | int) -> None:
    """Remove an exam from virtual session suggestion tracking (e.g. after confirm/override/unassign)."""
    with _route_state_lock:
        _session_suggestions_by_exam.pop(str(exam_id), None)


def _parse_exam_date(raw_val: Any) -> date | None:
    """Parse an exam visitdate/request_date into a date object, or None if absent/invalid."""
    norm = cfg_db._normalize_date_str(raw_val)
    if norm:
        try:
            return date.fromisoformat(norm)
        except ValueError:
            return None
    return None


# ── Admin session & rate limit stores (protected by _route_state_lock) ──
_ADMIN_SESSIONS_MAX = 200
_MIN_PASSWORD_LEN = 8
_admin_sessions: dict[str, dict] = {}
_failed_login_attempts: dict[str, list[float]] = {}


def _prune_expired_sessions() -> None:
    now = time.time()
    with _route_state_lock:
        expired = [tok for tok, s in _admin_sessions.items() if s.get("expires_at", 0) <= now]
        for tok in expired:
            _admin_sessions.pop(tok, None)


def _revoke_user_sessions(user_id: int, keep_token: str | None = None) -> None:
    """Immediately revoke active admin tokens for a user (on disable/delete/role or password change)."""
    with _route_state_lock:
        to_remove = [
            tok for tok, s in _admin_sessions.items()
            if s.get("id") == user_id and (keep_token is None or tok != keep_token)
        ]
        for tok in to_remove:
            _admin_sessions.pop(tok, None)


def _is_integrity_error(exc: Exception) -> bool:
    return isinstance(exc, (sqlite3.IntegrityError, SAIntegrityError))


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
    """Dependency: require a valid, non-expired admin token for an active user."""
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Απαιτείται σύνδεση διαχειριστή")

    now = time.time()
    with _route_state_lock:
        session = _admin_sessions.get(x_admin_token)
        if not session:
            raise HTTPException(status_code=401, detail="Απαιτείται σύνδεση διαχειριστή")
        if "expires_at" in session and session["expires_at"] <= now:
            _admin_sessions.pop(x_admin_token, None)
            raise HTTPException(status_code=401, detail="Η συνεδρία έληξε. Παρακαλώ συνδεθείτε ξανά.")
        session_copy = dict(session)
        session_copy["_token"] = x_admin_token

    # Re-verify account is still active and role is current in DB
    db_user = cfg_db.get_admin_user_by_id(session_copy["id"])
    if not db_user or not db_user.get("is_active", 1):
        _revoke_user_sessions(session_copy["id"])
        raise HTTPException(status_code=401, detail="Η συνεδρία δεν είναι πλέον έγκυρη")

    # Sync live role & username and slide TTL forward
    new_exp = now + (settings.admin_session_ttl_minutes * 60)
    with _route_state_lock:
        if x_admin_token in _admin_sessions:
            _admin_sessions[x_admin_token]["role"] = db_user["role"]
            _admin_sessions[x_admin_token]["username"] = db_user["username"]
            _admin_sessions[x_admin_token]["expires_at"] = new_exp
    session_copy["role"] = db_user["role"]
    session_copy["username"] = db_user["username"]
    return session_copy


def _require_it_support(session: dict = Depends(_require_admin)):
    """Dependency: require it_support role."""
    if session.get("role") != "it_support":
        raise HTTPException(status_code=403, detail="Απαιτούνται δικαιώματα IT support")
    return session


@router.post("/admin/auth/login", response_model=AdminLoginResponse)
async def admin_login(request: AdminLoginRequest, raw_request: Request):
    """Authenticate admin user with rate limiting and non-blocking bcrypt verification."""
    client_ip = raw_request.client.host if raw_request.client else "unknown"
    now = time.time()

    with _route_state_lock:
        attempts = [t for t in _failed_login_attempts.get(client_ip, []) if now - t < 60.0]
        if attempts:
            _failed_login_attempts[client_ip] = attempts
        else:
            _failed_login_attempts.pop(client_ip, None)

        if len(attempts) >= 5:
            raise HTTPException(
                status_code=429,
                detail="Πολλές αποτυχημένες προσπάθειες. Παρακαλώ περιμένετε 1 λεπτό."
            )

    def _verify_credentials():
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
            try:
                bcrypt.checkpw(password_bytes, b"$2b$12$0qxEPV2WtZ00AhsmOgAbJOQuiessOk/m5jq4x55CB/c680fNiW13i")
            except Exception:
                pass
        return user, username_valid, password_valid

    user, username_valid, password_valid = await asyncio.to_thread(_verify_credentials)

    if not (username_valid and password_valid):
        with _route_state_lock:
            _failed_login_attempts.setdefault(client_ip, []).append(now)
        await asyncio.sleep(1.0)
        raise HTTPException(status_code=401, detail="Λάθος στοιχεία σύνδεσης")

    if user and not user.get("is_active", 1):
        raise HTTPException(status_code=403, detail="Ο λογαριασμός σας έχει απενεργοποιηθεί")

    _prune_expired_sessions()
    token = secrets.token_hex(24)
    expires_at = time.time() + (settings.admin_session_ttl_minutes * 60)
    with _route_state_lock:
        _failed_login_attempts.pop(client_ip, None)
        if len(_admin_sessions) >= _ADMIN_SESSIONS_MAX:
            oldest_tok = min(_admin_sessions, key=lambda t: _admin_sessions[t].get("expires_at", 0))
            _admin_sessions.pop(oldest_tok, None)
        _admin_sessions[token] = {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "expires_at": expires_at,
        }
    return AdminLoginResponse(token=token, username=user["username"], role=user["role"])


@router.post("/admin/auth/logout")
def admin_logout(x_admin_token: str = Header(default="")):
    """Server-side logout: immediately invalidates the provided admin token."""
    if x_admin_token:
        with _route_state_lock:
            _admin_sessions.pop(x_admin_token, None)
    return {"status": "ok"}


@router.post("/admin/auth/change-credentials", response_model=AdminChangeCredentialsResponse)
def change_admin_credentials(
    req: AdminChangeCredentialsRequest,
    session: dict = Depends(_require_admin),
):
    """Update admin username and/or password. Enforces min password length and revokes other sessions."""
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

    new_pass = req.new_password if req.new_password and req.new_password.strip() else None
    if new_pass is not None and len(new_pass) < _MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Ο νέος κωδικός πρόσβασης πρέπει να έχει τουλάχιστον {_MIN_PASSWORD_LEN} χαρακτήρες",
        )

    new_hash = (
        bcrypt.hashpw(new_pass.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()
        if new_pass
        else None
    )
    new_user = req.new_username.strip() if req.new_username and req.new_username.strip() else None

    if not new_user and not new_hash:
        raise HTTPException(status_code=400, detail="Δεν δόθηκαν νέα στοιχεία προς ενημέρωση")

    try:
        updated_user = cfg_db.update_admin_user(user["id"], username=new_user, password_hash=new_hash)
    except Exception as exc:
        if _is_integrity_error(exc):
            raise HTTPException(status_code=409, detail="Το όνομα χρήστη υπάρχει ήδη") from exc
        raise

    if not updated_user:
        raise HTTPException(status_code=500, detail="Αποτυχία ενημέρωσης")

    # Revoke any other active tokens for this user when credentials change
    current_token = session.get("_token")
    if new_hash:
        _revoke_user_sessions(user["id"], keep_token=current_token)
    if new_user and current_token:
        with _route_state_lock:
            if current_token in _admin_sessions:
                _admin_sessions[current_token]["username"] = updated_user["username"]

    return AdminChangeCredentialsResponse(
        message="Τα στοιχεία σύνδεσης ενημερώθηκαν επιτυχώς",
        username=updated_user["username"]
    )


# ─────────────────────────────────────────────────────
#  Admin — Users Management (it_support only)
# ─────────────────────────────────────────────────────

class AdminUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=_MIN_PASSWORD_LEN)
    role: Literal["admin", "it_support"] = "admin"


class AdminUserUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=100)
    password: str | None = None
    role: Literal["admin", "it_support"] | None = None
    is_active: bool | None = None


@router.get("/admin/users")
def get_admin_users(session: dict = Depends(_require_it_support)):
    users = cfg_db.get_all_admin_users()
    for u in users:
        u.pop("password_hash", None)
    return users


@router.post("/admin/users")
def create_admin_user(req: AdminUserCreateRequest, session: dict = Depends(_require_it_support)):
    clean_username = req.username.strip()
    if not clean_username:
        raise HTTPException(status_code=400, detail="Απαιτείται όνομα χρήστη")
    existing = cfg_db.get_admin_user_by_username(clean_username)
    if existing:
        raise HTTPException(status_code=400, detail="Το όνομα χρήστη υπάρχει ήδη")
    new_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()
    try:
        user = cfg_db.create_admin_user(clean_username, new_hash, req.role)
    except Exception as exc:
        if _is_integrity_error(exc):
            raise HTTPException(status_code=409, detail="Το όνομα χρήστη υπάρχει ήδη") from exc
        raise
    user.pop("password_hash", None)
    return user


@router.put("/admin/users/{user_id}")
def update_admin_user(user_id: int, req: AdminUserUpdateRequest, session: dict = Depends(_require_it_support)):
    new_hash = None
    if req.password and req.password.strip():
        if len(req.password) < _MIN_PASSWORD_LEN:
            raise HTTPException(
                status_code=400,
                detail=f"Ο κωδικός πρόσβασης πρέπει να έχει τουλάχιστον {_MIN_PASSWORD_LEN} χαρακτήρες",
            )
        new_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()

    try:
        updated = cfg_db.update_admin_user(
            user_id,
            username=req.username.strip() if req.username else None,
            password_hash=new_hash,
            role=req.role,
            is_active=req.is_active
        )
    except Exception as exc:
        if _is_integrity_error(exc):
            raise HTTPException(status_code=409, detail="Το όνομα χρήστη υπάρχει ήδη") from exc
        raise

    if not updated:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")

    # Revoke active sessions if password, role, or active flag changed
    if new_hash is not None or req.role is not None or req.is_active is False:
        _revoke_user_sessions(user_id)

    updated.pop("password_hash", None)
    return updated


@router.post("/admin/users/{user_id}/reset")
def reset_admin_user(user_id: int, session: dict = Depends(_require_it_support)):
    """Reset a user's password to a freshly generated temporary password without clobbering username."""
    target_user = cfg_db.get_admin_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")
    if target_user["role"] == "it_support":
        raise HTTPException(status_code=400, detail="Δεν επιτρέπεται η επαναφορά του it_support")

    temp_password = secrets.token_urlsafe(9)
    new_hash = bcrypt.hashpw(temp_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()
    updated = cfg_db.update_admin_user(user_id, password_hash=new_hash)
    if not updated:
        raise HTTPException(status_code=500, detail="Αποτυχία επαναφοράς")

    _revoke_user_sessions(user_id)
    return {
        "message": f"Ο κωδικός για τον χρήστη '{target_user['username']}' επαναφέρθηκε. Προσωρινός κωδικός: {temp_password}",
        "username": target_user["username"],
        "temporary_password": temp_password,
    }


@router.post("/admin/users/{user_id}/toggle")
def toggle_admin_user(user_id: int, session: dict = Depends(_require_it_support)):
    target_user = cfg_db.get_admin_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")
    if target_user["role"] == "it_support":
        raise HTTPException(status_code=400, detail="Δεν επιτρέπεται η αλλαγή του it_support")

    new_active = not bool(target_user["is_active"])
    updated = cfg_db.update_admin_user(user_id, is_active=new_active)
    if not updated:
        raise HTTPException(status_code=500, detail="Αποτυχία ενημέρωσης")
    if not new_active:
        _revoke_user_sessions(user_id)
    return {"message": "Η κατάσταση του χρήστη ενημερώθηκε", "is_active": updated["is_active"]}


@router.delete("/admin/users/{user_id}")
def delete_admin_user(user_id: int, session: dict = Depends(_require_it_support)):
    if user_id == session["id"]:
        raise HTTPException(status_code=400, detail="Δεν μπορείτε να διαγράψετε τον εαυτό σας")
    if not cfg_db.delete_admin_user(user_id):
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")
    _revoke_user_sessions(user_id)
    return {"status": "ok"}


# ─────────────────────────────────────────────────────
#  Exams
# ─────────────────────────────────────────────────────

@router.get("/exams/pending")
def get_pending_exams(
    svc: AssignmentService = Depends(get_assignment_service),
):
    """Fetch all pending (unassigned) exams from Slis / mock DB."""
    return svc.get_pending_exams()


@router.get("/exams/assigned")
def get_assigned_exams(
    svc: AssignmentService = Depends(get_assignment_service),
):
    """Fetch assigned exams from Slis / mock DB."""
    return svc.get_assigned_exams()


# ─────────────────────────────────────────────────────
#  Assignment Engine
# ─────────────────────────────────────────────────────


class SuggestBatchRequest(BaseModel):
    exam_ids: list[str]


def _build_exam_context(exam_data: dict) -> tuple[ExamContext, date | None]:
    """Build an ExamContext and parsed request_date from a standardized exam dict."""
    raw_exam_date = exam_data.get("visitdate") or exam_data.get("request_date")
    parsed_req_date = _parse_exam_date(raw_exam_date)
    ctx = ExamContext(
        exam_id=str(exam_data["exam_id"]),
        patient_id=str(exam_data.get("patient_id") or ""),
        patient_name=exam_data.get("patient_name") or "",
        age=exam_data.get("age"),
        modality=normalize_modality(exam_data.get("modality") or exam_data.get("category")),
        body_part=exam_data.get("body_part") or "",
        exam_code=str(exam_data.get("examnumcode") or ""),
        exam_name=exam_data.get("examname") or "",
        lab_id=str(exam_data.get("lab_id") or ""),
        lab_name=exam_data.get("lab_name") or "",
        issuing_doctor_id=str(exam_data.get("issuing_doctor_id") or ""),
        issuing_doctor_name=exam_data.get("issuing_doctor_name") or "",
        comments=exam_data.get("comments") or "",
        is_pamakristos=_is_pamakristos_row(exam_data),
        oldpers=exam_data.get("oldpers"),
        request_date=parsed_req_date,
        extracode=str(exam_data.get("extracode") or ""),
    )
    return ctx, parsed_req_date


async def _generate_suggestion_for_exam(
    exam_data: dict,
    all_exams: list[dict],
    assign_svc: AssignmentService,
    diag_svc: DiagnosticianService,
    preloaded_candidates_map: dict[str, list] | None = None,
    preloaded_config: dict | None = None,
) -> AssignmentSuggestion | None:
    """Core suggestion generator with multi-exam order alignment and modality-aware virtual workload tracking."""
    import copy

    exam, parsed_req_date = _build_exam_context(exam_data)
    exam_date_key = (parsed_req_date or date.today()).isoformat()

    if preloaded_candidates_map is not None and str(exam.exam_id) in preloaded_candidates_map:
        candidates = [copy.copy(c) for c in preloaded_candidates_map[str(exam.exam_id)]]
    else:
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
            exam_date=parsed_req_date,
        )

    # Apply date-scoped & modality-aware session virtual workload (excluding this exam itself)
    for c in candidates:
        v_tot, v_mri, v_ct = _get_session_virtual_counts(c.id, exam_date_key, exclude_exam_id=exam.exam_id)
        c.current_day_count += v_tot
        c.current_day_mri_count += v_mri
        c.current_day_ct_count += v_ct

    cfg = preloaded_config or {}

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
            cached = _get_cached_suggestion(e_item_id)
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
                passed_target, _ = apply_hard_filters(
                    [target_cand],
                    exam,
                    exclusive_rules=cfg.get("exclusive_rules"),
                    modality_quotas=cfg.get("modality_quotas"),
                    comment_rule_enabled=cfg.get("comment_rule_enabled"),
                )
                if passed_target:
                    best_cand_id = target_cand.id

        cand_info = {}
        if not best_cand_id:
            order_contexts = []
            for e_dict in order_exams:
                e_ctx, parsed_e_date = _build_exam_context(e_dict)
                e_date_key = (parsed_e_date or date.today()).isoformat()
                if preloaded_candidates_map is not None and str(e_ctx.exam_id) in preloaded_candidates_map:
                    e_cands = [copy.copy(c) for c in preloaded_candidates_map[str(e_ctx.exam_id)]]
                else:
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
                        exam_date=parsed_e_date,
                    )
                for c in e_cands:
                    vt, vm, vc = _get_session_virtual_counts(c.id, e_date_key, exclude_exam_id=e_ctx.exam_id)
                    c.current_day_count += vt
                    c.current_day_mri_count += vm
                    c.current_day_ct_count += vc
                    cand_info[c.id] = c
                order_contexts.append((e_ctx, e_cands))

            cand_totals = {}
            cand_eligible_all = {}
            for ex_ctx, cands in order_contexts:
                passed, _ = apply_hard_filters(
                    cands,
                    ex_ctx,
                    exclusive_rules=cfg.get("exclusive_rules"),
                    modality_quotas=cfg.get("modality_quotas"),
                    comment_rule_enabled=cfg.get("comment_rule_enabled"),
                )
                passed_ids = {p.id for p in passed}
                for c in cands:
                    if c.id not in cand_eligible_all:
                        cand_eligible_all[c.id] = True
                    if c.id not in passed_ids:
                        cand_eligible_all[c.id] = False
                if passed:
                    scored = score_all_candidates(passed, ex_ctx, weights=cfg.get("weights"))
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

        suggestion = await assign_svc.suggest_assignment(exam, candidates, preloaded_config=preloaded_config)
        if suggestion and best_cand_id:
            best_cand = next((c for c in candidates if c.id == best_cand_id), cand_info.get(best_cand_id))
            if best_cand and suggestion.suggested_diagnostician_id != best_cand_id:
                # Recompute score breakdown & alternatives for the aligned diagnostician so UI metadata stays accurate
                passed_cur, filter_res_cur = apply_hard_filters(
                    candidates,
                    exam,
                    exclusive_rules=cfg.get("exclusive_rules"),
                    modality_quotas=cfg.get("modality_quotas"),
                    comment_rule_enabled=cfg.get("comment_rule_enabled"),
                )
                scored_cur = score_all_candidates(passed_cur, exam, weights=cfg.get("weights")) if passed_cur else []
                aligned_score = next((s for s in scored_cur if s.diagnostician_id == best_cand_id), None)

                suggestion.suggested_diagnostician_id = best_cand_id
                suggestion.suggested_diagnostician_name = best_cand.name
                if aligned_score:
                    suggestion.confidence_score = round(aligned_score.total_score, 3)
                    suggestion.score_breakdown = [
                        {
                            "rule": comp.rule_name,
                            "display_name": comp.display_name,
                            "raw_score": round(comp.raw_score, 3),
                            "weight": comp.weight,
                            "weighted_score": round(comp.weighted_score, 3),
                            "explanation": comp.explanation,
                        }
                        for comp in aligned_score.components
                    ]
                    suggestion.rules_fired = [
                        comp.rule_name for comp in aligned_score.components if comp.weighted_score > 0
                    ]
                suggestion.alternatives = assign_svc.pipeline._build_alternatives(
                    best_cand_id,
                    scored_cur,
                    candidates,
                    filter_res_cur,
                )
                if "Multi-exam Order Alignment" not in suggestion.rules_fired:
                    suggestion.rules_fired.insert(0, "Multi-exam Order Alignment")
    else:
        suggestion = await assign_svc.suggest_assignment(exam, candidates, preloaded_config=preloaded_config)

    if suggestion:
        if suggestion.suggested_diagnostician_id:
            diag_id = suggestion.suggested_diagnostician_id
            with _route_state_lock:
                _session_suggestions_by_exam[str(exam.exam_id)] = (diag_id, exam_date_key, exam.modality.upper())

        _store_suggestion_cache(str(exam.exam_id), suggestion)

    return suggestion


@router.post("/assignments/suggest-batch")
async def suggest_batch_assignments(
    request: SuggestBatchRequest,
    assign_svc: AssignmentService = Depends(get_assignment_service),
    diag_svc: DiagnosticianService = Depends(get_diagnostician_service),
):
    """Generate assignment suggestions for multiple exams in a single ultra-fast non-blocking pass."""
    pending = await asyncio.to_thread(assign_svc.get_pending_exams)
    assigned = await asyncio.to_thread(assign_svc.get_assigned_exams)
    all_exams = pending + assigned
    exams_map = {str(e["exam_id"]): e for e in all_exams}

    # Clear prior virtual suggestions for exams being re-evaluated in this batch
    for exam_id_str in request.exam_ids:
        _clear_session_suggestion(exam_id_str)

    # Pre-load candidates and rule/weight configs ONCE for the entire batch (eliminates N+1 DB queries)
    batch_exam_dicts: dict[str, dict] = {}
    target_order_keys: set[tuple[str, str]] = set()
    for exam_id_str in request.exam_ids:
        ed = exams_map.get(exam_id_str)
        if ed:
            batch_exam_dicts[str(ed["exam_id"])] = ed
            if ed.get("extracode") and ed.get("patient_id"):
                target_order_keys.add((str(ed["patient_id"]), str(ed["extracode"])))

    # Include multi-exam order siblings so order alignment also hits the pre-loaded batch map
    if target_order_keys:
        for e in all_exams:
            if e.get("extracode") and e.get("patient_id"):
                if (str(e["patient_id"]), str(e["extracode"])) in target_order_keys:
                    batch_exam_dicts.setdefault(str(e["exam_id"]), e)

    batch_contexts = [_build_exam_context(ed)[0] for ed in batch_exam_dicts.values()]
    preloaded_candidates_map = await diag_svc.get_candidates_for_exams_batch(batch_contexts) if batch_contexts else {}

    def _load_batch_cfg():
        return {
            "exclusive_rules": cfg_db.get_all_exclusive_lab_rules(),
            "modality_quotas": cfg_db.get_all_modality_quotas(),
            "comment_rule_enabled": cfg_db.get_comment_auto_assign_enabled(),
            "weights": cfg_db.get_system_weights(),
        }

    preloaded_config = await asyncio.to_thread(_load_batch_cfg)

    results = {}
    for exam_id_str in request.exam_ids:
        exam_data = exams_map.get(exam_id_str)
        if not exam_data:
            continue

        suggestion = await _generate_suggestion_for_exam(
            exam_data,
            all_exams,
            assign_svc,
            diag_svc,
            preloaded_candidates_map=preloaded_candidates_map,
            preloaded_config=preloaded_config,
        )
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
    pending = await asyncio.to_thread(assign_svc.get_pending_exams)
    assigned = await asyncio.to_thread(assign_svc.get_assigned_exams)
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
    if request.diagnostician_id <= 0:
        raise HTTPException(status_code=422, detail="Μη έγκυρος κωδικός διαγνώστη")
    diag = await asyncio.to_thread(cfg_db.get_diagnostician, request.diagnostician_id)
    if not diag:
        raise HTTPException(status_code=404, detail=f"Ο διαγνώστης {request.diagnostician_id} δεν βρέθηκε")

    suggestion = _get_cached_suggestion(request.exam_id)
    if not suggestion:
        suggestion = AssignmentSuggestion(
            exam_id=str(request.exam_id),
            patient_id="",
            exam_summary="",
            suggested_diagnostician_id=request.diagnostician_id,
            suggested_diagnostician_name=diag["name"],
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
        diagnostician_name=diag["name"],
        suggestion=suggestion,
    )
    _pop_cached_suggestion(request.exam_id)
    _clear_session_suggestion(request.exam_id)

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
    if request.override_diagnostician_id <= 0:
        raise HTTPException(status_code=422, detail="Μη έγκυρος κωδικός διαγνώστη")
    diag = await asyncio.to_thread(cfg_db.get_diagnostician, request.override_diagnostician_id)
    if not diag:
        raise HTTPException(status_code=404, detail=f"Ο διαγνώστης {request.override_diagnostician_id} δεν βρέθηκε")

    suggestion = _get_cached_suggestion(request.exam_id)
    if not suggestion:
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
    _pop_cached_suggestion(request.exam_id)
    _clear_session_suggestion(request.exam_id)

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

    from diagflow.engine.filters import apply_hard_filters, get_elimination_reason

    pending = await asyncio.to_thread(assign_svc.get_pending_exams)
    assigned = await asyncio.to_thread(assign_svc.get_assigned_exams)
    all_exams = pending + assigned
    req_ids = {str(x) for x in request.exam_ids}
    selected_exams = [e for e in all_exams if str(e.get("exam_id")) in req_ids or (e.get("exammoreid") and str(e.get("exammoreid")) in req_ids)]

    found_eids = {str(e.get("exam_id")) for e in selected_exams} | {str(e.get("exammoreid")) for e in selected_exams if e.get("exammoreid")}
    missing_ids = list(req_ids - found_eids)

    # First resolve missing exams from thread-safe _exam_details_cache
    if missing_ids:
        details_snapshot = get_exam_details_cache_snapshot()
        still_missing = []
        for mid in missing_ids:
            c_data = details_snapshot.get(int(mid)) if str(mid).isdigit() else None
            if c_data:
                selected_exams.append({
                    "exam_id": str(c_data.get("exammoreid") or mid),
                    "patient_id": str(c_data.get("demogid") or ""),
                    "patient_name": str(c_data.get("patient_name") or ""),
                    "modality": normalize_modality(c_data.get("category") or c_data.get("modality") or ""),
                    "body_part": "",
                    "examnumcode": str(c_data.get("examnumcode") or ""),
                    "examname": str(c_data.get("examname") or ""),
                    "lab_id": str(c_data.get("labcodeid") or ""),
                    "lab_name": str(c_data.get("lab_name") or ""),
                    "issuing_doctor_id": str(c_data.get("wcode") or ""),
                    "issuing_doctor_name": str(c_data.get("wname") or ""),
                    "comments": str(c_data.get("notes") or ""),
                    "visitdate": cfg_db._normalize_date_str(c_data.get("visitdate")) or "",
                    "oldpers": c_data.get("oldpers"),
                })
            else:
                still_missing.append(mid)
        missing_ids = still_missing

    if missing_ids and settings.use_mock_slis_db:
        def _load_missing_mock(mids: list[str]) -> list[dict]:
            out = []
            try:
                from diagflow.services.assignment import _get_mock_db
                con = _get_mock_db()
                for chunk in cfg_db._chunked(mids):
                    placeholders = ",".join("?" * len(chunk))
                    rows = con.execute(f"SELECT * FROM slis_exams WHERE exammoreid IN ({placeholders})", tuple(chunk)).fetchall()
                    for r in rows:
                        r_dict = dict(r)
                        out.append({
                            "exam_id": str(r_dict.get("exammoreid")),
                            "patient_id": str(r_dict.get("demogid") or r_dict.get("patientid") or ""),
                            "patient_name": f"{r_dict.get('fname', '')} {r_dict.get('lname', '')}".strip() if (r_dict.get('fname') or r_dict.get('lname')) else str(r_dict.get("patient_name") or ""),
                            "modality": normalize_modality(r_dict.get("category") or r_dict.get("modality") or ""),
                            "body_part": str(r_dict.get("bodypart") or ""),
                            "examnumcode": str(r_dict.get("examnumcode") or ""),
                            "examname": str(r_dict.get("examname") or ""),
                            "lab_id": str(r_dict.get("labcodeid") or r_dict.get("labid") or ""),
                            "lab_name": str(r_dict.get("labname") or r_dict.get("laboratoryname") or ""),
                            "issuing_doctor_id": str(r_dict.get("wcode") or r_dict.get("doctorid") or ""),
                            "issuing_doctor_name": str(r_dict.get("wname") or r_dict.get("issuing_doctor_name") or ""),
                            "comments": str(r_dict.get("notes") or r_dict.get("comments") or ""),
                            "visitdate": cfg_db._normalize_date_str(r_dict.get("visitdate")) or "",
                            "oldpers": r_dict.get("oldpers"),
                        })
                con.close()
            except Exception as ex:
                logger.warning("bulk_eligible_mock_fallback_failed", error=str(ex))
            return out

        selected_exams.extend(await asyncio.to_thread(_load_missing_mock, missing_ids))

    if not selected_exams:
        return BulkEligibleResponse(diagnosticians=[])

    # Start with all diagnosticians as eligible
    all_diags = await diag_svc.get_all_diagnosticians()
    eligible_diags = {d["id"]: d for d in all_diags}
    reasons: dict[int, str | None] = {d_id: None for d_id in eligible_diags}
    is_eligible = {d_id: True for d_id in eligible_diags}

    exam_contexts = [_build_exam_context(exam_data)[0] for exam_data in selected_exams]

    # Pre-fetch candidate evaluations and rules ONCE for the whole check
    batch_candidates = await diag_svc.get_candidates_for_exams_batch(exam_contexts)

    def _load_filter_cfg():
        return (
            cfg_db.get_all_exclusive_lab_rules(),
            cfg_db.get_all_modality_quotas(),
            cfg_db.get_comment_auto_assign_enabled(),
        )

    excl_rules, mod_quotas, comment_enabled = await asyncio.to_thread(_load_filter_cfg)

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
                exam_date=exam.request_date,
            )

        # Safe lookup via .get(c.id, False) prevents KeyError if a doctor was added mid-request
        passed, results_dict = apply_hard_filters(
            candidates=[c for c in candidates if is_eligible.get(c.id, False)],
            exam=exam,
            exclusive_rules=excl_rules,
            modality_quotas=mod_quotas,
            comment_rule_enabled=comment_enabled,
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
    assign_svc: AssignmentService = Depends(get_assignment_service),
    diag_svc: DiagnosticianService = Depends(get_diagnostician_service),
):
    """Confirm suggested assignments for multiple exams with preloaded batch fallback."""
    targets: list[tuple[str, int | None]] = []
    if request.items:
        for it in request.items:
            targets.append((str(it.exam_id), it.diagnostician_id))
    elif request.exam_ids:
        for eid in request.exam_ids:
            targets.append((str(eid), None))

    if not targets:
        return []

    all_exams_list: list[dict] = []
    all_exams_map: dict[str, dict] | None = None
    preloaded_candidates_map: dict[str, list] | None = None
    preloaded_config: dict | None = None

    results = []
    for exam_id_str, explicit_diag_id in targets:
        suggestion = _get_cached_suggestion(exam_id_str)

        diag_id_to_use = None
        if explicit_diag_id:
            diag_id_to_use = explicit_diag_id
        elif suggestion and suggestion.suggested_diagnostician_id:
            diag_id_to_use = suggestion.suggested_diagnostician_id

        if not diag_id_to_use:
            if all_exams_map is None:
                pending = await asyncio.to_thread(assign_svc.get_pending_exams)
                assigned = await asyncio.to_thread(assign_svc.get_assigned_exams)
                all_exams_list = pending + assigned
                all_exams_map = {str(e["exam_id"]): e for e in all_exams_list}
                missing_exam_dicts = [all_exams_map[eid] for eid, d in targets if not d and eid in all_exams_map]
                if missing_exam_dicts:
                    ctxs = [_build_exam_context(ed)[0] for ed in missing_exam_dicts]
                    preloaded_candidates_map = await diag_svc.get_candidates_for_exams_batch(ctxs)
                    preloaded_config = await asyncio.to_thread(lambda: {
                        "exclusive_rules": cfg_db.get_all_exclusive_lab_rules(),
                        "modality_quotas": cfg_db.get_all_modality_quotas(),
                        "comment_rule_enabled": cfg_db.get_comment_auto_assign_enabled(),
                        "weights": cfg_db.get_system_weights(),
                    })

            exam_data = all_exams_map.get(exam_id_str)
            if exam_data:
                suggestion = await _generate_suggestion_for_exam(
                    exam_data,
                    all_exams_list,
                    assign_svc,
                    diag_svc,
                    preloaded_candidates_map=preloaded_candidates_map,
                    preloaded_config=preloaded_config,
                )
                if suggestion and suggestion.suggested_diagnostician_id:
                    diag_id_to_use = suggestion.suggested_diagnostician_id

        if not diag_id_to_use:
            continue

        if not suggestion:
            suggestion = AssignmentSuggestion(
                exam_id=exam_id_str,
                patient_id="",
                exam_summary="",
                suggested_diagnostician_id=diag_id_to_use,
                suggested_diagnostician_name="",
                confidence_score=1.0,
                score_breakdown=[],
                alternatives=[],
                rules_fired=[],
                filter_results={},
                solver_status="fallback",
                pipeline_timestamp=datetime.now().isoformat(),
            )

        result = await assign_svc.confirm_assignment(
            exam_id=exam_id_str,
            diagnostician_id=diag_id_to_use,
            suggestion=suggestion,
        )
        _pop_cached_suggestion(exam_id_str)
        _clear_session_suggestion(exam_id_str)

        results.append(
            AssignmentConfirmation(
                exam_id=exam_id_str,
                diagnostician_id=diag_id_to_use,
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
    if request.override_diagnostician_id <= 0:
        raise HTTPException(status_code=422, detail="Μη έγκυρος κωδικός διαγνώστη")
    diag = await asyncio.to_thread(cfg_db.get_diagnostician, request.override_diagnostician_id)
    if not diag:
        raise HTTPException(status_code=404, detail=f"Ο διαγνώστης {request.override_diagnostician_id} δεν βρέθηκε")

    results = []
    for exam_id in request.exam_ids:
        exam_id_str = str(exam_id)
        suggestion = _get_cached_suggestion(exam_id_str)
        original_diagnostician_id = suggestion.suggested_diagnostician_id if suggestion else 0

        result = await svc.override_assignment(
            exam_id=exam_id_str,
            original_diagnostician_id=original_diagnostician_id,
            override_diagnostician_id=request.override_diagnostician_id,
            reason=request.reason,
            suggestion=suggestion,
        )
        _pop_cached_suggestion(exam_id_str)
        _clear_session_suggestion(exam_id_str)

        results.append(
            AssignmentConfirmation(
                exam_id=exam_id_str,
                diagnostician_id=request.override_diagnostician_id,
                was_overridden=True,
                status="overridden",
                timestamp=result["decision_timestamp"],
            )
        )
    return results


@router.delete("/assignments/{exam_id}")
def unassign_exam_by_id(exam_id: str):
    """Remove an exam from local staged assignments without affecting Slis."""
    try:
        eid_int = int(exam_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Μη έγκυρος κωδικός εξέτασης") from exc
    try:
        success = cfg_db.delete_local_assignment(eid_int)
        _clear_session_suggestion(exam_id)
        return {"success": success, "exam_id": exam_id}
    except Exception as e:
        logger.error("unassign_exam_by_id_error", exam_id=exam_id, error=str(e))
        raise HTTPException(status_code=500, detail="Αποτυχία αναίρεσης ανάθεσης") from e


@router.post("/assignments/unassign")
def unassign_exam(request: UnassignRequest):
    """Remove an exam from local staged assignments without affecting Slis."""
    try:
        eid_int = int(request.exam_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Μη έγκυρος κωδικός εξέτασης") from exc
    try:
        success = cfg_db.delete_local_assignment(eid_int)
        _clear_session_suggestion(request.exam_id)
        return {"success": success, "exam_id": str(request.exam_id)}
    except Exception as e:
        logger.error("unassign_exam_error", exam_id=request.exam_id, error=str(e))
        raise HTTPException(status_code=500, detail="Αποτυχία αναίρεσης ανάθεσης") from e


@router.post("/assignments/bulk-unassign")
def bulk_unassign_exams(request: BulkUnassignRequest):
    """Remove multiple exams from local staged assignments without affecting Slis."""
    unassigned = []
    failed_ids = []
    for eid in request.exam_ids:
        try:
            eid_int = int(eid)
            if cfg_db.delete_local_assignment(eid_int):
                unassigned.append(eid_int)
            _clear_session_suggestion(eid)
        except Exception as e:
            logger.warning("bulk_unassign_item_failed", exam_id=eid, error=str(e))
            failed_ids.append(str(eid))
    return {
        "success": len(failed_ids) == 0,
        "unassigned_count": len(unassigned),
        "unassigned_ids": unassigned,
        "failed_ids": failed_ids,
    }


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
    return cfg_db.get_all_doctors(q=q, skip=0, limit=max(0, min(limit, 500)))


@router.get("/dashboard")
def get_dashboard(date: str | None = None):
    """Get assigned exams per diagnostician for a given date (defaults to today)."""
    if date:
        norm_date = cfg_db._normalize_date_str(date)
        if not norm_date:
            raise HTTPException(status_code=422, detail="Μη έγκυρη μορφή ημερομηνίας (YYYY-MM-DD)")
        date = norm_date

    dashboard_data = cfg_db.get_dashboard_data(target_date=date)

    try:
        details_snapshot = get_exam_details_cache_snapshot()
        dict_entries = cfg_db.get_exam_dictionary()
        exam_dict_map = {str(e["code"]).strip(): e["name"] for e in dict_entries if e.get("code") and e.get("name")}
        local_assigns = cfg_db.get_all_local_assignments()

        # Batch fetch any missing exam names from mock_slis.db in ONE query (eliminates N+1 connection loop)
        mock_names_map: dict[int, str] = {}
        if settings.use_mock_slis_db:
            missing_for_mock: list[int] = []
            for d in dashboard_data:
                for eid in d.get("assigned_exam_ids", []):
                    eid_int = int(eid)
                    c_info = details_snapshot.get(eid_int) or {}
                    if not c_info.get("examname"):
                        missing_for_mock.append(eid_int)
            if missing_for_mock:
                from diagflow.services.assignment import _get_mock_db
                con = _get_mock_db()
                try:
                    for chunk in cfg_db._chunked(list(set(missing_for_mock))):
                        placeholders = ",".join("?" * len(chunk))
                        rows = con.execute(
                            f"SELECT exammoreid, examname, examnumcode FROM slis_exams WHERE exammoreid IN ({placeholders})",
                            tuple(chunk),
                        ).fetchall()
                        for r in rows:
                            nm = (r["examname"] or "").strip() or (
                                exam_dict_map.get(str(r["examnumcode"]).strip()) if r["examnumcode"] else ""
                            )
                            if nm:
                                mock_names_map[int(r["exammoreid"])] = nm
                finally:
                    con.close()

        for d in dashboard_data:
            d["exam_names"] = {}
            for eid in d.get("assigned_exam_ids", []):
                eid_int = int(eid)
                loc = local_assigns.get(eid_int) or {}
                c_info = details_snapshot.get(eid_int) or {}

                name = c_info.get("examname")
                if not name and c_info.get("examnumcode"):
                    name = exam_dict_map.get(str(c_info["examnumcode"]).strip())
                if not name:
                    name = mock_names_map.get(eid_int)

                if not name or name.startswith("Εξέταση ") or "Εξέταση 20" in name:
                    mod = normalize_modality(loc.get("modality") or c_info.get("modality") or "")
                    name = f"{mod} Απεικόνιση" if mod else "Απεικόνιση"

                d["exam_names"][name] = d["exam_names"].get(name, 0) + 1
    except Exception as e:
        logger.warning("dashboard_exam_names_enrichment_failed", error=str(e))

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
def get_pamakristos_weekly_schedule():
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
    _=Depends(_require_admin),
    scheduler: PamakristosScheduler = Depends(get_pamakristos_scheduler),
):
    try:
        target_date = date.fromisoformat(request.date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Μη έγκυρη ημερομηνία (YYYY-MM-DD)") from exc
    try:
        return await scheduler.set_oncall_diagnostician(target_date, request.diagnostician_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class WeeklyScheduleItem(BaseModel):
    weekday: int = Field(..., ge=0, le=6)
    diagnostician_id: int = Field(..., gt=0)


@router.get("/admin/pamakristos/weekly-schedule")
def admin_get_weekly_schedule(_=Depends(_require_admin)):
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
def admin_update_weekly_schedule(
    items: list[WeeklyScheduleItem],
    _=Depends(_require_admin),
):
    try:
        cfg_db.update_pamakristos_weekly_schedule_db([item.model_dump() for item in items])
    except Exception as exc:
        if _is_integrity_error(exc):
            raise HTTPException(status_code=400, detail="Μη έγκυρος διαγνώστης στο πρόγραμμα") from exc
        raise
    return {"status": "ok", "updated": len(items)}


# ─────────────────────────────────────────────────────
#  Admin — Diagnosticians  (diagflow.db — persistent)
# ─────────────────────────────────────────────────────

def _resolve_mock_slis_db_path() -> Path:
    p = Path(settings.mock_slis_db_path)
    if p.is_absolute():
        return p
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent.parent.parent
    return base / p


@router.get("/admin/exam-categories")
def admin_get_exam_categories(_=Depends(_require_admin)):
    items = cfg_db.get_exam_dictionary()
    if not items and settings.use_mock_slis_db:
        slis_db_path = _resolve_mock_slis_db_path()
        if slis_db_path.exists():
            with sqlite3.connect(slis_db_path, timeout=10.0) as con:
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    "SELECT DISTINCT examnumcode AS examnumcode, examname AS name, category FROM slis_exams "
                    "WHERE examnumcode IS NOT NULL AND examnumcode != ''"
                ).fetchall()
                batch_entries = [
                    (
                        str(r["examnumcode"]).strip(),
                        str(r["name"] or "").strip(),
                        normalize_modality(r["category"]),
                    )
                    for r in rows
                ]
                cfg_db.upsert_exam_dictionary_batch(batch_entries)
            items = cfg_db.get_exam_dictionary()
    return items


class DiagnosticianCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    active: bool = True
    can_ct: bool = True
    can_mri: bool = True
    quota_monday: int = Field(default=15, ge=0)
    quota_tuesday: int = Field(default=15, ge=0)
    quota_wednesday: int = Field(default=15, ge=0)
    quota_thursday: int = Field(default=15, ge=0)
    quota_friday: int = Field(default=15, ge=0)
    quota_saturday: int = Field(default=0, ge=0)
    quota_sunday: int = Field(default=0, ge=0)
    preferred_lab_id: int | None = None

    @field_validator("active", "can_ct", "can_mri", mode="before")
    @classmethod
    def coerce_int_bool(cls, v: Any) -> Any:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return bool(v)
        return v


@router.get("/admin/diagnosticians")
def admin_list_diagnosticians(_=Depends(_require_admin)):
    return cfg_db.get_all_diagnosticians()


@router.post("/admin/diagnosticians/sync")
def admin_sync_diagnosticians(_=Depends(_require_admin)):
    from diagflow.services.slis_sync import sync_diagnosticians
    return sync_diagnosticians()


@router.post("/admin/doctors/sync")
def admin_sync_doctors(_=Depends(_require_admin)):
    from diagflow.services.slis_sync import sync_doctors
    return sync_doctors()


@router.post("/admin/diagnosticians")
def admin_create_diagnostician(
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
def admin_update_diagnostician(
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
def admin_delete_diagnostician(diag_id: int, _=Depends(_require_admin)):
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
def admin_list_partnerships(_=Depends(_require_admin)):
    return cfg_db.get_all_partnerships()


@router.post("/admin/partnerships")
def admin_create_partnership(
    req: PartnershipCreateRequest,
    _=Depends(_require_admin),
):
    try:
        return cfg_db.create_partnership(
            issuing_doctor_id=req.issuing_doctor_id,
            issuing_doctor_name=req.issuing_doctor_name,
            preferred_diagnostician_id=req.preferred_diagnostician_id,
            priority=req.priority,
            exclusive=req.exclusive,
            is_active=req.is_active,
        )
    except Exception as exc:
        if _is_integrity_error(exc):
            raise HTTPException(status_code=400, detail="Μη έγκυρος διαγνώστης ή διπλότυπη σύμπραξη") from exc
        raise


@router.patch("/admin/partnerships/{part_id}")
def admin_update_partnership(
    part_id: int,
    req: PartnershipUpdateRequest,
    _=Depends(_require_admin),
):
    if req.exclusive is None and req.is_active is None:
        raise HTTPException(status_code=400, detail="Δεν δόθηκαν πεδία προς ενημέρωση")
    record = cfg_db.update_partnership(
        part_id=part_id,
        exclusive=req.exclusive,
        is_active=req.is_active,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Η σύμπραξη δεν βρέθηκε")
    return record


@router.delete("/admin/partnerships/{part_id}")
def admin_delete_partnership(part_id: int, _=Depends(_require_admin)):
    if not cfg_db.delete_partnership(part_id):
        raise HTTPException(status_code=404, detail="Η σύμπραξη δεν βρέθηκε")
    return {"deleted": part_id}


# ─────────────────────────────────────────────────────
#  Admin — Doctors  (diagflow.db — persistent)
# ─────────────────────────────────────────────────────

class DoctorCreateRequest(BaseModel):
    id: str = ""
    name: str = Field(..., min_length=1, max_length=200)


@router.get("/admin/doctors")
def admin_list_doctors(
    q: str = "",
    skip: int = 0,
    limit: int = 50,
    _=Depends(_require_admin)
):
    return cfg_db.get_all_doctors(q=q, skip=max(0, skip), limit=max(0, min(limit, 500)))


@router.post("/admin/doctors")
def admin_create_doctor(req: DoctorCreateRequest, _=Depends(_require_admin)):
    doc_id = req.id.strip() if req.id and req.id.strip() else f"DR-{secrets.token_hex(4).upper()}"
    return cfg_db.upsert_doctor(doctor_id=doc_id, name=req.name.strip())


@router.delete("/admin/doctors/{doctor_id}")
def admin_delete_doctor(doctor_id: str, _=Depends(_require_admin)):
    if not cfg_db.delete_doctor(doctor_id):
        raise HTTPException(status_code=404, detail="Ο γιατρός δεν βρέθηκε")
    return {"deleted": doctor_id}


# ─────────────────────────────────────────────────────
#  Admin — Availability  (diagflow.db — persistent)
# ─────────────────────────────────────────────────────

class AvailabilitySetRequest(BaseModel):
    diagnostician_id: int = Field(..., gt=0)
    date: str
    status: Literal["available", "on_leave"] = "available"
    is_pamakristos_oncall: bool = False
    notes: str = ""

    @field_validator("date")
    @classmethod
    def validate_avail_date(cls, v: str) -> str:
        res = _validate_iso_date_str(v)
        if not res:
            raise ValueError("Μη έγκυρη ημερομηνία (YYYY-MM-DD)")
        return res


@router.get("/admin/availability")
def admin_list_availability(_=Depends(_require_admin)):
    return cfg_db.get_all_availability()


@router.post("/admin/availability")
def admin_set_availability(
    req: AvailabilitySetRequest,
    _=Depends(_require_admin),
):
    try:
        return cfg_db.upsert_availability(
            diagnostician_id=req.diagnostician_id,
            date=req.date,
            status=req.status,
            is_pamakristos_oncall=req.is_pamakristos_oncall,
            notes=req.notes,
        )
    except Exception as exc:
        if _is_integrity_error(exc):
            raise HTTPException(status_code=400, detail="Μη έγκυρος διαγνώστης") from exc
        raise


@router.delete("/admin/availability/{diagnostician_id}/{date}")
def admin_delete_availability(
    diagnostician_id: int,
    date: str,
    _=Depends(_require_admin),
):
    norm_d = cfg_db._normalize_date_str(date)
    if not norm_d:
        raise HTTPException(status_code=422, detail="Μη έγκυρη ημερομηνία (YYYY-MM-DD)")
    success = cfg_db.delete_availability(diagnostician_id, norm_d)
    return {"success": success, "diagnostician_id": diagnostician_id, "date": norm_d}


# ─────────────────────────────────────────────────────
#  Admin — Skills  (diagflow.db — persistent)
# ─────────────────────────────────────────────────────

class SkillSetRequest(BaseModel):
    diagnostician_id: int = Field(..., gt=0)
    exam_code: str = Field(..., min_length=1, max_length=50)
    is_preferred: bool = False


class SkillUpdateRequest(BaseModel):
    is_preferred: bool = False


@router.get("/admin/skills")
def admin_list_skills(
    diagnostician_id: int | None = None,
    _=Depends(_require_admin),
):
    return cfg_db.get_skills(diagnostician_id)


@router.post("/admin/skills")
def admin_set_skill(req: SkillSetRequest, _=Depends(_require_admin)):
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
        raw_cat = (matched.get("category") or "").strip()
        category = normalize_modality(raw_cat) if raw_cat else ""
        name = matched.get("name") or ""
    else:
        name = ""

    if not category:
        name_upper = name.upper()
        if "CT" in name_upper or "ΑΞΟΝ" in name_upper or code.startswith("21"):
            category = "CT"
        elif "MRA" in name_upper or "ΑΓΓΕΙΟ" in name_upper or code.startswith("228"):
            category = "MRA"
        elif "MRI" in name_upper or "ΜΑΓΝΗΤ" in name_upper:
            category = "MRI"
        elif code in ("22140", "22141"):
            category = "CT"
        elif code.startswith("22"):
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
def admin_update_skill(skill_id: int, req: SkillUpdateRequest, _=Depends(_require_admin)):
    if not cfg_db.update_skill_preference(skill_id, req.is_preferred):
        raise HTTPException(status_code=404, detail="Η δεξιότητα δεν βρέθηκε")
    DiagnosticianService.clear_cache()
    return {"id": skill_id, "is_preferred": req.is_preferred}


@router.delete("/admin/skills/{skill_id}")
def admin_delete_skill(skill_id: int, _=Depends(_require_admin)):
    if not cfg_db.delete_skill(skill_id):
        raise HTTPException(status_code=404, detail="Η δεξιότητα δεν βρέθηκε")
    DiagnosticianService.clear_cache()
    return {"deleted": skill_id}


# ─────────────────────────────────────────────────────
#  Admin — Παμμακάριστος on-call override
# ─────────────────────────────────────────────────────

class OncallSetRequest(BaseModel):
    diagnostician_id: int = Field(..., gt=0)
    date: str

    @field_validator("date")
    @classmethod
    def validate_oncall_date(cls, v: str) -> str:
        res = _validate_iso_date_str(v)
        if not res:
            raise ValueError("Μη έγκυρη ημερομηνία (YYYY-MM-DD)")
        return res


@router.get("/admin/oncall")
def admin_get_oncall(_=Depends(_require_admin)):
    today = str(date.today())
    record = cfg_db.get_oncall_diagnostician(today)
    if record:
        return record
    return {"diagnostician_id": None, "diagnostician_name": None, "date": today}


@router.post("/admin/oncall")
def admin_set_oncall(
    req: OncallSetRequest,
    _=Depends(_require_admin),
    scheduler: PamakristosScheduler = Depends(get_pamakristos_scheduler),
):
    diag = cfg_db.get_diagnostician(req.diagnostician_id)
    if not diag:
        raise HTTPException(status_code=404, detail="Ο διαγνώστης δεν βρέθηκε")
    record = cfg_db.set_pamakristos_oncall_for_date(req.date, req.diagnostician_id)
    scheduler.set_manual_override_from_admin(record)
    return record


@router.get("/admin/pamakristos/overrides")
def admin_get_pamakristos_overrides(_=Depends(_require_admin)):
    return cfg_db.get_pamakristos_manual_overrides()


@router.delete("/admin/pamakristos/overrides/{avail_id}")
def admin_delete_pamakristos_override(avail_id: int, _=Depends(_require_admin)):
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
def slis_pull():
    """
    Pull fresh exam data from Slis (or refresh the mock DB).
    Atomic cache swap inside _fetch_slis_period_rows prevents empty-cache windows during refresh.
    """
    from diagflow.services.slis_sync import pull_from_slis
    from diagflow.services.assignment import invalidate_slis_period_cache
    with _route_state_lock:
        _session_suggestions_by_exam.clear()
        _suggestion_cache.clear()
    if not settings.use_mock_slis_db:
        invalidate_slis_period_cache()
    result = pull_from_slis()
    return {
        "status": "ok",
        "pulled": result.get("pulled", 0),
        "expired": result.get("expired", 0),
        "total_pending": result.get("total_pending", 0),
    }


@router.get("/slis/status")
def slis_status():
    """Return the current Slis DB connection status and error details if any."""
    from diagflow.main import SLIS_STATUS
    return SLIS_STATUS


@router.post("/slis/push-all")
def slis_push_all():
    """Push ALL assigned-but-not-yet-synced exams to Slis in one operation."""
    from diagflow.services.slis_sync import push_all_to_slis
    return push_all_to_slis()


@router.post("/slis/push-selected")
def slis_push_selected(req: PushSelectedRequest):
    """Push a specific list of exams (by exammoreid) to Slis."""
    from diagflow.services.slis_sync import push_selected_to_slis
    return push_selected_to_slis(req.exammoreid_list)


@router.post("/slis/search")
def slis_search_exams(req: SlisSearchRequest):
    """Search exams directly in Slis (production MSSQL or mock DB) by filters."""
    from diagflow.services.slis_sync import search_slis_exams
    try:
        return search_slis_exams(
            start_date=req.start_date,
            end_date=req.end_date,
            extracode=req.extracode,
            patient_query=req.patient_query,
            doctor_query=req.doctor_query,
            diagnostician_query=req.diagnostician_query,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/slis/reassign")
def slis_reassign_exam(req: SlisReassignRequest):
    """Re-assign an exam to a new diagnostician and immediately update Slis."""
    from diagflow.services.slis_sync import push_exam_to_slis
    return push_exam_to_slis(
        exammoreid=req.exammoreid,
        diagnostician_id=req.diagnostician_id,
        diagnostician_name=req.diagnostician_name,
        force=req.force,
    )


@router.post("/admin/sync-diagnosticians")
def admin_sync_diagnosticians_legacy(_=Depends(_require_admin)):
    """Manual trigger to pull diagnosticians from Slis DB into diagflow.db."""
    from diagflow.services.slis_sync import sync_diagnosticians
    return sync_diagnosticians()


@router.post("/admin/sync-doctors")
def admin_sync_doctors_legacy(_=Depends(_require_admin)):
    """Manual trigger to pull doctors from Slis DB into diagflow.db."""
    from diagflow.services.slis_sync import sync_doctors
    return sync_doctors()

# ─────────────────────────────────────────────────────
#  Admin Advanced Options
# ─────────────────────────────────────────────────────

from diagflow.api.schemas import (
    ExamRoutingRuleCreate, ExamRoutingRuleUpdate, ExamRoutingRuleResponse,
    ExclusiveLabRuleCreate, ExclusiveLabRuleUpdate, ExclusiveLabRuleResponse,
    ModalityQuotaCreate, ModalityQuotaUpdate, ModalityQuotaResponse
)

@router.get('/admin/advanced/exam-routing-rules', response_model=list[ExamRoutingRuleResponse])
def get_exam_routing_rules(_=Depends(_require_admin)):
    return cfg_db.get_all_exam_routing_rules()

@router.post('/admin/advanced/exam-routing-rules', response_model=ExamRoutingRuleResponse)
def add_exam_routing_rule(req: ExamRoutingRuleCreate, _=Depends(_require_admin)):
    try:
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
    except Exception as exc:
        if _is_integrity_error(exc):
            raise HTTPException(status_code=400, detail="Μη έγκυρος διαγνώστης στον κανόνα") from exc
        raise

@router.put('/admin/advanced/exam-routing-rules/{rule_id}', response_model=ExamRoutingRuleResponse)
def edit_exam_routing_rule(rule_id: int, req: ExamRoutingRuleUpdate, _=Depends(_require_admin)):
    result = cfg_db.update_exam_routing_rule(rule_id, req.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail='Rule not found')
    return result

@router.delete('/admin/advanced/exam-routing-rules/{rule_id}')
def remove_exam_routing_rule(rule_id: int, _=Depends(_require_admin)):
    success = cfg_db.delete_exam_routing_rule(rule_id)
    if not success:
        raise HTTPException(status_code=404, detail='Rule not found')
    return {'success': True}

@router.get('/admin/advanced/exclusive-lab-rules', response_model=list[ExclusiveLabRuleResponse])
def get_exclusive_lab_rules(_=Depends(_require_admin)):
    return cfg_db.get_all_exclusive_lab_rules()

@router.post('/admin/advanced/exclusive-lab-rules', response_model=ExclusiveLabRuleResponse)
def add_exclusive_lab_rule(req: ExclusiveLabRuleCreate, _=Depends(_require_admin)):
    try:
        return cfg_db.create_exclusive_lab_rule(
            diagnostician_id=req.diagnostician_id,
            lab_id=req.lab_id,
            lab_name=req.lab_name or '',
            is_active=req.is_active
        )
    except Exception as exc:
        if _is_integrity_error(exc):
            raise HTTPException(status_code=400, detail="Μη έγκυρος διαγνώστης στον κανόνα") from exc
        raise

@router.put('/admin/advanced/exclusive-lab-rules/{rule_id}', response_model=ExclusiveLabRuleResponse)
def edit_exclusive_lab_rule(rule_id: int, req: ExclusiveLabRuleUpdate, _=Depends(_require_admin)):
    result = cfg_db.update_exclusive_lab_rule(rule_id, req.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail='Rule not found')
    return result

@router.delete('/admin/advanced/exclusive-lab-rules/{rule_id}')
def remove_exclusive_lab_rule(rule_id: int, _=Depends(_require_admin)):
    success = cfg_db.delete_exclusive_lab_rule(rule_id)
    if not success:
        raise HTTPException(status_code=404, detail='Rule not found')
    return {'success': True}

@router.get('/admin/advanced/modality-quotas', response_model=list[ModalityQuotaResponse])
def get_modality_quotas(_=Depends(_require_admin)):
    return cfg_db.get_all_modality_quotas()

@router.post('/admin/advanced/modality-quotas', response_model=ModalityQuotaResponse)
def add_modality_quota(req: ModalityQuotaCreate, _=Depends(_require_admin)):
    try:
        return cfg_db.create_modality_quota(
            diagnostician_id=req.diagnostician_id,
            modality=req.modality,
            max_count=req.max_count,
            is_active=req.is_active
        )
    except Exception as exc:
        if _is_integrity_error(exc):
            raise HTTPException(status_code=400, detail="Μη έγκυρος διαγνώστης στο όριο") from exc
        raise

@router.put('/admin/advanced/modality-quotas/{rule_id}', response_model=ModalityQuotaResponse)
def edit_modality_quota(rule_id: int, req: ModalityQuotaUpdate, _=Depends(_require_admin)):
    result = cfg_db.update_modality_quota(rule_id, req.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail='Rule not found')
    return result

@router.delete('/admin/advanced/modality-quotas/{rule_id}')
def remove_modality_quota(rule_id: int, _=Depends(_require_admin)):
    success = cfg_db.delete_modality_quota(rule_id)
    if not success:
        raise HTTPException(status_code=404, detail='Rule not found')
    return {'success': True}

# ── Scoring System Weights ──────────────────────────────────────────────────────────

@router.get("/assignments/weights")
def get_weights():
    """Retrieve dynamic scoring weights from the DB."""
    return cfg_db.get_system_weights()

@router.put("/assignments/weights")
def update_weights(weights: dict[str, Any] = Body(...), _=Depends(_require_admin)):
    """Update whitelisted dynamic scoring weights (admin-protected with strict validation)."""
    unknown_keys = set(weights.keys()) - cfg_db._ALLOWED_WEIGHT_KEYS
    if unknown_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Μη επιτρεπτά κλειδιά βαρών: {', '.join(sorted(unknown_keys))}",
        )

    parsed: dict[str, float] = {}
    for k, raw_v in weights.items():
        try:
            v = float(raw_v)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=f"Μη έγκυρη αριθμητική τιμή για {k}") from exc
        if math.isnan(v) or math.isinf(v) or v < 0.0 or v > 1.0:
            raise HTTPException(status_code=400, detail=f"Η τιμή του {k} πρέπει να είναι μεταξύ 0% και 100%")
        parsed[k] = v

    # Merge with existing weights to validate sum & sub-tier ordering
    merged = cfg_db.get_system_weights()
    merged.update(parsed)

    if merged["pts_skills_pref"] < merged["pts_skills_neut"] or merged["pts_skills_neut"] < merged["pts_skills_none"]:
        raise HTTPException(status_code=400, detail="Τα επίπεδα Εξειδίκευσης πρέπει να τηρούν: Προτίμηση >= Ουδέτερο >= Χωρίς δεδομένα")
    if merged["pts_lab_pref"] < merged["pts_lab_neut"] or merged["pts_lab_neut"] < merged["pts_lab_other"]:
        raise HTTPException(status_code=400, detail="Τα επίπεδα Εργαστηρίου πρέπει να τηρούν: Προτίμηση >= Ουδέτερο >= Άλλο")

    max_pts = (
        merged["pts_partnership"]
        + merged["pts_history"]
        + merged["pts_skills_pref"]
        + merged["pts_lab_pref"]
        + merged["pts_capacity"]
    )
    if not math.isclose(max_pts, 1.0, abs_tol=0.01):
        raise HTTPException(status_code=400, detail=f"Το άθροισμα των μέγιστων πόντων πρέπει να είναι ακριβώς 100%. (Βρέθηκε {max_pts*100:.1f}%)")

    updated = cfg_db.update_system_weights(parsed)
    return {"message": "Τα βάρη αποθηκεύτηκαν επιτυχώς", "weights": updated}


# ── Comment-Based Auto-Assignment Toggle ─────────────────────────────

class CommentRuleToggleRequest(BaseModel):
    enabled: bool

@router.get("/admin/advanced/comment-rule")
def get_comment_rule_status():
    """Get the current enabled state of the comment-based auto-assign rule."""
    return {"enabled": cfg_db.get_comment_auto_assign_enabled()}

@router.post("/admin/advanced/comment-rule")
def toggle_comment_rule(req: CommentRuleToggleRequest, _=Depends(_require_admin)):
    """Enable or disable the comment-based auto-assign rule."""
    new_state = cfg_db.set_comment_auto_assign_enabled(req.enabled)
    return {
        "enabled": new_state,
        "message": f"Ο κανόνας αυτόματης ανάθεσης από σχόλια είναι πλέον {'ενεργός' if new_state else 'ανενεργός'}."
    }

