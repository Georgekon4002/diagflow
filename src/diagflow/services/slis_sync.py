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
      - Deletes the row from local_assignments.

    In production:
      - Runs: BEGIN TRAN; UPDATE exammore SET diagnostisid=? WHERE exammoreid=?; COMMIT
      - Deletes the local_assignments row.

    Returns:
        dict with success, exammoreid, diagnostician_id
    """
    if not settings.use_mock_slis_db:
        try:
            from sqlalchemy import create_engine, text
            engine = create_engine(settings.slis_db_connection_string)
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE exammore SET diagnostisid = :did WHERE exammoreid = :eid"),
                    {"did": diagnostician_id, "eid": exammoreid}
                )
            
            now_iso = datetime.now().isoformat()
            
            # Now we must delete from local_assignments!
            import diagflow.db.diagflow_db as cfg_db
            cfg_db.delete_local_assignment(exammoreid)
            
            logger.info(
                "pushed_to_slis_production",
                exammoreid=exammoreid,
                diagnostician_id=diagnostician_id,
            )
            return {
                "success": True,
                "exammoreid": exammoreid,
                "diagnostician_id": diagnostician_id,
                "synced_at": now_iso,
                "sql": f"UPDATE exammore SET diagnostisid = {diagnostician_id} WHERE exammoreid = {exammoreid};"
            }
        except Exception as exc:
            logger.error("push_to_slis_error", exammoreid=exammoreid, error=str(exc))
            return {"success": False, "exammoreid": exammoreid, "error": str(exc)}

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
        
        # Delete from local_assignments!
        import diagflow.db.diagflow_db as cfg_db
        cfg_db.delete_local_assignment(exammoreid)

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
            "sql": f"UPDATE slis_exams SET slis_synced_at = '{now_iso}', diagnostis = {diagnostician_id}, code = '{diagnostician_name}' WHERE exammoreid = {exammoreid};"
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
    import diagflow.db.diagflow_db as cfg_db
    local_assignments = cfg_db.get_all_local_assignments()
    rows = list(local_assignments.values())

    succeeded = []
    failed = []
    queries = []
    for row in rows:
        exammoreid       = row["exammoreid"]
        diagnostician_id = row["diagnostician_id"]
        diagnostician_name = row["diagnostician_name"] or ""
        result = push_exam_to_slis(exammoreid, diagnostician_id, diagnostician_name)
        if result.get("success"):
            succeeded.append(exammoreid)
            if "sql" in result:
                queries.append(result["sql"])
        else:
            failed.append({"exammoreid": exammoreid, "error": result.get("error")})

    logger.info("push_all_complete", total=len(rows), succeeded=len(succeeded), failed=len(failed))
    return {
        "total": len(rows),
        "succeeded": succeeded,
        "failed": failed,
        "queries": queries,
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
    queries = []

    if not exammoreid_list:
        return {"total": 0, "succeeded": [], "failed": [], "queries": []}

    import diagflow.db.diagflow_db as cfg_db
    local_assignments = cfg_db.get_all_local_assignments()

    for exammoreid in exammoreid_list:
        if exammoreid not in local_assignments:
            failed.append({"exammoreid": exammoreid, "error": "Not locally assigned or already pushed."})
            continue

        row = local_assignments[exammoreid]
        diagnostician_id = row["diagnostician_id"]
        diagnostician_name = row["diagnostician_name"] or ""
        
        result = push_exam_to_slis(exammoreid, diagnostician_id, diagnostician_name)
        if result.get("success"):
            succeeded.append(exammoreid)
            if "sql" in result:
                queries.append(result["sql"])
        else:
            failed.append({"exammoreid": exammoreid, "error": result.get("error")})

    logger.info("push_selected_complete", total=len(exammoreid_list), succeeded=len(succeeded), failed=len(failed))
    return {
        "total": len(exammoreid_list),
        "succeeded": succeeded,
        "failed": failed,
        "queries": queries,
    }


# ─────────────────────────────────────────────────────────────────
#  Sync Diagnosticians and Doctors
# ─────────────────────────────────────────────────────────────────

def sync_diagnosticians() -> dict:
    """
    Pull diagnosticians from Slis DB and insert new ones into local diagflow.db.
    """
    import diagflow.db.diagflow_db as cfg_db
    
    if not settings.use_mock_slis_db:
        logger.warning("sync_diagnosticians: real Slis DB not configured — skipping pull")
        return {"synced": 0}

    try:
        con = _get_db()
        rows = con.execute("SELECT PERSONELID, DOCNAME FROM diagnosticians").fetchall()
        con.close()
        
        synced_count = 0
        local_con = sqlite3.connect(cfg_db._DB_PATH)
        local_con.execute("PRAGMA foreign_keys = ON")
        
        for row in rows:
            diag_id = row['PERSONELID']
            diag_name = row['DOCNAME']
            
            # Insert only new entries, defaulting them to inactive (active=0)
            cur = local_con.execute("""
                INSERT INTO diagnosticians (id, name, active) 
                VALUES (?, ?, 0) 
                ON CONFLICT(id) DO NOTHING
            """, (diag_id, diag_name))
            if cur.rowcount > 0:
                synced_count += 1
            
        local_con.commit()
        local_con.close()
        
        logger.info("sync_diagnosticians_complete", new_count=synced_count)
        return {"synced": synced_count}
        
    except Exception as exc:
        logger.error("sync_diagnosticians_error", error=str(exc))
        return {"error": str(exc)}



def sync_doctors() -> dict:
    """
    Pull doctors from Slis DB and insert new ones into local diagflow.db.
    """
    import diagflow.db.diagflow_db as cfg_db
    
    if not settings.use_mock_slis_db:
        logger.warning("sync_doctors: real Slis DB not configured — skipping pull")
        return {"synced": 0}

    try:
        con = _get_db()
        rows = con.execute("SELECT CODE, DOCNAME FROM doctors").fetchall()
        con.close()
        
        synced_count = 0
        local_con = sqlite3.connect(cfg_db._DB_PATH)
        local_con.execute("PRAGMA foreign_keys = ON")
        
        for row in rows:
            doc_id = str(row['CODE'])  # Diagflow uses TEXT for doctor id
            doc_name = row['DOCNAME']
            
            # Insert only new entries
            cur = local_con.execute("""
                INSERT INTO doctors (id, name) 
                VALUES (?, ?) 
                ON CONFLICT(id) DO NOTHING
            """, (doc_id, doc_name))
            if cur.rowcount > 0:
                synced_count += 1
            
        local_con.commit()
        local_con.close()
        
        logger.info("sync_doctors_complete", new_count=synced_count)
        return {"synced": synced_count}
        
    except Exception as exc:
        logger.error("sync_doctors_error", error=str(exc))
        return {"error": str(exc)}

