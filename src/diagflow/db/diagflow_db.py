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
import structlog

from diagflow.config import settings

logger = structlog.get_logger()

# Resolve db/ relative to the project root.
if getattr(sys, "frozen", False):
    _PROJECT_ROOT = Path(sys.executable).parent
else:
    _PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

_DB_PATH = _PROJECT_ROOT / "db" / "diagflow.db"
_last_db_mtime = 0.0
_mssql_schema_checked = False
_table_columns_cache: dict[tuple[str, str], list[str]] = {}
_dismissed_table_checked_modes: set[str] = set()

_WEEKDAY_QUOTA_KEYS: tuple[str, ...] = (
    "quota_monday",
    "quota_tuesday",
    "quota_wednesday",
    "quota_thursday",
    "quota_friday",
    "quota_saturday",
    "quota_sunday",
)


def _normalize_date_str(val) -> str | None:
    """Normalize a date/datetime/string value into ISO 'YYYY-MM-DD' format, or None."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()
    s = str(val).strip()
    if not s or s.lower() in ("none", "null"):
        return None
    # Handle YYYY-MM-DD (with optional time component)
    if len(s) >= 10 and s[4] in ("-", "/", ".") and s[7] in ("-", "/", "."):
        cand = f"{s[0:4]}-{s[5:7]}-{s[8:10]}"
        try:
            return date.fromisoformat(cand).isoformat()
        except ValueError:
            pass
    # Handle DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    for sep in ("/", "-", "."):
        parts = s[:10].split(sep)
        if len(parts) == 3 and len(parts[2]) == 4:
            try:
                return date(int(parts[2]), int(parts[1]), int(parts[0])).isoformat()
            except ValueError:
                pass
    return s[:10] if len(s) >= 10 else None


def _parse_date_safe(val) -> date:
    """Parse any date representation to a `date` object, falling back to `date.today()`."""
    norm = _normalize_date_str(val)
    if norm:
        try:
            return date.fromisoformat(norm)
        except ValueError:
            pass
    return date.today()


def get_weekday_quota_key(target_date: str | date | datetime | None = None) -> str:
    """Return locale-independent column name ('quota_monday'..'quota_sunday') for the given date."""
    dt = _parse_date_safe(target_date) if target_date is not None else date.today()
    return _WEEKDAY_QUOTA_KEYS[dt.weekday()]


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


def _get_table_columns(con, table_name: str) -> list[str]:
    try:
        is_mssql = getattr(con, "mode", None) == "mssql" or (
            getattr(con, "mode", None) is None and not settings.use_mock_slis_db
        )
        mode_key = "mssql" if is_mssql else "sqlite"
        can_cache = isinstance(con, DBAdapter)
        cache_key = (mode_key, table_name)
        if can_cache and cache_key in _table_columns_cache:
            return _table_columns_cache[cache_key]

        if is_mssql:
            rows = con.execute(
                "SELECT COLUMN_NAME AS name FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ?",
                (table_name,),
            ).fetchall()
        else:
            rows = con.execute(f"PRAGMA table_info({table_name})").fetchall()
        cols = []
        for r in rows:
            if isinstance(r, dict):
                col = r.get("name") or r.get("NAME") or r.get("column_name") or r.get("COLUMN_NAME") or ""
                cols.append(str(col).lower())
            elif hasattr(r, "keys"):
                keys_lower = {k.lower(): k for k in r.keys()}
                if "name" in keys_lower:
                    cols.append(str(r[keys_lower["name"]]).lower())
                elif "column_name" in keys_lower:
                    cols.append(str(r[keys_lower["column_name"]]).lower())
                else:
                    cols.append(str(r[1] if len(r) > 1 else r[0]).lower())
            else:
                try:
                    cols.append(str(r["name"]).lower())
                except Exception:
                    cols.append(str(r[1] if len(r) > 1 else r[0]).lower())
        result = [c for c in cols if c]
        if can_cache and result:
            _table_columns_cache[cache_key] = result
        return result
    except Exception:
        return []


def _ensure_mssql_schema(con: DBAdapter) -> None:
    """Idempotently ensure newer columns (e.g. visitdate) exist on central MSSQL tables."""
    global _mssql_schema_checked
    if _mssql_schema_checked:
        return
    _mssql_schema_checked = True
    try:
        for base_name in ("local_assignments", "assignment_log"):
            tbl = _tbl(base_name)
            con.execute(
                f"IF EXISTS (SELECT * FROM sys.tables WHERE name = '{tbl}') "
                f"AND NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('{tbl}') AND name = 'visitdate') "
                f"ALTER TABLE {tbl} ADD visitdate NVARCHAR(50) NULL"
            )
    except Exception as exc:
        logger.warning("ensure_mssql_schema_warning", error=str(exc))


def _ensure_schema(con: sqlite3.Connection) -> None:
    try:
        cols = _get_table_columns(con, "local_assignments")
        if cols and "extracode" not in cols:
            con.execute("ALTER TABLE local_assignments ADD COLUMN extracode TEXT DEFAULT NULL")
        if cols and "modality" not in cols:
            con.execute("ALTER TABLE local_assignments ADD COLUMN modality TEXT DEFAULT NULL")
        if cols and "visitdate" not in cols:
            con.execute("ALTER TABLE local_assignments ADD COLUMN visitdate TEXT DEFAULT NULL")
        
        log_cols = _get_table_columns(con, "assignment_log")
        if log_cols and "extracode" not in log_cols:
            con.execute("ALTER TABLE assignment_log ADD COLUMN extracode TEXT DEFAULT NULL")
        if log_cols and "modality" not in log_cols:
            con.execute("ALTER TABLE assignment_log ADD COLUMN modality TEXT DEFAULT NULL")
        if log_cols and "visitdate" not in log_cols:
            con.execute("ALTER TABLE assignment_log ADD COLUMN visitdate TEXT DEFAULT NULL")

        con.execute(
            "CREATE TABLE IF NOT EXISTS exam_dictionary ("
            "code TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS dismissed_auto_assignments ("
            "exammoreid INTEGER PRIMARY KEY, dismissed_at TEXT)"
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
            _table_columns_cache.clear()
            _dismissed_table_checked_modes.discard("sqlite")
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
            _ensure_mssql_schema(adapter)
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

def _normalize_diagnostician_row(row) -> dict:
    """Convert diagnostician DB row to dict with clean boolean flags (protects against legacy non-0/1 ints)."""
    d = _row_to_dict(row)
    if not d:
        return d
    for flag in ("active", "can_ct", "can_mri"):
        if flag in d:
            d[flag] = bool(d[flag])
    return d


def get_all_diagnosticians() -> list[dict]:
    tbl = _tbl("diagnosticians")
    with _conn() as con:
        rows = con.execute(
            f"SELECT id, name, active, can_ct, can_mri, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id FROM {tbl} ORDER BY name"
        ).fetchall()
    return [_normalize_diagnostician_row(r) for r in rows]


def get_diagnostician(diag_id: int) -> dict | None:
    tbl = _tbl("diagnosticians")
    with _conn() as con:
        row = con.execute(
            f"SELECT id, name, active, can_ct, can_mri, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id FROM {tbl} WHERE id = ?",
            (diag_id,),
        ).fetchone()
    return _normalize_diagnostician_row(row) if row else None


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
        dict_rows = con.execute(f"SELECT code, name, category FROM {tbl_dict}").fetchall()
        exam_name_map = {str(r["code"]).strip(): r["name"] for r in dict_rows}
        exam_cat_map = {str(r["code"]).strip(): (r["category"] or "") for r in dict_rows}

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
        d["category"] = exam_cat_map.get(code_str, "")
        results.append(d)

    return results


def upsert_skill(diagnostician_id: int, exam_code: str,
                 is_preferred: bool = False) -> dict:
    code_str = str(exam_code).strip()
    tbl_skills = _tbl("diagnostician_skills")
    tbl_diags = _tbl("diagnosticians")
    tbl_dict = _tbl("exam_dictionary")
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
        dict_row = con.execute(
            f"SELECT name, category FROM {tbl_dict} WHERE code = ?",
            (code_str,),
        ).fetchone()
    d = _row_to_dict(row)
    if dict_row:
        d["exam_name"] = dict_row["name"]
        d["exam_title"] = dict_row["name"]
        d["category"] = dict_row["category"] or ""
    else:
        d["exam_name"] = code_str
        d["exam_title"] = code_str
        d["category"] = ""
    return d


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

def _ensure_dismissed_table_exists(con: DBAdapter) -> None:
    mode_key = "mssql" if not settings.use_mock_slis_db else "sqlite"
    can_cache = isinstance(con, DBAdapter)
    if can_cache and mode_key in _dismissed_table_checked_modes:
        return
    tbl = _tbl("dismissed_auto_assignments")
    try:
        if not settings.use_mock_slis_db:
            con.execute(
                f"IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = '{tbl}') "
                f"BEGIN CREATE TABLE {tbl} (exammoreid BIGINT PRIMARY KEY, dismissed_at NVARCHAR(50)); END"
            )
        else:
            con.execute(
                f"CREATE TABLE IF NOT EXISTS {tbl} (exammoreid INTEGER PRIMARY KEY, dismissed_at TEXT)"
            )
        if can_cache:
            _dismissed_table_checked_modes.add(mode_key)
    except Exception as exc:
        logger.warning("ensure_dismissed_table_warning", error=str(exc))


def record_dismissed_auto_assignment(exammoreid: int) -> None:
    tbl = _tbl("dismissed_auto_assignments")
    now_iso = datetime.now().isoformat()
    try:
        with _conn() as con:
            _ensure_dismissed_table_exists(con)
            con.execute(f"DELETE FROM {tbl} WHERE exammoreid = ?", (exammoreid,))
            con.execute(f"INSERT INTO {tbl} (exammoreid, dismissed_at) VALUES (?, ?)", (exammoreid, now_iso))
    except Exception as e:
        logger.warning("failed_to_record_dismissed_auto_assignment", exammoreid=exammoreid, error=str(e))


def get_dismissed_auto_assignments() -> set[int]:
    tbl = _tbl("dismissed_auto_assignments")
    try:
        with _conn() as con:
            _ensure_dismissed_table_exists(con)
            rows = con.execute(f"SELECT exammoreid FROM {tbl}").fetchall()
            return {int(r["exammoreid"]) for r in rows if r.get("exammoreid") is not None}
    except Exception as e:
        logger.warning("failed_to_get_dismissed_auto_assignments", error=str(e))
        return set()


def remove_dismissed_auto_assignment(exammoreid: int) -> None:
    tbl = _tbl("dismissed_auto_assignments")
    try:
        with _conn() as con:
            _ensure_dismissed_table_exists(con)
            con.execute(f"DELETE FROM {tbl} WHERE exammoreid = ?", (exammoreid,))
    except Exception as e:
        logger.warning("failed_to_remove_dismissed_auto_assignment", exammoreid=exammoreid, error=str(e))


def upsert_local_assignment(
    exammoreid: int,
    diagnostician_id: int,
    diagnostician_name: str,
    assigned_at: str,
    modality: str | None = None,
    extracode: str | None = None,
    is_auto: bool = False,
    rule_desc: str | None = None,
    visitdate: str | None = None,
) -> dict:
    tbl_local = _tbl("local_assignments")
    visitdate_norm = _normalize_date_str(visitdate)
    if not is_auto:
        remove_dismissed_auto_assignment(exammoreid)
    with _conn() as con:
        cols = _get_table_columns(con, tbl_local)
        has_vdate = "visitdate" in cols
        existing_local = con.execute(f"SELECT exammoreid FROM {tbl_local} WHERE exammoreid = ?", (exammoreid,)).fetchone()
        if existing_local:
            if has_vdate:
                con.execute(
                    f"UPDATE {tbl_local} SET diagnostician_id=?, diagnostician_name=?, assigned_at=?, is_auto=?, rule_desc=?, extracode=?, modality=?, visitdate=? WHERE exammoreid=?",
                    (diagnostician_id, diagnostician_name, assigned_at, int(is_auto), rule_desc, extracode, modality, visitdate_norm, exammoreid)
                )
            else:
                con.execute(
                    f"UPDATE {tbl_local} SET diagnostician_id=?, diagnostician_name=?, assigned_at=?, is_auto=?, rule_desc=?, extracode=?, modality=? WHERE exammoreid=?",
                    (diagnostician_id, diagnostician_name, assigned_at, int(is_auto), rule_desc, extracode, modality, exammoreid)
                )
        else:
            if has_vdate:
                con.execute(
                    f"INSERT INTO {tbl_local} (exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto, rule_desc, extracode, modality, visitdate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (exammoreid, diagnostician_id, diagnostician_name, assigned_at, int(is_auto), rule_desc, extracode, modality, visitdate_norm)
                )
            else:
                con.execute(
                    f"INSERT INTO {tbl_local} (exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto, rule_desc, extracode, modality) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (exammoreid, diagnostician_id, diagnostician_name, assigned_at, int(is_auto), rule_desc, extracode, modality)
                )

        row = con.execute(
            f"SELECT * FROM {tbl_local} WHERE exammoreid = ?",
            (exammoreid,)
        ).fetchone()
    return _row_to_dict(row)


def get_all_local_assignments() -> dict[int, dict]:
    tbl = _tbl("local_assignments")
    with _conn() as con:
        rows = con.execute(f"SELECT * FROM {tbl}").fetchall()
        return {r["exammoreid"]: _row_to_dict(r) for r in rows}


def delete_local_assignment(exammoreid: int, record_dismissed: bool = True) -> bool:
    tbl = _tbl("local_assignments")
    with _conn() as con:
        cur = con.execute(f"DELETE FROM {tbl} WHERE exammoreid = ?", (exammoreid,))
        deleted = bool(cur.rowcount > 0)
    if record_dismissed:
        record_dismissed_auto_assignment(exammoreid)
    return deleted


def log_assignment(
    exammoreid: int,
    diagnostician_id: int,
    assigned_at: str | None = None,
    modality: str | None = None,
    extracode: str | None = None,
    visitdate: str | None = None,
) -> None:
    if not assigned_at:
        assigned_at = datetime.now().isoformat()
    visitdate_norm = _normalize_date_str(visitdate)
    tbl = _tbl("assignment_log")
    with _conn() as con:
        cols = _get_table_columns(con, tbl)
        has_vdate = "visitdate" in cols
        existing = con.execute(f"SELECT exammoreid FROM {tbl} WHERE exammoreid = ?", (exammoreid,)).fetchone()
        if existing:
            if has_vdate:
                con.execute(
                    f"UPDATE {tbl} SET diagnostician_id = ?, assigned_at = ?, modality = ?, extracode = ?, visitdate = ? WHERE exammoreid = ?",
                    (diagnostician_id, assigned_at, modality, extracode, visitdate_norm, exammoreid)
                )
            else:
                con.execute(
                    f"UPDATE {tbl} SET diagnostician_id = ?, assigned_at = ?, modality = ?, extracode = ? WHERE exammoreid = ?",
                    (diagnostician_id, assigned_at, modality, extracode, exammoreid)
                )
        else:
            if has_vdate:
                con.execute(
                    f"INSERT INTO {tbl} (exammoreid, diagnostician_id, assigned_at, modality, extracode, visitdate) VALUES (?, ?, ?, ?, ?, ?)",
                    (exammoreid, diagnostician_id, assigned_at, modality, extracode, visitdate_norm)
                )
            else:
                con.execute(
                    f"INSERT INTO {tbl} (exammoreid, diagnostician_id, assigned_at, modality, extracode) VALUES (?, ?, ?, ?, ?)",
                    (exammoreid, diagnostician_id, assigned_at, modality, extracode)
                )


def mark_local_assignment_synced(exammoreid: int, synced_at: str | None = None) -> bool:
    remove_dismissed_auto_assignment(exammoreid)
    return delete_local_assignment(exammoreid, record_dismissed=False)


def finalize_synced_assignments_batch(entries: list[dict]) -> None:
    """
    Finalize a batch of Slis-pushed assignments in a single DB connection/transaction:
      1. Removes exammoreids from df_local_assignments and df_dismissed_auto_assignments
      2. Upserts them into df_assignment_log with normalized visitdate.
    """
    if not entries:
        return

    tbl_local = _tbl("local_assignments")
    tbl_dismissed = _tbl("dismissed_auto_assignments")
    tbl_log = _tbl("assignment_log")

    eids = [int(e["exammoreid"]) for e in entries]

    with _conn() as con:
        _ensure_dismissed_table_exists(con)
        placeholders = ",".join(["?"] * len(eids))
        con.execute(f"DELETE FROM {tbl_local} WHERE exammoreid IN ({placeholders})", tuple(eids))
        con.execute(f"DELETE FROM {tbl_dismissed} WHERE exammoreid IN ({placeholders})", tuple(eids))

        cols = _get_table_columns(con, tbl_log)
        has_vdate = "visitdate" in cols

        existing_rows = con.execute(
            f"SELECT exammoreid FROM {tbl_log} WHERE exammoreid IN ({placeholders})",
            tuple(eids),
        ).fetchall()
        existing_eids = {int(r["exammoreid"]) for r in existing_rows}

        for entry in entries:
            eid = int(entry["exammoreid"])
            diag_id = int(entry["diagnostician_id"])
            assigned_at = entry.get("assigned_at") or datetime.now().isoformat()
            modality = entry.get("modality")
            extracode = entry.get("extracode")
            visitdate_norm = _normalize_date_str(entry.get("visitdate"))

            if eid in existing_eids:
                if has_vdate:
                    con.execute(
                        f"UPDATE {tbl_log} SET diagnostician_id = ?, assigned_at = ?, modality = ?, extracode = ?, visitdate = ? WHERE exammoreid = ?",
                        (diag_id, assigned_at, modality, extracode, visitdate_norm, eid),
                    )
                else:
                    con.execute(
                        f"UPDATE {tbl_log} SET diagnostician_id = ?, assigned_at = ?, modality = ?, extracode = ? WHERE exammoreid = ?",
                        (diag_id, assigned_at, modality, extracode, eid),
                    )
            else:
                if has_vdate:
                    con.execute(
                        f"INSERT INTO {tbl_log} (exammoreid, diagnostician_id, assigned_at, modality, extracode, visitdate) VALUES (?, ?, ?, ?, ?, ?)",
                        (eid, diag_id, assigned_at, modality, extracode, visitdate_norm),
                    )
                else:
                    con.execute(
                        f"INSERT INTO {tbl_log} (exammoreid, diagnostician_id, assigned_at, modality, extracode) VALUES (?, ?, ?, ?, ?)",
                        (eid, diag_id, assigned_at, modality, extracode),
                    )


def _collect_resolved_assignments(
    target_date: str | None = None,
    since_date: str | None = None,
) -> dict[int, dict]:
    """
    Single source of truth for all assigned exams across:
      1. df_local_assignments (staged in DiagFlow — highest priority)
      2. Slis assignments (mock_slis.db in mock mode, _slis_assigned_cache in production)
      3. df_assignment_log (historical pushed assignments, filtered by target_date or since_date)

    Each entry is resolved to its authoritative diagnostician_id, normalized
    examination date (`visitdate` in YYYY-MM-DD, falling back to `assigned_at`
    only for legacy rows with no visitdate anywhere), extracode, and normalized modality.

    Shared by get_all_assignment_counts_by_date(), get_dashboard_data(), and
    get_daily_assignment_counts() so the Home Screen, Engine, and Dashboard are
    always 100% consistent.
    """
    from diagflow.services.slis_sync import normalize_modality

    tbl_local = _tbl("local_assignments")
    tbl_log = _tbl("assignment_log")

    local_assignment_map: dict[int, dict] = {}
    log_assignment_map: dict[int, dict] = {}

    with _conn() as con:
        # 1. Fetch from local_assignments (small active working table)
        local_cols = _get_table_columns(con, tbl_local)
        has_loc_vdate = "visitdate" in local_cols
        loc_q = (
            "SELECT diagnostician_id, exammoreid, extracode, modality, assigned_at"
            + (", visitdate" if has_loc_vdate else "")
            + f" FROM {tbl_local}"
        )
        for r in con.execute(loc_q).fetchall():
            eid = r["exammoreid"]
            local_assignment_map[eid] = {
                "diagnostician_id": r["diagnostician_id"],
                "extracode": r["extracode"],
                "category": r.get("modality"),
                "assigned_at": r["assigned_at"],
                "visitdate": _normalize_date_str(r["visitdate"]) if has_loc_vdate and r.get("visitdate") else None,
            }

        # 2. Fetch from assignment_log (scoped by target_date or since_date to avoid full-history scans)
        log_cols = _get_table_columns(con, tbl_log)
        has_log_vdate = "visitdate" in log_cols
        log_select = (
            "SELECT diagnostician_id, exammoreid, extracode, modality AS category, assigned_at"
            + (", visitdate" if has_log_vdate else "")
            + f" FROM {tbl_log}"
        )
        log_params: tuple = ()
        if target_date:
            like_pat = f"{target_date}%"
            if has_log_vdate:
                log_q = f"{log_select} WHERE visitdate LIKE ? OR (visitdate IS NULL AND assigned_at LIKE ?)"
                log_params = (like_pat, like_pat)
            else:
                log_q = f"{log_select} WHERE assigned_at LIKE ?"
                log_params = (like_pat,)
        elif since_date:
            if has_log_vdate:
                log_q = f"{log_select} WHERE visitdate >= ? OR (visitdate IS NULL AND assigned_at >= ?)"
                log_params = (since_date, since_date)
            else:
                log_q = f"{log_select} WHERE assigned_at >= ?"
                log_params = (since_date,)
        else:
            log_q = log_select

        for r in con.execute(log_q, log_params).fetchall():
            eid = r["exammoreid"]
            log_assignment_map[eid] = {
                "diagnostician_id": r["diagnostician_id"],
                "extracode": r["extracode"],
                "category": r.get("category"),
                "assigned_at": r["assigned_at"],
                "visitdate": _normalize_date_str(r["visitdate"]) if has_log_vdate and r.get("visitdate") else None,
            }

    # 3. Slis exam metadata & assignments
    exam_details: dict[int, dict] = {}
    slis_assignment_map: dict[int, dict] = {}

    if settings.use_mock_slis_db:
        try:
            from diagflow.services.assignment import _get_mock_db
            con_slis = _get_mock_db()
            cur_slis = con_slis.execute(
                "SELECT exammoreid, extracode, category, diagnostis, visitdate, slis_synced_at FROM slis_exams"
            )
            for r in cur_slis.fetchall():
                eid = r["exammoreid"]
                vdate = _normalize_date_str(r["visitdate"])
                exam_details[eid] = {
                    "extracode": r["extracode"],
                    "category": r["category"],
                    "visitdate": vdate,
                }
                raw_diag = r["diagnostis"]
                if raw_diag is not None and str(raw_diag).strip() not in ("", "0", "none", "None", "NULL"):
                    try:
                        d_id = int(float(str(raw_diag).strip()))
                    except Exception:
                        d_id = raw_diag
                    slis_assignment_map[eid] = {
                        "diagnostician_id": d_id,
                        "extracode": r["extracode"],
                        "category": r["category"],
                        "visitdate": vdate,
                    }
            con_slis.close()
        except Exception:
            pass
    else:
        # In production MSSQL mode, include assigned exams captured from Slis pulls/searches
        try:
            from diagflow.services.assignment import _slis_assigned_cache
            for eid, s_info in _slis_assigned_cache.items():
                slis_assignment_map[eid] = {
                    "diagnostician_id": s_info.get("diagnostician_id"),
                    "extracode": s_info.get("extracode"),
                    "category": s_info.get("category") or s_info.get("modality"),
                    "visitdate": _normalize_date_str(s_info.get("visitdate")),
                }
        except Exception:
            pass

    # Augment metadata with _exam_details_cache in memory if available
    try:
        from diagflow.services.assignment import _exam_details_cache
        for eid, c_info in _exam_details_cache.items():
            c_vdate = _normalize_date_str(c_info.get("visitdate"))
            if eid not in exam_details:
                exam_details[eid] = {
                    "extracode": c_info.get("extracode"),
                    "category": c_info.get("category") or c_info.get("modality"),
                    "visitdate": c_vdate,
                }
            else:
                if not exam_details[eid].get("visitdate") and c_vdate:
                    exam_details[eid]["visitdate"] = c_vdate
                if not exam_details[eid].get("extracode") and c_info.get("extracode"):
                    exam_details[eid]["extracode"] = c_info.get("extracode")
                if not exam_details[eid].get("category") and (c_info.get("category") or c_info.get("modality")):
                    exam_details[eid]["category"] = c_info.get("category") or c_info.get("modality")
    except Exception:
        pass

    all_assigned_eids = (
        set(local_assignment_map.keys())
        | set(slis_assignment_map.keys())
        | set(log_assignment_map.keys())
    )

    resolved: dict[int, dict] = {}
    for eid in all_assigned_eids:
        d_id = None
        extracode = None
        category = None
        exam_vdate = None
        assigned_at = None

        if eid in local_assignment_map:
            info = local_assignment_map[eid]
            d_id = info["diagnostician_id"]
            extracode = info["extracode"]
            category = info.get("category")
            exam_vdate = info.get("visitdate")
            assigned_at = info.get("assigned_at")
        elif eid in slis_assignment_map:
            info = slis_assignment_map[eid]
            d_id = info["diagnostician_id"]
            extracode = info["extracode"]
            category = info["category"]
            exam_vdate = info.get("visitdate")
        elif eid in log_assignment_map:
            info = log_assignment_map[eid]
            d_id = info["diagnostician_id"]
            extracode = info["extracode"]
            category = info["category"]
            exam_vdate = info.get("visitdate")
            assigned_at = info.get("assigned_at")

        # Cross-source metadata fallback for visitdate, extracode, category
        if eid in exam_details:
            if not exam_vdate:
                exam_vdate = exam_details[eid].get("visitdate")
            if not extracode:
                extracode = exam_details[eid].get("extracode")
            if not category:
                category = exam_details[eid].get("category")
        if not exam_vdate and eid in log_assignment_map:
            exam_vdate = log_assignment_map[eid].get("visitdate")
        if not exam_vdate and eid in local_assignment_map:
            exam_vdate = local_assignment_map[eid].get("visitdate")
        # Legacy fallback ONLY when visitdate is completely absent everywhere
        if not exam_vdate and assigned_at:
            exam_vdate = _normalize_date_str(assigned_at)

        if d_id is not None:
            try:
                d_id_int = int(float(str(d_id).strip()))
            except Exception:
                d_id_int = d_id
        else:
            d_id_int = None

        norm_cat = normalize_modality(category) if isinstance(category, str) and category.strip() else ""

        if d_id_int is not None and exam_vdate:
            resolved[eid] = {
                "diagnostician_id": d_id_int,
                "extracode": extracode,
                "category": norm_cat,
                "visitdate": exam_vdate,
            }

    return resolved


def get_daily_assignment_counts(target_date: str | None = None) -> dict[int, dict]:
    dash_data = get_dashboard_data(target_date)
    counts = {}
    for d in dash_data:
        did = d["diagnostician_id"]
        total = len(d.get("assigned_exam_ids", []))
        mod_counts = d.get("modality_counts", {})
        mri = mod_counts.get("MRI", 0) + mod_counts.get("MRA", 0)
        ct = mod_counts.get("CT", 0)
        counts[did] = {"total": total, "mri": mri, "ct": ct}
    return counts


def get_daily_assignment_counts_for_dates(dates: set[str] | list[str]) -> dict[str, dict[int, dict]]:
    """
    Batch-fetch daily assignment counts (total, mri, ct) for multiple dates in a single DB pass.
    Eliminates per-date DB round-trips during batch suggestion generation.
    """
    clean_dates = {d for d in (_normalize_date_str(x) for x in dates) if d}
    if not clean_dates:
        return {}
    min_date = min(clean_dates)
    resolved = _collect_resolved_assignments(since_date=min_date)
    result: dict[str, dict[int, dict]] = {dt: {} for dt in clean_dates}
    for info in resolved.values():
        dt_str = info["visitdate"]
        if dt_str not in result:
            continue
        did = info["diagnostician_id"]
        entry = result[dt_str].setdefault(did, {"total": 0, "mri": 0, "ct": 0})
        entry["total"] += 1
        mod = (info.get("category") or "").upper()
        if mod in ("MRI", "MRA"):
            entry["mri"] += 1
        elif mod == "CT":
            entry["ct"] += 1
    return result


def get_all_assignment_counts_by_date(days_back: int = 30) -> dict[int, dict[str, int]]:
    from datetime import timedelta

    counts_by_diag: dict[int, dict[str, int]] = {}
    tbl_diags = _tbl("diagnosticians")

    with _conn() as con:
        diags = con.execute(f"SELECT id FROM {tbl_diags} WHERE active = 1").fetchall()
        for d in diags:
            counts_by_diag[int(d["id"])] = {}

    since_date = (date.today() - timedelta(days=days_back)).isoformat() if days_back and days_back > 0 else None
    resolved = _collect_resolved_assignments(since_date=since_date)
    for info in resolved.values():
        did = info["diagnostician_id"]
        dt_str = info["visitdate"]
        if did is not None and dt_str:
            if did not in counts_by_diag:
                counts_by_diag[did] = {}
            counts_by_diag[did][dt_str] = counts_by_diag[did].get(dt_str, 0) + 1

    return counts_by_diag


def get_dashboard_data(target_date: str | None = None) -> list[dict]:
    tbl_diags = _tbl("diagnosticians")
    tbl_mod_quotas = _tbl("modality_quotas")

    target_dt = _parse_date_safe(target_date) if target_date else date.today()
    target_date_str = target_dt.isoformat()
    quota_col = _WEEKDAY_QUOTA_KEYS[target_dt.weekday()]

    with _conn() as con:
        diags = con.execute(
            f"SELECT id, name, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, "
            f"quota_friday, quota_saturday, quota_sunday FROM {tbl_diags} WHERE active = 1 ORDER BY name"
        ).fetchall()
        quota_rows = con.execute(
            f"SELECT diagnostician_id, modality, max_count FROM {tbl_mod_quotas} WHERE is_active = 1"
        ).fetchall()
        modality_limits: dict[int, dict[str, int]] = {}
        for qr in quota_rows:
            did = int(qr["diagnostician_id"])
            if did not in modality_limits:
                modality_limits[did] = {}
            modality_limits[did][qr["modality"].upper()] = qr["max_count"]

        dashboard_map: dict[int, dict] = {}
        for d in diags:
            did = int(d["id"])
            daily_quota = d.get(quota_col)
            if daily_quota is None:
                daily_quota = 0
            dashboard_map[did] = {
                "diagnostician_id": did,
                "diagnostician_name": d["name"],
                "daily_quota": int(daily_quota),
                "assigned_orders": [],
                "modality_counts": {"CT": 0, "MRI": 0, "US": 0, "XRAY": 0},
                "assigned_exam_ids": [],
                "modality_limits": modality_limits.get(did, {}),
            }

    resolved = _collect_resolved_assignments(target_date=target_date_str)

    for eid, info in resolved.items():
        if info["visitdate"] != target_date_str:
            continue
        d_id_int = info["diagnostician_id"]
        if d_id_int not in dashboard_map:
            continue

        dashboard_map[d_id_int]["assigned_exam_ids"].append(eid)

        extracode = info.get("extracode")
        order_val = str(extracode).strip() if (extracode is not None and str(extracode).strip() != "") else None
        if order_val:
            dashboard_map[d_id_int]["assigned_orders"].append(order_val)

        mod = info.get("category") or ""
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


def get_comment_auto_assign_enabled() -> bool:
    """Returns whether comment-based auto-assignment rule is enabled (default: True)."""
    tbl = _tbl("system_settings")
    with _conn() as con:
        if settings.use_mock_slis_db:
            con.execute(
                f"CREATE TABLE IF NOT EXISTS {tbl} ("
                "[key] TEXT PRIMARY KEY, [value] TEXT NOT NULL)"
            )
        row = con.execute(f"SELECT [value] FROM {tbl} WHERE [key] = 'comment_auto_assign_enabled'").fetchone()
    if not row:
        return True
    val = str(row["value"]).strip().lower()
    return val in ("1", "true", "yes", "on")


def set_comment_auto_assign_enabled(enabled: bool) -> bool:
    """Sets whether comment-based auto-assignment rule is enabled."""
    tbl = _tbl("system_settings")
    val_str = "1" if enabled else "0"
    with _conn() as con:
        if settings.use_mock_slis_db:
            con.execute(
                f"CREATE TABLE IF NOT EXISTS {tbl} ("
                "[key] TEXT PRIMARY KEY, [value] TEXT NOT NULL)"
            )
        existing = con.execute(f"SELECT [key] FROM {tbl} WHERE [key] = 'comment_auto_assign_enabled'").fetchone()
        if existing:
            con.execute(f"UPDATE {tbl} SET [value] = ? WHERE [key] = 'comment_auto_assign_enabled'", (val_str,))
        else:
            con.execute(f"INSERT INTO {tbl} ([key], [value]) VALUES ('comment_auto_assign_enabled', ?)", (val_str,))
    return get_comment_auto_assign_enabled()

