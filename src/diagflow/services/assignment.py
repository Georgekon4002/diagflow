"""
DiagFlow — Assignment Service

Handles the full lifecycle of assignments:
- Generating suggestions via the pipeline
- Confirming/overriding suggestions
- Logging decisions to the audit trail
- Writing final assignments back to Slis (when DB access is available)
"""

import asyncio
import json
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import structlog

from diagflow.config import settings
from diagflow.engine.comment_rules import normalize_greek_text
from diagflow.engine.filters import CandidateDiagnostician, ExamContext
from diagflow.engine.pipeline import AssignmentPipeline, AssignmentSuggestion
from diagflow.services.slis_sync import normalize_doctor_id, normalize_modality

logger = structlog.get_logger(__name__)

# Thread-safe in-memory cache manager for fast suggestion generation and metadata resolution
_cache_lock = threading.RLock()
_fetch_singleflight_lock = threading.Lock()
_exam_details_cache: dict[int, dict] = {}
_slis_assigned_cache: dict[int, dict] = {}
_staged_audit_cache: dict[int, dict] = {}
_EXAM_DETAILS_CACHE_MAX = 5000
_pending_exams_cache_data: list[dict] | None = None
_pending_exams_cache_time: float = 0.0
_slis_period_cache_days: int = 0
SLIS_PERIOD_CACHE_TTL_SECONDS: float = 15.0


def parse_stat_flag(raw_stat) -> int:
    """Safely normalize STAT flag across bool, int, float, Decimal, and string values."""
    if raw_stat is None:
        return 0
    if isinstance(raw_stat, bool):
        return 1 if raw_stat else 0
    try:
        return int(float(str(raw_stat).strip()))
    except (ValueError, TypeError):
        return 0


def get_exam_details_cache_snapshot() -> dict[int, dict]:
    with _cache_lock:
        return dict(_exam_details_cache)


def get_slis_assigned_cache_snapshot() -> dict[int, dict]:
    with _cache_lock:
        return dict(_slis_assigned_cache)


def put_exam_details_cache(exam_id: int, data: dict) -> None:
    with _cache_lock:
        if len(_exam_details_cache) >= _EXAM_DETAILS_CACHE_MAX and exam_id not in _exam_details_cache:
            # Evict oldest ~10% entries
            for old_key in list(_exam_details_cache.keys())[: _EXAM_DETAILS_CACHE_MAX // 10]:
                _exam_details_cache.pop(old_key, None)
        _exam_details_cache[exam_id] = data


def put_slis_assigned_cache(exam_id: int, data: dict) -> None:
    with _cache_lock:
        _slis_assigned_cache[exam_id] = data


def get_staged_audit_meta(exam_id: int) -> dict | None:
    with _cache_lock:
        return _staged_audit_cache.get(exam_id)


def pop_staged_audit_meta(exam_id: int) -> dict | None:
    with _cache_lock:
        return _staged_audit_cache.pop(exam_id, None)


def invalidate_slis_period_cache() -> None:
    """Invalidate the short-lived cached Slis stored-procedure snapshot."""
    global _pending_exams_cache_data, _pending_exams_cache_time, _slis_period_cache_days
    with _cache_lock:
        _pending_exams_cache_data = None
        _pending_exams_cache_time = 0.0
        _slis_period_cache_days = 0


def _fetch_slis_period_rows(days_back: int = 7, force_refresh: bool = False) -> list[dict]:
    """
    Fetch exams from production MSSQL `EXEC getExamsListForPeriod_V1` with a short TTL cache
    and singleflight lock to prevent stored-procedure stampedes.
    Updates caches atomically AFTER the query succeeds so concurrent readers never see empty counts.
    """
    global _pending_exams_cache_data, _pending_exams_cache_time, _slis_period_cache_days
    from datetime import date, timedelta
    import diagflow.db.diagflow_db as cfg_db
    from diagflow.db.engines import get_slis_engine
    from sqlalchemy import text

    effective_days = max(days_back, 7)

    with _cache_lock:
        now_ts = time.monotonic()
        if (
            not force_refresh
            and _pending_exams_cache_data is not None
            and _slis_period_cache_days >= effective_days
            and (now_ts - _pending_exams_cache_time) < SLIS_PERIOD_CACHE_TTL_SECONDS
        ):
            return list(_pending_exams_cache_data)

    # Singleflight lock ensures parallel frontend requests execute the stored proc only once
    with _fetch_singleflight_lock:
        with _cache_lock:
            now_ts = time.monotonic()
            if (
                not force_refresh
                and _pending_exams_cache_data is not None
                and _slis_period_cache_days >= effective_days
                and (now_ts - _pending_exams_cache_time) < SLIS_PERIOD_CACHE_TTL_SECONDS
            ):
                return list(_pending_exams_cache_data)

        today = date.today().isoformat()
        start_date = (date.today() - timedelta(days=effective_days)).isoformat()

        engine = get_slis_engine()
        with engine.connect() as conn:
            query = text("EXEC getExamsListForPeriod_V1 :start_date, :end_date")
            res = conn.execute(query, {"start_date": start_date, "end_date": today})
            keys = list(res.keys())
            raw_pulled = [dict(zip(keys, r)) for r in res.fetchall()]

        all_pulled = [{k.lower(): v for k, v in r.items()} for r in raw_pulled]

        # Build replacement caches off-lock, then swap atomically under _cache_lock
        new_assigned_cache: dict[int, dict] = {}
        new_details: dict[int, dict] = {}
        for r in all_pulled:
            raw_eid = r.get("exammoreid")
            if raw_eid is None:
                continue
            eid_i = int(raw_eid)
            norm_cat = normalize_modality(r.get("category"))
            r["category"] = norm_cat
            vdate_i = cfg_db._normalize_date_str(r.get("visitdate")) or ""
            s_val = parse_stat_flag(r.get("stat"))
            new_details[eid_i] = {
                "exammoreid": eid_i,
                "extracode": r.get("extracode"),
                "category": norm_cat,
                "modality": norm_cat,
                "examname": r.get("examname") or r.get("exam_name") or "",
                "examnumcode": r.get("examnumcode"),
                "patient_name": f"{r.get('fname') or ''} {r.get('lname') or ''}".strip(),
                "demogid": r.get("demogid"),
                "visitdate": vdate_i,
                "labcodeid": r.get("labcodeid"),
                "lab_name": (r.get("laboratoryname") or "").strip(),
                "wcode": r.get("wcode"),
                "wname": r.get("wname") or "",
                "notes": r.get("notes") or "",
                "oldpers": r.get("oldpers"),
                "stat": s_val,
            }
            raw_d = r.get("diagnostis")
            if raw_d is not None and str(raw_d).strip().lower() not in ("", "0", "none", "null"):
                try:
                    new_assigned_cache[eid_i] = {
                        "diagnostician_id": int(float(str(raw_d).strip())),
                        "extracode": r.get("extracode"),
                        "category": norm_cat,
                        "visitdate": vdate_i,
                    }
                except (ValueError, TypeError):
                    pass

        with _cache_lock:
            _slis_assigned_cache.clear()
            _slis_assigned_cache.update(new_assigned_cache)
            if force_refresh:
                _exam_details_cache.clear()
            _exam_details_cache.update(new_details)
            while len(_exam_details_cache) > _EXAM_DETAILS_CACHE_MAX:
                _exam_details_cache.pop(next(iter(_exam_details_cache)), None)
            _pending_exams_cache_data = all_pulled
            _pending_exams_cache_time = time.monotonic()
            _slis_period_cache_days = effective_days

        return list(all_pulled)


# ── Resolve mock DB path relative to the project root ─────────────
if getattr(sys, "frozen", False):
    _PROJECT_ROOT = Path(sys.executable).parent
else:
    _PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_MOCK_DB_PATH = _PROJECT_ROOT / settings.mock_slis_db_path


def _get_mock_db() -> sqlite3.Connection:
    """Open a read-write SQLite connection to the mock Slis database."""
    from diagflow.services.slis_sync import ensure_slis_exams_table, ensure_mock_slis_db_initialized
    if settings.use_mock_slis_db:
        ensure_mock_slis_db_initialized()
    _MOCK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_MOCK_DB_PATH))
    con.row_factory = sqlite3.Row
    ensure_slis_exams_table(con)
    return con


def _is_pamakristos_row(r: dict) -> bool:
    if not r:
        return False
    wname = normalize_greek_text(str(r.get("wname") or r.get("issuing_doctor_name") or ""))
    lab = normalize_greek_text(str(r.get("laboratoryname") or r.get("lab_name") or ""))
    return "ΠΑΜΜΑΚΑΡΙΣΤ" in wname or "ΠΑΜΑΚΑΡΙΣΤ" in wname or "ΠΑΜΜΑΚΑΡΙΣΤ" in lab or "ΠΑΜΑΚΑΡΙΣΤ" in lab


def _row_to_exam_dict(row: sqlite3.Row | dict) -> dict:
    """
    Convert an exam row (sqlite3.Row or dict) into the standardized exam dict format
    that the API routes and engine expect.
    """
    import diagflow.db.diagflow_db as cfg_db

    r = dict(row) if not isinstance(row, dict) else row
    eid = r.get("exammoreid")
    fname = r.get("fname") or ""
    lname = r.get("lname") or ""
    pat_name = f"{fname} {lname}".strip() or (r.get("patient_name") or "")
    stat_val = parse_stat_flag(r.get("stat"))
    norm_cat = normalize_modality(r.get("category"))
    norm_vdate = cfg_db._normalize_date_str(r.get("visitdate")) or ""
    raw_diag = r.get("diagnostis")
    has_diag = raw_diag is not None and str(raw_diag).strip().lower() not in ("", "0", "none", "null")
    norm_doc_id = normalize_doctor_id(r.get("wcode"))

    return {
        # ── Identifiers ──
        "exam_id":        str(eid),
        "extracode":      r.get("extracode"),
        "visitid":        r.get("visitid"),
        "exammoreid":     eid,

        # ── Patient ──
        "demogid":        r.get("demogid"),
        "patient_id":     str(r.get("demogid") or r.get("patient_id") or ""),
        "patient_name":   pat_name,
        "fname":          fname,
        "lname":          lname,
        "age":            r.get("age"),

        # ── Exam details ──
        "examid":         r.get("examid"),
        "examnumcode":    r.get("examnumcode"),
        "examname":       r.get("examname") or "",
        "modality":       norm_cat,
        "category":       norm_cat,
        "body_part":      "",
        "visitdate":      norm_vdate,
        "stat":           stat_val,

        # ── Laboratory ──
        "labcodeid":      r.get("labcodeid"),
        "lab_id":         str(r.get("labcodeid")) if r.get("labcodeid") is not None else None,
        "lab_name":       (r.get("laboratoryname") or r.get("lab_name") or "").strip(),

        # ── Issuing doctor ──
        "wcode":              r.get("wcode"),
        "issuing_doctor_id":  norm_doc_id or None,
        "wname":              r.get("wname") or "",
        "issuing_doctor_name": r.get("wname") or r.get("issuing_doctor_name") or "",

        # ── Assignment ──
        "diagnostis":     r.get("diagnostis"),
        "code":           r.get("code") or "",
        "diagnostician_name": r.get("code") or r.get("diagnostician_name") or "",
        "status":         "assigned" if has_diag else "pending",

        # ── Notes ──
        "notes":          r.get("notes") or "",
        "comments":       r.get("notes") or r.get("comments") or "",

        # ── OLD (last same-exam-type visit) ──
        "oldvisit":       r.get("oldvisit") or 0,
        "oldorder":       str(r.get("oldorder")) if r.get("oldorder") else "",
        "olddiagnostis":  str(r.get("olddiagnostis")) if r.get("olddiagnostis") else "",
        "oldpers":        r.get("oldpers"),

        # ── Slis sync tracking ──
        "slis_synced_at": r.get("slis_synced_at"),

        # ── Extras ──
        "suggestion":     None,
        "is_pamakristos": _is_pamakristos_row(r),
    }


class AssignmentService:
    """
    High-level service for managing exam assignments.

    This is the primary interface used by the API routes.
    """

    def __init__(self):
        self.pipeline = AssignmentPipeline()

    async def suggest_assignment(
        self,
        exam: ExamContext,
        candidates: list[CandidateDiagnostician],
        preloaded_config: dict | None = None,
    ) -> AssignmentSuggestion | None:
        """
        Generate an assignment suggestion for a single exam.

        Args:
            exam: The exam requiring assignment
            candidates: All potentially eligible diagnosticians
            preloaded_config: Optional pre-fetched config dict for batch scoring

        Returns:
            AssignmentSuggestion or None if no valid candidates
        """
        suggestion = self.pipeline.run(exam, candidates, preloaded_config=preloaded_config)

        if suggestion:
            logger.info(
                "suggestion_generated",
                exam_id=exam.exam_id,
                suggested=suggestion.suggested_diagnostician_name,
                score=suggestion.confidence_score,
            )
        else:
            logger.warning(
                "no_suggestion",
                exam_id=exam.exam_id,
                reason="No candidates survived the pipeline",
            )

        return suggestion

    def _confirm_assignment_sync(
        self,
        exam_id: str,
        diagnostician_id: int,
        suggestion: AssignmentSuggestion | None = None,
        diagnostician_name: str | None = None,
        reason: str | None = None,
        is_override: bool = False,
        original_diagnostician_id: int | None = None,
    ) -> dict:
        import diagflow.db.diagflow_db as cfg_db
        if not diagnostician_name:
            d = cfg_db.get_diagnostician(diagnostician_id)
            diagnostician_name = d["name"] if d else (suggestion.suggested_diagnostician_name if suggestion else f"ID:{diagnostician_id}")

        now_iso = datetime.now().isoformat()
        suggested_id = (
            suggestion.suggested_diagnostician_id
            if suggestion
            else (original_diagnostician_id if original_diagnostician_id else diagnostician_id)
        )
        rules_json = json.dumps(suggestion.rules_fired, ensure_ascii=False) if suggestion else "[]"
        breakdown_json = json.dumps(suggestion.score_breakdown, ensure_ascii=False) if suggestion else "[]"

        log_entry = {
            "exam_id": exam_id,
            "suggested_diagnostician_id": suggested_id,
            "final_diagnostician_id": diagnostician_id,
            "diagnostician_id": diagnostician_id,
            "diagnostician_name": diagnostician_name,
            "was_overridden": is_override,
            "is_override": is_override,
            "override_reason": reason,
            "rules_fired": rules_json,
            "score_breakdown": breakdown_json,
            "decision_timestamp": now_iso,
            "assigned_at": now_iso,
        }

        eid_int = int(exam_id)
        vdate = None
        mod, ext = None, None
        with _cache_lock:
            c_data = _exam_details_cache.get(eid_int)
        if c_data:
            mod = c_data.get("category") or c_data.get("modality")
            ext = c_data.get("extracode")
            vdate = c_data.get("visitdate")

        # Only query fallback metadata if fields stored in df_local_assignments are missing
        if not mod or not ext or not vdate:
            if not settings.use_mock_slis_db:
                try:
                    from sqlalchemy import text
                    from diagflow.db.engines import get_slis_engine
                    engine = get_slis_engine()
                    with engine.connect() as conn:
                        res = conn.execute(
                            text(
                                "SELECT "
                                "CASE WHEN X.KATEGORYID IN (21,22) THEN 'MRI' "
                                "WHEN X.KATEGORYID = 18 THEN 'CT' ELSE '' END AS category, "
                                "V.EXTRACODE AS extracode, "
                                "COALESCE(V.DATE, E.ORDERDATE) AS visitdate "
                                "FROM LISKOSMO.DBO.EXAMMORE E "
                                "INNER JOIN LISKOSMO.DBO.VISIT V ON V.VISITID = E.VISITID "
                                "LEFT JOIN LISKOSMO.DBO.EXAM X ON X.EXAMNUMCODE = E.EXAMCODE "
                                "WHERE E.EXAMMOREID = :id"
                            ),
                            {"id": eid_int},
                        ).fetchone()
                        if res:
                            if not mod and res[0]:
                                mod = normalize_modality(res[0])
                            if not ext and res[1]:
                                ext = str(res[1])
                            if not vdate and res[2]:
                                vdate = cfg_db._normalize_date_str(res[2])
                except Exception as meta_exc:
                    logger.warning("confirm_metadata_fallback_failed", exam_id=exam_id, error=str(meta_exc))
            else:
                try:
                    con = _get_mock_db()
                    row = con.execute("SELECT category, extracode, visitdate FROM slis_exams WHERE exammoreid = ?", (eid_int,)).fetchone()
                    if row:
                        if not mod and "category" in row.keys():
                            mod = row["category"]
                        if not ext and "extracode" in row.keys() and row["extracode"]:
                            ext = str(row["extracode"])
                        if not vdate and "visitdate" in row.keys() and row["visitdate"]:
                            vdate = cfg_db._normalize_date_str(row["visitdate"])
                    con.close()
                except Exception as meta_exc:
                    logger.warning("confirm_mock_metadata_fallback_failed", exam_id=exam_id, error=str(meta_exc))

        if mod:
            mod = normalize_modality(mod)

        # Do NOT swallow DB write failures — raise so caller never reports fake success
        cfg_db.upsert_local_assignment(
            eid_int,
            diagnostician_id,
            diagnostician_name,
            now_iso,
            modality=mod,
            extracode=ext,
            is_auto=False,
            visitdate=vdate,
        )

        # Retain decision audit trail until pushed to df_assignment_log
        with _cache_lock:
            _staged_audit_cache[eid_int] = {
                "suggested_diagnostician_id": suggested_id,
                "was_overridden": is_override,
                "override_reason": reason,
                "rules_fired": rules_json,
                "score_breakdown": breakdown_json,
            }

        logger.info(
            "assignment_staged",
            exam_id=exam_id,
            diagnostician=diagnostician_name,
            is_override=is_override,
        )

        return log_entry

    async def confirm_assignment(
        self,
        exam_id: str,
        diagnostician_id: int,
        suggestion: AssignmentSuggestion | None = None,
        diagnostician_name: str | None = None,
        reason: str | None = None,
        is_override: bool = False,
        original_diagnostician_id: int | None = None,
    ) -> dict:
        """
        Confirm an assignment (manual or accepted suggestion).
        Records the decision and stages it in df_local_assignments (non-blocking).
        """
        return await asyncio.to_thread(
            self._confirm_assignment_sync,
            exam_id,
            diagnostician_id,
            suggestion,
            diagnostician_name,
            reason,
            is_override,
            original_diagnostician_id,
        )

    async def override_assignment(
        self,
        exam_id: str,
        override_diagnostician_id: int,
        reason: str,
        original_diagnostician_id: int = 0,
        suggestion: AssignmentSuggestion | None = None,
    ) -> dict:
        """
        Override a suggested assignment with a different diagnostician.

        Convenience wrapper around confirm_assignment with is_override=True.
        """
        return await self.confirm_assignment(
            exam_id=exam_id,
            diagnostician_id=override_diagnostician_id,
            suggestion=suggestion,
            reason=reason,
            is_override=True,
            original_diagnostician_id=original_diagnostician_id or None,
        )


def _get_pending_exams_from_db(force_refresh: bool = False) -> list[dict]:
    """Fetch pending exams (unassigned in Slis and not yet staged in df_local_assignments)."""
    try:
        from datetime import date, timedelta
        import diagflow.db.diagflow_db as cfg_db
        from diagflow.engine.comment_rules import parse_comment_diagnosticians

        local_assignments = cfg_db.get_all_local_assignments()
        today = date.today().isoformat()
        start_date = (date.today() - timedelta(days=3)).isoformat()

        # Preload active exclusive partnerships (normalize doctor IDs for consistent matching)
        raw_exclusive_map = cfg_db.get_exclusive_partnerships()
        exclusive_map = {
            normalize_doctor_id(k): v
            for k, v in raw_exclusive_map.items()
            if normalize_doctor_id(k)
        }
        routing_rules = cfg_db.get_all_exam_routing_rules()
        dismissed_auto_assignments = cfg_db.get_dismissed_auto_assignments()
        all_diags = cfg_db.get_all_diagnosticians()
        all_diags_by_id = {int(d["id"]): d for d in all_diags}
        active_diagnosticians = [d for d in all_diags if d.get("active", True)]
        comment_rule_enabled = cfg_db.get_comment_auto_assign_enabled()

        raw_exam_rows = []

        if not settings.use_mock_slis_db:
            # ── PRODUCTION MODE: Use cached 7-day MSSQL snapshot (1 proc call per refresh) ──
            all_pulled = _fetch_slis_period_rows(days_back=7, force_refresh=force_refresh)

            # Clean ONLY local assignments confirmed already assigned in Slis (never delete out-of-window staged exams!)
            assigned_in_slis_ids = [
                int(r["exammoreid"]) for r in all_pulled
                if r.get("exammoreid") is not None and r.get("diagnostis") is not None
                and str(r.get("diagnostis")).strip().lower() not in ("", "0", "none", "null")
                and int(r["exammoreid"]) in local_assignments
            ]

            if assigned_in_slis_ids:
                with cfg_db._conn() as local_con:
                    tbl_local = cfg_db._tbl("local_assignments")
                    for chunk in cfg_db._chunked(assigned_in_slis_ids):
                        placeholders = ",".join(["?"] * len(chunk))
                        local_con.execute(f"DELETE FROM {tbl_local} WHERE exammoreid IN ({placeholders})", tuple(chunk))
                local_assignments = cfg_db.get_all_local_assignments()

            # Filter for exams with no diagnostician in Slis within the 3-day pending window
            for r in all_pulled:
                raw_d = r.get("diagnostis")
                if raw_d is not None and str(raw_d).strip().lower() not in ("", "0", "none", "null"):
                    continue
                vdate_s = cfg_db._normalize_date_str(r.get("visitdate")) or ""
                if vdate_s and vdate_s < start_date:
                    continue
                raw_exam_rows.append(r)
        else:
            # ── MOCK MODE: Query Local SQLite mock_slis.db ──
            cutoff_date = (date.today() - timedelta(days=3)).isoformat()
            con = _get_mock_db()
            cur = con.execute(
                """
                SELECT * FROM slis_exams
                WHERE (diagnostis IS NULL OR diagnostis = '' OR diagnostis = '0' OR LOWER(diagnostis) = 'none')
                  AND substr(visitdate, 1, 10) >= ?
                ORDER BY visitdate DESC, extracode ASC
                """,
                (cutoff_date,)
            )
            raw_exam_rows = [dict(r) for r in cur.fetchall()]
            con.close()

        # Preload absences & Pammakaristos on-call per unique exam visit date
        unique_exam_dates = {
            (cfg_db._normalize_date_str(r.get("visitdate")) or today)
            for r in raw_exam_rows
        }
        absent_by_date = cfg_db.get_absent_diagnostician_ids_for_dates(unique_exam_dates)
        oncall_by_date: dict[str, dict | None] = {}

        def _get_oncall_for_date(d_str: str) -> dict | None:
            if d_str not in oncall_by_date:
                oncall_by_date[d_str] = cfg_db.get_oncall_diagnostician(d_str)
            return oncall_by_date[d_str]

        def _is_target_eligible_for_auto(diag_id: int, vdate_str: str) -> bool:
            d_obj = all_diags_by_id.get(int(diag_id))
            if d_obj is not None and not d_obj.get("active", True):
                return False
            if int(diag_id) in absent_by_date.get(vdate_str, set()):
                return False
            return True

        # Pass 1: Update full 16-field _exam_details_cache & determine candidate auto-assignment per exam
        now_iso = datetime.now().isoformat()
        candidate_rows: list[tuple[dict, int, str, str, dict | None]] = []

        for r in raw_exam_rows:
            exam_id = int(r["exammoreid"])
            exam_vdate = cfg_db._normalize_date_str(r.get("visitdate")) or today
            norm_cat = normalize_modality(r.get("category"))
            stat_val = parse_stat_flag(r.get("stat"))

            # Always preserve FULL 16-field metadata in _exam_details_cache
            put_exam_details_cache(exam_id, {
                "exammoreid": exam_id,
                "extracode": r.get("extracode"),
                "category": norm_cat,
                "modality": norm_cat,
                "examname": r.get("examname") or r.get("exam_name") or r.get("exam_title") or "",
                "examnumcode": r.get("examnumcode"),
                "patient_name": f"{r.get('fname') or ''} {r.get('lname') or ''}".strip(),
                "demogid": r.get("demogid"),
                "visitdate": exam_vdate,
                "labcodeid": r.get("labcodeid"),
                "lab_name": (r.get("laboratoryname") or r.get("lab_name") or "").strip(),
                "wcode": r.get("wcode"),
                "wname": r.get("wname") or "",
                "notes": r.get("notes") or "",
                "oldpers": r.get("oldpers"),
                "stat": stat_val,
            })

            if exam_id in local_assignments:
                continue  # already handled (staged in df_local_assignments)

            if exam_id in dismissed_auto_assignments:
                candidate_rows.append((r, exam_id, exam_vdate, norm_cat, None))
                continue

            # Evaluate Stage 0 auto-assignment target (not yet written until order consistency checked)
            auto_target: dict | None = None
            comments_text = str(r.get("notes") or r.get("comments") or "").strip()
            matched_comment_diag = None
            excluded_comment_diag_ids: set[int] = set()

            if comment_rule_enabled and comments_text:
                matched_comment_diag, excluded_comment_diag_ids = parse_comment_diagnosticians(
                    comments_text, active_diagnosticians
                )

            if (
                comment_rule_enabled
                and matched_comment_diag
                and matched_comment_diag["id"] not in excluded_comment_diag_ids
                and _is_target_eligible_for_auto(matched_comment_diag["id"], exam_vdate)
            ):
                auto_target = {
                    "diag_id": int(matched_comment_diag["id"]),
                    "diag_name": matched_comment_diag["name"],
                    "rule_desc": "Όνομα Διαγνώστη αναφέρθηκε στα σχόλια",
                    "event": "comment_auto_assigned",
                }
            else:
                doc_id = normalize_doctor_id(r.get("wcode"))

                # Check 1: Exclusive partner auto-assignment
                if doc_id and doc_id in exclusive_map:
                    ex_part = exclusive_map[doc_id]
                    pref_diag_id = int(ex_part["preferred_diagnostician_id"])
                    if pref_diag_id not in excluded_comment_diag_ids and _is_target_eligible_for_auto(pref_diag_id, exam_vdate):
                        auto_target = {
                            "diag_id": pref_diag_id,
                            "diag_name": ex_part["preferred_diagnostician_name"],
                            "rule_desc": "Συνεργάτης (Αποκλειστικότητα)",
                            "event": "exclusive_partner_auto_assigned",
                        }
                    elif pref_diag_id in excluded_comment_diag_ids:
                        logger.info("exclusive_partner_suppressed_by_comment_exclusion", exam_id=exam_id, diagnostician=pref_diag_id)

                # Check 2: Dynamic Exam Routing Rules
                if auto_target is None:
                    exam_code_str = str(r.get("examnumcode") or "").strip()
                    lab_id_str = str(r.get("labcodeid")).strip() if r.get("labcodeid") is not None else ""
                    is_pam = _is_pamakristos_row(r)

                    for rule in routing_rules:
                        if not rule.get("is_active", True):
                            continue
                        rule_lab = rule.get("lab_id")
                        lab_match = (rule_lab is None or str(rule_lab).strip() == "") or (str(rule_lab).strip() == lab_id_str)
                        pam_match = (not rule.get("is_pamakristos")) or is_pam
                        rule_doc = normalize_doctor_id(rule.get("issuing_doctor_id"))
                        doc_match = (not rule_doc) or (rule_doc == doc_id)

                        if lab_match and pam_match and doc_match:
                            raw_codes = rule.get("exam_codes") or ""
                            rule_codes = [c.strip() for c in str(raw_codes).split(",") if c.strip()]
                            if exam_code_str and exam_code_str in rule_codes:
                                target_id = int(rule["diagnostician_id"])
                                if target_id not in excluded_comment_diag_ids and _is_target_eligible_for_auto(target_id, exam_vdate):
                                    d_info = all_diags_by_id.get(target_id)
                                    d_name = d_info["name"] if d_info else rule.get("diagnostician_name", f"ID:{target_id}")
                                    auto_target = {
                                        "diag_id": target_id,
                                        "diag_name": d_name,
                                        "rule_desc": rule.get("description") or "Κανόνας δρομολόγησης",
                                        "event": "dynamic_rule_auto_assigned",
                                    }
                                    break
                                elif target_id in excluded_comment_diag_ids:
                                    logger.info("dynamic_rule_suppressed_by_comment_exclusion", exam_id=exam_id, rule_id=rule["id"], target_id=target_id)

                # Check 3: Παμμακάριστος general on-call (resolved per exam's visitdate)
                if auto_target is None and _is_pamakristos_row(r):
                    pam_oncall = _get_oncall_for_date(exam_vdate)
                    if pam_oncall:
                        pam_diag_id = int(pam_oncall["diagnostician_id"])
                        if pam_diag_id not in excluded_comment_diag_ids and _is_target_eligible_for_auto(pam_diag_id, exam_vdate):
                            auto_target = {
                                "diag_id": pam_diag_id,
                                "diag_name": pam_oncall["diagnostician_name"],
                                "rule_desc": "Παμμακάριστος Εφημερία",
                                "event": "pam_exam_auto_assigned",
                            }
                        elif pam_diag_id in excluded_comment_diag_ids:
                            logger.info("pam_oncall_suppressed_by_comment_exclusion", exam_id=exam_id, oncall=pam_diag_id)

            candidate_rows.append((r, exam_id, exam_vdate, norm_cat, auto_target))

        # Pass 2: Multi-exam order consistency check — do not split a single order across different doctors
        order_targets: dict[tuple[str, str], set[int | None]] = {}
        for r, _eid, _vdate, _cat, target in candidate_rows:
            ext_s = str(r.get("extracode") or "").strip()
            if ext_s:
                okey = (str(r.get("demogid") or "").strip(), ext_s)
                order_targets.setdefault(okey, set()).add(target["diag_id"] if target else None)

        rows = []
        for r, exam_id, exam_vdate, norm_cat, target in candidate_rows:
            ext_s = str(r.get("extracode") or "").strip()
            split_conflict = False
            if ext_s and target is not None:
                okey = (str(r.get("demogid") or "").strip(), ext_s)
                # If siblings in the same order map to conflicting doctors or partial auto-assign, keep order together in Pending
                if len(order_targets.get(okey, set())) > 1:
                    split_conflict = True
                    logger.info("auto_assign_skipped_order_consistency", exam_id=exam_id, extracode=ext_s)

            if target is not None and not split_conflict:
                cfg_db.upsert_local_assignment(
                    exam_id,
                    target["diag_id"],
                    target["diag_name"],
                    now_iso,
                    modality=norm_cat,
                    extracode=ext_s or None,
                    is_auto=True,
                    rule_desc=target["rule_desc"],
                    visitdate=exam_vdate,
                )
                logger.info(
                    target["event"],
                    exam_id=exam_id,
                    diagnostician=target["diag_name"],
                )
                continue

            rows.append(_row_to_exam_dict(r))

        logger.info("pending_exams_loaded", count=len(rows))
        return rows
    except Exception as e:
        logger.error("get_pending_exams_failed", error=str(e))
        return []


def _get_assigned_exams_from_db() -> list[dict]:
    """
    Fetch exams that have been locally assigned in df_local_assignments (staged for Slis push).
    In production: Resolves metadata from MSSQL without ever wiping staged assignments on transient errors.
    In mock mode: Resolves from SQLite mock_slis.db.
    """
    try:
        import diagflow.db.diagflow_db as cfg_db

        local_assignments = cfg_db.get_all_local_assignments()
        if not local_assignments:
            return []

        exam_metadata: dict[int, dict] = {}
        fetch_succeeded = False

        if not settings.use_mock_slis_db:
            try:
                all_pulled = _fetch_slis_period_rows(days_back=7, force_refresh=False)
                fetch_succeeded = True
                for r_dict in all_pulled:
                    if r_dict.get("exammoreid") is not None:
                        exam_metadata[int(r_dict["exammoreid"])] = r_dict
            except Exception as e:
                logger.warning("failed_to_fetch_mssql_assigned_metadata", error=str(e))

            # For any staged exam outside the 7-day window, verify directly against LISKOSMO.DBO.EXAMMORE
            # before ever purging — NEVER delete on transient fetch failure!
            missing_eids = [int(eid) for eid in local_assignments if int(eid) not in exam_metadata]
            if fetch_succeeded and missing_eids:
                try:
                    from sqlalchemy import text
                    from diagflow.db.engines import get_slis_engine
                    engine = get_slis_engine()
                    with engine.connect() as conn:
                        for chunk in cfg_db._chunked(missing_eids):
                            binds = {f"id_{i}": eid for i, eid in enumerate(chunk)}
                            ph = ", ".join(f":{k}" for k in binds)
                            res = conn.execute(
                                text(
                                    "SELECT E.EXAMMOREID, V.EXTRACODE, V.VISITID, D.DEMOGID, D.FNAME, D.LNAME, "
                                    "X.EXAMID, X.EXAMNUMCODE, X.NAME AS EXAMNAME, COALESCE(V.DATE, E.ORDERDATE) AS VISITDATE, "
                                    "V.LABCODEID, L.LNAME AS LABORATORYNAME, V.WARDID, W.CODE AS WCODE, W.NAME AS WNAME, "
                                    "E.DIAGNOSTISID AS DIAGNOSTIS, V.STAT, "
                                    "CASE WHEN X.KATEGORYID IN (21,22) THEN 'MRI' WHEN X.KATEGORYID = 18 THEN 'CT' ELSE '' END AS CATEGORY "
                                    "FROM LISKOSMO.DBO.EXAMMORE E "
                                    "LEFT JOIN LISKOSMO.DBO.VISIT V ON V.VISITID = E.VISITID "
                                    "LEFT JOIN LISKOSMO.DBO.DEMOG D ON D.DEMOGID = E.DEMOGID "
                                    "LEFT JOIN LISKOSMO.DBO.EXAM X ON X.EXAMNUMCODE = E.EXAMCODE "
                                    "LEFT JOIN LISKOSMO.DBO.LABORATORY L ON L.LABCODEID = V.LABCODEID "
                                    "LEFT JOIN LISKOSMO.DBO.WARD W ON W.WARDID = V.WARDID "
                                    f"WHERE E.EXAMMOREID IN ({ph})"
                                ),
                                binds,
                            )
                            keys = list(res.keys())
                            for row in res.fetchall():
                                r_dict = {k.lower(): v for k, v in zip(keys, row)}
                                if r_dict.get("exammoreid") is not None:
                                    exam_metadata[int(r_dict["exammoreid"])] = r_dict
                except Exception as lookup_exc:
                    # Direct lookup failed — treat as transient error, do NOT delete staged rows
                    fetch_succeeded = False
                    logger.warning("assigned_direct_slis_lookup_failed", error=str(lookup_exc))
        else:
            try:
                con = _get_mock_db()
                eids = list(local_assignments.keys())
                for chunk in cfg_db._chunked(eids):
                    placeholders = ",".join("?" * len(chunk))
                    cur = con.execute(
                        f"SELECT * FROM slis_exams WHERE exammoreid IN ({placeholders}) ORDER BY visitdate DESC, extracode ASC",
                        chunk,
                    )
                    for r in cur.fetchall():
                        r_dict = dict(r)
                        exam_metadata[int(r_dict["exammoreid"])] = r_dict
                con.close()
                fetch_succeeded = True
            except Exception as e:
                logger.warning("mock_assigned_read_failed", error=str(e))

        details_snapshot = get_exam_details_cache_snapshot()
        rows = []
        for eid, loc in local_assignments.items():
            if not settings.use_mock_slis_db and fetch_succeeded and eid not in exam_metadata:
                # Confirmed missing/cancelled in LISKOSMO.DBO.EXAMMORE — purge without poisoning dismissed list
                try:
                    cfg_db.delete_local_assignment(eid, record_dismissed=False)
                except Exception:
                    pass
                continue

            meta = exam_metadata.get(eid) or details_snapshot.get(eid) or {}
            fname = meta.get("fname") or ""
            lname = meta.get("lname") or ""
            pat_name = f"{fname} {lname}".strip() or (meta.get("patient_name") or "")
            norm_mod = normalize_modality(loc.get("modality") or meta.get("category"))
            meta_stat = parse_stat_flag(meta.get("stat"))
            if meta_stat == 0 and eid in details_snapshot:
                meta_stat = parse_stat_flag(details_snapshot[eid].get("stat"))

            rows.append({
                "exam_id": str(eid),
                "exammoreid": eid,
                "extracode": loc.get("extracode") or meta.get("extracode") or "",
                "visitid": meta.get("visitid"),
                "demogid": meta.get("demogid"),
                "patient_id": str(meta.get("demogid") or meta.get("patient_id") or ""),
                "patient_name": pat_name,
                "fname": fname,
                "lname": lname,
                "age": meta.get("age"),
                "examid": meta.get("examid"),
                "examnumcode": meta.get("examnumcode") or "",
                "examname": meta.get("examname") or "",
                "modality": norm_mod,
                "category": norm_mod,
                "body_part": meta.get("body_part") or "",
                "visitdate": cfg_db._normalize_date_str(meta.get("visitdate")) or cfg_db._normalize_date_str(loc.get("visitdate")) or cfg_db._normalize_date_str(loc.get("assigned_at")) or "",
                "labcodeid": meta.get("labcodeid"),
                "lab_id": str(meta["labcodeid"]) if meta.get("labcodeid") is not None else None,
                "lab_name": meta.get("laboratoryname") or meta.get("lab_name") or "",
                "wcode": meta.get("wcode"),
                "issuing_doctor_id": normalize_doctor_id(meta.get("wcode")) or None,
                "wname": meta.get("wname") or meta.get("issuing_doctor_name") or "",
                "issuing_doctor_name": meta.get("wname") or meta.get("issuing_doctor_name") or "",
                "diagnostis": loc["diagnostician_id"],
                "code": loc["diagnostician_name"],
                "diagnostician_name": loc["diagnostician_name"],
                "status": "assigned",
                "notes": meta.get("notes") or "",
                "comments": meta.get("notes") or "",
                "oldvisit": meta.get("oldvisit") or 0,
                "oldorder": meta.get("oldorder") or "",
                "olddiagnostis": meta.get("olddiagnostis") or "",
                "oldpers": meta.get("oldpers"),
                "stat": meta_stat,
                "slis_synced_at": None,
                "suggestion": None,
                "is_pamakristos": _is_pamakristos_row(meta),
                "is_auto_assigned": bool(loc.get("is_auto", False)),
                "rule_desc": loc.get("rule_desc", ""),
            })

        logger.info("assigned_exams_loaded", count=len(rows))
        return rows
    except Exception as e:
        logger.error("get_assigned_exams_failed", error=str(e))
        return []

def _get_exam_categories_from_db() -> list[dict]:
    """Fetch exam categories from diagflow.db exam_dictionary table."""
    try:
        import diagflow.db.diagflow_db as cfg_db
        entries = cfg_db.get_exam_dictionary()
        return [{"examnumcode": e["code"], "name": e["name"], "category": e["category"]} for e in entries]
    except Exception as e:
        logger.error("exam_dictionary_read_failed", error=str(e))
        return []


# ── Inject methods into AssignmentService ─────────────────────────

def _get_pending_exams(self) -> list[dict]:
    """Fetch pending exams (from local slis_exams store, populated by mock or real Slis pull)."""
    return _get_pending_exams_from_db()


def _get_assigned_exams(self) -> list[dict]:
    """Fetch assigned exams (from local slis_exams store, populated by mock or real Slis pull)."""
    return _get_assigned_exams_from_db()

def _get_exam_categories(self) -> list[dict]:
    """Fetch exam categories (from local slis_exams store, populated by mock or real Slis pull)."""
    return _get_exam_categories_from_db()


AssignmentService.get_pending_exams = _get_pending_exams       # type: ignore
AssignmentService.get_assigned_exams = _get_assigned_exams     # type: ignore
AssignmentService.get_exam_categories = _get_exam_categories   # type: ignore
