"""
DiagFlow — Multi-Exam Order Alignment Test
============================================
Tests that multiple pending exams for the same patient under the same order ID (extracode)
propose the same diagnostician (the one who scores highest overall across all exams in the order).
"""
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

from diagflow.main import app

client = TestClient(app)


def test_multi_exam_order_proposal_alignment():
    """Multiple exams with the same extracode and patient_id should propose the same diagnostician."""
    pending_mock = [
        {
            "exam_id": "1001",
            "extracode": "ORDER-999",
            "patient_id": "PATIENT-77",
            "patient_name": "Test Order Patient",
            "modality": "CT",
            "category": "CT",
            "body_part": "",
            "examnumcode": "22140",
            "examname": "ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ",
            "visitdate": "2026-08-05",
            "labcodeid": 1,
            "lab_id": "1",
            "lab_name": "ΚΟΛΙΑΤΣΟΥ",
            "wcode": "DR-1",
            "issuing_doctor_id": "DR-1",
            "wname": "Δρ. Παπαδόπουλος",
            "issuing_doctor_name": "Δρ. Παπαδόπουλος",
            "diagnostis": None,
            "code": "",
            "diagnostician_name": "",
            "status": "pending",
            "notes": "",
            "comments": "",
            "oldvisit": 0,
            "oldpers": None,
        },
        {
            "exam_id": "1002",
            "extracode": "ORDER-999",
            "patient_id": "PATIENT-77",
            "patient_name": "Test Order Patient",
            "modality": "CT",
            "category": "CT",
            "body_part": "",
            "examnumcode": "22141",
            "examname": "ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΚΟΙΛΙΑΣ",
            "visitdate": "2026-08-05",
            "labcodeid": 1,
            "lab_id": "1",
            "lab_name": "ΚΟΛΙΑΤΣΟΥ",
            "wcode": "DR-1",
            "issuing_doctor_id": "DR-1",
            "wname": "Δρ. Παπαδόπουλος",
            "issuing_doctor_name": "Δρ. Παπαδόπουλος",
            "diagnostis": None,
            "code": "",
            "diagnostician_name": "",
            "status": "pending",
            "notes": "",
            "comments": "",
            "oldvisit": 0,
            "oldpers": None,
        },
    ]

    with patch("diagflow.services.assignment.AssignmentService.get_pending_exams", return_value=pending_mock), \
         patch("diagflow.services.assignment.AssignmentService.get_assigned_exams", return_value=[]):
        res1 = client.post("/api/assignments/suggest", json={"exam_id": "1001"})
        res2 = client.post("/api/assignments/suggest", json={"exam_id": "1002"})

        assert res1.status_code == 200
        assert res2.status_code == 200

        data1 = res1.json()
        data2 = res2.json()

        # Both exams in the same order must suggest the exact same diagnostician
        assert data1["suggested_diagnostician_id"] == data2["suggested_diagnostician_id"]
        assert data1["suggested_diagnostician_name"] == data2["suggested_diagnostician_name"]


def test_multi_exam_order_batch_suggest():
    """Batch suggestion should also propose the exact same diagnostician for exams in the same order."""
    pending_mock = [
        {
            "exam_id": "2001",
            "extracode": "ORDER-888",
            "patient_id": "PATIENT-99",
            "patient_name": "Batch Order Patient",
            "modality": "CT",
            "category": "CT",
            "body_part": "",
            "examnumcode": "22140",
            "examname": "ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ",
            "visitdate": "2026-08-05",
            "labcodeid": 1,
            "lab_id": "1",
            "lab_name": "ΚΟΛΙΑΤΣΟΥ",
            "wcode": "DR-1",
            "issuing_doctor_id": "DR-1",
            "wname": "Δρ. Παπαδόπουλος",
            "issuing_doctor_name": "Δρ. Παπαδόπουλος",
            "diagnostis": None,
            "code": "",
            "diagnostician_name": "",
            "status": "pending",
            "notes": "",
            "comments": "",
            "oldvisit": 0,
            "oldpers": None,
        },
        {
            "exam_id": "2002",
            "extracode": "ORDER-888",
            "patient_id": "PATIENT-99",
            "patient_name": "Batch Order Patient",
            "modality": "CT",
            "category": "CT",
            "body_part": "",
            "examnumcode": "22141",
            "examname": "ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΚΟΙΛΙΑΣ",
            "visitdate": "2026-08-05",
            "labcodeid": 1,
            "lab_id": "1",
            "lab_name": "ΚΟΛΙΑΤΣΟΥ",
            "wcode": "DR-1",
            "issuing_doctor_id": "DR-1",
            "wname": "Δρ. Παπαδόπουλος",
            "issuing_doctor_name": "Δρ. Παπαδόπουλος",
            "diagnostis": None,
            "code": "",
            "diagnostician_name": "",
            "status": "pending",
            "notes": "",
            "comments": "",
            "oldvisit": 0,
            "oldpers": None,
        },
    ]

    with patch("diagflow.services.assignment.AssignmentService.get_pending_exams", return_value=pending_mock), \
         patch("diagflow.services.assignment.AssignmentService.get_assigned_exams", return_value=[]):
        res = client.post("/api/assignments/suggest-batch", json={"exam_ids": ["2001", "2002"]})

        assert res.status_code == 200
        data = res.json()
        assert "suggestions" in data
        s1 = data["suggestions"]["2001"]
        s2 = data["suggestions"]["2002"]

        assert s1["suggested_diagnostician_id"] == s2["suggested_diagnostician_id"]
        assert s1["suggested_diagnostician_name"] == s2["suggested_diagnostician_name"]
