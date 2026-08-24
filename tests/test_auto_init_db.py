"""
Test database auto-initialization from templates when db/ folder or files are missing in mock mode.
"""
import sqlite3
from pathlib import Path

import diagflow.db.diagflow_db as cfg_db
import diagflow.services.slis_sync as slis_sync


def test_auto_init_diagflow_db(monkeypatch, tmp_path):
    """Verify that diagflow.db is automatically created and seeded if missing."""
    test_db = tmp_path / "db" / "diagflow.db"
    assert not test_db.exists()

    monkeypatch.setattr(cfg_db, "_DB_PATH", test_db)
    
    # Trigger auto-init via get_all_diagnosticians
    diags = cfg_db.get_all_diagnosticians()
    assert test_db.exists()
    assert len(diags) > 0

    # Verify admin users table was created and seeded
    admin = cfg_db.get_admin_user_by_username("admin")
    assert admin is not None
    assert admin["role"] == "admin"


def test_auto_init_mock_slis_db(monkeypatch, tmp_path):
    """Verify that mock_slis.db is automatically created and seeded with 100% fake data if missing."""
    test_mock_db = tmp_path / "db" / "mock_slis.db"
    assert not test_mock_db.exists()

    monkeypatch.setattr(slis_sync, "_MOCK_DB_PATH", test_mock_db)

    # Trigger auto-init via _get_db
    con = slis_sync._get_db()
    assert test_mock_db.exists()

    rows = con.execute("SELECT fname, lname, wname FROM slis_exams").fetchall()
    assert len(rows) > 0
    for r in rows:
        fname = r["fname"] or ""
        lname = r["lname"] or ""
        wname = r["wname"] or ""
        # Ensure all patients are purely fictional
        assert "ΔΟΚΙΜΑΣΤΙΚΟΣ" in fname
        assert "ΑΣΘΕΝΗΣ" in lname
        # Ensure doctors are purely fictional
        assert "ΠΑΡΑΠΕΜΠΩΝ" in wname or "ΠΑΜΜΑΚΑΡΙΣΤΟΣ" in wname

    # Verify diagnosticians are fictional
    diags = con.execute("SELECT DOCNAME FROM diagnosticians").fetchall()
    for d in diags:
        assert "ΔΙΑΓΝΩΣΤΗΣ" in d["DOCNAME"]

    con.close()


def test_cleanup_mock_data(monkeypatch, tmp_path):
    """Verify that cleanup_mock_data deletes mock_slis.db and companion files."""
    test_mock_db = tmp_path / "db" / "mock_slis.db"
    test_mock_db.parent.mkdir(parents=True, exist_ok=True)
    test_mock_db.write_text("dummy db data", encoding="utf-8")
    wal_file = tmp_path / "db" / "mock_slis.db-wal"
    wal_file.write_text("dummy wal", encoding="utf-8")
    shm_file = tmp_path / "db" / "mock_slis.db-shm"
    shm_file.write_text("dummy shm", encoding="utf-8")

    assert test_mock_db.exists()
    assert wal_file.exists()
    assert shm_file.exists()

    monkeypatch.setattr(slis_sync, "_MOCK_DB_PATH", test_mock_db)

    from diagflow.services.assignment import _exam_details_cache
    _exam_details_cache[9999] = {"patient_name": "Fake Stale Exam"}

    res = slis_sync.cleanup_mock_data()
    assert res["status"] == "ok"
    assert not test_mock_db.exists()
    assert not wal_file.exists()
    assert not shm_file.exists()
    assert len(_exam_details_cache) == 0
