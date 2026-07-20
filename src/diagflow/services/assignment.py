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
from datetime import datetime
from pathlib import Path

import structlog

from diagflow.config import settings
from diagflow.engine.filters import CandidateDiagnostician, ExamContext
from diagflow.engine.pipeline import AssignmentPipeline, AssignmentSuggestion

logger = structlog.get_logger(__name__)

# ── Resolve mock DB path relative to the project root ─────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # src/diagflow/services/ → project root
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
        "exam_id":        str(row["extracode"]),
        "extracode":      row["extracode"],
        "visitid":        row["visitid"],
        "exammoreid":     row["exammoreid"],

        # ── Patient ──
        "patient_id":     str(row["demogid"]) if row["demogid"] else None,
        "demogid":        row["demogid"],
        "fname":          row["fname"] or "",
        "lname":          row["lname"] or "",
        "patient_name":   f"{row['fname'] or ''} {row['lname'] or ''}".strip(),

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
        if settings.use_mock_slis_db:
            try:
                con = _get_mock_db()
                import diagflow.db.diagflow_db as cfg_db
                d_info = cfg_db.get_diagnostician(diagnostician_id)
                d_name = d_info["name"] if d_info else None
                con.execute(
                    "UPDATE slis_exams SET diagnostis = ?, code = ? WHERE extracode = ?",
                    (diagnostician_id, d_name, int(exam_id)),
                )
                con.commit()
                con.close()
            except Exception as e:
                logger.warning("mock_db_update_failed", error=str(e))

        return log_entry

    async def override_assignment(
        self,
        exam_id: str,
        original_diagnostician_id: int,
        override_diagnostician_id: int,
        reason: str,
        suggestion: AssignmentSuggestion,
    ) -> dict:
        """
        Override the suggested assignment with a different diagnostician.

        This is the critical feedback signal — every override is logged
        for weight tuning and rule refinement.

        TODO: Write to Slis DB and assignment_log when DB access is available.
        """
        log_entry = {
            "exam_id": exam_id,
            "suggested_diagnostician_id": original_diagnostician_id,
            "final_diagnostician_id": override_diagnostician_id,
            "was_overridden": True,
            "override_reason": reason,
            "rules_fired": json.dumps(suggestion.rules_fired, ensure_ascii=False),
            "score_breakdown": json.dumps(suggestion.score_breakdown, ensure_ascii=False),
            "decision_timestamp": datetime.now().isoformat(),
        }

        logger.warning(
            "assignment_overridden",
            exam_id=exam_id,
            original=original_diagnostician_id,
            override=override_diagnostician_id,
            reason=reason,
        )

        # Update the SQLite mock DB
        if settings.use_mock_slis_db:
            try:
                con = _get_mock_db()
                import diagflow.db.diagflow_db as cfg_db
                d_info = cfg_db.get_diagnostician(override_diagnostician_id)
                d_name = d_info["name"] if d_info else None
                con.execute(
                    "UPDATE slis_exams SET diagnostis = ?, code = ? WHERE extracode = ?",
                    (override_diagnostician_id, d_name, int(exam_id)),
                )
                con.commit()
                con.close()
            except Exception as e:
                logger.warning("mock_db_update_failed", error=str(e))

        return log_entry


def _get_pending_exams_from_db() -> list[dict]:
    """Fetch pending exams from the SQLite mock DB."""
    try:
        con = _get_mock_db()
        cur = con.execute(
            """
            SELECT * FROM slis_exams
            WHERE diagnostis IS NULL
            ORDER BY visitdate DESC, extracode ASC
            """
        )
        rows = [_row_to_exam_dict(r) for r in cur.fetchall()]
        con.close()
        logger.info("pending_exams_loaded_from_db", count=len(rows))
        return rows
    except Exception as e:
        logger.error("mock_db_read_failed", error=str(e))
        return []


def _get_assigned_exams_from_db() -> list[dict]:
    """Fetch assigned exams from the SQLite mock DB."""
    try:
        con = _get_mock_db()
        cur = con.execute(
            """
            SELECT * FROM slis_exams
            WHERE diagnostis IS NOT NULL
            ORDER BY visitdate DESC, extracode ASC
            """
        )
        rows = [_row_to_exam_dict(r) for r in cur.fetchall()]
        con.close()
        logger.info("assigned_exams_loaded_from_db", count=len(rows))
        return rows
    except Exception as e:
        logger.error("mock_db_read_failed", error=str(e))
        return []


def _get_exam_categories_from_db() -> list[dict]:
    """Fetch exam categories from the SQLite mock DB."""
    try:
        con = _get_mock_db()
        cur = con.execute("SELECT examnumcode, name, category FROM exam_categories")
        rows = [dict(r) for r in cur.fetchall()]
        con.close()
        return rows
    except Exception as e:
        logger.error("mock_db_read_failed", error=str(e))
        return []


# ── Inject methods into AssignmentService ─────────────────────────

def _get_pending_exams(self) -> list[dict]:
    """Fetch pending exams (real or mock DB)."""
    if settings.use_mock_slis_db:
        return _get_pending_exams_from_db()
    # TODO: implement real Slis DB query here when available
    return []


def _get_assigned_exams(self) -> list[dict]:
    """Fetch assigned exams (real or mock DB)."""
    if settings.use_mock_slis_db:
        return _get_assigned_exams_from_db()
    return []

def _get_exam_categories(self) -> list[dict]:
    """Fetch exam categories (real or mock DB)."""
    if settings.use_mock_slis_db:
        return _get_exam_categories_from_db()
    return []


AssignmentService.get_pending_exams = _get_pending_exams       # type: ignore
AssignmentService.get_assigned_exams = _get_assigned_exams     # type: ignore
AssignmentService.get_exam_categories = _get_exam_categories   # type: ignore
