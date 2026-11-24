"""
Regression tests for the DiagFlow Final Release Audit fixes.
"""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from diagflow.engine.comment_rules import parse_comment_diagnosticians
from diagflow.engine.filters import (
    CandidateDiagnostician,
    ExamContext,
    apply_hard_filters,
    filter_by_modality,
)
from diagflow.engine.scoring import CandidateScore
from diagflow.engine.solver import _greedy_fallback, solve_batch_assignment


ROOT = Path(__file__).resolve().parent.parent


def _mk_cand(
    cid: int,
    name: str,
    daily_quota: int = 10,
    current_day_count: int = 0,
    can_ct: bool = True,
    can_mri: bool = True,
) -> CandidateDiagnostician:
    return CandidateDiagnostician(
        id=cid,
        name=name,
        can_ct=can_ct,
        can_mri=can_mri,
        is_available=True,
        daily_quota=daily_quota,
        current_day_count=current_day_count,
    )


def _mk_score(cid: int, name: str, score: float) -> CandidateScore:
    return CandidateScore(
        diagnostician_id=cid,
        diagnostician_name=name,
        total_score=score,
        components=[],
    )


# ─────────────────────────────────────────────────────────────
#  1. CP-SAT Solver Upgrades (2.1)
# ─────────────────────────────────────────────────────────────


def test_cpsat_enforces_modality_quotas():
    """CP-SAT must respect per-modality limits (e.g. max 1 CT for Doc 1)."""
    exams = [
        ExamContext(exam_id="E1", patient_id="P1", extracode="ORD-1", modality="CT"),
        ExamContext(exam_id="E2", patient_id="P2", extracode="ORD-2", modality="CT"),
    ]
    cands = [_mk_cand(1, "Doc 1", daily_quota=10), _mk_cand(2, "Doc 2", daily_quota=10)]
    scores = {
        "E1": [_mk_score(1, "Doc 1", 0.95), _mk_score(2, "Doc 2", 0.50)],
        "E2": [_mk_score(1, "Doc 1", 0.90), _mk_score(2, "Doc 2", 0.50)],
    }
    res = solve_batch_assignment(
        exams=exams,
        candidates_per_exam=scores,
        candidate_objects={"E1": cands, "E2": cands},
        modality_quotas=[
            {"diagnostician_id": 1, "modality": "CT", "max_count": 1, "is_active": True},
            {"diagnostician_id": 2, "modality": "CT", "max_count": 5, "is_active": True},
        ],
    )
    assert res.solver_status in ("OPTIMAL", "FEASIBLE")
    by_exam = {a.exam_id: a.diagnostician_id for a in res.assignments}
    assert by_exam["E1"] == 1
    assert by_exam["E2"] == 2


def test_cpsat_enforces_same_order_consistency():
    """Exams sharing the same patient_id + extracode must be assigned to the same diagnostician."""
    exams = [
        ExamContext(exam_id="E1", patient_id="P1", extracode="ORD-999", modality="MRI"),
        ExamContext(exam_id="E2", patient_id="P1", extracode="ORD-999", modality="CT"),
    ]
    cands = [_mk_cand(1, "Doc 1", daily_quota=5), _mk_cand(2, "Doc 2", daily_quota=5)]
    scores = {
        "E1": [_mk_score(1, "Doc 1", 0.85), _mk_score(2, "Doc 2", 0.70)],
        "E2": [_mk_score(1, "Doc 1", 0.40), _mk_score(2, "Doc 2", 0.65)],
    }
    res = solve_batch_assignment(
        exams=exams,
        candidates_per_exam=scores,
        candidate_objects={"E1": cands, "E2": cands},
    )
    assert res.solver_status in ("OPTIMAL", "FEASIBLE")
    by_exam = {a.exam_id: a.diagnostician_id for a in res.assignments}
    assert by_exam["E1"] == by_exam["E2"]


def test_cpsat_over_capacity_assigns_maximum_instead_of_infeasible():
    """When exams exceed total doctor capacity, solver assigns up to capacity instead of INFEASIBLE."""
    exams = [
        ExamContext(exam_id="E1", patient_id="P1", extracode="O1", modality="CT"),
        ExamContext(exam_id="E2", patient_id="P2", extracode="O2", modality="CT"),
        ExamContext(exam_id="E3", patient_id="P3", extracode="O3", modality="CT"),
    ]
    cands = [_mk_cand(1, "Doc 1", daily_quota=2)]
    scores = {
        "E1": [_mk_score(1, "Doc 1", 0.9)],
        "E2": [_mk_score(1, "Doc 1", 0.8)],
        "E3": [_mk_score(1, "Doc 1", 0.7)],
    }
    res = solve_batch_assignment(
        exams=exams,
        candidates_per_exam=scores,
        candidate_objects={"E1": cands, "E2": cands, "E3": cands},
    )
    assert res.solver_status in ("OPTIMAL", "FEASIBLE")
    assert len(res.assignments) == 2
    assert {a.exam_id for a in res.assignments} == {"E1", "E2"}


def test_greedy_fallback_respects_modality_quotas():
    """Greedy fallback must enforce modality capacities just like CP-SAT."""
    exams = [
        ExamContext(exam_id="E1", patient_id="P1", extracode="O1", modality="MRI"),
        ExamContext(exam_id="E2", patient_id="P2", extracode="O2", modality="MRI"),
    ]
    cands = [_mk_cand(1, "Doc 1", daily_quota=10), _mk_cand(2, "Doc 2", daily_quota=10)]
    scores = {
        "E1": [_mk_score(1, "Doc 1", 0.9), _mk_score(2, "Doc 2", 0.4)],
        "E2": [_mk_score(1, "Doc 1", 0.9), _mk_score(2, "Doc 2", 0.4)],
    }
    res = _greedy_fallback(
        exams=exams,
        candidates_per_exam=scores,
        candidate_objects={"E1": cands, "E2": cands},
        modality_quotas=[
            {"diagnostician_id": 1, "modality": "MRI", "max_count": 1, "is_active": True},
            {"diagnostician_id": 2, "modality": "MRI", "max_count": 5, "is_active": True},
        ],
    )
    by_exam = {a.exam_id: a.diagnostician_id for a in res.assignments}
    assert by_exam["E1"] == 1
    assert by_exam["E2"] == 2


# ─────────────────────────────────────────────────────────────
#  2. Engine Filters (2.2) & Comment NLP (2.3)
# ─────────────────────────────────────────────────────────────


def test_mra_eliminates_ct_only_diagnostician():
    """MRA exams must require can_mri=True (not silently bypass modality check)."""
    ct_only = _mk_cand(1, "CT Only", can_ct=True, can_mri=False)
    mri_doc = _mk_cand(2, "MRI Doc", can_ct=True, can_mri=True)
    mra_exam = ExamContext(
        exam_id="EX-MRA-1",
        patient_id="P1",
        modality="MRA",
        body_part="brain",
        exam_code="22831",
        lab_id="6",
        issuing_doctor_id="100",
        request_date=date(2026, 11, 24),
    )

    r1 = filter_by_modality(ct_only, mra_exam)
    r2 = filter_by_modality(mri_doc, mra_exam)
    assert r1.passed is False
    assert r1.rule_name == "modality"
    assert r2.passed is True


def test_multiple_exclusive_labs_use_or_logic():
    """A doctor with exclusive rules for Lab 1 and Lab 6 should accept Lab 1 or Lab 6, reject Lab 7."""
    doc = _mk_cand(10, "Dr MultiLab")
    rules = [
        {"diagnostician_id": 10, "lab_id": 1, "lab_name": "ΚΟΛΙΑΤΣΟΥ", "is_active": True},
        {"diagnostician_id": 10, "lab_id": 6, "lab_name": "ΑΝΩ ΠΑΤΗΣΙΑ", "is_active": True},
    ]

    def _exam_for_lab(lid: str, lname: str) -> ExamContext:
        return ExamContext(
            exam_id=f"EX-{lid}",
            patient_id="P1",
            modality="CT",
            body_part="chest",
            exam_code="21100",
            lab_id=lid,
            lab_name=lname,
            issuing_doctor_id="100",
            request_date=date(2026, 11, 24),
        )

    passed1, _ = apply_hard_filters(
        [doc], _exam_for_lab("1", "ΚΟΛΙΑΤΣΟΥ"), exclusive_rules=rules, modality_quotas=[], comment_rule_enabled=False
    )
    passed6, _ = apply_hard_filters(
        [doc], _exam_for_lab("6", "ΑΝΩ ΠΑΤΗΣΙΑ"), exclusive_rules=rules, modality_quotas=[], comment_rule_enabled=False
    )
    passed7, _ = apply_hard_filters(
        [doc], _exam_for_lab("7", "ΙΛΙΟΝ"), exclusive_rules=rules, modality_quotas=[], comment_rule_enabled=False
    )
    assert len(passed1) == 1
    assert len(passed6) == 1
    assert len(passed7) == 0


def test_comment_multi_negation_and_contrastive():
    """Multi-negation excludes both doctors; contrastive 'ΑΛΛΑ' assigns the second."""
    diags = [
        {"id": 1, "name": "ΝΑΤΣΙΚΑ ΑΙΚΑΤΕΡΙΝΗ", "active": True},
        {"id": 2, "name": "ΜΠΕΡΕΤΗΣ ΙΩΑΝΝΗΣ", "active": True},
    ]

    # Multi-negation: "ΟΧΙ ΝΑΤΣΙΚΑ ΚΑΙ ΜΠΕΡΕΤΗ" -> both excluded, neither assigned
    matched, excluded = parse_comment_diagnosticians("ΟΧΙ ΝΑΤΣΙΚΑ ΚΑΙ ΜΠΕΡΕΤΗ", diags)
    assert matched is None
    assert 1 in excluded
    assert 2 in excluded

    # Contrastive: "ΟΧΙ ΝΑΤΣΙΚΑ ΑΛΛΑ ΜΠΕΡΕΤΗ" -> 1 excluded, 2 assigned
    matched2, excluded2 = parse_comment_diagnosticians("ΟΧΙ ΝΑΤΣΙΚΑ ΑΛΛΑ ΜΠΕΡΕΤΗ", diags)
    assert 1 in excluded2
    assert 2 not in excluded2
    assert matched2 is not None
    assert matched2["id"] == 2

    # Bare first name must NOT falsely auto-assign
    matched3, _ = parse_comment_diagnosticians("ΠΑΡΑΚΑΛΩ ΙΩΑΝΝΗΣ ΝΑ ΕΝΗΜΕΡΩΘΕΙ", diags)
    assert matched3 is None


# ─────────────────────────────────────────────────────────────
#  3. API Security, Validation & Auth Lifecycle (1.2, 1.5, 1.6, 4)
# ─────────────────────────────────────────────────────────────


def test_slis_search_rejects_sql_injection_dates():
    """Invalid/malicious dates in /api/slis/search must be rejected with 422."""
    from diagflow.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/slis/search",
        json={"start_date": "2026-01-01'; DROP TABLE EXAMMORE; --"},
    )
    assert resp.status_code == 422


def test_config_mutations_require_admin_auth():
    """PUT /api/assignments/weights and POST /api/pamakristos/oncall must require admin token."""
    from diagflow.main import app

    client = TestClient(app)
    r1 = client.put("/api/assignments/weights", json={"pts_partnership": 0.2})
    assert r1.status_code == 401

    r2 = client.post(
        "/api/pamakristos/oncall",
        json={"diagnostician_id": 1, "date": "2026-11-24"},
    )
    assert r2.status_code == 401


def test_admin_session_ttl_and_logout_revocation():
    """Expired sessions and logged-out tokens must be rejected with 401."""
    from diagflow.api import routes
    from diagflow.main import app

    client = TestClient(app)
    expired_tok = "test-expired-token-123"
    routes._admin_sessions[expired_tok] = {
        "user_id": 1,
        "username": "admin",
        "role": "admin",
        "expires_at": time.time() - 10,
    }
    try:
        r_exp = client.get("/api/admin/diagnosticians", headers={"X-Admin-Token": expired_tok})
        assert r_exp.status_code == 401
        assert expired_tok not in routes._admin_sessions
    finally:
        routes._admin_sessions.pop(expired_tok, None)

    active_tok = "test-logout-token-456"
    routes._admin_sessions[active_tok] = {
        "user_id": 1,
        "username": "admin",
        "role": "admin",
        "expires_at": time.time() + 3600,
    }
    r_logout = client.post("/api/admin/auth/logout", headers={"X-Admin-Token": active_tok})
    assert r_logout.status_code == 200
    assert active_tok not in routes._admin_sessions


def test_admin_backdoor_does_not_resurrect_default_admin(tmp_path):
    """Deleting/renaming default 'admin' when another admin exists must NOT re-seed admin/admin1234."""
    from diagflow.db import diagflow_db

    db_file = tmp_path / "auth_test.db"
    with patch.object(diagflow_db.settings, "use_mock_slis_db", True), \
         patch.object(diagflow_db, "_DB_PATH", db_file):
        diagflow_db._initialized_sqlite_paths.discard(str(db_file))
        diagflow_db._admin_table_checked_keys.clear()
        diagflow_db.ensure_admin_users_initialized()

        users = diagflow_db.get_all_admin_users()
        assert any(u["username"] == "admin" for u in users)

        # Create a custom admin and delete default 'admin'
        diagflow_db.create_admin_user("chief_admin", "SuperSecret123!", role="admin")
        default_admin = next(u for u in diagflow_db.get_all_admin_users() if u["username"] == "admin")
        diagflow_db.delete_admin_user(default_admin["id"])

        # Re-run table init: 'admin' must NOT be resurrected because users table is non-empty!
        diagflow_db._admin_table_checked_keys.clear()
        diagflow_db.ensure_admin_users_initialized()
        usernames = {u["username"] for u in diagflow_db.get_all_admin_users()}
        assert "chief_admin" in usernames
        assert "admin" not in usernames


def test_reset_admin_user_preserves_username_and_generates_random_password(tmp_path):
    """POST /api/admin/users/{id}/reset must keep username and issue a random temporary password."""
    from diagflow.api import routes
    from diagflow.db import diagflow_db
    from diagflow.main import app

    db_file = tmp_path / "reset_test.db"
    with patch.object(diagflow_db.settings, "use_mock_slis_db", True), \
         patch.object(diagflow_db, "_DB_PATH", db_file):
        diagflow_db._initialized_sqlite_paths.discard(str(db_file))
        diagflow_db._admin_table_checked_keys.clear()
        diagflow_db.ensure_admin_users_initialized()
        created = diagflow_db.create_admin_user("admin_two", "InitialPass123!", role="admin")
        it_user = next(u for u in diagflow_db.get_all_admin_users() if u["role"] == "it_support")

        tok = "test-it-support-reset-token"
        routes._admin_sessions[tok] = {
            "id": it_user["id"],
            "username": it_user["username"],
            "role": "it_support",
            "expires_at": time.time() + 3600,
        }
        try:
            client = TestClient(app)
            resp = client.post(
                f"/api/admin/users/{created['id']}/reset",
                headers={"X-Admin-Token": tok},
            )
            assert resp.status_code == 200
            body = resp.json()
            temp_pw = body["temporary_password"]
            assert isinstance(temp_pw, str)
            assert len(temp_pw) >= 12
            assert temp_pw != "admin1234"
            assert body["username"] == "admin_two"

            # New temporary password authenticates cleanly via login endpoint
            login_resp = client.post(
                "/api/admin/auth/login",
                json={"username": "admin_two", "password": temp_pw},
            )
            assert login_resp.status_code == 200
            login_token = login_resp.json().get("token")
            assert login_token
            routes._admin_sessions.pop(login_token, None)
        finally:
            routes._admin_sessions.pop(tok, None)


# ─────────────────────────────────────────────────────────────
#  4. Mass-Deletion Guard & Atomic On-Call (1.3, 1.10)
# ─────────────────────────────────────────────────────────────


def test_transient_slis_error_does_not_wipe_local_assignments():
    """If Slis DB fetch raises an exception, _get_assigned_exams_from_db must NOT delete staged assignments."""
    from diagflow.services import assignment

    staged = {
        99001: {
            "exammoreid": 99001,
            "extracode": 55501,
            "diagnostician_id": 1,
            "diagnostician_name": "Test Doc",
            "assigned_at": "2026-11-24T10:00:00",
        }
    }
    with patch.object(assignment.settings, "use_mock_slis_db", False), \
         patch("diagflow.services.assignment._fetch_slis_period_rows", side_effect=RuntimeError("ODBC timeout")), \
         patch("diagflow.db.diagflow_db.get_all_local_assignments", return_value=staged), \
         patch("diagflow.db.diagflow_db.delete_local_assignment") as mock_del, \
         patch("diagflow.db.diagflow_db.get_all_diagnosticians", return_value=[]):
        results = assignment._get_assigned_exams_from_db()
        mock_del.assert_not_called()
        assert len(results) == 1
        assert results[0]["exammoreid"] == 99001


def test_atomic_pamakristos_oncall_preserves_notes_and_clears_previous(tmp_path):
    """set_pamakristos_oncall_for_date must clear old on-call for that date and preserve status/notes."""
    from diagflow.db import diagflow_db

    db_file = tmp_path / "oncall_test.db"
    with patch.object(diagflow_db.settings, "use_mock_slis_db", True), \
         patch.object(diagflow_db, "_DB_PATH", db_file):
        diagflow_db._initialized_sqlite_paths.discard(str(db_file))
        d1 = diagflow_db.create_diagnostician(name="Doc One")
        d2 = diagflow_db.create_diagnostician(name="Doc Two")
        id1, id2 = d1["id"], d2["id"]
        diagflow_db.upsert_availability(id1, "2026-11-24", "available", False, "Morning shift")
        diagflow_db.upsert_availability(id2, "2026-11-24", "available", False, "Evening shift")

        diagflow_db.set_pamakristos_oncall_for_date("2026-11-24", id1)
        assert diagflow_db.get_oncall_diagnostician("2026-11-24")["diagnostician_id"] == id1

        diagflow_db.set_pamakristos_oncall_for_date("2026-11-24", id2)
        assert diagflow_db.get_oncall_diagnostician("2026-11-24")["diagnostician_id"] == id2

        # Doc One's notes must still be intact, only is_pamakristos_oncall cleared
        rows = {
            r["diagnostician_id"]: r
            for r in diagflow_db.get_all_availability()
            if r["date"] == "2026-11-24"
        }
        assert bool(rows[id1]["is_pamakristos_oncall"]) is False
        assert rows[id1]["notes"] == "Morning shift"
        assert bool(rows[id2]["is_pamakristos_oncall"]) is True
        assert rows[id2]["notes"] == "Evening shift"


# ─────────────────────────────────────────────────────────────
#  5. Offline Assets, Packaging & SQL Migration (1.7, 1.8, 6)
# ─────────────────────────────────────────────────────────────


def test_offline_assets_and_zero_cdn_links():
    """Vendor Flatpickr assets must exist locally and HTML pages must not depend on external CDNs."""
    vendor = ROOT / "frontend" / "vendor" / "flatpickr"
    assert (vendor / "flatpickr.min.css").is_file()
    assert (vendor / "flatpickr.min.js").is_file()
    assert (vendor / "gr.js").is_file()

    for page in ("index.html", "admin.html"):
        html = (ROOT / "frontend" / page).read_text(encoding="utf-8")
        assert "cdn.jsdelivr.net" not in html, f"{page} still references jsdelivr CDN"
        assert "fonts.googleapis.com" not in html, f"{page} still references Google Fonts CDN"


def test_build_script_includes_numpy_and_noupx():
    """EXE build script must NOT exclude numpy (required by OR-Tools CP-SAT) and should pass --noupx."""
    build_src = (ROOT / "scripts" / "build_exe.py").read_text(encoding="utf-8")
    assert '"--exclude-module", "numpy"' not in build_src
    assert '"--noupx"' in build_src


def test_noconsole_uvicorn_config_and_ortools_import():
    """Uvicorn config with log_config=None must initialize cleanly when stdout/stderr are None."""
    import uvicorn
    from ortools.sat.python import cp_model
    from diagflow.main import app

    assert cp_model.CpModel() is not None

    orig_out, orig_err = sys.stdout, sys.stderr
    try:
        sys.stdout = None  # type: ignore[assignment]
        sys.stderr = None  # type: ignore[assignment]
        cfg = uvicorn.Config(app, host="127.0.0.1", port=8080, log_config=None, access_log=False)
        cfg.configure_logging()
    finally:
        sys.stdout, sys.stderr = orig_out, orig_err


def test_supervisor_sql_migration_file_exists_and_is_idempotent():
    """Single SQL migration file for supervisor must exist with idempotent guards."""
    sql_file = ROOT / "db" / "migrate_final_release.sql"
    assert sql_file.is_file()
    sql = sql_file.read_text(encoding="utf-8")
    assert "IF NOT EXISTS" in sql
    assert "ON DELETE CASCADE" in sql
    assert "df_dismissed_auto_assignments" in sql
    assert "was_overridden" in sql
    assert "score_breakdown" in sql


def test_clean_exam_name_strips_modality_and_no_yellow_selection_lines():
    """cleanExamName must strip MRI/CT/MRA prefixes without corrupting words like SPECT, and styles.css must not use #FDE047 yellow borders."""
    import json
    import subprocess

    app_js = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    # Extract cleanExamName function source
    start = app_js.index("function cleanExamName(")
    end = app_js.index("\n}\n", start) + 3
    fn_src = app_js[start:end]

    script = (
        fn_src
        + """
const cases = [
  ['MRI ΑΝΩ ΚΑΙ ΚΑΤΩ ΚΟΙΛΙΑΣ', 'ΑΝΩ ΚΑΙ ΚΑΤΩ ΚΟΙΛΙΑΣ'],
  ['CT ΘΩΡΑΚΟΣ', 'ΘΩΡΑΚΟΣ'],
  ['MRA ΕΓΚΕΦΑΛΟΥ', 'ΕΓΚΕΦΑΛΟΥ'],
  ['MRI - ΕΓΚΕΦΑΛΟΥ', 'ΕΓΚΕΦΑΛΟΥ'],
  ['ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ (MRI)', 'ΕΓΚΕΦΑΛΟΥ'],
  ['ΑΞΟΝΙΚΗ (CT) ΘΩΡΑΚΟΣ', 'ΘΩΡΑΚΟΣ'],
  ['M.R.I. ΑΥΧΕΝΑ', 'ΑΥΧΕΝΑ'],
  ['SPECT ΕΓΚΕΦΑΛΟΥ', 'SPECT ΕΓΚΕΦΑΛΟΥ'],
  ['MRI', 'MRI'],
];
const out = cases.map(([inp, exp]) => ({ inp, exp, got: cleanExamName(inp) }));
console.log(JSON.stringify(out));
"""
    )
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    results = json.loads(proc.stdout)
    for r in results:
        assert r["got"] == r["exp"], f"cleanExamName({r['inp']!r}) -> {r['got']!r}, expected {r['exp']!r}"

    styles_css = (ROOT / "frontend" / "css" / "styles.css").read_text(encoding="utf-8")
    assert "#FDE047" not in styles_css


def test_noconsole_stream_to_logger_no_recursion_with_basicConfig():
    """Frozen --noconsole mode: _StreamToLogger + logging.basicConfig(stream=sys.stdout) must not recurse."""
    import logging
    import structlog
    from diagflow import launcher

    orig_out, orig_err = sys.stdout, sys.stderr
    root = logging.getLogger()
    orig_handlers = list(root.handlers)
    try:
        sys.stdout = None  # type: ignore[assignment]
        sys.stderr = None  # type: ignore[assignment]
        lg = launcher._configure_launcher_logging()
        assert lg.propagate is False
        assert isinstance(sys.stdout, launcher._StreamToLogger)
        assert isinstance(sys.stderr, launcher._StreamToLogger)

        # Simulate setup_logging() attaching a root StreamHandler pointing at sys.stdout
        stream_handler = logging.StreamHandler(sys.stdout)
        root.addHandler(stream_handler)

        # None of these must trigger RecursionError
        launcher.log("Launcher test message")
        logging.getLogger("uvicorn.error").error("Simulated lifespan error message")
        structlog.get_logger("test_noconsole").info("simulated_event", ok=True)
        print("Simulated print to stdout")
    finally:
        root.handlers[:] = orig_handlers
        sys.stdout, sys.stderr = orig_out, orig_err
