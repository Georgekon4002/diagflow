"""
DiagFlow — Diagnostician Service

Provides queries and data loading for diagnosticians,
their skills, capacity, availability, and partnerships.

TODO: Replace mock data with real DB queries when Slis access is available.
"""

from datetime import date

import structlog

from diagflow.engine.filters import CandidateDiagnostician

logger = structlog.get_logger(__name__)


class DiagnosticianService:
    """
    Service for loading and querying diagnostician data.

    Currently returns mock data. Will be connected to the config DB
    once database access is available.
    """

    # ── Mock diagnostician data for development ──
    MOCK_DIAGNOSTICIANS: list[dict] = [
        {
            "id": 1,
            "name": "Νάτσικα Α.",
            "can_ct": True,
            "can_mri": True,
            "daily_quota": 15,
            "skills": [
                {"exam_code": "21100", "modality": "MRI", "is_preferred": True},
                {"exam_code": "22140", "modality": "CT", "is_preferred": False},
                {"exam_code": "21063", "modality": "MRI", "is_preferred": False},
            ],
            "accepted_labs": ["LAB-KIF", "LAB-MAR", "LAB-GLY"],
            "available": True,
            "current_day_count": 5,
            "subcategory_counts": {"abdomen": 3, "neuro": 1},
            "soft_caps": {"abdomen": 5},
        },
        {
            "id": 2,
            "name": "Κωνσταντίνου Β.",
            "can_ct": True,
            "can_mri": True,
            "daily_quota": 12,
            "skills": [
                {"exam_code": "22140", "modality": "CT", "is_preferred": True},
                {"exam_code": "21100", "modality": "CT", "is_preferred": False},
            ],
            "accepted_labs": ["LAB-KIF", "LAB-MAR"],
            "available": True,
            "current_day_count": 3,
            "subcategory_counts": {"chest": 2},
            "soft_caps": {"chest": 4},
        },
        {
            "id": 3,
            "name": "Παπαδόπουλος Γ.",
            "can_ct": True,
            "can_mri": True,
            "daily_quota": 18,
            "skills": [
                {"exam_code": "21063", "modality": "MRI", "is_preferred": True},
                {"exam_code": "22200", "modality": "CT", "is_preferred": True},
                {"exam_code": "21400", "modality": "MRI", "is_preferred": False},
            ],
            "accepted_labs": ["LAB-KIF", "LAB-MAR", "LAB-GLY", "LAB-PAM"],
            "available": True,
            "current_day_count": 8,
            "subcategory_counts": {"neuro": 5, "msk": 2},
            "soft_caps": {"neuro": 7},
        },
        {
            "id": 4,
            "name": "Λιάκος Δ.",
            "can_ct": True,
            "can_mri": False,  # CT only
            "daily_quota": 10,
            "skills": [
                {"exam_code": "22140", "modality": "CT", "is_preferred": True},
                {"exam_code": "22200", "modality": "CT", "is_preferred": True},
            ],
            "accepted_labs": ["LAB-MAR", "LAB-GLY"],
            "available": True,
            "current_day_count": 4,
            "subcategory_counts": {"chest": 1, "abdomen": 2},
            "soft_caps": {},
        },
        {
            "id": 5,
            "name": "Δημητρίου Ε.",
            "can_ct": True,
            "can_mri": True,
            "daily_quota": 14,
            "skills": [
                {"exam_code": "21400", "modality": "MRI", "is_preferred": True},
                {"exam_code": "22500", "modality": "CT", "is_preferred": True},
                {"exam_code": "21100", "modality": "MRI", "is_preferred": False},
            ],
            "accepted_labs": ["LAB-KIF", "LAB-GLY", "LAB-PAM"],
            "available": True,
            "current_day_count": 6,
            "subcategory_counts": {"msk": 4},
            "soft_caps": {"msk": 6},
        },
        {
            "id": 6,
            "name": "Αντωνίου Ζ.",
            "can_ct": True,
            "can_mri": True,
            "daily_quota": 16,
            "skills": [
                {"exam_code": "21100", "modality": "MRI", "is_preferred": True},
                {"exam_code": "22200", "modality": "CT", "is_preferred": True},
                {"exam_code": "22140", "modality": "CT", "is_preferred": False},
            ],
            "accepted_labs": ["LAB-KIF", "LAB-MAR", "LAB-GLY"],
            "available": False,  # On leave today
            "current_day_count": 0,
            "subcategory_counts": {},
            "soft_caps": {"abdomen": 6},
        },
    ]

    # Mock partnerships
    MOCK_PARTNERSHIPS = {
        "DR-101": {"diagnostician_id": 3, "exclusive": True},  # Dr. Παπαδόπουλος Ν. prefers diagnostician Παπαδόπουλος Γ. (id=3)
        "DR-310": {"diagnostician_id": 5, "exclusive": False},  # Dr. Βασιλείου Κ. prefers diagnostician Δημητρίου Ε. (id=5)
    }

    # Mock patient history
    MOCK_PATIENT_HISTORY = {
        "PT-5432": {"diagnostician_id": 1, "count": 3},  # Γεώργιος → Νάτσικα (3 times)
        "PT-1190": {"diagnostician_id": 3, "count": 2},  # Δημήτρης → Παπαδόπουλος (2 times)
    }

    async def get_candidates_for_exam(
        self,
        exam_id: str,
        modality: str,
        body_part: str,
        lab_id: str,
        issuing_doctor_id: str,
        patient_id: str,
        exam_code: str = "",
    ) -> list[CandidateDiagnostician]:
        """
        Load all potentially eligible diagnosticians for an exam.

        Populates the CandidateDiagnostician objects with data from:
        - diagnosticians table (basic info)
        - diagnostician_skills (proficiency for this body part)
        - diagnostician_capacity (quotas and today's counts)
        - diagnostician_lab_preference (lab acceptance)
        - diagnostician_availability (today's status)
        - partnerships (issuing doctor preference)
        - patient history (past assignments for this patient)

        TODO: Replace mock data with real DB queries.
        """
        candidates = []
        
        from diagflow.api.routes import _mock_availability, _mock_skills
        # Group dynamic mock data
        absent_ids = {a["diagnostician_id"] for a in _mock_availability if a["status"] == "on_leave"}
        dynamic_skills_by_id = {}
        for s in _mock_skills:
            dynamic_skills_by_id.setdefault(s["diagnostician_id"], []).append(s)

        for mock in self.MOCK_DIAGNOSTICIANS:
            mock_id = int(mock["id"]) # type: ignore
            mock_name = str(mock["name"]) # type: ignore
            # Override skills with dynamic skills from Admin UI if present, else fallback to mock
            mock_skills: list[dict] = dynamic_skills_by_id.get(mock_id) or mock.get("skills", []) # type: ignore
            mock_accepted_labs: list[str] = mock["accepted_labs"] # type: ignore
            mock_subcats: dict[str, int] = mock["subcategory_counts"] # type: ignore
            mock_soft_caps: dict[str, int] = mock["soft_caps"] # type: ignore

            skill_match = None
            for skill in mock_skills:
                # Mock data doesn't have exam context body_part matching anymore, use exam_code if present.
                # Assuming exam context would pass exam_code in real implementation, for now let's just use what's there
                # Or just match by modality as fallback for testing since ExamContext still only has body_part.
                if skill.get("exam_code") == exam_code and skill["modality"] == modality:
                     skill_match = skill
                     break
                # Fallback to body_part mapping for our mock
                body_part_mapping = {
                    "21100": "abdomen", "22140": "chest", "21063": "neuro",
                    "22200": "abdomen", "21400": "msk", "22500": "msk"
                }
                mapped_bp = body_part_mapping.get(skill.get("exam_code", ""))
                if mapped_bp == body_part and skill["modality"] == modality:
                    skill_match = skill
                    break

            # Check lab acceptance
            accepts_lab = lab_id in mock_accepted_labs

            # Check partnership
            partnership: dict | None = self.MOCK_PARTNERSHIPS.get(issuing_doctor_id) # type: ignore
            is_partner = False
            is_exclusive = False
            if partnership and partnership.get("diagnostician_id") == mock_id:
                is_partner = True
                is_exclusive = bool(partnership.get("exclusive", False))

            # Check patient history
            patient_hist: dict | None = self.MOCK_PATIENT_HISTORY.get(patient_id) # type: ignore
            has_history = bool(patient_hist and patient_hist.get("diagnostician_id") == mock_id)
            history_count = int(patient_hist.get("count", 0)) if has_history and patient_hist else 0

            # Subcategory count for this body part
            subcat_count = mock_subcats.get(body_part, 0)
            subcat_soft_cap = mock_soft_caps.get(body_part)

            if skill_match:
                skill_proficiency = 1.0 if skill_match.get("is_preferred") else 0.5
            else:
                skill_proficiency = 0.0

            candidate = CandidateDiagnostician(
                id=mock_id,
                name=mock_name,
                can_ct=bool(mock["can_ct"]),
                can_mri=bool(mock["can_mri"]),
                is_available=mock_id not in absent_ids,
                daily_quota=int(mock["daily_quota"]), # type: ignore
                current_day_count=int(mock["current_day_count"]), # type: ignore
                current_subcategory_count=subcat_count,
                subcategory_soft_cap=subcat_soft_cap,
                skill_proficiency=skill_proficiency,
                has_skill_match=skill_match is not None,
                has_skill_data=len(mock_skills) > 0,
                accepts_lab=accepts_lab,
                is_partnership_match=is_partner,
                is_partnership_exclusive=is_exclusive,
                has_patient_history=has_history,
                patient_history_count=history_count,
            )
            candidates.append(candidate)

        logger.info(
            "candidates_loaded",
            exam_id=exam_id,
            total=len(candidates),
        )

        return candidates

    async def get_all_diagnosticians(self) -> list[dict]:
        """Get all diagnosticians for the UI dropdown/list."""
        return [
            {
                "id": m["id"],
                "name": m["name"],
                "can_ct": m["can_ct"],
                "can_mri": m["can_mri"],
                "daily_quota": m["daily_quota"],
                "current_day_count": m["current_day_count"],
                "available": m["available"],
            }
            for m in self.MOCK_DIAGNOSTICIANS
        ]
