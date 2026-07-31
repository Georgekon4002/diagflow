"""
DiagFlow — Admin Auth & Security Unit Tests
Tests for Findings 1, 4, and 5:
- Admin login with bcrypt hash comparison and DB credentials.
- SHA-256 → bcrypt auto-migration on login.
- Credential update workflow (stores new bcrypt hash).
- SQL column whitelisting on dynamic update queries.
"""

import hashlib
import bcrypt
import pytest
from fastapi.testclient import TestClient

from diagflow.main import app
import diagflow.db.diagflow_db as cfg_db

client = TestClient(app)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin1234"


def _bcrypt_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def _sha256_hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _reset_default_credentials():
    """Reset DB to default admin/admin1234 with a fresh bcrypt hash."""
    user = cfg_db.get_admin_user_by_username(ADMIN_USERNAME)
    if user:
        cfg_db.update_admin_user(user["id"], password_hash=_bcrypt_hash(ADMIN_PASSWORD))


class TestAdminLoginBcrypt:
    def test_login_with_bcrypt_hash_succeeds(self):
        _reset_default_credentials()
        res = client.post("/api/admin/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        assert res.status_code == 200
        data = res.json()
        assert "token" in data
        assert data["username"] == ADMIN_USERNAME

    def test_login_wrong_password_fails(self):
        _reset_default_credentials()
        res = client.post("/api/admin/auth/login", json={"username": ADMIN_USERNAME, "password": "wrongpassword"})
        assert res.status_code == 401

    def test_login_wrong_username_fails(self):
        _reset_default_credentials()
        res = client.post("/api/admin/auth/login", json={"username": "notadmin", "password": ADMIN_PASSWORD})
        assert res.status_code == 401

    def test_sha256_legacy_hash_auto_migrates_to_bcrypt(self):
        """Login should succeed against a legacy SHA-256 hash and silently upgrade it to bcrypt."""
        legacy_hash = _sha256_hash(ADMIN_PASSWORD)
        user = cfg_db.get_admin_user_by_username(ADMIN_USERNAME)
        cfg_db.update_admin_user(user["id"], password_hash=legacy_hash)

        # Confirm the stored hash is still SHA-256 (64 hex chars)
        user = cfg_db.get_admin_user_by_username(ADMIN_USERNAME)
        stored_hash = user["password_hash"]
        assert len(stored_hash) == 64
        assert not stored_hash.startswith("$2")

        # Login — should succeed and trigger migration
        res = client.post("/api/admin/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        assert res.status_code == 200

        # Hash should now be bcrypt
        user = cfg_db.get_admin_user_by_username(ADMIN_USERNAME)
        new_hash = user["password_hash"]
        assert new_hash.startswith("$2b$12$")
        assert bcrypt.checkpw(ADMIN_PASSWORD.encode(), new_hash.encode())

    def test_change_credentials_stores_bcrypt_hash(self):
        _reset_default_credentials()

        # Login to get token
        login_res = client.post("/api/admin/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        assert login_res.status_code == 200
        token = login_res.json()["token"]
        headers = {"X-Admin-Token": token}

        # Change password
        change_res = client.post(
            "/api/admin/auth/change-credentials",
            headers=headers,
            json={"old_password": ADMIN_PASSWORD, "new_username": None, "new_password": "newSecure999"},
        )
        assert change_res.status_code == 200

        # Verify stored hash is bcrypt
        user = cfg_db.get_admin_user_by_username(ADMIN_USERNAME)
        new_hash = user["password_hash"]
        assert new_hash.startswith("$2b$12$")
        assert bcrypt.checkpw(b"newSecure999", new_hash.encode())

        # Login with new credentials
        new_login = client.post("/api/admin/auth/login", json={"username": ADMIN_USERNAME, "password": "newSecure999"})
        assert new_login.status_code == 200

        # Revert
        _reset_default_credentials()

    def test_change_credentials_wrong_old_password_fails(self):
        _reset_default_credentials()
        login_res = client.post("/api/admin/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        token = login_res.json()["token"]
        headers = {"X-Admin-Token": token}

        res = client.post(
            "/api/admin/auth/change-credentials",
            headers=headers,
            json={"old_password": "notthepassword", "new_password": "something"},
        )
        assert res.status_code == 400


class TestSqlColumnWhitelisting:
    def test_unknown_columns_are_ignored(self):
        """Passing unallowed column names should not raise or inject SQL."""
        res = cfg_db.update_exam_routing_rule(
            1,
            {"description": "Test", "malicious_column": "DROP TABLE users;"}
        )
        # The function should complete; malicious_column is silently dropped
        if res:
            assert "malicious_column" not in res


class TestAdminAvailabilityDelete:
    def test_delete_availability_record(self):
        _reset_default_credentials()
        login_res = client.post("/api/admin/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        token = login_res.json()["token"]
        headers = {"X-Admin-Token": token}

        diags = cfg_db.get_all_diagnosticians()
        assert len(diags) > 0
        diag_id = diags[0]["id"]

        # 1. Upsert an availability leave record
        post_res = client.post(
            "/api/admin/availability",
            headers=headers,
            json={"diagnostician_id": diag_id, "date": "2026-07-29", "status": "on_leave", "notes": "Test Leave"},
        )
        assert post_res.status_code == 200

        # Verify it is in DB
        absent_ids = cfg_db.get_absent_diagnostician_ids("2026-07-29")
        assert diag_id in absent_ids

        # 2. Delete the availability record via API
        del_res = client.delete(f"/api/admin/availability/{diag_id}/2026-07-29", headers=headers)
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True

        # Verify it is removed from DB
        absent_ids_after = cfg_db.get_absent_diagnostician_ids("2026-07-29")
        assert diag_id not in absent_ids_after

