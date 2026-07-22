"""
DiagFlow — Diagnostician Service

Provides queries and data loading for diagnosticians,
their skills, capacity, availability, and partnerships.

Data source: diagflow.db (via diagflow_db module) — persisted across restarts.
"""

from datetime import date

import structlog

from diagflow.engine.filters import CandidateDiagnostician
import diagflow.db.diagflow_db as cfg_db

logger = structlog.get_logger(__name__)


class DiagnosticianService:
    """
    Service for loading and querying diagnostician data.
    Reads directly from diagflow.db — all data persists across server restarts.
    """

    async def get_candidates_for_exam(
        self,
        exam_id: str,
        modality: str,
        body_part: str,
        lab_id: str,
        issuing_doctor_id: str,
        patient_id: str,
        exam_code: str = "",
        lab_name: str = "",
    ) -> list[CandidateDiagnostician]:
        """
        Load all potentially eligible diagnosticians for an exam.

        For each diagnostician from diagflow.db:
        - Checks availability (on_leave for today)
        - Checks skills (exact exam_code match)
        - Checks partnership (issuing doctor preference)
        - Derives can_ct / can_mri flags
        """
        today = str(date.today())

        # Load all diagnosticians from DB
        all_diags = cfg_db.get_all_diagnosticians()

        # Load absent IDs for today
        absent_ids = cfg_db.get_absent_diagnostician_ids(today)

        # Load partnerships for this issuing doctor
        partnerships = cfg_db.get_partnerships_by_doctor(issuing_doctor_id)
        partnership_map: dict[int, dict] = {
            p["preferred_diagnostician_id"]: p for p in partnerships if p.get("is_active", 1) == 1
        }

        # Load current daily counts from assignment log
        daily_counts = cfg_db.get_daily_assignment_counts()

        candidates = []

        for diag in all_diags:
            if not diag["active"]:
                continue

            diag_id = int(diag["id"])

            # Skills: load from DB
            skills = cfg_db.get_skills_for_diagnostician(diag_id)

            # Determine skill match for this exam code
            skill_match = None
            for skill in skills:
                if str(skill["exam_code"]) == str(exam_code):
                    skill_match = skill
                    break

            if skill_match:
                skill_proficiency = 2 if skill_match.get("is_preferred") else 1
            else:
                skill_proficiency = 0

            # Modality capability
            can_ct = bool(diag["can_ct"])
            can_mri = bool(diag["can_mri"])
            preferred_lab_id = diag.get("preferred_lab_id")

            # Check if diagnostician is absent
            is_available = diag_id not in absent_ids

            # Find quota based on weekday
            weekday_str = date.today().strftime("%A").lower()
            quota_key = f"quota_{weekday_str}"
            daily_quota = diag.get(quota_key, 0)
            
            # Check for partnership match
            pship = partnership_map.get(diag_id)
            is_partner = pship is not None
            is_exclusive = bool(pship.get("exclusive", 0)) if pship else False

            # Patient history — not yet tracked in DB; default to no history
            has_history = False
            history_count = 0

            candidate = CandidateDiagnostician(
                id=diag_id,
                name=str(diag["name"]),
                can_ct=can_ct,
                can_mri=can_mri,
                is_available=is_available,
                daily_quota=daily_quota,
                current_day_count=daily_counts.get(diag_id, 0),
                current_subcategory_count=0,  # TODO: track per body-part
                subcategory_soft_cap=None,
                skill_proficiency=skill_proficiency,
                has_skill_match=skill_match is not None,
                has_skill_data=len(skills) > 0,
                accepts_lab=True,
                is_partnership_match=is_partner,
                is_partnership_exclusive=is_exclusive,
                has_patient_history=has_history,
                patient_history_count=history_count,
            )
            # Monkey-patch preferred_lab_id onto the candidate object to be used by scoring.py
            setattr(candidate, "preferred_lab_id", preferred_lab_id)
            
            candidates.append(candidate)

        logger.info(
            "candidates_loaded",
            exam_id=exam_id,
            total=len(candidates),
        )

        return candidates

    async def get_all_diagnosticians(self) -> list[dict]:
        """Get all active diagnosticians for the UI dropdown/list."""
        diags = cfg_db.get_all_diagnosticians()
        counts = cfg_db.get_daily_assignment_counts()
        today = str(date.today())
        absent_ids = cfg_db.get_absent_diagnostician_ids(today)

        return [
            {
                "id": d["id"],
                "name": d["name"],
                "can_ct": bool(d["can_ct"]),
                "can_mri": bool(d["can_mri"]),
                "quota_monday": d["quota_monday"],
                "quota_tuesday": d["quota_tuesday"],
                "quota_wednesday": d["quota_wednesday"],
                "quota_thursday": d["quota_thursday"],
                "quota_friday": d["quota_friday"],
                "quota_saturday": d["quota_saturday"],
                "quota_sunday": d["quota_sunday"],
                "current_day_count": counts.get(d["id"], 0),
                "available": bool(d["active"]) and (d["id"] not in absent_ids),
            }
            for d in diags
            if d["active"]
        ]
