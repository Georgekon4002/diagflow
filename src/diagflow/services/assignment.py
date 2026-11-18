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
from diagflow.services.slis_sync import normalize_modality

logger = structlog.get_logger(__name__)

# Global in-memory cache for fast suggestion generation and metadata resolution
_exam_details_cache: dict[int, dict] = {}
_pending_exams_cache_data: list[dict] | None = None
_pending_exams_cache_time: float = 0.0


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
    wname = (r.get("wname") or "").upper()
    lab = (r.get("laboratoryname") or r.get("lab_name") or "").upper()
    return "ΠΑΜΜΑΚΑΡΙΣΤ" in wname or "ΠΑΜΑΚΑΡΙΣΤ" in wname or "ΠΑΜΜΑΚΑΡΙΣΤ" in lab or "ΠΑΜΑΚΑΡΙΣΤ" in lab


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

    raw_stat = r.get("stat")
    stat_val = 0
    if raw_stat is not None:
        try:
            stat_val = int(raw_stat)
        except (ValueError, TypeError):
            stat_val = 0

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
        "stat":           stat_val,

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
            vdate = None
            if eid_int in _exam_details_cache:
                c_data = _exam_details_cache[eid_int]
                mod = c_data.get("category") or c_data.get("modality")
                ext = c_data.get("extracode")
                ename = c_data.get("examname")
                vdate = c_data.get("visitdate")
            else:
                mod, ext, ename = None, None, None
            
            if not mod or not ext or not ename or not vdate:
                if not settings.use_mock_slis_db:
                    try:
                        from sqlalchemy import create_engine, text
                        engine = create_engine(settings.slis_db_connection_string, connect_args={"timeout": 5})
                        with engine.connect() as conn:
                            res = conn.execute(text("SELECT category, extracode, examname, visitdate FROM exammore e LEFT JOIN exams ex ON ex.examid = e.examid WHERE e.exammoreid = :id"), {"id": eid_int}).fetchone()
                            if res:
                                if not mod and res[0]: mod = normalize_modality(res[0])
                                if not ext and res[1]: ext = str(res[1])
                                if not ename and res[2]: ename = str(res[2])
                                if not vdate and res[3]: vdate = str(res[3])[:10]
                    except Exception:
                        pass
                else:
                    try:
                        con = _get_mock_db()
                        row = con.execute("SELECT category, extracode, examname, visitdate FROM slis_exams WHERE exammoreid = ?", (eid_int,)).fetchone()
                        if row:
                            if not mod: mod = row["category"] if "category" in row.keys() else None
                            if not ext: ext = str(row["extracode"]) if ("extracode" in row.keys() and row["extracode"]) else None
                            if not ename: ename = row["examname"] if "examname" in row.keys() else None
                            if not vdate and "visitdate" in row.keys() and row["visitdate"]: vdate = str(row["visitdate"])[:10]
                        con.close()
                    except Exception:
                        pass

            if mod:
                mod = normalize_modality(mod)

            cfg_db.upsert_local_assignment(eid_int, diagnostician_id, diagnostician_name, now_iso, modality=mod, extracode=ext, is_auto=False, visitdate=vdate)
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
        # Fetch exams that were explicitly unassigned/dismissed by user
        dismissed_auto_assignments = cfg_db.get_dismissed_auto_assignments()
        # Fetch active diagnosticians and comment auto-assign rule status
        from diagflow.engine.comment_rules import parse_comment_diagnosticians
        active_diagnosticians = [d for d in cfg_db.get_all_diagnosticians() if d.get("active", True)]
        comment_rule_enabled = cfg_db.get_comment_auto_assign_enabled()

        raw_exam_rows = []

        if not settings.use_mock_slis_db:
            # ── PRODUCTION MODE: Query Central MSSQL Directly ──
            _exam_details_cache.clear()
            from sqlalchemy import create_engine, text
            engine = create_engine(settings.slis_db_connection_string, connect_args={"timeout": 10})
            with engine.connect() as conn:
                query = text(f"EXEC getExamsListForPeriod_V1 '{start_date}', '{end_date}'")
                res = conn.execute(query)
                keys = list(res.keys())
                raw_pulled = [dict(zip(keys, r)) for r in res.fetchall()]

            all_pulled = [{k.lower(): v for k, v in r.items()} for r in raw_pulled]
            all_pulled_eids = {r.get("exammoreid") for r in all_pulled if r.get("exammoreid") is not None}

            # Clean orphaned & already-synced local assignments in central DB
            assigned_in_slis_ids = [
                r.get("exammoreid") for r in all_pulled
                if r.get("exammoreid") is not None and r.get("diagnostis") is not None
                and str(r.get("diagnostis")).strip().lower() not in ("", "0", "none", "null")
            ]
            # Also clean local assignments for exams no longer existing in the real period
            stale_or_mock_ids = [
                eid for eid in local_assignments
                if eid not in all_pulled_eids
            ]
            to_delete_local = list(set(assigned_in_slis_ids + stale_or_mock_ids))

            if to_delete_local:
                with cfg_db._conn() as local_con:
                    tbl_local = cfg_db._tbl("local_assignments")
                    placeholders_assigned = ",".join(["?"] * len(to_delete_local))
                    local_con.execute(f"DELETE FROM {tbl_local} WHERE exammoreid IN ({placeholders_assigned})", to_delete_local)
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
            cutoff_date = (date.today() - timedelta(days=3)).isoformat()
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
            exam_vdate = str(r.get("visitdate") or "")[:10]
            raw_stat = r.get("stat")
            stat_val = 0
            if raw_stat is not None:
                try:
                    stat_val = int(raw_stat)
                except (ValueError, TypeError):
                    stat_val = 0

            _exam_details_cache[exam_id] = {
                "exammoreid": exam_id,
                "extracode": r.get("extracode"),
                "category": r.get("category"),
                "modality": r.get("category"),
                "examname": r.get("examname") or r.get("exam_name") or r.get("exam_title") or "",
                "examnumcode": r.get("examnumcode"),
                "patient_name": f"{r.get('fname') or ''} {r.get('lname') or ''}".strip(),
                "visitdate": exam_vdate,
                "stat": stat_val,
            }
            if exam_id in local_assignments:
                continue  # already handled (staged in df_local_assignments)

            if exam_id in dismissed_auto_assignments:
                # User explicitly unassigned/dismissed this auto-assignment — keep as normal pending exam
                rows.append(_row_to_exam_dict(r))
                continue

            # ── Check 0: Comment-based Auto-Assignment & 'ΟΧΙ' Exclusion (Above all rules) ──
            comments_text = str(r.get("notes") or r.get("comments") or "").strip()
            matched_comment_diag = None
            excluded_comment_diag_ids: set[int] = set()

            if comment_rule_enabled and comments_text:
                matched_comment_diag, excluded_comment_diag_ids = parse_comment_diagnosticians(
                    comments_text, active_diagnosticians
                )

            if comment_rule_enabled and matched_comment_diag and matched_comment_diag["id"] not in excluded_comment_diag_ids:
                cfg_db.upsert_local_assignment(
                    exam_id,
                    matched_comment_diag["id"],
                    matched_comment_diag["name"],
                    now_iso,
                    modality=r.get("category"),
                    extracode=str(r.get("extracode")) if r.get("extracode") else None,
                    is_auto=True,
                    rule_desc="Όνομα Διαγνώστη αναφέρθηκε στα σχόλια",
                    visitdate=exam_vdate,
                )
                logger.info(
                    "comment_auto_assigned",
                    exam_id=exam_id,
                    diagnostician=matched_comment_diag["name"],
                    token=matched_comment_diag.get("matched_token"),
                )
                continue

            doc_id = str(r.get("wcode")) if r.get("wcode") else ""

            # Check 1: Exclusive partner auto-assignment (bypasses regular filters, but respects comment exclusion)
            if doc_id and doc_id in exclusive_map:
                ex_part = exclusive_map[doc_id]
                pref_diag_id = ex_part["preferred_diagnostician_id"]
                if pref_diag_id not in excluded_comment_diag_ids:
                    cfg_db.upsert_local_assignment(
                        exam_id,
                        pref_diag_id,
                        ex_part["preferred_diagnostician_name"],
                        now_iso,
                        modality=r.get("category"),
                        extracode=str(r.get("extracode")) if r.get("extracode") else None,
                        is_auto=True,
                        rule_desc="Συνεργάτης (Αποκλειστικότητα)",
                        visitdate=exam_vdate,
                    )
                    logger.info(
                        "exclusive_partner_auto_assigned",
                        exam_id=exam_id,
                        doctor=doc_id,
                        diagnostician=ex_part["preferred_diagnostician_name"],
                    )
                    continue
                else:
                    logger.info(
                        "exclusive_partner_suppressed_by_comment_exclusion",
                        exam_id=exam_id,
                        diagnostician=pref_diag_id,
                    )

            # Check 2: Dynamic Exam Routing Rules (suppressed if target is excluded by comment)
            exam_code_str = str(r.get("examnumcode") or "").strip()
            lab_id_val = r.get("labcodeid")
            is_pam = _is_pamakristos_row(r)
            
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
                        if target_id not in excluded_comment_diag_ids:
                            d_info = cfg_db.get_diagnostician(target_id)
                            d_name = d_info["name"] if d_info else rule["diagnostician_name"]
                            cfg_db.upsert_local_assignment(
                                exam_id, target_id, d_name, now_iso,
                                modality=r.get("category"),
                                extracode=str(r.get("extracode")) if r.get("extracode") else None,
                                is_auto=True,
                                rule_desc=rule["description"],
                                visitdate=exam_vdate,
                            )
                            logger.info("dynamic_rule_auto_assigned", exam_id=exam_id, rule_id=rule["id"], diagnostician=target_id)
                            routed = True
                            break
                        else:
                            logger.info("dynamic_rule_suppressed_by_comment_exclusion", exam_id=exam_id, rule_id=rule["id"], target_id=target_id)
            
            if routed:
                continue

            # Check 3: Παμμακάριστος general on-call (suppressed if on-call is excluded by comment)
            if is_pam and pam_oncall:
                pam_diag_id = pam_oncall["diagnostician_id"]
                if pam_diag_id not in excluded_comment_diag_ids:
                    cfg_db.upsert_local_assignment(
                        exam_id,
                        pam_diag_id,
                        pam_oncall["diagnostician_name"],
                        now_iso,
                        modality=r.get("category"),
                        extracode=str(r.get("extracode")) if r.get("extracode") else None,
                        is_auto=True,
                        rule_desc="Παμμακάριστος Εφημερία",
                        visitdate=exam_vdate,
                    )
                    logger.info(
                        "pam_exam_auto_assigned",
                        exam_id=exam_id,
                        oncall=pam_oncall["diagnostician_name"],
                    )
                    continue
                else:
                    logger.info("pam_oncall_suppressed_by_comment_exclusion", exam_id=exam_id, oncall=pam_diag_id)

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
        from diagflow.services.slis_sync import normalize_modality
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
                            raw_s = r_dict.get("stat")
                            s_val = 0
                            if raw_s is not None:
                                try:
                                    s_val = int(raw_s)
                                except (ValueError, TypeError):
                                    s_val = 0
                            _exam_details_cache[eid] = {
                                "exammoreid": eid,
                                "extracode": r_dict.get("extracode"),
                                "category": normalize_modality(r_dict.get("category")),
                                "modality": normalize_modality(r_dict.get("category")),
                                "examname": r_dict.get("examname") or r_dict.get("exam_name") or "",
                                "examnumcode": r_dict.get("examnumcode"),
                                "stat": s_val,
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
            if not settings.use_mock_slis_db and eid not in exam_metadata:
                # In production, skip and purge orphaned mock or out-of-window staged assignments
                try:
                    cfg_db.delete_local_assignment(eid)
                except Exception:
                    pass
                continue

            meta = exam_metadata.get(eid, {})
            fname = meta.get("fname") or ""
            lname = meta.get("lname") or ""
            pat_name = f"{fname} {lname}".strip() or (meta.get("patient_name") or "")
            norm_mod = normalize_modality(loc.get("modality") or meta.get("category"))

            meta_stat = 0
            if meta.get("stat") is not None:
                try:
                    meta_stat = int(meta["stat"])
                except (ValueError, TypeError):
                    meta_stat = 0
            elif eid in _exam_details_cache and "stat" in _exam_details_cache[eid]:
                meta_stat = _exam_details_cache[eid]["stat"]

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
