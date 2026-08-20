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


def _get_templates_dir() -> Path:
    """Resolve directory where template databases & SQL scripts reside."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "db" / "templates"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent.parent / "db" / "templates"


def ensure_mock_slis_db_initialized() -> None:
    """If mock_slis.db is missing or empty in mock mode, seed it from templates."""
    if not _MOCK_DB_PATH.exists() or _MOCK_DB_PATH.stat().st_size == 0:
        _MOCK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmpl_dir = _get_templates_dir()
        tmpl_db = tmpl_dir / "mock_slis.db"
        if tmpl_db.exists():
            import shutil
            try:
                shutil.copy2(tmpl_db, _MOCK_DB_PATH)
                return
            except Exception:
                pass

        tmpl_sql = tmpl_dir / "init_mock_slis.sql"
        if tmpl_sql.exists():
            try:
                with open(tmpl_sql, "r", encoding="utf-8") as f:
                    sql_content = f.read()
                con = sqlite3.connect(str(_MOCK_DB_PATH))
                con.executescript(sql_content)
                con.close()
            except Exception:
                pass


def ensure_slis_exams_table(con: sqlite3.Connection) -> None:
    """Ensure the slis_exams table and required columns exist in the SQLite cache DB."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS slis_exams (
            exammoreid INTEGER PRIMARY KEY,
            oldexam INTEGER,
            oldvisit INTEGER,
            oldorder TEXT,
            oldpers INTEGER,
            olddiagnostis TEXT,
            aa INTEGER,
            extracode TEXT,
            visitid INTEGER,
            demogid INTEGER,
            fname TEXT,
            lname TEXT,
            age INTEGER,
            examid INTEGER,
            examnumcode TEXT,
            examname TEXT,
            visitdate TEXT,
            labcodeid INTEGER,
            laboratoryname TEXT,
            wardid INTEGER,
            wcode TEXT,
            wname TEXT,
            diagnostis INTEGER,
            personelid INTEGER,
            code TEXT,
            name TEXT,
            notes TEXT,
            category TEXT,
            slis_synced_at TEXT DEFAULT NULL
        )
    """)
    cols = [row[1] for row in con.execute("PRAGMA table_info(slis_exams)").fetchall()]
    if "slis_synced_at" not in cols:
        con.execute("ALTER TABLE slis_exams ADD COLUMN slis_synced_at TEXT DEFAULT NULL")
    if "age" not in cols:
        con.execute("ALTER TABLE slis_exams ADD COLUMN age INTEGER DEFAULT NULL")
    con.commit()


def _get_db() -> sqlite3.Connection:
    """Open a read-write SQLite connection to the mock Slis DB."""
    ensure_mock_slis_db_initialized()
    _MOCK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_MOCK_DB_PATH))
    con.row_factory = sqlite3.Row
    ensure_slis_exams_table(con)
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
    # User requested to NOT automatically update mock DB dates anymore, as it messes with fixed test scenarios.
    pass


def pull_from_slis() -> dict:
    """
    Pull exam data from Slis DB or mock DB.

    In production (USE_MOCK_SLIS_DB=false):
      - Directly queries central MSSQL getExamsListForPeriod_V1 for the last 3 days.
      - Cleans up already-synced exams in df_local_assignments.
      - Applies Stage 0 auto-assignment rules into df_local_assignments.
      - Returns the pending exam count. No local SQLite table is needed.

    In mock mode (USE_MOCK_SLIS_DB=true):
      - Verifies slis_synced_at column exists.
      - Expire old synced rows.
      - Counts pending exams for the last 3 days.
    """
    ensure_mock_slis_dates_last_3_days()

    if not settings.use_mock_slis_db:
        from diagflow.services.assignment import _get_pending_exams_from_db
        pending_list = _get_pending_exams_from_db()
        return {
            "pulled": len(pending_list),
            "expired": 0,
            "total_pending": len(pending_list),
        }

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
    close_con = False
    if con is None:
        con = _get_db()
        close_con = True

    cutoff_date = (date.today() - timedelta(days=3)).isoformat()
    cur = con.execute(
        "DELETE FROM slis_exams WHERE visitdate < ? AND slis_synced_at IS NOT NULL",
        (cutoff_date,)
    )
    deleted_count = cur.rowcount
    con.commit()
    if close_con:
        con.close()
    return deleted_count

def push_exam_to_slis(exammoreid: int, diagnostician_id: int, diagnostician_name: str) -> dict:
    """
    Execute the SQL update required to update a single exam in Slis (or mock_slis.db).
    Updates the database and records local assignment sync timestamp.
    Implements Optimistic Locking: Prevents overwriting if the exam was already assigned concurrently by another user.

    Returns:
        dict with success, exammoreid, diagnostician_id, sql (or conflict, error)
    """
    import diagflow.db.diagflow_db as cfg_db
    now_iso = datetime.now().isoformat()
    sql_cmd = f"UPDATE exammore SET diagnostisid = {diagnostician_id} WHERE exammoreid = {exammoreid};"
    
    try:
        if not settings.use_mock_slis_db:
            from sqlalchemy import create_engine, text
            engine = create_engine(settings.slis_db_connection_string, connect_args={"timeout": 10})
            with engine.connect() as conn:
                # Optimistic locking: Only update if unassigned (NULL / 0) or already set to this diagnostician
                result = conn.execute(
                    text("UPDATE exammore SET diagnostisid = :diag_id WHERE exammoreid = :id AND (diagnostisid IS NULL OR diagnostisid = 0 OR diagnostisid = :diag_id)"),
                    {"diag_id": diagnostician_id, "id": exammoreid}
                )
                conn.commit()
                if result.rowcount == 0:
                    # Concurrency conflict detected! Another user already updated Slis
                    curr = conn.execute(
                        text("SELECT e.diagnostisid, d.docname FROM exammore e LEFT JOIN diagnosticians d ON d.personelid = e.diagnostisid WHERE e.exammoreid = :id"),
                        {"id": exammoreid}
                    ).fetchone()
                    assigned_name = curr[1] if (curr and curr[1]) else (f"ID {curr[0]}" if (curr and curr[0]) else "άλλον χρήστη")
                    logger.warning("optimistic_lock_conflict_detected", exammoreid=exammoreid, current_diag=assigned_name)
                    return {
                        "success": False,
                        "conflict": True,
                        "exammoreid": exammoreid,
                        "current_diagnostician": assigned_name,
                        "error": f"Η εξέταση #{exammoreid} έχει ήδη ανατεθεί στον/στην {assigned_name} στο Slis από άλλον χρήστη.",
                    }

        cat = None
        extra = None
        local_assign = cfg_db.get_all_local_assignments().get(exammoreid)
        if local_assign:
            cat = local_assign.get("modality")
            extra = local_assign.get("extracode")

        try:
            con = _get_db()
            row = con.execute("SELECT category, extracode, diagnostis, code, slis_synced_at FROM slis_exams WHERE exammoreid = ?", (exammoreid,)).fetchone()
            if row:
                cat = cat or (row["category"] if "category" in row.keys() else None)
                extra = extra or (str(row["extracode"]) if ("extracode" in row.keys() and row["extracode"]) else None)

                # Mock Mode Optimistic Locking: check if already assigned to someone else
                if (settings.use_mock_slis_db and 
                    row["diagnostis"] is not None and 
                    str(row["diagnostis"]).strip() not in ("", "0", "None", str(diagnostician_id)) and 
                    row["slis_synced_at"] is not None):
                    current_name = row["code"] or f"ID {row['diagnostis']}"
                    con.close()
                    logger.warning("optimistic_lock_conflict_mock", exammoreid=exammoreid, current_diag=current_name)
                    return {
                        "success": False,
                        "conflict": True,
                        "exammoreid": exammoreid,
                        "current_diagnostician": current_name,
                        "error": f"Η εξέταση #{exammoreid} έχει ήδη ανατεθεί στον/στην {current_name} στο Slis από άλλον χρήστη.",
                    }

            con.execute(
                "UPDATE slis_exams SET diagnostis = ?, code = ?, slis_synced_at = ? WHERE exammoreid = ?",
                (diagnostician_id, diagnostician_name, now_iso, exammoreid)
            )
            con.commit()
            con.close()
        except Exception as cache_exc:
            logger.warning("failed_to_update_local_slis_cache", exammoreid=exammoreid, error=str(cache_exc))

        cfg_db.mark_local_assignment_synced(exammoreid, now_iso)
        cfg_db.log_assignment(exammoreid, diagnostician_id, now_iso, cat, extra)

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


def search_slis_exams(
    start_date: str | None = None,
    end_date: str | None = None,
    extracode: str | None = None,
    patient_query: str | None = None,
    doctor_query: str | None = None,
    diagnostician_query: str | None = None,
) -> list[dict]:
    """
    Search exams directly in Slis (production MSSQL or mock_slis.db).
    Defaults to last 7 days if date range is omitted.
    Filters by extracode (Order ID), patient name/ID, doctor name/ID, diagnostician name/ID.
    Returns list of exam dicts with current Slis assignment details.
    """
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_dt = date.today() - timedelta(days=7)
        start_date = start_dt.isoformat()

    logger.info("searching_slis_exams", start=start_date, end=end_date, extracode=extracode)

    rows = []
    if not settings.use_mock_slis_db:
        try:
            from sqlalchemy import create_engine, text
            engine = create_engine(settings.slis_db_connection_string, connect_args={"timeout": 10})
            with engine.connect() as conn:
                query = text(f"EXEC getExamsListForPeriod_V1 '{start_date}', '{end_date}'")
                res = conn.execute(query)
                keys = list(res.keys())
                raw_rows = [dict(zip(keys, r)) for r in res.fetchall()]
                for r in raw_rows:
                    row_dict = {k.lower(): v for k, v in r.items()}
                    rows.append(row_dict)
        except Exception as exc:
            logger.error("search_slis_production_error", error=str(exc))
            return []
    else:
        try:
            con = _get_db()
            cur = con.execute(
                "SELECT * FROM slis_exams WHERE visitdate BETWEEN ? AND ?",
                (start_date, end_date)
            )
            rows = [dict(r) for r in cur.fetchall()]
            con.close()
        except Exception as exc:
            logger.error("search_slis_mock_error", error=str(exc))
            return []

    # Fetch local diagnostician names and local pending assignments
    import diagflow.db.diagflow_db as cfg_db
    local_diags = {d["id"]: d["name"] for d in cfg_db.get_all_diagnosticians()}
    local_assignments = cfg_db.get_all_local_assignments()

    # Apply filters in Python
    filtered = []
    extracode_clean = str(extracode).strip().lower() if extracode else ""
    patient_clean = str(patient_query).strip().lower() if patient_query else ""
    doctor_clean = str(doctor_query).strip().lower() if doctor_query else ""
    diag_clean = str(diagnostician_query).strip().lower() if diagnostician_query else ""

    for r in rows:
        if extracode_clean:
            row_ext = str(r.get("extracode") or "").strip().lower()
            if extracode_clean not in row_ext:
                continue

        if patient_clean:
            pat_haystack = f"{r.get('demogid') or ''} {r.get('fname') or ''} {r.get('lname') or ''}".lower()
            if patient_clean not in pat_haystack:
                continue

        if doctor_clean:
            doc_haystack = f"{r.get('wcode') or ''} {r.get('wname') or ''}".lower()
            if doctor_clean not in doc_haystack:
                continue

        exam_more_id = r.get("exammoreid")
        local_assign = local_assignments.get(exam_more_id) if exam_more_id else None

        # Check Slis diagnostis field
        raw_diag = r.get("diagnostis")
        slis_diag_id = None
        if raw_diag is not None:
            try:
                diag_str = str(raw_diag).strip().lower()
                if diag_str and diag_str not in ("none", "null", "0", ""):
                    slis_diag_id = int(float(diag_str))
            except (ValueError, TypeError):
                pass

        if slis_diag_id is not None:
            # Real Slis DB is updated! Clear any stale local draft assignment for this exam
            if local_assign and exam_more_id:
                cfg_db.delete_local_assignment(exam_more_id)
            diag_id = slis_diag_id
            raw_name = r.get("code") or r.get("name")
            diag_name = str(raw_name).strip() if raw_name else (local_diags.get(diag_id) or f"ID: {diag_id}")
            status = "synced"
            pending_slis_update = False
        elif local_assign:
            diag_id = local_assign["diagnostician_id"]
            diag_name = local_assign.get("diagnostician_name") or (local_diags.get(diag_id) or f"ID: {diag_id}")
            status = "pending_slis_update"
            pending_slis_update = True
        else:
            diag_id = None
            diag_name = ""
            status = "pending"
            pending_slis_update = False

        if diag_clean:
            diag_haystack = f"{diag_id or ''} {diag_name}".lower()
            if diag_clean not in diag_haystack:
                continue

        raw_cat = r.get("category")
        norm_cat = normalize_modality(raw_cat)

        filtered.append({
            "exam_id": str(r.get("exammoreid")),
            "exammoreid": r.get("exammoreid"),
            "extracode": r.get("extracode"),
            "visitid": r.get("visitid"),
            "patient_id": str(r.get("demogid")) if r.get("demogid") else None,
            "demogid": r.get("demogid"),
            "fname": r.get("fname") or "",
            "lname": r.get("lname") or "",
            "patient_name": f"{r.get('fname') or ''} {r.get('lname') or ''}".strip(),
            "age": r.get("age"),
            "examnumcode": r.get("examnumcode"),
            "examname": r.get("examname") or "",
            "modality": norm_cat,
            "category": norm_cat,
            "visitdate": str(r.get("visitdate"))[:10] if r.get("visitdate") else "",
            "labcodeid": r.get("labcodeid"),
            "lab_name": (r.get("laboratoryname") or "").strip(),
            "wcode": r.get("wcode"),
            "issuing_doctor_name": r.get("wname") or "",
            "diagnostis": diag_id,
            "diagnostician_name": diag_name,
            "status": status,
            "pending_slis_update": pending_slis_update,
            "notes": r.get("notes") or "",
        })

    logger.info("search_slis_complete", total_found=len(rows), filtered=len(filtered))
    return filtered



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
            failed.append({
                "exammoreid": exammoreid,
                "conflict": result.get("conflict", False),
                "error": result.get("error", "Failed to update")
            })

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
            failed.append({
                "exammoreid": exammoreid,
                "conflict": result.get("conflict", False),
                "error": result.get("error", "Failed to update")
            })

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
    and insert NEW ones into diagflow tables (active=0 default).
    """
    import diagflow.db.diagflow_db as cfg_db

    synced_count = 0
    try:
        if not settings.use_mock_slis_db:
            from diagflow.db.engines import get_slis_engine
            from sqlalchemy import text
            engine = get_slis_engine()
            with engine.connect() as conn:
                res = conn.execute(text("EXEC getdiagnosticsList"))
                keys = list(res.keys())
                rows = [dict(zip(keys, row)) for row in res.fetchall()]

            for row in rows:
                r_dict = {k.lower(): v for k, v in row.items()}
                diag_id = normalize_diag_id(r_dict.get("personelid"))
                diag_name = r_dict.get("docname")
                if diag_id is not None and diag_name:
                    existing = cfg_db.get_diagnostician(int(diag_id))
                    if not existing:
                        cfg_db.upsert_diagnostician(int(diag_id), str(diag_name).strip(), active=False)
                        synced_count += 1
        else:
            con = _get_db()
            rows = con.execute("SELECT PERSONELID, DOCNAME FROM diagnosticians").fetchall()
            con.close()

            for row in rows:
                diag_id = normalize_diag_id(row['PERSONELID'])
                diag_name = row['DOCNAME']
                if diag_id is not None and diag_name:
                    existing = cfg_db.get_diagnostician(int(diag_id))
                    if not existing:
                        cfg_db.upsert_diagnostician(int(diag_id), str(diag_name).strip(), active=False)
                        synced_count += 1

        logger.info("sync_diagnosticians_complete", new_count=synced_count)
        return {"synced": synced_count}

    except Exception as exc:
        logger.error("sync_diagnosticians_error", error=str(exc))
        return {"error": str(exc)}


def sync_doctors() -> dict:
    """
    Pull ward doctors from Slis DB (EXEC getWardDoctors) or mock DB,
    and insert NEW ones into diagflow tables.
    """
    import diagflow.db.diagflow_db as cfg_db

    synced_count = 0
    try:
        if not settings.use_mock_slis_db:
            from diagflow.db.engines import get_slis_engine
            from sqlalchemy import text
            engine = get_slis_engine()
            with engine.connect() as conn:
                res = conn.execute(text("EXEC getWardDoctors"))
                keys = list(res.keys())
                rows = [dict(zip(keys, row)) for row in res.fetchall()]

            for row in rows:
                r_dict = {k.lower(): v for k, v in row.items()}
                doc_id = normalize_doctor_id(r_dict.get("code"))
                doc_name = r_dict.get("docname")
                if doc_id and doc_name:
                    cfg_db.upsert_doctor(doc_id, str(doc_name).strip())
                    synced_count += 1
        else:
            con = _get_db()
            rows = con.execute("SELECT CODE, DOCNAME FROM doctors").fetchall()
            con.close()

            for row in rows:
                doc_id = normalize_doctor_id(row['CODE'])
                doc_name = str(row['DOCNAME']).strip()
                if doc_id and doc_name:
                    cfg_db.upsert_doctor(doc_id, doc_name)
                    synced_count += 1

        logger.info("sync_doctors_complete", new_count=synced_count)
        return {"synced": synced_count}

    except Exception as exc:
        logger.error("sync_doctors_error", error=str(exc))
        return {"error": str(exc)}

