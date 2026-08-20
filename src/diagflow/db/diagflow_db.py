"""
DiagFlow — Config DB Access Layer
==================================
Universal CRUD for DiagFlow configuration and operational tables:
- In mock/dev mode (USE_MOCK_SLIS_DB=true): Connects via sqlite3 to db/diagflow.db
- In production mode (USE_MOCK_SLIS_DB=false): Connects via SQLAlchemy to the central
  MSSQL database using the 'df_' table prefix.
"""
import sqlite3
import sys
from datetime import date, datetime
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from diagflow.config import settings

# Resolve db/ relative to the project root.
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

_DB_PATH = _PROJECT_ROOT / "db" / "diagflow.db"
_last_db_mtime = 0.0


def _get_templates_dir() -> Path:
    """Resolve directory where template databases & SQL scripts reside."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "db" / "templates"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent.parent / "db" / "templates"


def _ensure_diagflow_db_initialized() -> None:
    """If diagflow.db is missing or empty in mock mode, seed it from templates."""
    if not _DB_PATH.exists() or _DB_PATH.stat().st_size == 0:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmpl_dir = _get_templates_dir()
        tmpl_db = tmpl_dir / "diagflow.db"
        if tmpl_db.exists():
            import shutil
            try:
                shutil.copy2(tmpl_db, _DB_PATH)
                return
            except Exception:
                pass
        
        tmpl_sql = tmpl_dir / "init_diagflow.sql"
        if tmpl_sql.exists():
            try:
                with open(tmpl_sql, "r", encoding="utf-8") as f:
                    sql_content = f.read()
                con = sqlite3.connect(_DB_PATH)
                con.executescript(sql_content)
                con.close()
            except Exception:
                pass


def _tbl(name: str) -> str:
    """Return 'df_<name>' when using central DB, else '<name>' for mock SQLite."""
    if not settings.use_mock_slis_db:
        return f"df_{name}"
    return name


def _convert_qmark_to_named(sql: str, params: tuple | list) -> tuple[str, dict]:
    """Convert '?' placeholders to named parameters ':p_0', ':p_1' for SQLAlchemy/pyodbc."""
    param_dict = {}
    parts = sql.split("?")
    new_sql = []
    for i, part in enumerate(parts[:-1]):
        param_name = f"p_{i}"
        new_sql.append(part)
        new_sql.append(f":{param_name}")
        param_dict[param_name] = params[i]
    new_sql.append(parts[-1])
    return "".join(new_sql), param_dict


class ResultAdapter:
    """Wraps SQLite cursor or SQLAlchemy CursorResult to uniformly return dicts."""
    def __init__(self, mode: str, res):
        self.mode = mode
        self.res = res
        if mode == "sqlite":
            self.rowcount = getattr(res, "rowcount", 0)
            self.lastrowid = getattr(res, "lastrowid", None)
        else:
            self.rowcount = getattr(res, "rowcount", 0)
            self.lastrowid = None

    def fetchall(self) -> list[dict]:
        if self.mode == "sqlite":
            rows = self.res.fetchall()
            return [_row_to_dict(r) for r in rows]
        else:
            if hasattr(self.res, "mappings") and self.res.returns_rows:
                return [dict(r) for r in self.res.mappings().all()]
            return []

    def fetchone(self) -> dict | None:
        if self.mode == "sqlite":
            row = self.res.fetchone()
            return _row_to_dict(row) if row else None
        else:
            if hasattr(self.res, "mappings") and self.res.returns_rows:
                row = self.res.mappings().fetchone()
                return dict(row) if row else None
            return None


class DBAdapter:
    """Uniform connection adapter bridging SQLite and SQLAlchemy engines."""
    def __init__(self, mode: str = "sqlite", raw_conn=None):
        self.mode = mode
        self.raw_conn = raw_conn
        self.lastrowid = None
        self.rowcount = 0

    def execute(self, sql: str, params: tuple | list | dict = ()):
        if self.mode == "sqlite":
            cur = self.raw_conn.execute(sql, params)
            self.lastrowid = cur.lastrowid
            self.rowcount = cur.rowcount
            return ResultAdapter("sqlite", cur)
        else:
            from sqlalchemy import text
            if isinstance(params, (tuple, list)):
                t_sql, p_dict = _convert_qmark_to_named(sql, params)
            else:
                t_sql, p_dict = sql, params
            res = self.raw_conn.execute(text(t_sql), p_dict)
            self.rowcount = res.rowcount
            return ResultAdapter("mssql", res)

    def commit(self):
        if self.mode == "sqlite":
            self.raw_conn.commit()
        else:
            self.raw_conn.commit()

    def rollback(self):
        if self.mode == "sqlite":
            self.raw_conn.rollback()
        else:
            self.raw_conn.rollback()


def _ensure_schema(con: sqlite3.Connection) -> None:
    try:
        cols = [row[1] for row in con.execute("PRAGMA table_info(local_assignments)").fetchall()]
        if cols and "extracode" not in cols:
            con.execute("ALTER TABLE local_assignments ADD COLUMN extracode TEXT DEFAULT NULL")
        if cols and "modality" not in cols:
            con.execute("ALTER TABLE local_assignments ADD COLUMN modality TEXT DEFAULT NULL")
        
        log_cols = [row[1] for row in con.execute("PRAGMA table_info(assignment_log)").fetchall()]
        if log_cols and "extracode" not in log_cols:
            con.execute("ALTER TABLE assignment_log ADD COLUMN extracode TEXT DEFAULT NULL")
        if log_cols and "modality" not in log_cols:
            con.execute("ALTER TABLE assignment_log ADD COLUMN modality TEXT DEFAULT NULL")

        con.execute(
            "CREATE TABLE IF NOT EXISTS exam_dictionary ("
            "code TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT)"
        )
        if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='diagnostician_skills'").fetchone():
            con.execute("UPDATE diagnostician_skills SET exam_code = TRIM(exam_code) WHERE exam_code IS NOT NULL")
            con.execute(
                "DELETE FROM diagnostician_skills WHERE rowid NOT IN ("
                "SELECT MIN(rowid) FROM diagnostician_skills GROUP BY diagnostician_id, TRIM(exam_code))"
            )
            con.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_diag_code ON diagnostician_skills(diagnostician_id, exam_code)"
            )
        con.commit()
    except Exception:
        pass


@contextmanager
def _conn() -> Generator[DBAdapter, None, None]:
    global _last_db_mtime
    if settings.use_mock_slis_db:
        _ensure_diagflow_db_initialized()
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        raw_con = sqlite3.connect(_DB_PATH, timeout=10.0)
        raw_con.row_factory = sqlite3.Row
        raw_con.execute("PRAGMA journal_mode = WAL")
        raw_con.execute("PRAGMA foreign_keys = ON")
        raw_con.execute("PRAGMA busy_timeout = 5000")
        
        current_mtime = _DB_PATH.stat().st_mtime if _DB_PATH.exists() else 0.0
        if current_mtime != _last_db_mtime:
            _ensure_schema(raw_con)
            _last_db_mtime = current_mtime

        adapter = DBAdapter("sqlite", raw_con)
        try:
            yield adapter
            adapter.commit()
        except Exception:
            adapter.rollback()
            raise
        finally:
            raw_con.close()
    else:
        from diagflow.db.engines import get_config_engine
        engine = get_config_engine()
        with engine.connect() as raw_conn:
            adapter = DBAdapter("mssql", raw_conn)
            try:
                yield adapter
                adapter.commit()
            except Exception:
                adapter.rollback()
                raise


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    return dict(row)


# ── Diagnosticians ────────────────────────────────────────────────────────────

def get_all_diagnosticians() -> list[dict]:
    tbl = _tbl("diagnosticians")
    with _conn() as con:
        rows = con.execute(
            f"SELECT id, name, active, can_ct, can_mri, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id FROM {tbl} ORDER BY name"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_diagnostician(diag_id: int) -> dict | None:
    tbl = _tbl("diagnosticians")
    with _conn() as con:
        row = con.execute(
            f"SELECT id, name, active, can_ct, can_mri, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id FROM {tbl} WHERE id = ?",
            (diag_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def create_diagnostician(name: str, active: bool = True, can_ct: bool = True,
                         can_mri: bool = True, quota_monday: int = 15, quota_tuesday: int = 15,
                         quota_wednesday: int = 15, quota_thursday: int = 15, quota_friday: int = 15,
                         quota_saturday: int = 0, quota_sunday: int = 0, preferred_lab_id: int | None = None,
                         diag_id: int | None = None) -> dict:
    tbl = _tbl("diagnosticians")
    with _conn() as con:
        if diag_id is None:
            max_row = con.execute(f"SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM {tbl}").fetchone()
            next_id = max_row["next_id"] if isinstance(max_row, dict) else max_row[0]
            diag_id = int(next_id)

        con.execute(
            f"INSERT INTO {tbl} (id, name, active, can_ct, can_mri, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (diag_id, name, int(active), int(can_ct), int(can_mri), quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id),
        )
        row = con.execute(
            f"SELECT id, name, active, can_ct, can_mri, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id FROM {tbl} WHERE id = ?",
            (diag_id,),
        ).fetchone()
    return _row_to_dict(row)


def upsert_diagnostician(diag_id: int, diag_name: str, active: bool = False) -> None:
    tbl = _tbl("diagnosticians")
    with _conn() as con:
        existing = con.execute(f"SELECT id FROM {tbl} WHERE id = ?", (diag_id,)).fetchone()
        if not existing:
            con.execute(
                f"INSERT INTO {tbl} (id, name, active) VALUES (?, ?, ?)",
                (diag_id, str(diag_name).strip(), int(active))
            )


def update_diagnostician(diag_id: int, name: str, active: bool,
                         can_ct: bool, can_mri: bool, quota_monday: int, quota_tuesday: int,
                         quota_wednesday: int, quota_thursday: int, quota_friday: int,
                         quota_saturday: int, quota_sunday: int, preferred_lab_id: int | None = None) -> dict | None:
    tbl = _tbl("diagnosticians")
    with _conn() as con:
        con.execute(
            f"UPDATE {tbl} SET name=?, active=?, can_ct=?, can_mri=?, quota_monday=?, quota_tuesday=?, quota_wednesday=?, quota_thursday=?, quota_friday=?, quota_saturday=?, quota_sunday=?, preferred_lab_id=? WHERE id=?",
            (name, int(active), int(can_ct), int(can_mri), quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id, diag_id),
        )
        row = con.execute(
            f"SELECT id, name, active, can_ct, can_mri, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id FROM {tbl} WHERE id = ?",
            (diag_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def delete_diagnostician(diag_id: int) -> bool:
    tbl = _tbl("diagnosticians")
    with _conn() as con:
        cur = con.execute(f"DELETE FROM {tbl} WHERE id = ?", (diag_id,))
    return cur.rowcount > 0


# ── Skills ────────────────────────────────────────────────────────────────────

def get_skills(diagnostician_id: int | None = None) -> list[dict]:
    tbl_skills = _tbl("diagnostician_skills")
    tbl_diags = _tbl("diagnosticians")
    tbl_dict = _tbl("exam_dictionary")
    with _conn() as con:
        dict_rows = con.execute(f"SELECT code, name FROM {tbl_dict}").fetchall()
        exam_name_map = {str(r["code"]).strip(): r["name"] for r in dict_rows}

        if diagnostician_id is not None:
            rows = con.execute(
                f"SELECT ds.id, ds.diagnostician_id, d.name AS diagnostician_name, "
                f"ds.exam_code AS exam_code, ds.is_preferred "
                f"FROM {tbl_skills} ds "
                f"JOIN {tbl_diags} d ON d.id = ds.diagnostician_id "
                f"WHERE ds.diagnostician_id = ? "
                f"ORDER BY ds.exam_code",
                (diagnostician_id,),
            ).fetchall()
        else:
            rows = con.execute(
                f"SELECT ds.id, ds.diagnostician_id, d.name AS diagnostician_name, "
                f"ds.exam_code AS exam_code, ds.is_preferred "
                f"FROM {tbl_skills} ds "
                f"JOIN {tbl_diags} d ON d.id = ds.diagnostician_id "
                f"ORDER BY d.name, ds.exam_code",
            ).fetchall()

    results = []
    for r in rows:
        d = _row_to_dict(r)
        code_str = str(d.get("exam_code") or "").strip()
        d["exam_code"] = code_str
        d["exam_name"] = exam_name_map.get(code_str, code_str)
        d["exam_title"] = d["exam_name"]
        results.append(d)

    return results


def upsert_skill(diagnostician_id: int, exam_code: str,
                 is_preferred: bool = False) -> dict:
    code_str = str(exam_code).strip()
    tbl_skills = _tbl("diagnostician_skills")
    tbl_diags = _tbl("diagnosticians")
    with _conn() as con:
        con.execute(
            f"DELETE FROM {tbl_skills} WHERE diagnostician_id = ? AND exam_code = ?",
            (diagnostician_id, code_str),
        )
        con.execute(
            f"INSERT INTO {tbl_skills} (diagnostician_id, exam_code, is_preferred) "
            "VALUES (?, ?, ?)",
            (diagnostician_id, code_str, int(is_preferred)),
        )
        row = con.execute(
            f"SELECT ds.id, ds.diagnostician_id, d.name AS diagnostician_name, "
            f"ds.exam_code AS exam_code, ds.is_preferred "
            f"FROM {tbl_skills} ds "
            f"JOIN {tbl_diags} d ON d.id = ds.diagnostician_id "
            f"WHERE ds.diagnostician_id = ? AND ds.exam_code = ?",
            (diagnostician_id, code_str),
        ).fetchone()
    return _row_to_dict(row)


def delete_skill(skill_id: int) -> bool:
    tbl = _tbl("diagnostician_skills")
    with _conn() as con:
        cur = con.execute(f"DELETE FROM {tbl} WHERE id = ?", (skill_id,))
    return cur.rowcount > 0


def update_skill_preference(skill_id: int, is_preferred: bool) -> bool:
    tbl = _tbl("diagnostician_skills")
    with _conn() as con:
        cur = con.execute(
            f"UPDATE {tbl} SET is_preferred = ? WHERE id = ?",
            (1 if is_preferred else 0, skill_id),
        )
    return cur.rowcount > 0


def get_skills_for_diagnostician(diag_id: int) -> list[dict]:
    """Returns list of {exam_code, is_preferred} dicts for engine use."""
    tbl = _tbl("diagnostician_skills")
    with _conn() as con:
        rows = con.execute(
            f"SELECT exam_code, is_preferred FROM {tbl} WHERE diagnostician_id = ?",
            (diag_id,),
        ).fetchall()
    return [{"exam_code": str(r["exam_code"]).strip(), "is_preferred": bool(r["is_preferred"])} for r in rows]


def get_all_skills_grouped() -> dict[int, list[dict]]:
    """Load ALL diagnostician skills in a single query, grouped by diagnostician_id."""
    tbl = _tbl("diagnostician_skills")
    with _conn() as con:
        rows = con.execute(
            f"SELECT diagnostician_id, exam_code, is_preferred FROM {tbl}"
        ).fetchall()
    result: dict[int, list[dict]] = {}
    for r in rows:
        result.setdefault(r["diagnostician_id"], []).append({
            "exam_code": str(r["exam_code"]).strip(),
            "is_preferred": bool(r["is_preferred"])
        })
    return result


def get_exam_dictionary() -> list[dict]:
    tbl = _tbl("exam_dictionary")
    with _conn() as con:
        rows = con.execute(f"SELECT code, name, category FROM {tbl} ORDER BY category, code").fetchall()
    return [{"examnumcode": str(r["code"]).strip(), "code": str(r["code"]).strip(), "name": r["name"], "category": r["category"]} for r in rows]


def upsert_exam_dictionary_entry(code: str, name: str, category: str | None = None) -> dict:
    code_clean = str(code).strip()
    if not code_clean:
        return {}
    tbl = _tbl("exam_dictionary")
    with _conn() as con:
        existing = con.execute(f"SELECT code, category FROM {tbl} WHERE code = ?", (code_clean,)).fetchone()
        if existing:
            cat_val = category if category else existing.get("category")
            con.execute(f"UPDATE {tbl} SET name = ?, category = ? WHERE code = ?", (name.strip(), cat_val, code_clean))
        else:
            con.execute(f"INSERT INTO {tbl} (code, name, category) VALUES (?, ?, ?)", (code_clean, name.strip(), category))
        row = con.execute(f"SELECT code, name, category FROM {tbl} WHERE code = ?", (code_clean,)).fetchone()
    return _row_to_dict(row)


# ── Partnerships ──────────────────────────────────────────────────────────────

def get_all_partnerships() -> list[dict]:
    tbl_p = _tbl("partnerships")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        rows = con.execute(
            f"SELECT p.id, p.issuing_doctor_id, p.issuing_doctor_name, "
            f"p.preferred_diagnostician_id, d.name AS preferred_diagnostician_name, "
            f"p.priority, p.exclusive, p.is_active "
            f"FROM {tbl_p} p "
            f"JOIN {tbl_d} d ON d.id = p.preferred_diagnostician_id "
            f"ORDER BY p.issuing_doctor_name",
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def create_partnership(issuing_doctor_id: str, issuing_doctor_name: str,
                       preferred_diagnostician_id: int, priority: int = 1,
                       exclusive: bool = False, is_active: bool = True) -> dict:
    tbl_p = _tbl("partnerships")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        con.execute(
            f"INSERT INTO {tbl_p} "
            "(issuing_doctor_id, issuing_doctor_name, preferred_diagnostician_id, priority, exclusive, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (issuing_doctor_id, issuing_doctor_name, preferred_diagnostician_id,
             priority, int(exclusive), int(is_active)),
        )
        row = con.execute(
            f"SELECT p.id, p.issuing_doctor_id, p.issuing_doctor_name, "
            f"p.preferred_diagnostician_id, d.name AS preferred_diagnostician_name, "
            f"p.priority, p.exclusive, p.is_active "
            f"FROM {tbl_p} p "
            f"JOIN {tbl_d} d ON d.id = p.preferred_diagnostician_id "
            f"WHERE p.issuing_doctor_id = ? AND p.preferred_diagnostician_id = ? "
            f"ORDER BY p.id DESC",
            (issuing_doctor_id, preferred_diagnostician_id),
        ).fetchone()
    return _row_to_dict(row)


def delete_partnership(part_id: int) -> bool:
    tbl = _tbl("partnerships")
    with _conn() as con:
        cur = con.execute(f"DELETE FROM {tbl} WHERE id = ?", (part_id,))
    return cur.rowcount > 0


def update_partnership(part_id: int, exclusive: bool | None = None, is_active: bool | None = None) -> dict | None:
    tbl_p = _tbl("partnerships")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        updates = []
        params = []
        if exclusive is not None:
            updates.append("exclusive = ?")
            params.append(int(exclusive))
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(int(is_active))
            
        if not updates:
            return None
            
        params.append(part_id)
        query = f"UPDATE {tbl_p} SET {', '.join(updates)} WHERE id = ?"
        con.execute(query, tuple(params))
        
        row = con.execute(
            f"SELECT p.id, p.issuing_doctor_id, p.issuing_doctor_name, "
            f"p.preferred_diagnostician_id, d.name AS preferred_diagnostician_name, "
            f"p.priority, p.exclusive, p.is_active "
            f"FROM {tbl_p} p "
            f"JOIN {tbl_d} d ON d.id = p.preferred_diagnostician_id "
            f"WHERE p.id = ?",
            (part_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_partnerships_by_doctor(issuing_doctor_id: str) -> list[dict]:
    tbl = _tbl("partnerships")
    with _conn() as con:
        rows = con.execute(
            f"SELECT preferred_diagnostician_id, priority, exclusive, is_active "
            f"FROM {tbl} "
            f"WHERE issuing_doctor_id = ? "
            f"ORDER BY priority DESC",
            (issuing_doctor_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_partnerships_for_doctors(doctor_ids: list[str]) -> dict[str, list[dict]]:
    """Batch fetch active partnerships for multiple issuing doctor IDs."""
    if not doctor_ids:
        return {}
    tbl = _tbl("partnerships")
    clean_ids = list({str(d).strip() for d in doctor_ids if str(d).strip()})
    if not clean_ids:
        return {}
    placeholders = ", ".join(["?"] * len(clean_ids))
    with _conn() as con:
        rows = con.execute(
            f"SELECT issuing_doctor_id, preferred_diagnostician_id, priority, exclusive, is_active "
            f"FROM {tbl} "
            f"WHERE issuing_doctor_id IN ({placeholders}) "
            f"ORDER BY priority DESC",
            tuple(clean_ids),
        ).fetchall()
    result: dict[str, list[dict]] = {}
    for r in rows:
        r_dict = _row_to_dict(r)
        result.setdefault(str(r_dict["issuing_doctor_id"]).strip(), []).append(r_dict)
    return result


# ── Availability ──────────────────────────────────────────────────────────────

def get_all_availability() -> list[dict]:
    tbl_a = _tbl("availability")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        rows = con.execute(
            f"SELECT a.id, a.diagnostician_id, d.name AS diagnostician_name, "
            f"a.date, a.status, a.is_pamakristos_oncall, a.notes "
            f"FROM {tbl_a} a "
            f"JOIN {tbl_d} d ON d.id = a.diagnostician_id "
            f"ORDER BY a.date DESC, d.name",
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def upsert_availability(diagnostician_id: int, date: str, status: str = "available",
                        is_pamakristos_oncall: bool = False, notes: str = "") -> dict:
    tbl_a = _tbl("availability")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        existing = con.execute(
            f"SELECT id FROM {tbl_a} WHERE diagnostician_id = ? AND date = ?",
            (diagnostician_id, date)
        ).fetchone()
        if existing:
            con.execute(
                f"UPDATE {tbl_a} SET status = ?, is_pamakristos_oncall = ?, notes = ? WHERE id = ?",
                (status, int(is_pamakristos_oncall), notes, existing["id"])
            )
        else:
            con.execute(
                f"INSERT INTO {tbl_a} (diagnostician_id, date, status, is_pamakristos_oncall, notes) VALUES (?, ?, ?, ?, ?)",
                (diagnostician_id, date, status, int(is_pamakristos_oncall), notes)
            )
        row = con.execute(
            f"SELECT a.id, a.diagnostician_id, d.name AS diagnostician_name, "
            f"a.date, a.status, a.is_pamakristos_oncall, a.notes "
            f"FROM {tbl_a} a "
            f"JOIN {tbl_d} d ON d.id = a.diagnostician_id "
            f"WHERE a.diagnostician_id = ? AND a.date = ?",
            (diagnostician_id, date),
        ).fetchone()
    return _row_to_dict(row)


def delete_availability(diagnostician_id: int, date: str) -> bool:
    tbl = _tbl("availability")
    with _conn() as con:
        res = con.execute(
            f"DELETE FROM {tbl} WHERE diagnostician_id = ? AND date = ?",
            (diagnostician_id, date),
        )
        return res.rowcount > 0


def get_absent_diagnostician_ids(date: str) -> set[int]:
    tbl = _tbl("availability")
    with _conn() as con:
        rows = con.execute(
            f"SELECT diagnostician_id FROM {tbl} WHERE date = ? AND status = 'on_leave'",
            (date,),
        ).fetchall()
    return {r["diagnostician_id"] for r in rows}


def get_exclusive_partnerships() -> dict[str, dict]:
    tbl_p = _tbl("partnerships")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        rows = con.execute(
            f"SELECT p.issuing_doctor_id, p.issuing_doctor_name, "
            f"p.preferred_diagnostician_id, d.name AS preferred_diagnostician_name "
            f"FROM {tbl_p} p "
            f"JOIN {tbl_d} d ON d.id = p.preferred_diagnostician_id "
            f"WHERE p.is_active = 1 AND p.exclusive = 1"
        ).fetchall()
    return {str(r["issuing_doctor_id"]): _row_to_dict(r) for r in rows}


# ── Παμμακάριστος Weekly Schedule ──────────────────────────────────────────────

def init_pamakristos_schedule():
    tbl_ps = _tbl("pamakristos_schedule")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        count_row = con.execute(f"SELECT COUNT(*) AS c FROM {tbl_ps}").fetchone()
        count = count_row["c"] if isinstance(count_row, dict) else count_row[0]
        if count == 0:
            diags = con.execute(f"SELECT id FROM {tbl_d} WHERE active = 1 ORDER BY id").fetchall()
            if diags:
                diag_ids = [d["id"] for d in diags]
                for w in range(min(5, len(diag_ids))):
                    con.execute(
                        f"INSERT INTO {tbl_ps} (weekday, diagnostician_id) VALUES (?, ?)",
                        (w, diag_ids[w % len(diag_ids)])
                    )


def get_pamakristos_weekly_schedule_db() -> list[dict]:
    init_pamakristos_schedule()
    tbl_ps = _tbl("pamakristos_schedule")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        rows = con.execute(
            f"SELECT ps.weekday, ps.diagnostician_id, d.name AS diagnostician_name "
            f"FROM {tbl_ps} ps "
            f"JOIN {tbl_d} d ON d.id = ps.diagnostician_id "
            f"ORDER BY ps.weekday"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_pamakristos_weekly_schedule_db(schedule_items: list[dict]):
    init_pamakristos_schedule()
    tbl_ps = _tbl("pamakristos_schedule")
    with _conn() as con:
        con.execute(f"DELETE FROM {tbl_ps}")
        for item in schedule_items:
            w = int(item["weekday"])
            d_id = item.get("diagnostician_id")
            if d_id is not None and str(d_id).strip() != "":
                con.execute(
                    f"INSERT INTO {tbl_ps} (weekday, diagnostician_id) VALUES (?, ?)",
                    (w, int(d_id)),
                )


def get_oncall_diagnostician(date_str: str) -> dict | None:
    tbl_a = _tbl("availability")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        row = con.execute(
            f"SELECT a.diagnostician_id, d.name AS diagnostician_name, a.date "
            f"FROM {tbl_a} a "
            f"JOIN {tbl_d} d ON d.id = a.diagnostician_id "
            f"WHERE a.date = ? AND a.is_pamakristos_oncall = 1",
            (date_str,),
        ).fetchone()
    if row:
        return _row_to_dict(row)

    try:
        from datetime import date as dt_date
        dt = dt_date.fromisoformat(date_str)
        weekday = dt.weekday()
        if weekday in (5, 6):
            return None
        weekly = get_pamakristos_weekly_schedule_db()
        match = next((item for item in weekly if item["weekday"] == weekday), None)
        if match:
            return {
                "date": date_str,
                "diagnostician_id": match["diagnostician_id"],
                "diagnostician_name": match["diagnostician_name"],
            }
    except Exception:
        pass
    return None


def get_pamakristos_manual_overrides(from_date: str | None = None) -> list[dict]:
    """Retrieve manual on-call schedule overrides for Pammakaristos from today onwards."""
    if from_date is None:
        from datetime import date
        from_date = str(date.today())
    tbl_a = _tbl("availability")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        rows = con.execute(
            f"SELECT a.id, a.diagnostician_id, d.name AS diagnostician_name, a.date, a.status, a.notes "
            f"FROM {tbl_a} a "
            f"JOIN {tbl_d} d ON d.id = a.diagnostician_id "
            f"WHERE a.is_pamakristos_oncall = 1 AND a.date >= ? "
            f"ORDER BY a.date ASC",
            (from_date,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_pamakristos_manual_override(avail_id: int) -> bool:
    """Delete or revert a manual on-call schedule override."""
    tbl_a = _tbl("availability")
    with _conn() as con:
        cur = con.execute(
            f"DELETE FROM {tbl_a} WHERE id = ? AND is_pamakristos_oncall = 1",
            (avail_id,)
        )
        return cur.rowcount > 0


# ── Doctors ───────────────────────────────────────────────────────────────────

def _normalize_greek_str(s: str) -> str:
    if not s:
        return ""
    import unicodedata
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.upper().strip()


def get_all_doctors(q: str = "", skip: int = 0, limit: int = 50) -> dict:
    tbl_doc = _tbl("doctors")
    tbl_p = _tbl("partnerships")
    tbl_diag = _tbl("diagnosticians")
    with _conn() as con:
        rows = con.execute(f"""
            SELECT doc.id, doc.name, diag.name AS partner_name
            FROM {tbl_doc} doc
            LEFT JOIN {tbl_p} p ON doc.id = p.issuing_doctor_id AND p.is_active = 1
            LEFT JOIN {tbl_diag} diag ON p.preferred_diagnostician_id = diag.id
            ORDER BY doc.name
        """).fetchall()

    doc_map = {}
    for r in rows:
        d_dict = _row_to_dict(r)
        d_id = d_dict["id"]
        if d_id not in doc_map:
            doc_map[d_id] = {
                "id": d_id,
                "name": d_dict["name"],
                "partner_names": []
            }
        p_name = d_dict.get("partner_name")
        if p_name and p_name not in doc_map[d_id]["partner_names"]:
            doc_map[d_id]["partner_names"].append(p_name)

    all_items = [
        {
            "id": v["id"],
            "name": v["name"],
            "partner_name": ", ".join(v["partner_names"]) if v["partner_names"] else None
        }
        for v in doc_map.values()
    ]

    if q:
        norm_tokens = [_normalize_greek_str(t) for t in q.split() if t]
        filtered = []
        for d in all_items:
            haystack = _normalize_greek_str(f"{d.get('id', '')} {d.get('name', '')} {d.get('partner_name', '')}")
            if all(token in haystack for token in norm_tokens):
                filtered.append(d)
        total = len(filtered)
        paged = filtered[skip : skip + limit] if limit else filtered[skip:]
        return {"items": paged, "total": total}
    else:
        total = len(all_items)
        paged = all_items[skip : skip + limit] if limit else all_items[skip:]
        return {"items": paged, "total": total}


def upsert_doctor(doctor_id: str, name: str) -> dict:
    if not doctor_id:
        return {}
    tbl = _tbl("doctors")
    with _conn() as con:
        existing = con.execute(f"SELECT id FROM {tbl} WHERE id = ?", (doctor_id,)).fetchone()
        if existing:
            con.execute(f"UPDATE {tbl} SET name = ? WHERE id = ?", (str(name).strip(), doctor_id))
        else:
            con.execute(f"INSERT INTO {tbl} (id, name) VALUES (?, ?)", (doctor_id, str(name).strip()))
        row = con.execute(f"SELECT id, name FROM {tbl} WHERE id = ?", (doctor_id,)).fetchone()
    return _row_to_dict(row)


def delete_doctor(doctor_id: str) -> bool:
    tbl = _tbl("doctors")
    with _conn() as con:
        cur = con.execute(f"DELETE FROM {tbl} WHERE id = ?", (doctor_id,))
    return cur.rowcount > 0


# ── Local Assignments & Assignment Log ───────────────────────────────────────

def upsert_local_assignment(exammoreid: int, diagnostician_id: int, diagnostician_name: str, assigned_at: str, modality: str | None = None, extracode: str | None = None, is_auto: bool = False, rule_desc: str | None = None) -> dict:
    tbl_local = _tbl("local_assignments")
    with _conn() as con:
        existing_local = con.execute(f"SELECT exammoreid FROM {tbl_local} WHERE exammoreid = ?", (exammoreid,)).fetchone()
        if existing_local:
            con.execute(
                f"UPDATE {tbl_local} SET diagnostician_id=?, diagnostician_name=?, assigned_at=?, is_auto=?, rule_desc=?, extracode=?, modality=? WHERE exammoreid=?",
                (diagnostician_id, diagnostician_name, assigned_at, int(is_auto), rule_desc, extracode, modality, exammoreid)
            )
        else:
            con.execute(
                f"INSERT INTO {tbl_local} (exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto, rule_desc, extracode, modality) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (exammoreid, diagnostician_id, diagnostician_name, assigned_at, int(is_auto), rule_desc, extracode, modality)
            )

        row = con.execute(
            f"SELECT exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto, rule_desc, extracode, modality FROM {tbl_local} WHERE exammoreid = ?",
            (exammoreid,)
        ).fetchone()
    return _row_to_dict(row)


def get_all_local_assignments() -> dict[int, dict]:
    tbl = _tbl("local_assignments")
    with _conn() as con:
        rows = con.execute(f"SELECT exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto, rule_desc, extracode, modality FROM {tbl}").fetchall()
        return {r["exammoreid"]: _row_to_dict(r) for r in rows}


def delete_local_assignment(exammoreid: int) -> bool:
    tbl = _tbl("local_assignments")
    with _conn() as con:
        cur = con.execute(f"DELETE FROM {tbl} WHERE exammoreid = ?", (exammoreid,))
        return cur.rowcount > 0


def log_assignment(exammoreid: int, diagnostician_id: int, assigned_at: str | None = None, modality: str | None = None, extracode: str | None = None) -> None:
    if not assigned_at:
        assigned_at = datetime.now().isoformat()
    tbl = _tbl("assignment_log")
    with _conn() as con:
        existing = con.execute(f"SELECT exammoreid FROM {tbl} WHERE exammoreid = ?", (exammoreid,)).fetchone()
        if existing:
            con.execute(
                f"UPDATE {tbl} SET diagnostician_id = ?, assigned_at = ?, modality = ?, extracode = ? WHERE exammoreid = ?",
                (diagnostician_id, assigned_at, modality, extracode, exammoreid)
            )
        else:
            con.execute(
                f"INSERT INTO {tbl} (exammoreid, diagnostician_id, assigned_at, modality, extracode) VALUES (?, ?, ?, ?, ?)",
                (exammoreid, diagnostician_id, assigned_at, modality, extracode)
            )


def mark_local_assignment_synced(exammoreid: int, synced_at: str | None = None) -> bool:
    return delete_local_assignment(exammoreid)


def get_daily_assignment_counts() -> dict[int, dict]:
    dash_data = get_dashboard_data()
    counts = {}
    for d in dash_data:
        did = d["diagnostician_id"]
        total = len(d.get("assigned_exam_ids", []))
        mod_counts = d.get("modality_counts", {})
        mri = mod_counts.get("MRI", 0) + mod_counts.get("MRA", 0)
        ct = mod_counts.get("CT", 0)
        counts[did] = {"total": total, "mri": mri, "ct": ct}
    return counts


def get_dashboard_data() -> list[dict]:
    tbl_diags = _tbl("diagnosticians")
    tbl_mod_quotas = _tbl("modality_quotas")
    tbl_local = _tbl("local_assignments")
    tbl_log = _tbl("assignment_log")
    
    with _conn() as con:
        diags = con.execute(f"SELECT id, name FROM {tbl_diags} WHERE active = 1 ORDER BY name").fetchall()
        quota_rows = con.execute(f"SELECT diagnostician_id, modality, max_count FROM {tbl_mod_quotas} WHERE is_active = 1").fetchall()
        modality_limits = {}
        for qr in quota_rows:
            did = qr["diagnostician_id"]
            if did not in modality_limits:
                modality_limits[did] = {}
            modality_limits[did][qr["modality"].upper()] = qr["max_count"]

        dashboard_map = {}
        for d in diags:
            did = d["id"]
            dashboard_map[did] = {
                "diagnostician_id": did,
                "diagnostician_name": d["name"],
                "assigned_orders": [],
                "modality_counts": {"CT": 0, "MRI": 0, "US": 0, "XRAY": 0},
                "assigned_exam_ids": [],
                "modality_limits": modality_limits.get(did, {})
            }

        today_str = date.today().isoformat()

        # 1. Fetch from local_assignments
        local_assignment_map = {}
        local_rows = con.execute(f"SELECT diagnostician_id, exammoreid, extracode, modality, assigned_at FROM {tbl_local}").fetchall()
        for r in local_rows:
            local_assignment_map[r["exammoreid"]] = {
                "diagnostician_id": r["diagnostician_id"],
                "extracode": r["extracode"],
                "category": r.get("modality"),
                "assigned_at": r["assigned_at"]
            }

        # 2. Fetch from assignment_log for today
        log_assignment_map = {}
        log_rows = con.execute(
            f"SELECT diagnostician_id, exammoreid, extracode, modality as category, assigned_at FROM {tbl_log} WHERE assigned_at LIKE ?",
            (f"{today_str}%",)
        ).fetchall()
        for r in log_rows:
            log_assignment_map[r["exammoreid"]] = {
                "diagnostician_id": r["diagnostician_id"],
                "extracode": r["extracode"],
                "category": r["category"],
                "assigned_at": r["assigned_at"]
            }

    # 3. In Mock mode, check mock_slis.db
    slis_assignment_map = {}
    exam_details = {}
    if settings.use_mock_slis_db:
        try:
            from diagflow.services.assignment import _get_mock_db
            con_slis = _get_mock_db()
            cols = [row[1] for row in con_slis.execute("PRAGMA table_info(slis_exams)").fetchall()]
            has_synced_col = "slis_synced_at" in cols
            query_cols = "exammoreid, extracode, category, diagnostis, visitdate" + (", slis_synced_at" if has_synced_col else "")
            cur_slis = con_slis.execute(f"SELECT {query_cols} FROM slis_exams")
            for r in cur_slis.fetchall():
                eid = r["exammoreid"]
                exam_details[eid] = (r["extracode"], r["category"])
                vdate = str(r["visitdate"])[:10] if (r.keys() and "visitdate" in r.keys() and r["visitdate"]) else None
                synced_at = str(r["slis_synced_at"])[:10] if (has_synced_col and "slis_synced_at" in r.keys() and r["slis_synced_at"]) else None
                
                raw_diag = r["diagnostis"]
                if raw_diag is not None and str(raw_diag).strip() not in ("", "0", "none", "None", "NULL"):
                    try:
                        d_id = int(raw_diag)
                    except Exception:
                        d_id = raw_diag
                    slis_assignment_map[eid] = {
                        "diagnostician_id": d_id,
                        "extracode": r["extracode"],
                        "category": r["category"],
                        "vdate": vdate,
                        "synced_at": synced_at
                    }
            con_slis.close()
        except Exception:
            pass

    all_assigned_eids = set(local_assignment_map.keys()) | set(slis_assignment_map.keys()) | set(log_assignment_map.keys())

    for eid in all_assigned_eids:
        d_id = None
        extracode = None
        category = None
        is_today = False

        if eid in local_assignment_map:
            info = local_assignment_map[eid]
            d_id = info["diagnostician_id"]
            extracode = info["extracode"]
            category = info.get("category")
            assign_date = str(info["assigned_at"])[:10] if info["assigned_at"] else None
            is_today = (assign_date == today_str) or (eid in slis_assignment_map and (slis_assignment_map[eid]["synced_at"] == today_str or slis_assignment_map[eid]["vdate"] == today_str))
        elif eid in slis_assignment_map:
            info = slis_assignment_map[eid]
            d_id = info["diagnostician_id"]
            extracode = info["extracode"]
            category = info["category"]
            synced_at = info["synced_at"]
            vdate = info["vdate"]
            is_today = (synced_at == today_str) or (vdate == today_str) or (eid in log_assignment_map)
        elif eid in log_assignment_map:
            info = log_assignment_map[eid]
            d_id = info["diagnostician_id"]
            extracode = info["extracode"]
            category = info["category"]
            is_today = True

        if d_id is not None:
            try:
                d_id_int = int(d_id)
            except Exception:
                d_id_int = d_id
        else:
            d_id_int = None

        if is_today and d_id_int is not None and d_id_int in dashboard_map:
            dashboard_map[d_id_int]["assigned_exam_ids"].append(eid)

            if not extracode and eid in exam_details:
                extracode = exam_details[eid][0]
            if not category and eid in exam_details:
                category = exam_details[eid][1]

            order_val = str(extracode).strip() if (extracode is not None and str(extracode).strip() != "") else None
            if order_val:
                dashboard_map[d_id_int]["assigned_orders"].append(order_val)

            mod = category.upper() if isinstance(category, str) else ""
            if mod:
                if mod not in dashboard_map[d_id_int]["modality_counts"]:
                    dashboard_map[d_id_int]["modality_counts"][mod] = 0
                dashboard_map[d_id_int]["modality_counts"][mod] += 1

    return [d for d in dashboard_map.values() if len(d["assigned_exam_ids"]) > 0 or len(d["assigned_orders"]) > 0]


# ── Advanced Options: Exam Routing Rules ──────────────────────────────────────

ALLOWED_EXAM_ROUTING_FIELDS = {
    'lab_id', 'issuing_doctor_id', 'issuing_doctor_name',
    'is_pamakristos', 'exam_codes', 'diagnostician_id', 'description', 'is_active'
}
ALLOWED_EXCLUSIVE_LAB_FIELDS = {'diagnostician_id', 'lab_id', 'lab_name', 'is_active'}
ALLOWED_MODALITY_QUOTA_FIELDS = {'diagnostician_id', 'modality', 'max_count', 'is_active'}

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD_HASH = "$2b$12$SsLUct5RLmZJBwDQDBQ7xusD4CrjabY8EX9q.gKZjZbch5HZ2Ovly"
DEFAULT_IT_SUPPORT_USERNAME = "it_support"
DEFAULT_IT_SUPPORT_PASSWORD_HASH = "$2b$12$dk9gH/KU49ZmcFDnQo8bl.D7q8/wcHT.icrlAFlJ8Kd9E3AjItrFa"


def get_all_exam_routing_rules() -> list[dict]:
    tbl_err = _tbl("exam_routing_rules")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        rows = con.execute(
            f'''SELECT err.id, err.lab_id, err.issuing_doctor_id, err.issuing_doctor_name, err.is_pamakristos, err.exam_codes, err.diagnostician_id, err.description, err.is_active, d.name AS diagnostician_name
               FROM {tbl_err} err
               JOIN {tbl_d} d ON err.diagnostician_id = d.id
               ORDER BY err.id'''
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def create_exam_routing_rule(lab_id: int | None, issuing_doctor_id: str | None, issuing_doctor_name: str | None, is_pamakristos: bool, exam_codes: str, diagnostician_id: int, description: str, is_active: bool = True) -> dict:
    tbl_err = _tbl("exam_routing_rules")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        con.execute(
            f'''INSERT INTO {tbl_err} (lab_id, issuing_doctor_id, issuing_doctor_name, is_pamakristos, exam_codes, diagnostician_id, description, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (lab_id, issuing_doctor_id, issuing_doctor_name, int(is_pamakristos), exam_codes, diagnostician_id, description, int(is_active))
        )
        row = con.execute(
            f'''SELECT err.id, err.lab_id, err.issuing_doctor_id, err.issuing_doctor_name, err.is_pamakristos, err.exam_codes, err.diagnostician_id, err.description, err.is_active, d.name AS diagnostician_name
               FROM {tbl_err} err
               JOIN {tbl_d} d ON err.diagnostician_id = d.id
               WHERE err.diagnostician_id = ? AND err.exam_codes = ?
               ORDER BY err.id DESC''',
            (diagnostician_id, exam_codes)
        ).fetchone()
    return _row_to_dict(row)


def update_exam_routing_rule(rule_id: int, update_data: dict) -> dict | None:
    tbl_err = _tbl("exam_routing_rules")
    tbl_d = _tbl("diagnosticians")
    if update_data:
        with _conn() as con:
            sets = []
            vals = []
            for k, v in update_data.items():
                if k not in ALLOWED_EXAM_ROUTING_FIELDS:
                    continue
                if k in ('is_pamakristos', 'is_active'):
                    v = int(v)
                sets.append(f"{k} = ?")
                vals.append(v)
            if sets:
                vals.append(rule_id)
                con.execute(f"UPDATE {tbl_err} SET {', '.join(sets)} WHERE id = ?", tuple(vals))
            
    with _conn() as con:
        row = con.execute(
            f'''SELECT err.id, err.lab_id, err.issuing_doctor_id, err.issuing_doctor_name, err.is_pamakristos, err.exam_codes, err.diagnostician_id, err.description, err.is_active, d.name AS diagnostician_name
               FROM {tbl_err} err
               JOIN {tbl_d} d ON err.diagnostician_id = d.id
               WHERE err.id = ?''',
            (rule_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def delete_exam_routing_rule(rule_id: int) -> bool:
    tbl = _tbl("exam_routing_rules")
    with _conn() as con:
        cur = con.execute(f'DELETE FROM {tbl} WHERE id = ?', (rule_id,))
    return cur.rowcount > 0


# ── Advanced Options: Exclusive Lab Rules ─────────────────────────────────────

def get_all_exclusive_lab_rules() -> list[dict]:
    tbl_elr = _tbl("exclusive_lab_rules")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        rows = con.execute(
            f'''SELECT elr.id, elr.diagnostician_id, elr.lab_id, elr.lab_name, elr.is_active, d.name AS diagnostician_name
               FROM {tbl_elr} elr
               JOIN {tbl_d} d ON elr.diagnostician_id = d.id
               ORDER BY elr.id'''
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def create_exclusive_lab_rule(diagnostician_id: int, lab_id: int, lab_name: str, is_active: bool = True) -> dict:
    tbl_elr = _tbl("exclusive_lab_rules")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        con.execute(
            f'''INSERT INTO {tbl_elr} (diagnostician_id, lab_id, lab_name, is_active)
               VALUES (?, ?, ?, ?)''',
            (diagnostician_id, lab_id, lab_name, int(is_active))
        )
        row = con.execute(
            f'''SELECT elr.id, elr.diagnostician_id, elr.lab_id, elr.lab_name, elr.is_active, d.name AS diagnostician_name
               FROM {tbl_elr} elr
               JOIN {tbl_d} d ON elr.diagnostician_id = d.id
               WHERE elr.diagnostician_id = ? AND elr.lab_id = ?
               ORDER BY elr.id DESC''',
            (diagnostician_id, lab_id)
        ).fetchone()
    return _row_to_dict(row)


def update_exclusive_lab_rule(rule_id: int, update_data: dict) -> dict | None:
    tbl_elr = _tbl("exclusive_lab_rules")
    tbl_d = _tbl("diagnosticians")
    if update_data:
        with _conn() as con:
            sets = []
            vals = []
            for k, v in update_data.items():
                if k not in ALLOWED_EXCLUSIVE_LAB_FIELDS:
                    continue
                if k == 'is_active':
                    v = int(v)
                sets.append(f"{k} = ?")
                vals.append(v)
            if sets:
                vals.append(rule_id)
                con.execute(f"UPDATE {tbl_elr} SET {', '.join(sets)} WHERE id = ?", tuple(vals))
            
    with _conn() as con:
        row = con.execute(
            f'''SELECT elr.id, elr.diagnostician_id, elr.lab_id, elr.lab_name, elr.is_active, d.name AS diagnostician_name
               FROM {tbl_elr} elr
               JOIN {tbl_d} d ON elr.diagnostician_id = d.id
               WHERE elr.id = ?''',
            (rule_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def delete_exclusive_lab_rule(rule_id: int) -> bool:
    tbl = _tbl("exclusive_lab_rules")
    with _conn() as con:
        cur = con.execute(f'DELETE FROM {tbl} WHERE id = ?', (rule_id,))
    return cur.rowcount > 0


# ── Advanced Options: Modality Quotas ─────────────────────────────────────────

def get_all_modality_quotas() -> list[dict]:
    tbl_mq = _tbl("modality_quotas")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        rows = con.execute(
            f'''SELECT mq.id, mq.diagnostician_id, mq.modality, mq.max_count, mq.is_active, d.name AS diagnostician_name
               FROM {tbl_mq} mq
               JOIN {tbl_d} d ON mq.diagnostician_id = d.id
               ORDER BY mq.id'''
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def create_modality_quota(diagnostician_id: int, modality: str, max_count: int, is_active: bool = True) -> dict:
    tbl_mq = _tbl("modality_quotas")
    tbl_d = _tbl("diagnosticians")
    with _conn() as con:
        con.execute(
            f'''INSERT INTO {tbl_mq} (diagnostician_id, modality, max_count, is_active)
               VALUES (?, ?, ?, ?)''',
            (diagnostician_id, modality, max_count, int(is_active))
        )
        row = con.execute(
            f'''SELECT mq.id, mq.diagnostician_id, mq.modality, mq.max_count, mq.is_active, d.name AS diagnostician_name
               FROM {tbl_mq} mq
               JOIN {tbl_d} d ON mq.diagnostician_id = d.id
               WHERE mq.diagnostician_id = ? AND mq.modality = ?
               ORDER BY mq.id DESC''',
            (diagnostician_id, modality)
        ).fetchone()
    return _row_to_dict(row)


def update_modality_quota(rule_id: int, update_data: dict) -> dict | None:
    tbl_mq = _tbl("modality_quotas")
    tbl_d = _tbl("diagnosticians")
    if update_data:
        with _conn() as con:
            sets = []
            vals = []
            for k, v in update_data.items():
                if k not in ALLOWED_MODALITY_QUOTA_FIELDS:
                    continue
                if k == 'is_active':
                    v = int(v)
                sets.append(f"{k} = ?")
                vals.append(v)
            if sets:
                vals.append(rule_id)
                con.execute(f"UPDATE {tbl_mq} SET {', '.join(sets)} WHERE id = ?", tuple(vals))
            
    with _conn() as con:
        row = con.execute(
            f'''SELECT mq.id, mq.diagnostician_id, mq.modality, mq.max_count, mq.is_active, d.name AS diagnostician_name
               FROM {tbl_mq} mq
               JOIN {tbl_d} d ON mq.diagnostician_id = d.id
               WHERE mq.id = ?''',
            (rule_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def delete_modality_quota(quota_id: int) -> bool:
    tbl = _tbl("modality_quotas")
    with _conn() as con:
        cur = con.execute(f'DELETE FROM {tbl} WHERE id = ?', (quota_id,))
    return cur.rowcount > 0


# ── System Settings & Admin Users ─────────────────────────────────────────────

def _ensure_admin_users_table(con):
    tbl = _tbl("admin_users")
    if settings.use_mock_slis_db:
        con.execute(
            f"CREATE TABLE IF NOT EXISTS {tbl} ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "username TEXT UNIQUE NOT NULL, "
            "password_hash TEXT NOT NULL, "
            "role TEXT NOT NULL DEFAULT 'admin', "
            "is_active INTEGER NOT NULL DEFAULT 1)"
        )

    admin_row = con.execute(f"SELECT id FROM {tbl} WHERE username = ?", (DEFAULT_ADMIN_USERNAME,)).fetchone()
    if not admin_row:
        con.execute(
            f"INSERT INTO {tbl} (username, password_hash, role, is_active) VALUES (?, ?, 'admin', 1)",
            (DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD_HASH)
        )

    it_row = con.execute(f"SELECT id FROM {tbl} WHERE username = ?", (DEFAULT_IT_SUPPORT_USERNAME,)).fetchone()
    if not it_row:
        con.execute(
            f"INSERT INTO {tbl} (username, password_hash, role, is_active) VALUES (?, ?, 'it_support', 1)",
            (DEFAULT_IT_SUPPORT_USERNAME, DEFAULT_IT_SUPPORT_PASSWORD_HASH)
        )


def get_admin_user_by_username(username: str) -> dict | None:
    tbl = _tbl("admin_users")
    with _conn() as con:
        _ensure_admin_users_table(con)
        row = con.execute(f"SELECT * FROM {tbl} WHERE username = ?", (username,)).fetchone()
    return _row_to_dict(row) if row else None


def get_admin_user_by_id(user_id: int) -> dict | None:
    tbl = _tbl("admin_users")
    with _conn() as con:
        _ensure_admin_users_table(con)
        row = con.execute(f"SELECT * FROM {tbl} WHERE id = ?", (user_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_all_admin_users() -> list[dict]:
    tbl = _tbl("admin_users")
    with _conn() as con:
        _ensure_admin_users_table(con)
        rows = con.execute(f"SELECT id, username, role, is_active FROM {tbl} ORDER BY id").fetchall()
    return [_row_to_dict(r) for r in rows]


def create_admin_user(username: str, password_hash: str, role: str) -> dict:
    tbl = _tbl("admin_users")
    with _conn() as con:
        _ensure_admin_users_table(con)
        con.execute(
            f"INSERT INTO {tbl} (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role)
        )
        row = con.execute(f"SELECT id, username, role, is_active FROM {tbl} WHERE username = ?", (username,)).fetchone()
    return _row_to_dict(row)


def update_admin_user(user_id: int, username: str | None = None, password_hash: str | None = None, role: str | None = None, is_active: bool | None = None) -> dict | None:
    tbl = _tbl("admin_users")
    with _conn() as con:
        _ensure_admin_users_table(con)
        fields = []
        params = []
        if username is not None:
            fields.append("username=?")
            params.append(username)
        if password_hash is not None:
            fields.append("password_hash=?")
            params.append(password_hash)
        if role is not None:
            fields.append("role=?")
            params.append(role)
        if is_active is not None:
            fields.append("is_active=?")
            params.append(int(is_active))
        
        if fields:
            params.append(user_id)
            con.execute(f"UPDATE {tbl} SET {','.join(fields)} WHERE id=?", tuple(params))
        row = con.execute(f"SELECT id, username, role, is_active FROM {tbl} WHERE id = ?", (user_id,)).fetchone()
    return _row_to_dict(row) if row else None


def delete_admin_user(user_id: int) -> bool:
    tbl = _tbl("admin_users")
    with _conn() as con:
        _ensure_admin_users_table(con)
        cur = con.execute(f"DELETE FROM {tbl} WHERE id = ?", (user_id,))
    return cur.rowcount > 0


def get_system_weights() -> dict:
    """Returns the current AI scoring weights from the DB."""
    tbl = _tbl("system_settings")
    with _conn() as con:
        if settings.use_mock_slis_db:
            con.execute(
                f"CREATE TABLE IF NOT EXISTS {tbl} ("
                "[key] TEXT PRIMARY KEY, [value] TEXT NOT NULL)"
            )
        rows = con.execute(f"SELECT [key], [value] FROM {tbl}").fetchall()
    
    weights = {
        "pts_partnership": 0.20,
        "pts_history": 0.35,
        "pts_skills_pref": 0.20,
        "pts_skills_neut": 0.10,
        "pts_skills_none": 0.00,
        "pts_lab_pref": 0.15,
        "pts_lab_neut": 0.10,
        "pts_lab_other": 0.02,
        "pts_capacity": 0.10
    }
    
    for r in rows:
        key = r["key"]
        try:
            if key in weights:
                weights[key] = float(r["value"])
        except (ValueError, TypeError):
            pass
            
    return weights


def update_system_weights(new_weights: dict) -> dict:
    """Updates the AI scoring weights in the DB."""
    tbl = _tbl("system_settings")
    with _conn() as con:
        for k, v in new_weights.items():
            existing = con.execute(f"SELECT [key] FROM {tbl} WHERE [key] = ?", (k,)).fetchone()
            if existing:
                con.execute(f"UPDATE {tbl} SET [value] = ? WHERE [key] = ?", (str(v), k))
            else:
                con.execute(f"INSERT INTO {tbl} ([key], [value]) VALUES (?, ?)", (k, str(v)))
    return get_system_weights()
