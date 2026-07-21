"""
DiagFlow — Slis Sync Service
=============================
Handles pulling exam data from Slis into the app's working DB,
pushing confirmed assignments back to Slis, and expiring old entries.

In development (USE_MOCK_SLIS_DB=true):
  - pull_from_slis()    reads from mock_slis.db itself, simulating the
                        supervisor's stored-procedure result set by selecting
                        exams from the last 3 days with no diagnostician.
  - push_to_slis()      updates the mock_slis.db slis_exams table (sets
                        slis_synced_at) instead of calling real Slis MSSQL.
  - delete_expired()    removes rows where visitdate < today-3 days AND
                        slis_synced_at IS NOT NULL (already pushed to Slis).

In production (USE_MOCK_SLIS_DB=false):
  - Replace the mock queries with real pyodbc / MSSQL calls.
  - push_to_slis() should run:
      BEGIN TRAN
        UPDATE exammore SET diagnostisid=? WHERE exammoreid=?
      COMMIT
    and then delete the local row.
"""

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import structlog

from diagflow.config import settings

logger = structlog.get_logger(__name__)

# ── Resolve mock DB path ───────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_MOCK_DB_PATH = _PROJECT_ROOT / settings.mock_slis_db_path


def _get_db() -> sqlite3.Connection:
    """Open a read-write SQLite connection to the mock Slis DB."""
    con = sqlite3.connect(str(_MOCK_DB_PATH))
    con.row_factory = sqlite3.Row
    return con


# ─────────────────────────────────────────────────────────────────
#  Pull from Slis
# ─────────────────────────────────────────────────────────────────

def pull_from_slis() -> dict:
    """
    Simulate pulling fresh exam data from the Slis DB.

    In production this would run the supervisor's stored procedure
    (which produces the #TMP_LIST result set in docs/table.sql).

    In mock mode:
      - The mock_slis.db already contains seeded data.
      - We simply verify the schema is up to date (add slis_synced_at
        if it is missing from an older DB file).
      - Returns a count of how many eligible exams are currently visible.

    Returns:
        dict with keys: pulled (int), expired (int), total_pending (int)
    """
    if not settings.use_mock_slis_db:
        # TODO: implement real Slis pull via pyodbc
        logger.warning("pull_from_slis: real Slis DB not configured — skipping pull")
        return {"pulled": 0, "expired": 0, "total_pending": 0}

    try:
        con = _get_db()

        # ── Ensure slis_synced_at column exists (migration guard) ──
        cols = [row[1] for row in con.execute("PRAGMA table_info(slis_exams)").fetchall()]
        if "slis_synced_at" not in cols:
            con.execute("ALTER TABLE slis_exams ADD COLUMN slis_synced_at TEXT DEFAULT NULL")
            con.commit()
            logger.info("pull_from_slis: added slis_synced_at column to existing DB")

        # ── Expire & remove old synced rows ───────────────────────
        expired = delete_expired(con)

        # ── Count currently-visible pending exams ─────────────────
        cutoff_date = (date.today() - timedelta(days=3)).isoformat()
        today_str   = date.today().isoformat()

        row = con.execute(
            """
            SELECT COUNT(*) FROM slis_exams
            WHERE diagnostis IS NULL
              AND visitdate BETWEEN ? AND ?
            """,
            (cutoff_date, today_str),
        ).fetchone()
        total_pending = row[0] if row else 0

        con.close()

        logger.info(
            "pull_from_slis_complete",
            expired=expired,
            total_pending=total_pending,
        )
        return {
            "pulled": 0,          # In mock mode, data is pre-seeded
            "expired": expired,
            "total_pending": total_pending,
        }

    except Exception as exc:
        logger.error("pull_from_slis_error", error=str(exc))
        return {"pulled": 0, "expired": 0, "total_pending": 0}


# ─────────────────────────────────────────────────────────────────
#  Delete expired rows
# ─────────────────────────────────────────────────────────────────

def delete_expired(con: sqlite3.Connection | None = None) -> int:
    """
    Remove exams that are:
      - Older than 3 days (visitdate < today - 3 days), AND
      - Already pushed to Slis (slis_synced_at IS NOT NULL)

    Unsynced old exams are kept so the user can still push them to Slis
    before they disappear.

    Returns:
        Number of rows deleted.
    """
    close_after = con is None
    if con is None:
        con = _get_db()

    cutoff = (date.today() - timedelta(days=3)).isoformat()
    try:
        cur = con.execute(
            """
            DELETE FROM slis_exams
            WHERE visitdate < ?
              AND slis_synced_at IS NOT NULL
            """,
            (cutoff,),
        )
        con.commit()
        count = cur.rowcount
        if count:
            logger.info("expired_exams_deleted", count=count, cutoff=cutoff)
        return count
    finally:
        if close_after:
            con.close()


# ─────────────────────────────────────────────────────────────────
#  Push to Slis
# ─────────────────────────────────────────────────────────────────

def push_exam_to_slis(exammoreid: int, diagnostician_id: int, diagnostician_name: str) -> dict:
    """
    Push a single exam assignment back to Slis and mark it as synced.

    In mock mode:
      - Updates the mock_slis.db slis_exams row:
          SET slis_synced_at = <now>  (marks it as pushed)
        The real Slis DB is simulated by updating the same row's diagnostis
        field too (so the mock data stays consistent).

    In production:
      - Run: BEGIN TRAN; UPDATE exammore SET diagnostisid=? WHERE exammoreid=?; COMMIT
      - Then set slis_synced_at locally so the row expires on next pull cycle.

    Returns:
        dict with success, exammoreid, diagnostician_id
    """
    if not settings.use_mock_slis_db:
        # TODO: run real Slis MSSQL update via pyodbc
        logger.warning("push_exam_to_slis: real Slis DB not configured")
        return {"success": False, "exammoreid": exammoreid, "error": "Real Slis DB not configured"}

    try:
        con = _get_db()
        now_iso = datetime.now().isoformat()

        # Simulate the Slis update: mark slis_synced_at AND keep diagnostis consistent
        cur = con.execute(
            """
            UPDATE slis_exams
            SET slis_synced_at = ?,
                diagnostis     = ?,
                code           = ?
            WHERE exammoreid = ?
            """,
            (now_iso, diagnostician_id, diagnostician_name, exammoreid),
        )
        con.commit()
        con.close()

        if cur.rowcount == 0:
            return {
                "success": False,
                "exammoreid": exammoreid,
                "error": f"No exam found with exammoreid={exammoreid}",
            }

        logger.info(
            "pushed_to_slis",
            exammoreid=exammoreid,
            diagnostician_id=diagnostician_id,
        )
        return {
            "success": True,
            "exammoreid": exammoreid,
            "diagnostician_id": diagnostician_id,
            "synced_at": now_iso,
        }

    except Exception as exc:
        logger.error("push_to_slis_error", exammoreid=exammoreid, error=str(exc))
        return {"success": False, "exammoreid": exammoreid, "error": str(exc)}


def push_all_to_slis() -> dict:
    """
    Push ALL assigned-but-not-yet-synced exams to Slis in a single loop.

    Returns:
        dict with total, succeeded, failed lists
    """
    try:
        con = _get_db()
        rows = con.execute(
            """
            SELECT exammoreid, diagnostis, code
            FROM slis_exams
            WHERE diagnostis IS NOT NULL
              AND slis_synced_at IS NULL
            """
        ).fetchall()
        con.close()
    except Exception as exc:
        logger.error("push_all_to_slis_query_error", error=str(exc))
        return {"total": 0, "succeeded": [], "failed": []}

    succeeded = []
    failed = []
    for row in rows:
        exammoreid       = row["exammoreid"]
        diagnostician_id = row["diagnostis"]
        diagnostician_name = row["code"] or ""
        result = push_exam_to_slis(exammoreid, diagnostician_id, diagnostician_name)
        if result.get("success"):
            succeeded.append(exammoreid)
        else:
            failed.append({"exammoreid": exammoreid, "error": result.get("error")})

    logger.info("push_all_complete", total=len(rows), succeeded=len(succeeded), failed=len(failed))
    return {
        "total": len(rows),
        "succeeded": succeeded,
        "failed": failed,
    }


def push_selected_to_slis(exammoreid_list: list[int]) -> dict:
    """
    Push a specific selection of exams to Slis.

    Args:
        exammoreid_list: list of exammoreid values to push

    Returns:
        dict with total, succeeded, failed lists
    """
    succeeded = []
    failed = []

    if not exammoreid_list:
        return {"total": 0, "succeeded": [], "failed": []}

    try:
        con = _get_db()
        placeholders = ",".join("?" * len(exammoreid_list))
        rows = con.execute(
            f"""
            SELECT exammoreid, diagnostis, code
            FROM slis_exams
            WHERE exammoreid IN ({placeholders})
              AND diagnostis IS NOT NULL
              AND slis_synced_at IS NULL
            """,
            exammoreid_list,
        ).fetchall()
        con.close()
    except Exception as exc:
        logger.error("push_selected_query_error", error=str(exc))
        return {"total": 0, "succeeded": [], "failed": []}

    for row in rows:
        exammoreid         = row["exammoreid"]
        diagnostician_id   = row["diagnostis"]
        diagnostician_name = row["code"] or ""
        result = push_exam_to_slis(exammoreid, diagnostician_id, diagnostician_name)
        if result.get("success"):
            succeeded.append(exammoreid)
        else:
            failed.append({"exammoreid": exammoreid, "error": result.get("error")})

    logger.info(
        "push_selected_complete",
        requested=len(exammoreid_list),
        succeeded=len(succeeded),
        failed=len(failed),
    )
    return {
        "total": len(rows),
        "succeeded": succeeded,
        "failed": failed,
    }
