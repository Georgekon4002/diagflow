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
    con = sqlite3.connect(str(_MOCK_DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def _row_to_exam_dict(row: sqlite3.Row) -> dict:
    """
    Convert a slis_exams SQLite row into the exam dict format
    that the API routes and engine expect.
    """
    return {
        # ── Identifiers ──
        # exam_id is exammoreid (globally unique per exam instance).
        # extracode is the order ID — one order can contain multiple exams.
        "exam_id":        str(row["exammoreid"]),
        "extracode":      row["extracode"],
        "visitid":        row["visitid"],
        "exammoreid":     row["exammoreid"],

        # ── Patient ──
        "patient_id":     str(row["demogid"]) if row["demogid"] else None,
        "demogid":        row["demogid"],
        "fname":          row["fname"] or "",
        "lname":          row["lname"] or "",
        "patient_name":   f"{row['fname'] or ''} {row['lname'] or ''}".strip(),
        "age":            row["age"] if "age" in row.keys() else None,

        # ── Exam type ──
        "examnumcode":    row["examnumcode"],
        "examname":       row["examname"] or "",
        "modality":       row["category"] or "MRI",   # CT | MRI | MRA → used by engine
        "category":       row["category"] or "",
        "body_part":      "",   # Not in Slis data; filled by engine if needed

        # ── Visit logistics ──
        "visitdate":      row["visitdate"],
        "request_date":   row["visitdate"],            # alias used by frontend

        # ── Lab ──
        "labcodeid":      row["labcodeid"],
        "lab_id":         str(row["labcodeid"]) if row["labcodeid"] else None,
        "lab_name":       (row["laboratoryname"] or "").strip(),

        # ── Issuing doctor ──
        "wcode":              row["wcode"],
        "issuing_doctor_id":  str(row["wcode"]) if row["wcode"] else None,
        "wname":              row["wname"] or "",
        "issuing_doctor_name": row["wname"] or "",

        # ── Assignment ──
        "diagnostis":     row["diagnostis"],
        "code":           row["code"] or "",
        "diagnostician_name": row["code"] or "",       # last-name / code
        "status":         "assigned" if row["diagnostis"] else "pending",

        # ── Notes ──
        "notes":          row["notes"] or "",
        "comments":       row["notes"] or "",          # alias used by engine

        # ── OLD (last same-exam-type visit) ──
        "oldvisit":       row["oldvisit"] or 0,
        "oldorder":       row["oldorder"] or "",
        "olddiagnostis":  row["olddiagnostis"] or "",
        "oldpers":        row["oldpers"],

        # ── Slis sync tracking ──
        # None = assigned locally but NOT yet pushed to Slis
        # value = ISO timestamp of the push (row will expire on next pull)
        "slis_synced_at": row["slis_synced_at"] if "slis_synced_at" in row.keys() else None,

        # ── Extras ──
        "suggestion":     None,
        "is_pamakristos": False,
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
        suggestion: AssignmentSuggestion,
    ) -> dict:
        """
        Confirm the suggested assignment (no override).

        TODO: Write back to Slis DB when real DB access is available.
        """
        log_entry = {
            "exam_id": exam_id,
            "suggested_diagnostician_id": suggestion.suggested_diagnostician_id,
            "final_diagnostician_id": diagnostician_id,
            "was_overridden": False,
            "rules_fired": json.dumps(suggestion.rules_fired, ensure_ascii=False),
            "score_breakdown": json.dumps(suggestion.score_breakdown, ensure_ascii=False),
            "decision_timestamp": datetime.now().isoformat(),
        }

        logger.info(
            "assignment_confirmed",
            exam_id=exam_id,
            diagnostician_id=diagnostician_id,
        )

        # Update the SQLite mock DB so the assignment persists
        try:
            import diagflow.db.diagflow_db as cfg_db
            d_info = cfg_db.get_diagnostician(diagnostician_id)
            d_name = d_info["name"] if d_info else ""
            
            # Fetch modality and extracode from mock_slis.db
            mod, ext = None, None
            try:
                con = _get_mock_db()
                row = con.execute("SELECT category, extracode FROM slis_exams WHERE exammoreid = ?", (int(exam_id),)).fetchone()
                if row:
                    mod = row["category"]
                    ext = str(row["extracode"]) if row["extracode"] else None
            except Exception as db_e:
                logger.warning("failed_to_fetch_exam_details", error=str(db_e))

            cfg_db.upsert_local_assignment(int(exam_id), diagnostician_id, d_name, datetime.now().isoformat(), modality=mod, extracode=ext)
        except Exception as e:
            logger.warning("local_assignment_update_failed", error=str(e))

        return log_entry

    async def override_assignment(
        self,
        exam_id: str,
        original_diagnostician_id: int,
        override_diagnostician_id: int,
        reason: str,
        suggestion: AssignmentSuggestion | None = None,
    ) -> dict:
        """
        Override the suggested assignment with a different diagnostician.

        This is the critical feedback signal — every override is logged
        for weight tuning and rule refinement.
        """
        log_entry = {
            "exam_id": exam_id,
            "suggested_diagnostician_id": original_diagnostician_id,
            "final_diagnostician_id": override_diagnostician_id,
            "was_overridden": True,
            "override_reason": reason,
            "rules_fired": json.dumps(suggestion.rules_fired, ensure_ascii=False) if suggestion else "[]",
            "score_breakdown": json.dumps(suggestion.score_breakdown, ensure_ascii=False) if suggestion else "[]",
            "decision_timestamp": datetime.now().isoformat(),
        }

        logger.warning(
            "assignment_overridden",
            exam_id=exam_id,
            original=original_diagnostician_id,
            override=override_diagnostician_id,
            reason=reason,
        )

        # Update the local assignments DB
        try:
            import diagflow.db.diagflow_db as cfg_db
            d_info = cfg_db.get_diagnostician(override_diagnostician_id)
            d_name = d_info["name"] if d_info else ""

            # Fetch modality and extracode from mock_slis.db
            mod, ext = None, None
            try:
                con = _get_mock_db()
                row = con.execute("SELECT category, extracode FROM slis_exams WHERE exammoreid = ?", (int(exam_id),)).fetchone()
                if row:
                    mod = row["category"]
                    ext = str(row["extracode"]) if row["extracode"] else None
            except Exception as db_e:
                logger.warning("failed_to_fetch_exam_details", error=str(db_e))

            cfg_db.upsert_local_assignment(int(exam_id), override_diagnostician_id, d_name, datetime.now().isoformat(), modality=mod, extracode=ext)
        except Exception as e:
            logger.warning("local_assignment_update_failed", error=str(e))

        return log_entry


def _get_pending_exams_from_db() -> list[dict]:
    """Fetch pending exams from the SQLite mock DB (past 3 days, no diagnostician).

    Auto-assignments applied directly to local_assignments (bypassing filters):
    1. Exclusive partnerships: Exams issued by doctors with an active exclusive
       partnership are automatically assigned to that preferred diagnostician.
    2. Dynamic exam routing rules: Exams matching defined lab, doctor, or exam code
       routing rules are automatically assigned to the designated diagnostician.
    3. Παμμακάριστος general: Other Παμμακάριστος exams are automatically assigned
       to today's on-call diagnostician.

    All auto-assigned exams appear directly in the assigned tab. Slis is NOT
    updated automatically; the secretariat must push manually as usual.
    """
    try:
        from datetime import date, timedelta
        import diagflow.db.diagflow_db as cfg_db
        local_assignments = cfg_db.get_all_local_assignments()
        cutoff_date = (date.today() - timedelta(days=150)).isoformat()
        today = date.today().isoformat()

        # Fetch today's Παμμακάριστος on-call diagnostician once
        pam_oncall = cfg_db.get_oncall_diagnostician(today)
        # Fetch active exclusive partnerships once
        exclusive_map = cfg_db.get_exclusive_partnerships()
        # Fetch dynamic routing rules
        routing_rules = cfg_db.get_all_exam_routing_rules()

        con = _get_mock_db()
        cur = con.execute(
            """
            SELECT * FROM slis_exams
            WHERE diagnostis IS NULL
              AND visitdate >= ?
            ORDER BY visitdate DESC, extracode ASC
            """,
            (cutoff_date,)
        )
        rows = []
        now_iso = datetime.now().isoformat()
        for r in cur.fetchall():
            exam_id = int(r["exammoreid"])
            if exam_id in local_assignments:
                continue  # already handled (assigned locally)

            doc_id = str(r["wcode"]) if r["wcode"] else ""

            # Check 1: Exclusive partner auto-assignment (bypasses all filters)
            if doc_id and doc_id in exclusive_map:
                ex_part = exclusive_map[doc_id]
                cfg_db.upsert_local_assignment(
                    exam_id,
                    ex_part["preferred_diagnostician_id"],
                    ex_part["preferred_diagnostician_name"],
                    now_iso,
                    modality=r["category"] if "category" in r.keys() else None,
                    extracode=str(r["extracode"]) if ("extracode" in r.keys() and r["extracode"]) else None,
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
            exam_code_str = str(r["examnumcode"]).strip() if ("examnumcode" in r.keys() and r["examnumcode"]) else ""
            lab_id_val = r["labcodeid"] if "labcodeid" in r.keys() else None
            is_pam = "ΠΑΜΜΑΚΑΡΙΣΤΟΣ" in (r.get("wname") or "").upper() if hasattr(r, "get") else "ΠΑΜΜΑΚΑΡΙΣΤΟΣ" in (r["wname"] or "").upper() if "wname" in r.keys() else False
            
            routed = False
            for rule in routing_rules:
                if not rule.get("is_active", True):
                    continue
                
                # Does the rule apply to this exam?
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
                            modality=r["category"] if "category" in r.keys() else None,
                            extracode=str(r["extracode"]) if ("extracode" in r.keys() and r["extracode"]) else None,
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
                    modality=r["category"] if "category" in r.keys() else None,
                    extracode=str(r["extracode"]) if ("extracode" in r.keys() and r["extracode"]) else None,
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

        con.close()
        logger.info("pending_exams_loaded_from_db", count=len(rows))
        return rows
    except Exception as e:
        logger.error("mock_db_read_failed", error=str(e))
        return []



def _get_assigned_exams_from_db() -> list[dict]:
    """
    Fetch exams that have been locally assigned but NOT yet pushed to Slis.
    """
    try:
        import diagflow.db.diagflow_db as cfg_db
        local_assignments = cfg_db.get_all_local_assignments()
        if not local_assignments:
            return []
            
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
        rows = []
        for r in cur.fetchall():
            exam_dict = _row_to_exam_dict(r)
            loc = local_assignments[int(exam_dict["exammoreid"])]
            exam_dict["diagnostis"] = loc["diagnostician_id"]
            exam_dict["code"] = loc["diagnostician_name"]
            exam_dict["diagnostician_name"] = loc["diagnostician_name"]
            exam_dict["status"] = "assigned"
            exam_dict["is_auto_assigned"] = bool(loc.get("is_auto", False))
            exam_dict["rule_desc"] = loc.get("rule_desc", "")
            rows.append(exam_dict)
        con.close()
        logger.info("assigned_exams_loaded_from_db", count=len(rows))
        return rows
    except Exception as e:
        logger.error("mock_db_read_failed", error=str(e))
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
