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
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import structlog

from diagflow.config import settings

logger = structlog.get_logger(__name__)

# ── Resolve project root and mock DB path ──────────────────────────
if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).parent
    if (_exe_dir / "db").exists():
        _PROJECT_ROOT = _exe_dir
    elif (_exe_dir.parent / "db").exists():
        _PROJECT_ROOT = _exe_dir.parent
    else:
        _PROJECT_ROOT = _exe_dir
else:
    _PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_MOCK_DB_PATH = _PROJECT_ROOT / settings.mock_slis_db_path


def _get_db() -> sqlite3.Connection:
    """Open a read-write SQLite connection to the mock Slis DB."""
    _MOCK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_MOCK_DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def normalize_modality(cat: str | None) -> str:
    """
    Normalize raw SLIS exam category/modality to standard codes: MRI, CT, MRA.
    Handles Greek category strings (e.g., ΜΑΓΝΗΤΙΚΗ, ΑΞΟΝΙΚΗ, ΑΓΓΕΙΟΓΡΑΦΙΑ).
    """
    if not cat:
        return "MRI"
    cat_upper = str(cat).upper().strip()
    if "MRA" in cat_upper or "ΑΓΓΕΙΟ" in cat_upper:
        return "MRA"
    if "ΜΑΓΝΗΤ" in cat_upper or "MRI" in cat_upper:
        return "MRI"
    if "ΑΞΟΝ" in cat_upper or "CT" in cat_upper:
        return "CT"
    return cat_upper


# ─────────────────────────────────────────────────────────────────
#  Pull from Slis
# ─────────────────────────────────────────────────────────────────

def ensure_mock_slis_dates_last_3_days():
    """Ensure mock_slis.db exams always have visitdate values within the last 3 days relative to today."""
    if not settings.use_mock_slis_db:
        return
    try:
        con = _get_db()
        today = date.today()
        dates = [
            (today - timedelta(days=2)).isoformat(),
            (today - timedelta(days=1)).isoformat(),
            today.isoformat()
        ]
        rows = con.execute("SELECT exammoreid FROM slis_exams").fetchall()
        for r in rows:
            eid = r[0]
            target_date = dates[eid % 3]
            con.execute("UPDATE slis_exams SET visitdate = ? WHERE exammoreid = ?", (target_date, eid))
        con.commit()
        con.close()
    except Exception as exc:
        logger.warning("ensure_mock_slis_dates_failed", error=str(exc))


def pull_from_slis() -> dict:
    """
    Pull exam data from Slis DB or mock DB.

    In production (USE_MOCK_SLIS_DB=false):
      - Executes stored procedure `EXEC getExamsListForPeriod 'YYYY-MM-DD', 'YYYY-MM-DD'`
        for the last 3 days up to today.
      - Filters results to only exams where DIAGNOSTIS IS NULL (unassigned).
      - Clears old mock/non-existent exams in local slis_exams table.
      - Populates local slis_exams table in mock_slis.db so the app's local processing pipeline runs seamlessly.

    In mock mode (USE_MOCK_SLIS_DB=true):
      - Ensures visitdate values in mock DB are dynamically within the last 3 days.
      - Verifies slis_synced_at column exists.
      - Expire old synced rows.
      - Counts pending exams for the last 3 days.
    """
    ensure_mock_slis_dates_last_3_days()

    if not settings.use_mock_slis_db:
        try:
            from sqlalchemy import create_engine, text
            engine = create_engine(settings.slis_db_connection_string)

            end_date = date.today()
            start_date = end_date - timedelta(days=3)
            start_str = start_date.strftime("%Y-%m-%d")
            end_str = end_date.strftime("%Y-%m-%d")

            logger.info("pulling_real_slis_exams", start=start_str, end=end_str)

            with engine.connect() as conn:
                query = text(f"EXEC getExamsListForPeriod '{start_str}', '{end_str}'")
                res = conn.execute(query)
                keys = list(res.keys())
                rows = [dict(zip(keys, row)) for row in res.fetchall()]

            unassigned_rows = [
                r for r in rows
                if r.get("DIAGNOSTIS") is None or r.get("DIAGNOSTIS") == "" or str(r.get("DIAGNOSTIS")).strip().lower() == "none"
            ]

            pulled_count = len(unassigned_rows)
            pulled_exammoreids = [r.get("exammoreid") for r in rows if r.get("exammoreid") is not None]

            con = _get_db()
            cols = [row[1] for row in con.execute("PRAGMA table_info(slis_exams)").fetchall()]
            if "slis_synced_at" not in cols:
                con.execute("ALTER TABLE slis_exams ADD COLUMN slis_synced_at TEXT DEFAULT NULL")
                con.commit()

            # Clean out pre-existing mock/stale exams that are NOT in the pulled real SLIS exams list
            if pulled_exammoreids:
                placeholders = ",".join(["?"] * len(pulled_exammoreids))
                con.execute(f"DELETE FROM slis_exams WHERE exammoreid NOT IN ({placeholders})", pulled_exammoreids)
            else:
                con.execute("DELETE FROM slis_exams")
            con.commit()

            expired = delete_expired(con)

            for r in rows:
                row_dict = {k.lower(): v for k, v in r.items()}
                exammoreid = row_dict.get("exammoreid")
                if not exammoreid:
                    continue

                raw_cat = row_dict.get("category")
                norm_cat = normalize_modality(raw_cat)

                con.execute(
                    """
                    INSERT INTO slis_exams (
                        oldexam, oldvisit, oldorder, oldpers, olddiagnostis, aa,
                        extracode, visitid, demogid, fname, lname, examid,
                        examnumcode, examname, visitdate, labcodeid, laboratoryname,
                        wardid, wcode, wname, diagnostis, personelid, code, name,
                        notes, exammoreid, category
                    ) VALUES (
                        :oldexam, :oldvisit, :oldorder, :oldpers, :olddiagnostis, :aa,
                        :extracode, :visitid, :demogid, :fname, :lname, :examid,
                        :examnumcode, :examname, :visitdate, :labcodeid, :laboratoryname,
                        :wardid, :wcode, :wname, :diagnostis, :personelid, :code, :name,
                        :notes, :exammoreid, :category
                    )
                    ON CONFLICT(exammoreid) DO UPDATE SET
                        extracode=excluded.extracode,
                        visitid=excluded.visitid,
                        demogid=excluded.demogid,
                        fname=excluded.fname,
                        lname=excluded.lname,
                        examnumcode=excluded.examnumcode,
                        examname=excluded.examname,
                        visitdate=excluded.visitdate,
                        labcodeid=excluded.labcodeid,
                        laboratoryname=excluded.laboratoryname,
                        wardid=excluded.wardid,
                        wcode=excluded.wcode,
                        wname=excluded.wname,
                        diagnostis=excluded.diagnostis,
                        notes=excluded.notes,
                        category=excluded.category
                    """,
                    {
                        "oldexam": row_dict.get("oldexam"),
                        "oldvisit": row_dict.get("oldvisit"),
                        "oldorder": str(row_dict.get("oldorder")) if row_dict.get("oldorder") else None,
                        "oldpers": row_dict.get("oldpers"),
                        "olddiagnostis": str(row_dict.get("olddiagnostis")) if row_dict.get("olddiagnostis") else None,
                        "aa": row_dict.get("aa"),
                        "extracode": row_dict.get("extracode"),
                        "visitid": row_dict.get("visitid"),
                        "demogid": row_dict.get("demogid"),
                        "fname": row_dict.get("fname"),
                        "lname": row_dict.get("lname"),
                        "examid": row_dict.get("examid"),
                        "examnumcode": row_dict.get("examnumcode"),
                        "examname": row_dict.get("examname"),
                        "visitdate": str(row_dict.get("visitdate"))[:10] if row_dict.get("visitdate") else None,
                        "labcodeid": row_dict.get("labcodeid"),
                        "laboratoryname": row_dict.get("laboratoryname"),
                        "wardid": row_dict.get("wardid"),
                        "wcode": str(row_dict.get("wcode")) if row_dict.get("wcode") else None,
                        "wname": row_dict.get("wname"),
                        "diagnostis": row_dict.get("diagnostis"),
                        "personelid": row_dict.get("personelid"),
                        "code": row_dict.get("code"),
                        "name": row_dict.get("name"),
                        "notes": row_dict.get("notes"),
                        "exammoreid": exammoreid,
                        "category": norm_cat,
                    }
                )

                # Populate exam_dictionary in diagflow.db with pulled exam codes
                if row_dict.get("examnumcode") and row_dict.get("examname"):
                    try:
                        import diagflow.db.diagflow_db as cfg_db
                        cfg_db.upsert_exam_dictionary_entry(str(row_dict["examnumcode"]), str(row_dict["examname"]), norm_cat)
                    except Exception:
                        pass

            con.commit()

            cutoff_date = (date.today() - timedelta(days=3)).isoformat()
            today_str = date.today().isoformat()
            count_row = con.execute(
                "SELECT COUNT(*) FROM slis_exams WHERE diagnostis IS NULL AND visitdate BETWEEN ? AND ?",
                (cutoff_date, today_str),
            ).fetchone()
            total_pending = count_row[0] if count_row else 0
            con.close()

            # Clean orphaned local assignments in diagflow.db that no longer match any pulled SLIS exam
            import diagflow.db.diagflow_db as cfg_db
            with cfg_db._conn() as local_con:
                if pulled_exammoreids:
                    placeholders = ",".join(["?"] * len(pulled_exammoreids))
                    local_con.execute(f"DELETE FROM local_assignments WHERE exammoreid NOT IN ({placeholders})", pulled_exammoreids)

            logger.info("pull_from_slis_production_complete", pulled=pulled_count, total_pending=total_pending)
            return {"pulled": pulled_count, "expired": expired, "total_pending": total_pending}

        except Exception as exc:
            logger.error("pull_from_slis_production_error", error=str(exc))
            return {"pulled": 0, "expired": 0, "total_pending": 0}

    try:
        con = _get_db()

        # ── Ensure slis_synced_at column exists (migration guard) ──
        cols = [row[1] for row in con.execute("PRAGMA table_info(slis_exams)").fetchall()]
        if "slis_synced_at" not in cols:
            con.execute("ALTER TABLE slis_exams ADD COLUMN slis_synced_at TEXT DEFAULT NULL")
            con.commit()
            logger.info("pull_from_slis: added slis_synced_at column to existing DB")

        # Normalize any existing categories in mock DB
        rows = con.execute("SELECT exammoreid, category FROM slis_exams").fetchall()
        for r in rows:
            eid = r["exammoreid"]
            cat = r["category"]
            norm = normalize_modality(cat)
            if norm != cat:
                con.execute("UPDATE slis_exams SET category = ? WHERE exammoreid = ?", (norm, eid))
        con.commit()

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
    if con is None:
        con = _get_db()

def push_exam_to_slis(exammoreid: int, diagnostician_id: int, diagnostician_name: str) -> dict:
    """
    Execute the SQL update required to update a single exam in Slis (or mock_slis.db).
    Updates the database and records local assignment sync timestamp.

    Returns:
        dict with success, exammoreid, diagnostician_id, sql
    """
    import diagflow.db.diagflow_db as cfg_db
    now_iso = datetime.now().isoformat()
    sql_cmd = f"UPDATE exammore SET diagnostisid = {diagnostician_id} WHERE exammoreid = {exammoreid};"
    
    try:
        if not settings.use_mock_slis_db:
            from sqlalchemy import create_engine, text
            engine = create_engine(settings.slis_db_connection_string)
            with engine.connect() as conn:
                conn.execute(
                    text("UPDATE exammore SET diagnostisid = :diag_id WHERE exammoreid = :id"),
                    {"diag_id": diagnostician_id, "id": exammoreid}
                )
                conn.commit()
        else:
            con = _get_db()
            con.execute(
                "UPDATE exammore SET diagnostisid = ? WHERE exammoreid = ?",
                (diagnostician_id, exammoreid)
            )
            con.commit()
            con.close()

        cfg_db.mark_local_assignment_synced(exammoreid, now_iso)

        logger.info(
            "push_to_slis_success",
            exammoreid=exammoreid,
            diagnostician_id=diagnostician_id,
            synced_at=now_iso,
        )
        return {
            "success": True,
            "exammoreid": exammoreid,
            "diagnostician_id": diagnostician_id,
            "diagnostician_name": diagnostician_name,
            "synced_at": now_iso,
            "sql": sql_cmd,
        }
    except Exception as exc:
        logger.error(
            "push_to_slis_error",
            exammoreid=exammoreid,
            error=str(exc),
        )
        return {
            "success": False,
            "exammoreid": exammoreid,
            "error": str(exc),
        }


def push_all_to_slis() -> dict:
    """
    Execute the SQL update to push ALL assigned-but-not-yet-synced exams to Slis.

    Returns:
        dict with total, succeeded, failed lists, queries, and sql_script
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

    script_lines = ["BEGIN TRANSACTION;"] + [f"  {q}" for q in queries] + ["COMMIT;"]
    formatted_script = "\n".join(script_lines)

    logger.info("push_all_complete", total=len(rows), succeeded=len(succeeded))
    return {
        "total": len(rows),
        "succeeded": succeeded,
        "failed": failed,
        "queries": queries,
        "sql_script": formatted_script,
    }


def push_selected_to_slis(exammoreid_list: list[int]) -> dict:
    """
    Execute the SQL update to push a specific selection of exams to Slis.

    Args:
        exammoreid_list: list of exammoreid values to push

    Returns:
        dict with total, succeeded, failed lists, queries, and sql_script
    """
    succeeded = []
    failed = []
    queries = []

    if not exammoreid_list:
        return {"total": 0, "succeeded": [], "failed": [], "queries": [], "sql_script": "-- No exams selected"}

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

    script_lines = ["BEGIN TRANSACTION;"] + [f"  {q}" for q in queries] + ["COMMIT;"]
    formatted_script = "\n".join(script_lines)

    logger.info("push_selected_complete", total=len(exammoreid_list), succeeded=len(succeeded))
    return {
        "total": len(exammoreid_list),
        "succeeded": succeeded,
        "failed": failed,
        "queries": queries,
        "sql_script": formatted_script,
    }


# ─────────────────────────────────────────────────────────────────
#  Sync Diagnosticians and Doctors
# ─────────────────────────────────────────────────────────────────

def sync_diagnosticians() -> dict:
    """
    Pull diagnosticians from Slis DB (EXEC getdiagnosticsList) or mock DB,
    and insert NEW ones into local diagflow.db (active=0 default, ON CONFLICT DO NOTHING).
    """
    import diagflow.db.diagflow_db as cfg_db

def normalize_diag_id(raw_id) -> int | None:
    if raw_id is None:
        return None
    try:
        return int(float(str(raw_id).strip()))
    except (ValueError, TypeError):
        return None


def normalize_doctor_id(raw_id) -> str:
    if raw_id is None:
        return ""
    s = str(raw_id).strip()
    if s.endswith(".0"):
        s = s[:-2]
    try:
        f = float(s)
        if f.is_integer():
            return str(int(f))
    except (ValueError, TypeError):
        pass
    return s


def sync_diagnosticians() -> dict:
    """
    Pull diagnosticians from Slis DB (EXEC getdiagnosticsList) or mock DB,
    and insert NEW ones into local diagflow.db (active=0 default, ON CONFLICT DO NOTHING).
    """
    import diagflow.db.diagflow_db as cfg_db

    synced_count = 0
    local_con = sqlite3.connect(cfg_db._DB_PATH)
    local_con.execute("PRAGMA foreign_keys = ON")

    try:
        if not settings.use_mock_slis_db:
            from sqlalchemy import create_engine, text
            engine = create_engine(settings.slis_db_connection_string)
            with engine.connect() as conn:
                res = conn.execute(text("EXEC getdiagnosticsList"))
                keys = list(res.keys())
                rows = [dict(zip(keys, row)) for row in res.fetchall()]

            for row in rows:
                r_dict = {k.lower(): v for k, v in row.items()}
                diag_id = normalize_diag_id(r_dict.get("personelid"))
                diag_name = r_dict.get("docname")
                if diag_id is not None and diag_name:
                    cur = local_con.execute("""
                        INSERT INTO diagnosticians (id, name, active) 
                        VALUES (?, ?, 0) 
                        ON CONFLICT(id) DO NOTHING
                    """, (diag_id, str(diag_name).strip()))
                    if cur.rowcount > 0:
                        synced_count += 1
        else:
            con = _get_db()
            rows = con.execute("SELECT PERSONELID, DOCNAME FROM diagnosticians").fetchall()
            con.close()

            for row in rows:
                diag_id = normalize_diag_id(row['PERSONELID'])
                diag_name = row['DOCNAME']
                if diag_id is not None and diag_name:
                    cur = local_con.execute("""
                        INSERT INTO diagnosticians (id, name, active) 
                        VALUES (?, ?, 0) 
                        ON CONFLICT(id) DO NOTHING
                    """, (diag_id, str(diag_name).strip()))
                    if cur.rowcount > 0:
                        synced_count += 1

        local_con.commit()
        local_con.close()

        logger.info("sync_diagnosticians_complete", new_count=synced_count)
        return {"synced": synced_count}

    except Exception as exc:
        local_con.close()
        logger.error("sync_diagnosticians_error", error=str(exc))
        return {"error": str(exc)}


def sync_doctors() -> dict:
    """
    Pull ward doctors from Slis DB (EXEC getWardDoctors) or mock DB,
    and insert NEW ones into local diagflow.db (ON CONFLICT DO NOTHING).
    """
    import diagflow.db.diagflow_db as cfg_db

    synced_count = 0
    local_con = sqlite3.connect(cfg_db._DB_PATH)
    local_con.execute("PRAGMA foreign_keys = ON")

    try:
        if not settings.use_mock_slis_db:
            from sqlalchemy import create_engine, text
            engine = create_engine(settings.slis_db_connection_string)
            with engine.connect() as conn:
                res = conn.execute(text("EXEC getWardDoctors"))
                keys = list(res.keys())
                rows = [dict(zip(keys, row)) for row in res.fetchall()]

            for row in rows:
                r_dict = {k.lower(): v for k, v in row.items()}
                doc_id = normalize_doctor_id(r_dict.get("code"))
                doc_name = r_dict.get("docname")
                if doc_id and doc_name:
                    cur = local_con.execute("""
                        INSERT INTO doctors (id, name) 
                        VALUES (?, ?) 
                        ON CONFLICT(id) DO NOTHING
                    """, (doc_id, str(doc_name).strip()))
                    if cur.rowcount > 0:
                        synced_count += 1
        else:
            con = _get_db()
            rows = con.execute("SELECT CODE, DOCNAME FROM doctors").fetchall()
            con.close()

            for row in rows:
                doc_id = normalize_doctor_id(row['CODE'])
                doc_name = str(row['DOCNAME']).strip()
                if doc_id and doc_name:
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
        local_con.close()
        logger.error("sync_doctors_error", error=str(exc))
        return {"error": str(exc)}

