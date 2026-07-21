-- ============================================================
-- DiagFlow — Slis Update Script
-- ============================================================
-- Updates the diagnostician assignment for a single exam in Slis.
--
-- In production (real Slis MSSQL DB):
--   Replace :diagnostician_id and :exammoreid with actual values
--   via your application's parameterised query.
--
-- Example:
--   BEGIN TRAN
--       UPDATE exammore
--       SET diagnostisid = 97
--       WHERE exammoreid = 20475133
--   COMMIT
--
-- In the mock SQLite DB (development):
--   This script is used as a template; see slis_sync.py for execution.
-- ============================================================

BEGIN TRAN
    UPDATE exammore
    SET diagnostisid = :diagnostician_id
    WHERE exammoreid = :exammoreid
COMMIT
