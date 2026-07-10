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
    MOCK_DIAGNOSTICIANS = [
        {
            "id": 1,
            "name": "Νάτσικα Α.",
            "can_ct": True,
            "can_mri": True,
            "daily_quota": 15,
            "skills": [
                {"body_part": "abdomen", "modality": "MRI", "proficiency": 0.9},
                {"body_part": "abdomen", "modality": "CT", "proficiency": 0.8},
                {"body_part": "neuro", "modality": "MRI", "proficiency": 0.7},
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
                {"body_part": "chest", "modality": "CT", "proficiency": 0.95},
                {"body_part": "chest", "modality": "MRI", "proficiency": 0.8},
                {"body_part": "abdomen", "modality": "CT", "proficiency": 0.6},
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
                {"body_part": "neuro", "modality": "MRI", "proficiency": 0.95},
                {"body_part": "neuro", "modality": "CT", "proficiency": 0.9},
                {"body_part": "msk", "modality": "MRI", "proficiency": 0.7},
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
                {"body_part": "chest", "modality": "CT", "proficiency": 0.85},
                {"body_part": "abdomen", "modality": "CT", "proficiency": 0.8},
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
                {"body_part": "msk", "modality": "MRI", "proficiency": 0.9},
                {"body_part": "msk", "modality": "CT", "proficiency": 0.85},
                {"body_part": "abdomen", "modality": "MRI", "proficiency": 0.65},
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
                {"body_part": "abdomen", "modality": "MRI", "proficiency": 0.85},
                {"body_part": "abdomen", "modality": "CT", "proficiency": 0.9},
                {"body_part": "chest", "modality": "CT", "proficiency": 0.7},
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
        "DR-101": 3,  # Dr. Παπαδόπουλος Ν. prefers diagnostician Παπαδόπουλος Γ. (id=3)
        "DR-310": 5,  # Dr. Βασιλείου Κ. prefers diagnostician Δημητρίου Ε. (id=5)
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

        for mock in self.MOCK_DIAGNOSTICIANS:
            # Find skill match for this body part + modality
            skill_match = None
            for skill in mock["skills"]:
                if skill["body_part"] == body_part and skill["modality"] == modality:
                    skill_match = skill
                    break

            # Check lab acceptance
            accepts_lab = lab_id in mock["accepted_labs"]

            # Check partnership
            partnership_diag_id = self.MOCK_PARTNERSHIPS.get(issuing_doctor_id)
            is_partner = partnership_diag_id == mock["id"]

            # Check patient history
            patient_hist = self.MOCK_PATIENT_HISTORY.get(patient_id)
            has_history = patient_hist and patient_hist["diagnostician_id"] == mock["id"]

            # Subcategory count for this body part
            subcat_count = mock["subcategory_counts"].get(body_part, 0)
            subcat_soft_cap = mock["soft_caps"].get(body_part)

            candidate = CandidateDiagnostician(
                id=mock["id"],
                name=mock["name"],
                can_ct=mock["can_ct"],
                can_mri=mock["can_mri"],
                is_available=mock["available"],
                daily_quota=mock["daily_quota"],
                current_day_count=mock["current_day_count"],
                current_subcategory_count=subcat_count,
                subcategory_soft_cap=subcat_soft_cap,
                skill_proficiency=skill_match["proficiency"] if skill_match else 0.0,
                has_skill_match=skill_match is not None,
                accepts_lab=accepts_lab,
                is_partnership_match=is_partner,
                partnership_priority=3 if is_partner else 0,
                has_patient_history=has_history,
                patient_history_count=patient_hist["count"] if has_history else 0,
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
