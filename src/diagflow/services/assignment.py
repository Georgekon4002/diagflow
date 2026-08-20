"""
DiagFlow — Assignment Service

Handles the full lifecycle of assignments:
- Generating suggestions via the pipeline
- Confirming/overriding suggestions
- Logging decisions to the audit trail
- Writing final assignments back to Slis (when DB access is available)
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import structlog

from diagflow.config import settings
from diagflow.engine.filters import CandidateDiagnostician, ExamContext
from diagflow.engine.pipeline import AssignmentPipeline, AssignmentSuggestion

logger = structlog.get_logger(__name__)

# Global in-memory cache for fast suggestion generation and metadata resolution
_exam_details_cache: dict[int, dict] = {}
_pending_exams_cache_data: list[dict] | None = None
_pending_exams_cache_time: float = 0.0


# ── Resolve mock DB path relative to the project root ─────────────
if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).parent
    if (_exe_dir / "db").exists():
        _PROJECT_ROOT = _exe_dir
    elif (_exe_dir.parent / "db").exists():
        _PROJECT_ROOT = _exe_dir.parent
    else:
        _PROJECT_ROOT = _exe_dir
else:
    _PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_MOCK_DB_PATH = _PROJECT_ROOT / settings.mock_slis_db_path


def _get_mock_db() -> sqlite3.Connection:
    """Open a read-write SQLite connection to the mock Slis database."""
    from diagflow.services.slis_sync import ensure_slis_exams_table, ensure_mock_slis_db_initialized
    ensure_mock_slis_db_initialized()
    _MOCK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_MOCK_DB_PATH))
    con.row_factory = sqlite3.Row
    ensure_slis_exams_table(con)
    return con


def _row_to_exam_dict(row: sqlite3.Row | dict) -> dict:
    """
    Convert an exam row (sqlite3.Row or dict) into the standardized exam dict format
    that the API routes and engine expect.
    """
    r = dict(row) if not isinstance(row, dict) else row
    eid = r.get("exammoreid")
    fname = r.get("fname") or ""
    lname = r.get("lname") or ""
    pat_name = f"{fname} {lname}".strip() or (r.get("patient_name") or "")

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
        "modality":       r.get("category") or "MRI",
        "category":       r.get("category") or "MRI",
        "body_part":      "",
        "visitdate":      str(r.get("visitdate"))[:10] if r.get("visitdate") else "",

        # ── Laboratory ──
        "labcodeid":      r.get("labcodeid"),
        "lab_id":         str(r.get("labcodeid")) if r.get("labcodeid") else None,
        "lab_name":       (r.get("laboratoryname") or r.get("lab_name") or "").strip(),

        # ── Issuing doctor ──
        "wcode":              r.get("wcode"),
        "issuing_doctor_id":  str(r.get("wcode")) if r.get("wcode") else None,
        "wname":              r.get("wname") or "",
        "issuing_doctor_name": r.get("wname") or r.get("issuing_doctor_name") or "",

        # ── Assignment ──
        "diagnostis":     r.get("diagnostis"),
        "code":           r.get("code") or "",
        "diagnostician_name": r.get("code") or r.get("diagnostician_name") or "",
        "status":         "assigned" if r.get("diagnostis") else "pending",

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
        "is_pamakristos": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ" in (r.get("wname") or "").upper(),
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
    ) -> AssignmentSuggestion | None:
        """
        Generate an assignment suggestion for a single exam.

        Args:
            exam: The exam requiring assignment
            candidates: All potentially eligible diagnosticians

        Returns:
            AssignmentSuggestion or None if no valid candidates
        """
        suggestion = self.pipeline.run(exam, candidates)

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

    async def confirm_assignment(
        self,
        exam_id: str,
        diagnostician_id: int,
        suggestion: AssignmentSuggestion | None = None,
        diagnostician_name: str | None = None,
        reason: str | None = None,
        is_override: bool = False,
    ) -> dict:
        """
        Confirm an assignment (manual or accepted suggestion).

        Records the decision and stages it in df_local_assignments.
        The assignment will only be pushed to Slis when the user clicks 'Push to Slis'.
        """
        import diagflow.db.diagflow_db as cfg_db
        if not diagnostician_name:
            d = cfg_db.get_diagnostician(diagnostician_id)
            diagnostician_name = d["name"] if d else (suggestion.suggested_diagnostician_name if suggestion else f"ID:{diagnostician_id}")

        now_iso = datetime.now().isoformat()
        log_entry = {
            "exam_id": exam_id,
            "suggested_diagnostician_id": suggestion.suggested_diagnostician_id if suggestion else diagnostician_id,
            "final_diagnostician_id": diagnostician_id,
            "diagnostician_id": diagnostician_id,
            "diagnostician_name": diagnostician_name,
            "was_overridden": is_override,
            "is_override": is_override,
            "override_reason": reason,
            "rules_fired": json.dumps(suggestion.rules_fired, ensure_ascii=False) if suggestion else "[]",
            "score_breakdown": json.dumps(suggestion.score_breakdown, ensure_ascii=False) if suggestion else "[]",
            "decision_timestamp": now_iso,
            "assigned_at": now_iso,
        }

        logger.info(
            "assignment_staged",
            exam_id=exam_id,
            diagnostician=diagnostician_name,
            is_override=is_override,
        )

        try:
            eid_int = int(exam_id)
            exam_info = _exam_details_cache.get(eid_int) or {}
            mod = exam_info.get("category") or exam_info.get("modality")
            ext = str(exam_info.get("extracode")) if exam_info.get("extracode") else None
            ename = exam_info.get("examname") or exam_info.get("exam_name") or exam_info.get("exam_title")
            
            if not mod or not ext or not ename:
                if settings.use_mock_slis_db:
                    try:
                        con = _get_mock_db()
                        row = con.execute("SELECT category, extracode, examname FROM slis_exams WHERE exammoreid = ?", (eid_int,)).fetchone()
                        if row:
                            if not mod: mod = row["category"] if "category" in row.keys() else None
                            if not ext: ext = str(row["extracode"]) if ("extracode" in row.keys() and row["extracode"]) else None
                            if not ename: ename = row["examname"] if "examname" in row.keys() else None
                        con.close()
                    except Exception:
                        pass

            cfg_db.upsert_local_assignment(eid_int, diagnostician_id, diagnostician_name, now_iso, modality=mod, extracode=ext, is_auto=False)
        except Exception as e:
            logger.warning("local_assignment_update_failed", error=str(e))

        return log_entry

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
        )


def _get_pending_exams_from_db() -> list[dict]:
    """Fetch pending exams (unassigned in Slis and not yet staged in df_local_assignments).

    In production: Direct MSSQL execution of getExamsListForPeriod_V1 for the last 3 days.
    In mock mode: Reads from SQLite mock_slis.db.

    Auto-assignments applied directly to df_local_assignments (bypassing filters):
    1. Exclusive partnerships: Exams issued by doctors with an active exclusive
       partnership are automatically assigned to that preferred diagnostician.
    2. Dynamic exam routing rules: Exams matching defined lab, doctor, or exam code
       routing rules are automatically assigned to the designated diagnostician.
    3. Παμμακάριστος general: Other Παμμακάριστος exams are automatically assigned
       to today's on-call diagnostician.
    """
    try:
        from datetime import date, timedelta
        import diagflow.db.diagflow_db as cfg_db
        from diagflow.services.slis_sync import normalize_modality

        local_assignments = cfg_db.get_all_local_assignments()
        today = date.today().isoformat()
        start_date = (date.today() - timedelta(days=3)).isoformat()
        end_date = today

        # Fetch today's Παμμακάριστος on-call diagnostician once
        pam_oncall = cfg_db.get_oncall_diagnostician(today)
        # Fetch active exclusive partnerships once
        exclusive_map = cfg_db.get_exclusive_partnerships()
        # Fetch dynamic routing rules
        routing_rules = cfg_db.get_all_exam_routing_rules()

        raw_exam_rows = []

        if not settings.use_mock_slis_db:
            # ── PRODUCTION MODE: Query Central MSSQL Directly ──
            from sqlalchemy import create_engine, text
            engine = create_engine(settings.slis_db_connection_string, connect_args={"timeout": 10})
            with engine.connect() as conn:
                query = text(f"EXEC getExamsListForPeriod_V1 '{start_date}', '{end_date}'")
                res = conn.execute(query)
                keys = list(res.keys())
                raw_pulled = [dict(zip(keys, r)) for r in res.fetchall()]

            all_pulled = [{k.lower(): v for k, v in r.items()} for r in raw_pulled]

            # Clean orphaned & already-synced local assignments in central DB
            assigned_in_slis_ids = [
                r.get("exammoreid") for r in all_pulled
                if r.get("exammoreid") is not None and r.get("diagnostis") is not None
                and str(r.get("diagnostis")).strip().lower() not in ("", "0", "none", "null")
            ]
            if assigned_in_slis_ids:
                with cfg_db._conn() as local_con:
                    tbl_local = cfg_db._tbl("local_assignments")
                    placeholders_assigned = ",".join(["?"] * len(assigned_in_slis_ids))
                    local_con.execute(f"DELETE FROM {tbl_local} WHERE exammoreid IN ({placeholders_assigned})", assigned_in_slis_ids)
                local_assignments = cfg_db.get_all_local_assignments()

            # Filter for exams with no diagnostician in Slis
            unassigned_rows = [
                r for r in all_pulled
                if r.get("diagnostis") is None or str(r.get("diagnostis")).strip().lower() in ("", "0", "none", "null")
            ]

            for r in unassigned_rows:
                r["category"] = normalize_modality(r.get("category"))
                raw_exam_rows.append(r)
        else:
            # ── MOCK MODE: Query Local SQLite mock_slis.db ──
            cutoff_date = (date.today() - timedelta(days=150)).isoformat()
            con = _get_mock_db()
            cur = con.execute(
                """
                SELECT * FROM slis_exams
                WHERE (diagnostis IS NULL OR diagnostis = '' OR diagnostis = '0' OR LOWER(diagnostis) = 'none')
                  AND visitdate >= ?
                ORDER BY visitdate DESC, extracode ASC
                """,
                (cutoff_date,)
            )
            raw_exam_rows = [dict(r) for r in cur.fetchall()]
            con.close()

        rows = []
        now_iso = datetime.now().isoformat()
        for r in raw_exam_rows:
            exam_id = int(r["exammoreid"])
            _exam_details_cache[exam_id] = {
                "exammoreid": exam_id,
                "extracode": r.get("extracode"),
                "category": r.get("category"),
                "modality": r.get("category"),
                "examname": r.get("examname") or r.get("exam_name") or r.get("exam_title") or "",
                "examnumcode": r.get("examnumcode"),
                "patient_name": f"{r.get('fname') or ''} {r.get('lname') or ''}".strip(),
            }
            if exam_id in local_assignments:
                continue  # already handled (staged in df_local_assignments)

            doc_id = str(r.get("wcode")) if r.get("wcode") else ""

            # Check 1: Exclusive partner auto-assignment (bypasses all filters)
            if doc_id and doc_id in exclusive_map:
                ex_part = exclusive_map[doc_id]
                cfg_db.upsert_local_assignment(
                    exam_id,
                    ex_part["preferred_diagnostician_id"],
                    ex_part["preferred_diagnostician_name"],
                    now_iso,
                    modality=r.get("category"),
                    extracode=str(r.get("extracode")) if r.get("extracode") else None,
                    is_auto=True,
                    rule_desc="Συνεργάτης (Αποκλειστικότητα)"
                )
                logger.info(
                    "exclusive_partner_auto_assigned",
                    exam_id=exam_id,
                    doctor=doc_id,
                    diagnostician=ex_part["preferred_diagnostician_name"],
                )
                continue

            # Check 2: Dynamic Exam Routing Rules (Replaces hardcoded lab & exam rules)
            exam_code_str = str(r.get("examnumcode") or "").strip()
            lab_id_val = r.get("labcodeid")
            is_pam = "ΠΑΜΜΑΚΑΡΙΣΤΟΣ" in (r.get("wname") or "").upper()
            
            routed = False
            for rule in routing_rules:
                if not rule.get("is_active", True):
                    continue
                
                lab_match = (rule["lab_id"] is None) or (rule["lab_id"] == lab_id_val)
                pam_match = (not rule["is_pamakristos"]) or is_pam
                doc_match = (rule.get("issuing_doctor_id") is None) or (rule.get("issuing_doctor_id") == doc_id)
                
                if lab_match and pam_match and doc_match:
                    rule_codes = [c.strip() for c in rule["exam_codes"].split(",")]
                    if exam_code_str in rule_codes:
                        target_id = rule["diagnostician_id"]
                        d_info = cfg_db.get_diagnostician(target_id)
                        d_name = d_info["name"] if d_info else rule["diagnostician_name"]
                        cfg_db.upsert_local_assignment(
                            exam_id, target_id, d_name, now_iso,
                            modality=r.get("category"),
                            extracode=str(r.get("extracode")) if r.get("extracode") else None,
                            is_auto=True,
                            rule_desc=rule["description"]
                        )
                        logger.info("dynamic_rule_auto_assigned", exam_id=exam_id, rule_id=rule["id"], diagnostician=target_id)
                        routed = True
                        break
            
            if routed:
                continue

            # Check 3: Παμμακάριστος general on-call (if not routed by a specific rule)
            if is_pam and pam_oncall:
                cfg_db.upsert_local_assignment(
                    exam_id,
                    pam_oncall["diagnostician_id"],
                    pam_oncall["diagnostician_name"],
                    now_iso,
                    modality=r.get("category"),
                    extracode=str(r.get("extracode")) if r.get("extracode") else None,
                    is_auto=True,
                    rule_desc="Παμμακάριστος Εφημερία"
                )
                logger.info(
                    "pam_exam_auto_assigned",
                    exam_id=exam_id,
                    oncall=pam_oncall["diagnostician_name"],
                )
                continue

            # Normal pending exam
            rows.append(_row_to_exam_dict(r))

        logger.info("pending_exams_loaded", count=len(rows))
        return rows
    except Exception as e:
        logger.error("get_pending_exams_failed", error=str(e))
        return []


def _get_assigned_exams_from_db() -> list[dict]:
    """
    Fetch exams that have been locally assigned in df_local_assignments (staged for Slis push).
    In production: Resolves metadata directly from MSSQL.
    In mock mode: Resolves from SQLite mock_slis.db.
    """
    try:
        from datetime import date, timedelta
        import diagflow.db.diagflow_db as cfg_db
        local_assignments = cfg_db.get_all_local_assignments()
        if not local_assignments:
            return []

        exam_metadata = {}
        if not settings.use_mock_slis_db:
            try:
                from sqlalchemy import create_engine, text
                engine = create_engine(settings.slis_db_connection_string, connect_args={"timeout": 10})
                today = date.today().isoformat()
                start_date = (date.today() - timedelta(days=7)).isoformat()
                with engine.connect() as conn:
                    query = text(f"EXEC getExamsListForPeriod_V1 '{start_date}', '{today}'")
                    res = conn.execute(query)
                    keys = list(res.keys())
                    for r in res.fetchall():
                        r_dict = {k.lower(): v for k, v in zip(keys, r)}
                        if r_dict.get("exammoreid"):
                            eid = int(r_dict["exammoreid"])
                            exam_metadata[eid] = r_dict
                            _exam_details_cache[eid] = {
                                "exammoreid": eid,
                                "extracode": r_dict.get("extracode"),
                                "category": r_dict.get("category"),
                                "modality": r_dict.get("category"),
                                "examname": r_dict.get("examname") or r_dict.get("exam_name") or "",
                                "examnumcode": r_dict.get("examnumcode"),
                            }
            except Exception as e:
                logger.warning("failed_to_fetch_mssql_assigned_metadata", error=str(e))
        else:
            try:
                con = _get_mock_db()
                placeholders = ",".join("?" * len(local_assignments))
                cur = con.execute(
                    f"""
                    SELECT * FROM slis_exams
                    WHERE exammoreid IN ({placeholders})
                    ORDER BY visitdate DESC, extracode ASC
                    """,
                    list(local_assignments.keys())
                )
                for r in cur.fetchall():
                    r_dict = dict(r)
                    exam_metadata[int(r_dict["exammoreid"])] = r_dict
                con.close()
            except Exception as e:
                logger.warning("mock_assigned_read_failed", error=str(e))

        rows = []
        for eid, loc in local_assignments.items():
            meta = exam_metadata.get(eid, {})
            fname = meta.get("fname") or ""
            lname = meta.get("lname") or ""
            pat_name = f"{fname} {lname}".strip() or (meta.get("patient_name") or "")

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
                "modality": loc.get("modality") or meta.get("category") or "MRI",
                "category": loc.get("modality") or meta.get("category") or "MRI",
                "body_part": meta.get("body_part") or "",
                "visitdate": str(meta.get("visitdate") or loc.get("assigned_at") or "")[:10],
                "labcodeid": meta.get("labcodeid"),
                "lab_id": str(meta["labcodeid"]) if meta.get("labcodeid") else None,
                "lab_name": meta.get("laboratoryname") or meta.get("lab_name") or "",
                "wcode": meta.get("wcode"),
                "issuing_doctor_id": str(meta["wcode"]) if meta.get("wcode") else None,
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
                "slis_synced_at": None,
                "suggestion": None,
                "is_pamakristos": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ" in (meta.get("wname") or "").upper(),
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
