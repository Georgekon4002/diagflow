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
    """Verify that mock_slis.db is automatically created and seeded if missing."""
    test_mock_db = tmp_path / "db" / "mock_slis.db"
    assert not test_mock_db.exists()

    monkeypatch.setattr(slis_sync, "_MOCK_DB_PATH", test_mock_db)

    # Trigger auto-init via _get_db
    con = slis_sync._get_db()
    assert test_mock_db.exists()

    rows = con.execute("SELECT COUNT(*) FROM slis_exams").fetchone()
    con.close()
    assert rows[0] > 0
