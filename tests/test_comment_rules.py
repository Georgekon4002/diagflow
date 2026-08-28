"""
Tests for Comment-Based Auto-Assignment & 'ΟΧΙ' Exclusion Rule
==============================================================
Tests:
1. Text normalization, consonant skeleton extraction & typo matching.
2. Positive matches: exact, skeleton ('ΝΤΣΚ'), accented ('Νάτσικα'), typos ('Νατσκα').
3. 'ΟΧΙ' exclusions: 'ΟΧΙ ΝΑΤΣΙΚΑ', 'όχι νάτσικα', 'οχι ντσκ', and combined 'ΟΧΙ ΜΠΕΡΕΤΗΣ - ΝΑΤΣΙΚΑ'.
4. Pipeline & service integration: 'Όνομα Διαγνώστη αναφέρθηκε στα σχόλια' auto-assignment.
5. Suppression of exclusive doctor partnerships when 'ΟΧΙ' is in comments.
6. Admin API toggle for turning the rule ON and OFF.
"""

import pytest
from datetime import date
from fastapi.testclient import TestClient

from diagflow.engine.comment_rules import (
    normalize_greek_text,
    extract_consonant_skeleton,
    levenshtein_distance,
    parse_comment_diagnosticians,
)
from diagflow.engine.filters import CandidateDiagnostician, ExamContext, apply_hard_filters
from diagflow.engine.pipeline import AssignmentPipeline
from diagflow.services.assignment import AssignmentService
import diagflow.db.diagflow_db as cfg_db
from diagflow.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def ensure_comment_rule_enabled():
    cfg_db.set_comment_auto_assign_enabled(True)
    yield
    cfg_db.set_comment_auto_assign_enabled(True)


def test_greek_normalization_and_skeleton():
    """Test text normalization and consonant skeleton extraction."""
    assert normalize_greek_text("Νάτσικα") == "ΝΑΤΣΙΚΑ"
    assert normalize_greek_text("Μπερέτης") == "ΜΠΕΡΕΤΗΣ"
    assert normalize_greek_text("Σιγάλας") == "ΣΙΓΑΛΑΣ"
    assert normalize_greek_text("Κουλογιώργα") == "ΚΟΥΛΟΓΙΩΡΓΑ"

    # Consonant skeletons (vowels stripped)
    assert extract_consonant_skeleton("ΝΑΤΣΙΚΑ") == "ΝΤΣΚ"
    assert extract_consonant_skeleton("ΜΠΕΡΕΤΗΣ") == "ΜΠΡΤΣ"
    assert extract_consonant_skeleton("ΣΙΓΑΛΑΣ") == "ΣΓΛΣ"
    assert extract_consonant_skeleton("ΚΟΥΛΟΓΙΩΡΓΑ") == "ΚΛΓΡΓ"

    # Typo edit distance
    assert levenshtein_distance("ΝΑΤΣΚΑ", "ΝΑΤΣΙΚΑ") == 1
    assert levenshtein_distance("ΝΑΤΣΙΚ", "ΝΑΤΣΚ") == 1


def test_comment_parsing_variations():
    """Test matching various forms of diagnostician names in comments."""
    diags = [
        {"id": 14, "name": "ΝΑΤΣΙΚΑ ΜΑΡΓΑΡΙΤΑ", "active": True},
        {"id": 59, "name": "ΜΠΕΡΕΤΗΣ ΓΕΩΡΓΙΟΣ", "active": True},
        {"id": 264, "name": "ΣΙΓΑΛΑΣ ΑΝΤΩΝΙΟΣ", "active": True},
        {"id": 34, "name": "ΚΟΥΛΟΓΙΩΡΓΑ ΔΗΜΗΤΡΑ", "active": True},
    ]

    # Exact uppercase
    m, excl = parse_comment_diagnosticians("ΠΑΡΑΚΑΛΩ ΝΑΤΣΙΚΑ", diags)
    assert m is not None and m["id"] == 14 and len(excl) == 0

    # Consonant skeleton
    m, excl = parse_comment_diagnosticians("ΝΤΣΚ", diags)
    assert m is not None and m["id"] == 14 and len(excl) == 0

    # Accented mixed case
    m, excl = parse_comment_diagnosticians("Σχόλιο: Νάτσικα", diags)
    assert m is not None and m["id"] == 14 and len(excl) == 0

    # Typo / fuzzy
    m, excl = parse_comment_diagnosticians("Νατσκα", diags)
    assert m is not None and m["id"] == 14 and len(excl) == 0

    # Another diagnostician with skeleton
    m, excl = parse_comment_diagnosticians("ΜΠΡΤ", diags)
    assert m is not None and m["id"] == 59 and len(excl) == 0

    m, excl = parse_comment_diagnosticians("ΣΓΛ", diags)
    assert m is not None and m["id"] == 264 and len(excl) == 0

    m, excl = parse_comment_diagnosticians("ΚΛΓΡΓ", diags)
    assert m is not None and m["id"] == 34 and len(excl) == 0


def test_comment_exclusion_oxi():
    """Test negative exclusions with 'ΟΧΙ' / 'όχι' / 'οχι'."""
    diags = [
        {"id": 14, "name": "ΝΑΤΣΙΚΑ ΜΑΡΓΑΡΙΤΑ", "active": True},
        {"id": 59, "name": "ΜΠΕΡΕΤΗΣ ΓΕΩΡΓΙΟΣ", "active": True},
    ]

    # Simple ΟΧΙ
    m, excl = parse_comment_diagnosticians("ΟΧΙ ΝΑΤΣΙΚΑ", diags)
    assert m is None and 14 in excl

    # Lowercase όχι with accent
    m, excl = parse_comment_diagnosticians("όχι νάτσικα", diags)
    assert m is None and 14 in excl

    # Lowercase skeleton with οχι
    m, excl = parse_comment_diagnosticians("οχι ντσκ", diags)
    assert m is None and 14 in excl

    # Preposition
    m, excl = parse_comment_diagnosticians("ΟΧΙ ΣΤΟΝ ΝΑΤΣΙΚΑ", diags)
    assert m is None and 14 in excl

    # Combined exclusion + assignment: 'ΟΧΙ ΜΠΕΡΕΤΗΣ - ΝΑΤΣΙΚΑ'
    m, excl = parse_comment_diagnosticians("ΟΧΙ ΜΠΕΡΕΤΗΣ - ΝΑΤΣΙΚΑ", diags)
    assert m is not None and m["id"] == 14
    assert 59 in excl


def test_hard_filter_comment_exclusion():
    """Test that apply_hard_filters eliminates candidates with 'ΟΧΙ' comment."""
    exam = ExamContext(
        exam_id="9999",
        patient_id="8888",
        modality="MRI",
        body_part="knee",
        comments="ΟΧΙ ΝΑΤΣΙΚΑ",
    )

    candidates = [
        CandidateDiagnostician(id=14, name="ΝΑΤΣΙΚΑ ΜΑΡΓΑΡΙΤΑ", is_available=True, daily_quota=20),
        CandidateDiagnostician(id=59, name="ΜΠΕΡΕΤΗΣ ΓΕΩΡΓΙΟΣ", is_available=True, daily_quota=20),
    ]

    passed, results = apply_hard_filters(candidates, exam)
    passed_ids = [c.id for c in passed]

    assert 14 not in passed_ids
    assert 59 in passed_ids

    # Check elimination reason
    r14 = results[14]
    first_failed = next(r for r in r14 if not r.passed)
    assert first_failed.rule_name == "comment_exclusion"
    assert first_failed.reason == "Αποκλείστηκε λόγω σχολίου"


def test_pipeline_alternatives_show_comment_elimination():
    """Test that AssignmentPipeline includes eliminated diagnostician with exact reason."""
    exam = ExamContext(
        exam_id="9998",
        patient_id="8887",
        modality="MRI",
        body_part="brain",
        comments="ΟΧΙ ΝΑΤΣΙΚΑ",
    )

    candidates = [
        CandidateDiagnostician(id=14, name="ΝΑΤΣΙΚΑ ΜΑΡΓΑΡΙΤΑ", is_available=True, daily_quota=20),
        CandidateDiagnostician(id=59, name="ΜΠΕΡΕΤΗΣ ΓΕΩΡΓΙΟΣ", is_available=True, daily_quota=20),
    ]

    pipeline = AssignmentPipeline()
    suggestion = pipeline.run(exam, candidates)

    assert suggestion is not None
    assert suggestion.suggested_diagnostician_id == 59

    # Check alternatives
    alt14 = next((a for a in suggestion.alternatives if a["id"] == 14), None)
    assert alt14 is not None
    assert alt14["eliminated"] is True
    assert alt14["elimination_reason"] == "Αποκλείστηκε λόγω σχολίου"


def test_comment_rule_admin_toggle():
    """Test toggling the comment auto-assign rule via db and API."""
    cfg_db.set_comment_auto_assign_enabled(True)
    assert cfg_db.get_comment_auto_assign_enabled() is True

    # Test GET endpoint
    res = client.get("/api/admin/advanced/comment-rule")
    assert res.status_code == 200
    assert res.json()["enabled"] is True

    # Admin Login to obtain token
    login_res = client.post("/api/admin/auth/login", json={"username": "admin", "password": "admin1234"})
    token = login_res.json().get("token")
    headers = {"X-Admin-Token": token} if token else {}

    # Test POST endpoint to toggle False
    res_post = client.post("/api/admin/advanced/comment-rule", json={"enabled": False}, headers=headers)
    assert res_post.status_code == 200
    assert res_post.json()["enabled"] is False
    assert cfg_db.get_comment_auto_assign_enabled() is False

    # Test POST endpoint to toggle True
    res_post_true = client.post("/api/admin/advanced/comment-rule", json={"enabled": True}, headers=headers)
    assert res_post_true.status_code == 200
    assert res_post_true.json()["enabled"] is True
    assert cfg_db.get_comment_auto_assign_enabled() is True


def test_end_to_end_comment_auto_assignment_and_exclusion():
    """Test full end-to-end auto-assignment and exclusive suppression from mock DB."""
    from scripts.seed_fresh_mock_data import seed_all
    cfg_db.set_comment_auto_assign_enabled(True)
    seed_all()

    svc = AssignmentService()
    # Loading pending triggers the auto-assignment rules
    pending = svc.get_pending_exams()
    assigned = svc.get_assigned_exams()

    assigned_map = {int(a["exam_id"]): a for a in assigned}
    pending_map = {int(p["exam_id"]): p for p in pending}

    # 1. Check positive auto-assignments
    for eid in (5001, 5002, 5003, 5004):
        assert eid in assigned_map, f"Exam {eid} should be auto-assigned"
        assert assigned_map[eid]["diagnostis"] == 14
        assert assigned_map[eid]["is_auto_assigned"] is True
        assert assigned_map[eid]["rule_desc"] == "Όνομα Διαγνώστη αναφέρθηκε στα σχόλια"

    # Exam 5005: 'ΜΠΡΤ' -> ΜΠΕΡΕΤΗΣ (59)
    assert 5005 in assigned_map
    assert assigned_map[5005]["diagnostis"] == 59
    assert assigned_map[5005]["rule_desc"] == "Όνομα Διαγνώστη αναφέρθηκε στα σχόλια"

    # Exam 5008: 'ΟΧΙ ΜΠΕΡΕΤΗΣ - ΝΑΤΣΙΚΑ' -> ΝΑΤΣΙΚΑ (14)
    assert 5008 in assigned_map
    assert assigned_map[5008]["diagnostis"] == 14
    assert assigned_map[5008]["rule_desc"] == "Όνομα Διαγνώστη αναφέρθηκε στα σχόλια"

    # Exam 5009: 'ΣΓΛ' -> ΣΙΓΑΛΑΣ (264)
    assert 5009 in assigned_map
    assert assigned_map[5009]["diagnostis"] == 264
    assert assigned_map[5009]["rule_desc"] == "Όνομα Διαγνώστη αναφέρθηκε στα σχόλια"

    # Exam 5010: 'ΚΛΓΡΓ' -> ΚΟΥΛΟΓΙΩΡΓΑ (34)
    assert 5010 in assigned_map
    assert assigned_map[5010]["diagnostis"] == 34
    assert assigned_map[5010]["rule_desc"] == "Όνομα Διαγνώστη αναφέρθηκε στα σχόλια"

    # 2. Check exclusions
    # Exam 5006: 'ΟΧΙ ΝΑΤΣΙΚΑ' -> must remain pending
    assert 5006 in pending_map
    assert 5006 not in assigned_map

    # Exam 5007: Exclusive Doctor (570859) with 'όχι νάτσικα' -> exclusive rule must be SUPPRESSED!
    assert 5007 in pending_map, "Exam 5007 with 'όχι νάτσικα' must have its exclusive partnership suppressed"
    assert 5007 not in assigned_map

