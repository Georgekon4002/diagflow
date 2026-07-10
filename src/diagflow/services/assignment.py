"""
DiagFlow — Assignment Service

Handles the full lifecycle of assignments:
- Generating suggestions via the pipeline
- Confirming/overriding suggestions
- Logging decisions to the audit trail
- Writing final assignments back to Slis (when DB access is available)
"""

import json
from datetime import datetime

import structlog

from diagflow.engine.filters import CandidateDiagnostician, ExamContext
from diagflow.engine.pipeline import AssignmentPipeline, AssignmentSuggestion

logger = structlog.get_logger(__name__)


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
        comment_analysis: dict | None = None,
    ) -> AssignmentSuggestion | None:
        """
        Generate an assignment suggestion for a single exam.

        Args:
            exam: The exam requiring assignment
            candidates: All potentially eligible diagnosticians
            comment_analysis: Pre-parsed LLM analysis of comments

        Returns:
            AssignmentSuggestion or None if no valid candidates
        """
        suggestion = self.pipeline.run(exam, candidates, comment_analysis)

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

        TODO: Write to Slis DB and assignment_log when DB access is available.
        """
        log_entry = {
            "exam_id": exam_id,
            "suggested_diagnostician_id": suggestion.suggested_diagnostician_id,
            "final_diagnostician_id": diagnostician_id,
            "was_overridden": False,
            "rules_fired": json.dumps(suggestion.rules_fired, ensure_ascii=False),
            "score_breakdown": json.dumps(suggestion.score_breakdown, ensure_ascii=False),
            "comment_raw": suggestion.comment_raw,
            "comment_parsed": suggestion.comment_parsed,
            "decision_timestamp": datetime.now().isoformat(),
        }

        logger.info(
            "assignment_confirmed",
            exam_id=exam_id,
            diagnostician_id=diagnostician_id,
        )

        # TODO: Write to assignment_log table
        # TODO: Write to Slis assignments table

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
            "comment_raw": suggestion.comment_raw,
            "comment_parsed": suggestion.comment_parsed,
            "decision_timestamp": datetime.now().isoformat(),
        }

        logger.warning(
            "assignment_overridden",
            exam_id=exam_id,
            original=original_diagnostician_id,
            override=override_diagnostician_id,
            reason=reason,
        )

        # TODO: Write to assignment_log table (was_overridden = True)
        # TODO: Write to Slis assignments table

        return log_entry

    async def get_pending_exams(self) -> list[dict]:
        """
        Fetch pending (unassigned) exams from Slis.

        TODO: Replace with real Slis query when DB access is available.
        Returns mock data for development.
        """
        # Mock data for development
        return [
            {
                "exam_id": "EX-2026-001",
                "patient_id": "PT-5432",
                "patient_name": "Γεώργιος Κ.",
                "modality": "MRI",
                "body_part": "abdomen",
                "lab_id": "LAB-KIF",
                "lab_name": "Κηφισιά",
                "issuing_doctor_id": "DR-101",
                "issuing_doctor_name": "Παπαδόπουλος Ν.",
                "request_date": "2026-07-10",
                "status": "pending",
                "comments": "",
            },
            {
                "exam_id": "EX-2026-002",
                "patient_id": "PT-8821",
                "patient_name": "Μαρία Α.",
                "modality": "CT",
                "body_part": "chest",
                "lab_id": "LAB-MAR",
                "lab_name": "Μαρούσι",
                "issuing_doctor_id": "DR-205",
                "issuing_doctor_name": "Ιωάννου Ε.",
                "request_date": "2026-07-10",
                "status": "pending",
                "comments": "Επείγον",
            },
            {
                "exam_id": "EX-2026-003",
                "patient_id": "PT-1190",
                "patient_name": "Δημήτρης Λ.",
                "modality": "MRI",
                "body_part": "neuro",
                "lab_id": "LAB-KIF",
                "lab_name": "Κηφισιά",
                "issuing_doctor_id": "DR-101",
                "issuing_doctor_name": "Παπαδόπουλος Ν.",
                "request_date": "2026-07-10",
                "status": "pending",
                "comments": "ΟΧΙ ΝΑΤΣΙΚΑ, ασθενής ζήτησε συγκεκριμένο ιατρό",
            },
            {
                "exam_id": "EX-2026-004",
                "patient_id": "PT-3301",
                "patient_name": "Ελένη Π.",
                "modality": "CT",
                "body_part": "abdomen",
                "lab_id": "LAB-PAM",
                "lab_name": "Παμμακάριστος",
                "issuing_doctor_id": "DR-PAM-01",
                "issuing_doctor_name": "Παμμακάριστος (Εφημερία)",
                "request_date": "2026-07-10",
                "status": "pending",
                "comments": "ΕΦΗΜΕΡΙΑ ΠΑΜΜΑΚΑΡΙΣΤΟΥ",
            },
            {
                "exam_id": "EX-2026-005",
                "patient_id": "PT-6677",
                "patient_name": "Αντώνης Σ.",
                "modality": "MRI",
                "body_part": "msk",
                "lab_id": "LAB-GLY",
                "lab_name": "Γλυφάδα",
                "issuing_doctor_id": "DR-310",
                "issuing_doctor_name": "Βασιλείου Κ.",
                "request_date": "2026-07-10",
                "status": "pending",
                "comments": "",
            },
        ]
