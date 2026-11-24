"""
DiagFlow — Diagnostician Service

Provides queries and data loading for diagnosticians,
their skills, capacity, availability, and partnerships.

Data source: diagflow.db (via diagflow_db module) — persisted across restarts.
"""

from datetime import date
import asyncio

import structlog

from diagflow.engine.filters import CandidateDiagnostician, ExamContext
from diagflow.services.slis_sync import normalize_doctor_id
import diagflow.db.diagflow_db as cfg_db

logger = structlog.get_logger(__name__)


def _safe_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None


class DiagnosticianService:
    """
    Service for loading and querying diagnostician data.
    Reads directly from diagflow.db — all data persists across server restarts.
    """
    _cache_timestamp: float = 0.0
    _cached_all_diags: list = []
    _cached_absent_ids: set = set()
    _cached_daily_counts: dict = {}
    _cached_skills_by_diag: dict = {}

    @classmethod
    def clear_cache(cls):
        """Invalidate in-memory cache to force fresh DB read on next query."""
        cls._cache_timestamp = 0.0
        cls._cached_all_diags = []
        cls._cached_absent_ids = set()
        cls._cached_daily_counts = {}
        cls._cached_skills_by_diag = {}

    def _get_candidates_for_exam_sync(
        self,
        exam_id: str,
        modality: str,
        body_part: str,
        lab_id: str,
        issuing_doctor_id: str,
        patient_id: str,
        exam_code: str = "",
        lab_name: str = "",
        oldpers: int | None = None,
        exam_date: str | date | None = None,
    ) -> list[CandidateDiagnostician]:
        target_dt = cfg_db._parse_date_safe(exam_date) if exam_date is not None else date.today()
        target_date_str = target_dt.isoformat()
        oldpers_int = _safe_int(oldpers)

        all_diags = cfg_db.get_all_diagnosticians()
        # Keep leave check against target_date_str (exam date) per user instruction
        absent_ids = cfg_db.get_absent_diagnostician_ids(target_date_str)
        daily_counts = cfg_db.get_daily_assignment_counts(target_date_str)
        all_skills_by_diag = cfg_db.get_all_skills_grouped()

        # Pre-calculate configured exam codes across all diagnosticians
        all_configured_exam_codes = {
            str(sk["exam_code"]).strip()
            for diag_skills in all_skills_by_diag.values()
            for sk in diag_skills
            if sk.get("exam_code")
        }
        clean_exam_code = str(exam_code or "").strip()
        exam_code_has_skills = bool(clean_exam_code) and (clean_exam_code in all_configured_exam_codes)

        # Load partnerships for this issuing doctor (normalized ID)
        norm_doc_id = normalize_doctor_id(issuing_doctor_id)
        partnerships = cfg_db.get_partnerships_by_doctor(norm_doc_id) if norm_doc_id else []
        partnership_map: dict[int, dict] = {
            int(p["preferred_diagnostician_id"]): p for p in partnerships if p.get("is_active", 1) == 1
        }

        candidates = []

        # Pre-compute locale-independent weekday quota column for target exam date
        quota_key = cfg_db.get_weekday_quota_key(target_dt)
        weekday_str = quota_key.replace("quota_", "")

        for diag in all_diags:
            if not diag["active"]:
                continue

            diag_id = int(diag["id"])

            # Skills: fetched from the pre-loaded batch map (no extra DB hit)
            skills = all_skills_by_diag.get(diag_id, [])

            # Determine skill match for this exam code
            skill_match = None
            for skill in skills:
                if str(skill["exam_code"]).strip() == clean_exam_code:
                    skill_match = skill
                    break

            if skill_match:
                skill_proficiency = 1.0 if skill_match.get("is_preferred") else 0.5
            else:
                skill_proficiency = 0.0

            # Modality capability
            can_ct = bool(diag["can_ct"])
            can_mri = bool(diag["can_mri"])
            preferred_lab_id = diag.get("preferred_lab_id")

            # Check if diagnostician is absent on exam date
            is_available = diag_id not in absent_ids

            # Daily quota for exam date's weekday (safe against NULL in DB)
            raw_quota = diag.get(quota_key)
            daily_quota = 0 if raw_quota is None else int(raw_quota)

            # Check for partnership match
            pship = partnership_map.get(diag_id)
            is_partner = pship is not None
            is_exclusive = bool(pship.get("exclusive", 0)) if pship else False

            # Patient history (uses local parameter, never mutates shared self)
            has_history = False
            history_count = 0
            if oldpers_int is not None and oldpers_int != 0 and oldpers_int == diag_id:
                has_history = True
                history_count = 1

            counts_dict = daily_counts.get(diag_id, {"total": 0, "mri": 0, "ct": 0})
            if isinstance(counts_dict, int):
                counts_dict = {"total": counts_dict, "mri": 0, "ct": 0}

            # Only enforce hard skills filter when this exam code actually has skill records configured
            has_skill_data = exam_code_has_skills

            candidate = CandidateDiagnostician(
                id=diag_id,
                name=str(diag["name"]),
                can_ct=can_ct,
                can_mri=can_mri,
                is_available=is_available,
                daily_quota=daily_quota,
                current_day_count=counts_dict.get("total", 0),
                current_day_mri_count=counts_dict.get("mri", 0),
                current_day_ct_count=counts_dict.get("ct", 0),
                skill_proficiency=skill_proficiency,
                has_skill_match=skill_match is not None,
                has_skill_data=has_skill_data,
                accepts_lab=True,
                preferred_lab_id=preferred_lab_id,
                is_partnership_match=is_partner,
                is_partnership_exclusive=is_exclusive,
                has_patient_history=has_history,
                patient_history_count=history_count,
            )

            candidates.append(candidate)

        logger.info(
            "candidates_loaded",
            exam_id=exam_id,
            exam_date=target_date_str,
            weekday=weekday_str,
            total=len(candidates),
        )

        return candidates

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
        oldpers: int | None = None,
        exam_date: str | date | None = None,
    ) -> list[CandidateDiagnostician]:
        """Load all potentially eligible diagnosticians for an exam (non-blocking)."""
        return await asyncio.to_thread(
            self._get_candidates_for_exam_sync,
            exam_id,
            modality,
            body_part,
            lab_id,
            issuing_doctor_id,
            patient_id,
            exam_code,
            lab_name,
            oldpers,
            exam_date,
        )

    def _get_candidates_for_exams_batch_sync(
        self,
        exams: list[ExamContext],
    ) -> dict[str, list[CandidateDiagnostician]]:
        if not exams:
            return {}

        all_diags = cfg_db.get_all_diagnosticians()
        all_skills_by_diag = cfg_db.get_all_skills_grouped()

        # Gather distinct exam dates across the batch
        unique_dates: set[str] = set()
        for e in exams:
            dt_obj = cfg_db._parse_date_safe(e.request_date) if e.request_date else date.today()
            unique_dates.add(dt_obj.isoformat())

        absent_ids_by_date = cfg_db.get_absent_diagnostician_ids_for_dates(unique_dates)
        daily_counts_by_date = cfg_db.get_daily_assignment_counts_for_dates(unique_dates)

        # Gather all unique normalized doctor IDs across the batch (1 batched query, no N+1)
        doctor_ids = [
            norm_id
            for e in exams
            if e.issuing_doctor_id and (norm_id := normalize_doctor_id(e.issuing_doctor_id))
        ]
        doctor_partnerships_batch = cfg_db.get_partnerships_for_doctors(doctor_ids)

        all_configured_exam_codes = {
            str(sk["exam_code"]).strip()
            for diag_skills in all_skills_by_diag.values()
            for sk in diag_skills
            if sk.get("exam_code")
        }

        batch_result: dict[str, list[CandidateDiagnostician]] = {}

        for exam in exams:
            clean_exam_code = str(exam.exam_code or "").strip()
            exam_code_has_skills = bool(clean_exam_code) and (clean_exam_code in all_configured_exam_codes)

            target_dt = cfg_db._parse_date_safe(exam.request_date) if exam.request_date else date.today()
            target_dt_str = target_dt.isoformat()
            quota_key = cfg_db.get_weekday_quota_key(target_dt)

            absent_ids = absent_ids_by_date.get(target_dt_str, set())
            daily_counts = daily_counts_by_date.get(target_dt_str, {})

            norm_doc_id = normalize_doctor_id(exam.issuing_doctor_id)
            if norm_doc_id and norm_doc_id in doctor_partnerships_batch:
                partnerships = doctor_partnerships_batch[norm_doc_id]
            elif norm_doc_id:
                partnerships = cfg_db.get_partnerships_by_doctor(norm_doc_id)
                doctor_partnerships_batch[norm_doc_id] = partnerships
            else:
                partnerships = []

            partnership_map: dict[int, dict] = {
                int(p["preferred_diagnostician_id"]): p for p in partnerships if p.get("is_active", 1) == 1
            }

            oldpers_int = _safe_int(exam.oldpers)
            candidates: list[CandidateDiagnostician] = []

            for diag in all_diags:
                if not diag["active"]:
                    continue

                diag_id = int(diag["id"])
                skills = all_skills_by_diag.get(diag_id, [])

                skill_match = None
                for skill in skills:
                    if str(skill["exam_code"]).strip() == clean_exam_code:
                        skill_match = skill
                        break

                if skill_match:
                    skill_proficiency = 1.0 if skill_match.get("is_preferred") else 0.5
                else:
                    skill_proficiency = 0.0

                can_ct = bool(diag["can_ct"])
                can_mri = bool(diag["can_mri"])
                preferred_lab_id = diag.get("preferred_lab_id")
                is_available = diag_id not in absent_ids
                raw_quota = diag.get(quota_key)
                daily_quota = 0 if raw_quota is None else int(raw_quota)

                pship = partnership_map.get(diag_id)
                is_partner = pship is not None
                is_exclusive = bool(pship.get("exclusive", 0)) if pship else False

                has_history = False
                history_count = 0
                if oldpers_int is not None and oldpers_int != 0 and oldpers_int == diag_id:
                    has_history = True
                    history_count = 1

                counts_dict = daily_counts.get(diag_id, {"total": 0, "mri": 0, "ct": 0})
                if isinstance(counts_dict, int):
                    counts_dict = {"total": counts_dict, "mri": 0, "ct": 0}

                has_skill_data = exam_code_has_skills

                candidate = CandidateDiagnostician(
                    id=diag_id,
                    name=str(diag["name"]),
                    can_ct=can_ct,
                    can_mri=can_mri,
                    is_available=is_available,
                    daily_quota=daily_quota,
                    current_day_count=counts_dict.get("total", 0),
                    current_day_mri_count=counts_dict.get("mri", 0),
                    current_day_ct_count=counts_dict.get("ct", 0),
                    skill_proficiency=skill_proficiency,
                    has_skill_match=skill_match is not None,
                    has_skill_data=has_skill_data,
                    accepts_lab=True,
                    preferred_lab_id=preferred_lab_id,
                    is_partnership_match=is_partner,
                    is_partnership_exclusive=is_exclusive,
                    has_patient_history=has_history,
                    patient_history_count=history_count,
                )
                candidates.append(candidate)

            batch_result[str(exam.exam_id)] = candidates

        return batch_result

    async def get_candidates_for_exams_batch(
        self,
        exams: list[ExamContext],
    ) -> dict[str, list[CandidateDiagnostician]]:
        """High-performance non-blocking batch candidate evaluation."""
        return await asyncio.to_thread(self._get_candidates_for_exams_batch_sync, exams)

    def _get_all_diagnosticians_sync(self) -> list[dict]:
        diags = cfg_db.get_all_diagnosticians()
        counts_by_date_map = cfg_db.get_all_assignment_counts_by_date()
        today_dt = date.today()
        today = today_dt.isoformat()
        absent_ids = cfg_db.get_absent_diagnostician_ids(today)
        quota_key = cfg_db.get_weekday_quota_key(today_dt)

        return [
            {
                "id": d["id"],
                "name": d["name"],
                "can_ct": bool(d["can_ct"]),
                "can_mri": bool(d["can_mri"]),
                "quota_monday": d["quota_monday"] if d.get("quota_monday") is not None else 0,
                "quota_tuesday": d["quota_tuesday"] if d.get("quota_tuesday") is not None else 0,
                "quota_wednesday": d["quota_wednesday"] if d.get("quota_wednesday") is not None else 0,
                "quota_thursday": d["quota_thursday"] if d.get("quota_thursday") is not None else 0,
                "quota_friday": d["quota_friday"] if d.get("quota_friday") is not None else 0,
                "quota_saturday": d["quota_saturday"] if d.get("quota_saturday") is not None else 0,
                "quota_sunday": d["quota_sunday"] if d.get("quota_sunday") is not None else 0,
                "current_day_count": counts_by_date_map.get(d["id"], {}).get(today, 0),
                "counts_by_date": counts_by_date_map.get(d["id"], {}),
                "available": bool(d["active"]) and (d["id"] not in absent_ids) and ((d.get(quota_key) or 0) > 0),
            }
            for d in diags
            if d["active"]
        ]

    async def get_all_diagnosticians(self) -> list[dict]:
        """Get all active diagnosticians for the UI dropdown/list with counts_by_date."""
        return await asyncio.to_thread(self._get_all_diagnosticians_sync)
