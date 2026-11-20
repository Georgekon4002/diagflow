"""
DiagFlow — Speed & Batch Optimization Regression Tests

Verifies that:
1. Production Slis stored-procedure snapshots are cached across sequential reads
   and properly invalidated on force_refresh / invalidate_slis_period_cache().
2. Batch Slis pushes reuse ONE pooled Slis connection + ONE config DB commit and
   never touch SQLite mock_slis.db when running in MSSQL mode.
3. Preloaded config/weights bypass per-exam DB hits in filters & scoring.
4. Multi-date daily counts return accurate per-date modality breakdowns in one pass.
"""

from unittest.mock import MagicMock, patch

from diagflow.engine.filters import CandidateDiagnostician, ExamContext, apply_hard_filters
from diagflow.engine.scoring import score_all_candidates
from diagflow.services import assignment as assign_mod
from diagflow.services.slis_sync import push_selected_to_slis
import diagflow.db.diagflow_db as cfg_db


def test_slis_period_cache_deduplicates_stored_proc_calls():
    """Verify _fetch_slis_period_rows executes the stored proc once within TTL and refreshes on invalidation."""
    assign_mod.invalidate_slis_period_cache()

    mock_res = MagicMock()
    mock_res.keys.return_value = ["exammoreid", "extracode", "category", "visitdate", "diagnostis", "stat"]
    mock_res.fetchall.return_value = [
        (5001, "ORD-1", "ΜΑΓΝΗΤΙΚΗ", "2026-11-19", None, 0),
        (5002, "ORD-2", "ΑΞΟΝΙΚΗ", "2026-11-19", 14, 1),
    ]
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_res
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    try:
        with patch("diagflow.db.engines.get_slis_engine", return_value=mock_engine):
            rows1 = assign_mod._fetch_slis_period_rows(days_back=3)
            rows2 = assign_mod._fetch_slis_period_rows(days_back=7)
            assert len(rows1) == 2
            assert len(rows2) == 2
            # Stored proc must have been executed ONLY ONCE for both 3-day and 7-day calls
            assert mock_conn.execute.call_count == 1

            # Explicit invalidation triggers a fresh execution
            assign_mod.invalidate_slis_period_cache()
            rows3 = assign_mod._fetch_slis_period_rows(days_back=7)
            assert len(rows3) == 2
            assert mock_conn.execute.call_count == 2
    finally:
        assign_mod.invalidate_slis_period_cache()


def test_batch_push_reuses_single_slis_connection_and_skips_sqlite_in_mssql_mode():
    """Verify push_selected_to_slis opens ONE Slis connection for N exams, never opens SQLite, and batches config DB writes."""
    fake_local = {
        1001: {
            "exammoreid": 1001,
            "diagnostician_id": 14,
            "diagnostician_name": "ΝΑΤΣΙΚΑ ΜΑΡΓΑΡΙΤΑ",
            "modality": "MRI",
            "extracode": "EXT-1",
            "visitdate": "2026-11-19",
        },
        1002: {
            "exammoreid": 1002,
            "diagnostician_id": 14,
            "diagnostician_name": "ΝΑΤΣΙΚΑ ΜΑΡΓΑΡΙΤΑ",
            "modality": "CT",
            "extracode": "EXT-2",
            "visitdate": "2026-11-19",
        },
    }

    mock_update_result = MagicMock()
    mock_update_result.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_update_result
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("diagflow.services.slis_sync.settings.use_mock_slis_db", False), \
         patch("diagflow.db.engines.get_slis_engine", return_value=mock_engine), \
         patch("diagflow.db.diagflow_db.get_all_local_assignments", return_value=fake_local) as mock_get_local, \
         patch("diagflow.db.diagflow_db.finalize_synced_assignments_batch") as mock_finalize, \
         patch("diagflow.services.slis_sync._get_db") as mock_sqlite_db:

        res = push_selected_to_slis([1001, 1002])

        assert res["succeeded"] == [1001, 1002]
        assert res["failed"] == []
        # ONE pooled Slis connection opened for the whole batch
        assert mock_engine.connect.call_count == 1
        # get_all_local_assignments called ONCE (not once per exam)
        assert mock_get_local.call_count == 1
        # SQLite mock_slis.db must NEVER be touched in MSSQL mode
        mock_sqlite_db.assert_not_called()
        # Config DB finalized ONCE with both entries
        mock_finalize.assert_called_once()
        finalized_entries = mock_finalize.call_args[0][0]
        assert len(finalized_entries) == 2
        assert {e["exammoreid"] for e in finalized_entries} == {1001, 1002}


def test_preloaded_config_avoids_db_queries_in_filters_and_scoring():
    """Verify passing preloaded rules & weights skips DB calls during batch scoring."""
    exam = ExamContext(
        exam_id="E-1",
        patient_id="P-1",
        modality="MRI",
        lab_id="1",
        lab_name="ΚΟΛΙΑΤΣΟΥ",
        issuing_doctor_id="D-1",
        issuing_doctor_name="DOC",
    )
    cand = CandidateDiagnostician(
        id=1,
        name="ΔΙΑΓΝΩΣΤΗΣ Α",
        can_ct=True,
        can_mri=True,
        is_available=True,
        daily_quota=10,
        current_day_count=2,
        has_skill_data=False,
    )

    with patch("diagflow.db.diagflow_db.get_all_exclusive_lab_rules") as mock_excl, \
         patch("diagflow.db.diagflow_db.get_all_modality_quotas") as mock_mq, \
         patch("diagflow.db.diagflow_db.get_comment_auto_assign_enabled") as mock_cm, \
         patch("diagflow.db.diagflow_db.get_system_weights") as mock_w:

        passed, _ = apply_hard_filters(
            [cand],
            exam,
            exclusive_rules=[],
            modality_quotas=[],
            comment_rule_enabled=True,
        )
        assert len(passed) == 1

        scores = score_all_candidates(
            passed,
            exam,
            weights={"pts_capacity": 0.1, "pts_partnership": 0.2, "pts_history": 0.35, "pts_skills_pref": 0.2, "pts_skills_neut": 0.1, "pts_skills_none": 0.0, "pts_lab_pref": 0.15, "pts_lab_neut": 0.1, "pts_lab_other": 0.02},
        )
        assert len(scores) == 1

        mock_excl.assert_not_called()
        mock_mq.assert_not_called()
        mock_cm.assert_not_called()
        mock_w.assert_not_called()


def test_get_daily_assignment_counts_for_dates_single_pass():
    """Verify get_daily_assignment_counts_for_dates computes accurate total/mri/ct per date."""
    diag = cfg_db.create_diagnostician(name="TEST_BATCH_COUNTS_DIAG", active=True, can_ct=True, can_mri=True)
    did = diag["id"]
    try:
        cfg_db.upsert_local_assignment(995001, did, diag["name"], "2026-11-20T09:00:00", modality="MRI", extracode="X1", visitdate="2026-11-18")
        cfg_db.upsert_local_assignment(995002, did, diag["name"], "2026-11-20T09:05:00", modality="CT", extracode="X2", visitdate="2026-11-18")
        cfg_db.upsert_local_assignment(995003, did, diag["name"], "2026-11-20T09:10:00", modality="MRI", extracode="X3", visitdate="2026-11-19")

        by_date = cfg_db.get_daily_assignment_counts_for_dates({"2026-11-18", "2026-11-19", "2026-11-20"})
        assert by_date["2026-11-18"][did] == {"total": 2, "mri": 1, "ct": 1}
        assert by_date["2026-11-19"][did] == {"total": 1, "mri": 1, "ct": 0}
        assert did not in by_date["2026-11-20"]
    finally:
        cfg_db.delete_local_assignment(995001, record_dismissed=False)
        cfg_db.delete_local_assignment(995002, record_dismissed=False)
        cfg_db.delete_local_assignment(995003, record_dismissed=False)
        cfg_db.delete_diagnostician(did)
