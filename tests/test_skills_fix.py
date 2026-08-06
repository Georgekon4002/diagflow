"""
DiagFlow — Skills Fix & Cache Tests

Tests for system-wide skill configuration check, PUT skill endpoint,
and DiagnosticianService cache invalidation.
"""

import anyio
import pytest
from diagflow.db import diagflow_db as cfg_db
from diagflow.services.diagnostician import DiagnosticianService
from diagflow.engine.filters import filter_by_skills_hard, ExamContext


def test_update_skill_preference_in_db():
    """Verify update_skill_preference updates is_preferred column in DB."""
    diags = cfg_db.get_all_diagnosticians()
    assert len(diags) > 0
    diag_id = diags[0]["id"]

    # Insert dummy skill
    skill = cfg_db.upsert_skill(diagnostician_id=diag_id, exam_code="TEST_CODE_99", is_preferred=False)
    skill_id = skill["id"]

    # Update preference to True
    updated = cfg_db.update_skill_preference(skill_id, True)
    assert updated is True

    # Retrieve and verify
    skills = cfg_db.get_skills(diag_id)
    matched = next((s for s in skills if s["id"] == skill_id), None)
    assert matched is not None
    assert bool(matched["is_preferred"]) is True

    # Clean up
    cfg_db.delete_skill(skill_id)


def test_diagnostician_service_clear_cache():
    """Verify DiagnosticianService.clear_cache resets cache timestamp and values."""
    DiagnosticianService._cache_timestamp = 1000.0
    DiagnosticianService._cached_all_diags = [{"id": 1}]
    DiagnosticianService._cached_skills_by_diag = {1: []}

    DiagnosticianService.clear_cache()

    assert DiagnosticianService._cache_timestamp == 0.0
    assert DiagnosticianService._cached_all_diags == []
    assert DiagnosticianService._cached_skills_by_diag == {}


def test_candidate_without_skill_fails_hard_filter_when_exam_has_skills():
    """
    When an exam code has a skill registered for any diagnostician in the DB,
    a candidate who does NOT have that skill has has_skill_data=True and skill_proficiency=0.0,
    thus failing filter_by_skills_hard.
    """
    async def _test():
        diags = cfg_db.get_all_diagnosticians()
        assert len(diags) > 0
        diag_id = diags[0]["id"]

        # Register skill for first diagnostician
        skill = cfg_db.upsert_skill(diagnostician_id=diag_id, exam_code="998877", is_preferred=True)

        svc = DiagnosticianService()
        DiagnosticianService.clear_cache()

        # Load candidates for exam_code "998877"
        cands = await svc.get_candidates_for_exam(
            exam_id="E99",
            modality="CT",
            body_part="CHEST",
            lab_id="L1",
            issuing_doctor_id="DOC1",
            patient_id="P1",
            exam_code="998877",
        )

        exam_ctx = ExamContext(
            exam_id="E99",
            patient_id="P1",
            patient_name="Test Patient",
            modality="CT",
            body_part="CHEST",
            exam_code="998877",
            lab_id="L1",
            lab_name="Lab",
            issuing_doctor_id="DOC1",
            issuing_doctor_name="Doc",
        )

        # Candidate with skill
        cand_with_skill = next((c for c in cands if c.id == diag_id), None)
        if cand_with_skill:
            res1 = filter_by_skills_hard(cand_with_skill, exam_ctx)
            assert res1.passed is True

        # Other candidates (do not have skill 998877)
        other_cands = [c for c in cands if c.id != diag_id]
        for c in other_cands:
            assert c.has_skill_data is True
            assert c.skill_proficiency == 0.0
            res = filter_by_skills_hard(c, exam_ctx)
            assert res.passed is False
            assert "Δεν μπορεί να διαγνώσει" in res.reason

        # Clean up
        cfg_db.delete_skill(skill["id"])
        DiagnosticianService.clear_cache()

    anyio.run(_test)
