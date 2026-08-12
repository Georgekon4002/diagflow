"""
DiagFlow — Config DB Access Layer
==================================
Raw-SQLite CRUD for diagflow.db (diagnosticians, skills, partnerships,
availability, doctors).  Intentionally kept simple — no ORM, no sessions,
just plain sqlite3 so it behaves identically to the mock_slis.db pattern
already in use.
"""
import sqlite3
import sys
from datetime import date, datetime
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# Resolve db/ relative to the project root.
# When running as a PyInstaller EXE, __file__ points inside a temp dir,
# so we fall back to the directory containing the EXE.
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

# Path → db/diagflow.db
_DB_PATH = _PROJECT_ROOT / "db" / "diagflow.db"


_last_db_mtime = 0.0


def _ensure_schema(con: sqlite3.Connection) -> None:
    try:
        cols = [row[1] for row in con.execute("PRAGMA table_info(local_assignments)").fetchall()]
        if cols and "extracode" not in cols:
            con.execute("ALTER TABLE local_assignments ADD COLUMN extracode TEXT DEFAULT NULL")
        
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
def _conn() -> Generator[sqlite3.Connection, None, None]:
    global _last_db_mtime
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(_DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    
    current_mtime = _DB_PATH.stat().st_mtime if _DB_PATH.exists() else 0.0
    if current_mtime != _last_db_mtime:
        _ensure_schema(con)
        _last_db_mtime = current_mtime

    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


# ── Diagnosticians ────────────────────────────────────────────────────────────

def get_all_diagnosticians() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT id, name, active, can_ct, can_mri, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id FROM diagnosticians ORDER BY name"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_diagnostician(diag_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT id, name, active, can_ct, can_mri, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id FROM diagnosticians WHERE id = ?",
            (diag_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def create_diagnostician(name: str, active: bool = True, can_ct: bool = True,
                         can_mri: bool = True, quota_monday: int = 15, quota_tuesday: int = 15,
                         quota_wednesday: int = 15, quota_thursday: int = 15, quota_friday: int = 15,
                         quota_saturday: int = 0, quota_sunday: int = 0, preferred_lab_id: int | None = None) -> dict:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO diagnosticians (name, active, can_ct, can_mri, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, int(active), int(can_ct), int(can_mri), quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id),
        )
        row = con.execute(
            "SELECT id, name, active, can_ct, can_mri, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id FROM diagnosticians WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return _row_to_dict(row)


def update_diagnostician(diag_id: int, name: str, active: bool,
                         can_ct: bool, can_mri: bool, quota_monday: int, quota_tuesday: int,
                         quota_wednesday: int, quota_thursday: int, quota_friday: int,
                         quota_saturday: int, quota_sunday: int, preferred_lab_id: int | None = None) -> dict | None:
    with _conn() as con:
        con.execute(
            "UPDATE diagnosticians SET name=?, active=?, can_ct=?, can_mri=?, quota_monday=?, quota_tuesday=?, quota_wednesday=?, quota_thursday=?, quota_friday=?, quota_saturday=?, quota_sunday=?, preferred_lab_id=? WHERE id=?",
            (name, int(active), int(can_ct), int(can_mri), quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id, diag_id),
        )
        row = con.execute(
            "SELECT id, name, active, can_ct, can_mri, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id FROM diagnosticians WHERE id = ?",
            (diag_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def delete_diagnostician(diag_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM diagnosticians WHERE id = ?", (diag_id,))
    return cur.rowcount > 0


# ── Skills ────────────────────────────────────────────────────────────────────

def get_skills(diagnostician_id: int | None = None) -> list[dict]:
    with _conn() as con:
        # Create table if it doesn't exist
        con.execute(
            "CREATE TABLE IF NOT EXISTS exam_dictionary ("
            "code TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT)"
        )
        dict_rows = con.execute("SELECT code, name FROM exam_dictionary").fetchall()
        exam_name_map = {str(r["code"]).strip(): r["name"] for r in dict_rows}

        if diagnostician_id is not None:
            rows = con.execute(
                "SELECT ds.id, ds.diagnostician_id, d.name AS diagnostician_name, "
                "TRIM(ds.exam_code) AS exam_code, ds.is_preferred "
                "FROM diagnostician_skills ds "
                "JOIN diagnosticians d ON d.id = ds.diagnostician_id "
                "WHERE ds.diagnostician_id = ? "
                "ORDER BY TRIM(ds.exam_code)",
                (diagnostician_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT ds.id, ds.diagnostician_id, d.name AS diagnostician_name, "
                "TRIM(ds.exam_code) AS exam_code, ds.is_preferred "
                "FROM diagnostician_skills ds "
                "JOIN diagnosticians d ON d.id = ds.diagnostician_id "
                "ORDER BY d.name, TRIM(ds.exam_code)",
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
    with _conn() as con:
        con.execute(
            "DELETE FROM diagnostician_skills WHERE diagnostician_id = ? AND TRIM(exam_code) = ?",
            (diagnostician_id, code_str),
        )
        con.execute(
            "INSERT INTO diagnostician_skills (diagnostician_id, exam_code, is_preferred) "
            "VALUES (?, ?, ?)",
            (diagnostician_id, code_str, int(is_preferred)),
        )
        row = con.execute(
            "SELECT ds.id, ds.diagnostician_id, d.name AS diagnostician_name, "
            "TRIM(ds.exam_code) AS exam_code, ds.is_preferred "
            "FROM diagnostician_skills ds "
            "JOIN diagnosticians d ON d.id = ds.diagnostician_id "
            "WHERE ds.diagnostician_id = ? AND TRIM(ds.exam_code) = ?",
            (diagnostician_id, code_str),
        ).fetchone()
    return _row_to_dict(row)


def delete_skill(skill_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM diagnostician_skills WHERE id = ?", (skill_id,))
    return cur.rowcount > 0


def update_skill_preference(skill_id: int, is_preferred: bool) -> bool:
    with _conn() as con:
        cur = con.execute(
            "UPDATE diagnostician_skills SET is_preferred = ? WHERE id = ?",
            (1 if is_preferred else 0, skill_id),
        )
    return cur.rowcount > 0



def get_skills_for_diagnostician(diag_id: int) -> list[dict]:
    """Returns list of {exam_code, is_preferred} dicts for engine use."""
    with _conn() as con:
        rows = con.execute(
            "SELECT exam_code, is_preferred FROM diagnostician_skills WHERE diagnostician_id = ?",
            (diag_id,),
        ).fetchall()
    return [{"exam_code": r["exam_code"], "is_preferred": bool(r["is_preferred"])} for r in rows]


def get_all_skills_grouped() -> dict[int, list[dict]]:
    """Load ALL diagnostician skills in a single query, grouped by diagnostician_id.
    
    Used by get_candidates_for_exam to avoid N+1 queries (one per diagnostician).
    Returns: {diagnostician_id: [{exam_code, is_preferred}, ...]}
    """
    with _conn() as con:
        rows = con.execute(
            "SELECT diagnostician_id, exam_code, is_preferred FROM diagnostician_skills"
        ).fetchall()
    result: dict[int, list[dict]] = {}
    for r in rows:
        result.setdefault(r["diagnostician_id"], []).append({
            "exam_code": r["exam_code"],
            "is_preferred": bool(r["is_preferred"])
        })
    return result


DEFAULT_EXAM_SEED = [
    {"code": "22140", "name": "ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ", "category": "CT"},
    {"code": "22141", "name": "ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΚΟΙΛΙΑΣ", "category": "CT"},
    {"code": "22142", "name": "ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ", "category": "CT"},
    {"code": "22143", "name": "ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ", "category": "CT"},
    {"code": "22144", "name": "ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΤΡΑΧΗΛΟΥ", "category": "CT"},
    {"code": "22145", "name": "ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΚΑΤΩ ΚΟΙΛΙΑΣ & ΛΕΚΑΝΗΣ", "category": "CT"},
    {"code": "22146", "name": "ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΑΓΓΕΙΟΓΡΑΦΙΑ (CTA)", "category": "CT"},
    {"code": "21000", "name": "ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ (CT) ΓΕΝΙΚΗ", "category": "CT"},
    {"code": "22150", "name": "ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ", "category": "MRI"},
    {"code": "22151", "name": "ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ", "category": "MRI"},
    {"code": "22152", "name": "ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ", "category": "MRI"},
    {"code": "22153", "name": "ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΑΝΩ & ΚΑΤΩ ΚΟΙΛΙΑΣ", "category": "MRI"},
    {"code": "22154", "name": "ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΓΟΝΑΤΟΣ / ΑΡΘΡΩΣΗΣ", "category": "MRI"},
    {"code": "22155", "name": "ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΙΣΧΙΟΥ", "category": "MRI"},
    {"code": "22156", "name": "ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΩΜΟΥ", "category": "MRI"},
    {"code": "22705", "name": "ΜΑΓΝΗΤΙΚΗ ΦΑΣΜΑΤΟΣΚΟΠΙΑ (MRS)", "category": "MRI"},
    {"code": "22630", "name": "ΜΑΓΝΗΤΙΚΗ ΑΓΓΕΙΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ (MRA)", "category": "MRA"},
    {"code": "22631", "name": "ΜΑΓΝΗΤΙΚΗ ΑΓΓΕΙΟΓΡΑΦΙΑ ΤΡΑΧΗΛΟΥ / ΚΑΡΩΤΙΔΩΝ (MRA)", "category": "MRA"},
    {"code": "22632", "name": "ΜΑΓΝΗΤΙΚΗ ΑΓΓΕΙΟΓΡΑΦΙΑ ΑΟΡΤΗΣ & ΑΓΓΕΙΩΝ", "category": "MRA"},
]


def get_exam_dictionary() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT code AS examnumcode, code, name, category FROM exam_dictionary ORDER BY CAST(code AS INTEGER), code").fetchall()
        if not rows or len(rows) < 300:
            slis_db_path = _PROJECT_ROOT / "db" / "mock_slis.db"
            if slis_db_path.exists():
                try:
                    with sqlite3.connect(slis_db_path) as con_slis:
                        slis_rows = con_slis.execute("SELECT examnumcode, name, category FROM exam_categories").fetchall()
                        if slis_rows:
                            con.executemany(
                                "INSERT INTO exam_dictionary (code, name, category) VALUES (?, ?, ?) "
                                "ON CONFLICT(code) DO UPDATE SET name=excluded.name, category=excluded.category",
                                [(str(r[0]).strip(), str(r[1]).strip(), str(r[2] or "").strip()) for r in slis_rows if r[0] is not None],
                            )
                            con.commit()
                            rows = con.execute("SELECT code AS examnumcode, code, name, category FROM exam_dictionary ORDER BY CAST(code AS INTEGER), code").fetchall()
                except Exception:
                    pass
    return [{"examnumcode": str(r["code"]).strip(), "code": str(r["code"]).strip(), "name": r["name"], "category": r["category"]} for r in rows]


def upsert_exam_dictionary_entry(code: str, name: str, category: str = "") -> None:
    if not code:
        return
    code_clean = str(code).strip()
    if not code_clean:
        return
    with _conn() as con:
        con.execute(
            "INSERT INTO exam_dictionary (code, name, category) VALUES (?, ?, ?) "
            "ON CONFLICT(code) DO UPDATE SET name=excluded.name, category=excluded.category",
            (code_clean, name.strip(), category.strip()),
        )


# ── Partnerships ──────────────────────────────────────────────────────────────

def get_all_partnerships() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT p.id, p.issuing_doctor_id, p.issuing_doctor_name, "
            "p.preferred_diagnostician_id, d.name AS preferred_diagnostician_name, "
            "p.priority, p.exclusive, p.is_active "
            "FROM partnerships p "
            "JOIN diagnosticians d ON d.id = p.preferred_diagnostician_id "
            "ORDER BY p.issuing_doctor_name",
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def create_partnership(issuing_doctor_id: str, issuing_doctor_name: str,
                       preferred_diagnostician_id: int, priority: int = 1,
                       exclusive: bool = False, is_active: bool = True) -> dict:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO partnerships "
            "(issuing_doctor_id, issuing_doctor_name, preferred_diagnostician_id, priority, exclusive, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (issuing_doctor_id, issuing_doctor_name, preferred_diagnostician_id,
             priority, int(exclusive), int(is_active)),
        )
        row = con.execute(
            "SELECT p.id, p.issuing_doctor_id, p.issuing_doctor_name, "
            "p.preferred_diagnostician_id, d.name AS preferred_diagnostician_name, "
            "p.priority, p.exclusive, p.is_active "
            "FROM partnerships p "
            "JOIN diagnosticians d ON d.id = p.preferred_diagnostician_id "
            "WHERE p.id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return _row_to_dict(row)


def delete_partnership(part_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM partnerships WHERE id = ?", (part_id,))
    return cur.rowcount > 0


def update_partnership(part_id: int, exclusive: bool | None = None, is_active: bool | None = None) -> dict | None:
    with _conn() as con:
        # Build dynamic update query
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
        query = f"UPDATE partnerships SET {', '.join(updates)} WHERE id = ?"
        con.execute(query, tuple(params))
        
        row = con.execute(
            "SELECT p.id, p.issuing_doctor_id, p.issuing_doctor_name, "
            "p.preferred_diagnostician_id, d.name AS preferred_diagnostician_name, "
            "p.priority, p.exclusive, p.is_active "
            "FROM partnerships p "
            "JOIN diagnosticians d ON d.id = p.preferred_diagnostician_id "
            "WHERE p.id = ?",
            (part_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_partnerships_by_doctor(issuing_doctor_id: str) -> list[dict]:
    """Used by the engine to look up partnerships for an issuing doctor."""
    with _conn() as con:
        rows = con.execute(
            "SELECT preferred_diagnostician_id, priority, exclusive, is_active "
            "FROM partnerships "
            "WHERE issuing_doctor_id = ? "
            "ORDER BY priority DESC",
            (issuing_doctor_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── Availability ──────────────────────────────────────────────────────────────

def get_all_availability() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT a.id, a.diagnostician_id, d.name AS diagnostician_name, "
            "a.date, a.status, a.is_pamakristos_oncall, a.notes "
            "FROM availability a "
            "JOIN diagnosticians d ON d.id = a.diagnostician_id "
            "ORDER BY a.date DESC, d.name",
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def upsert_availability(diagnostician_id: int, date: str, status: str = "available",
                        is_pamakristos_oncall: bool = False, notes: str = "") -> dict:
    with _conn() as con:
        con.execute(
            "INSERT INTO availability "
            "(diagnostician_id, date, status, is_pamakristos_oncall, notes) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(diagnostician_id, date) DO UPDATE SET "
            "status=excluded.status, "
            "is_pamakristos_oncall=excluded.is_pamakristos_oncall, "
            "notes=excluded.notes",
            (diagnostician_id, date, status, int(is_pamakristos_oncall), notes),
        )
        row = con.execute(
            "SELECT a.id, a.diagnostician_id, d.name AS diagnostician_name, "
            "a.date, a.status, a.is_pamakristos_oncall, a.notes "
            "FROM availability a "
            "JOIN diagnosticians d ON d.id = a.diagnostician_id "
            "WHERE a.diagnostician_id = ? AND a.date = ?",
            (diagnostician_id, date),
        ).fetchone()
    return _row_to_dict(row)


def delete_availability(diagnostician_id: int, date: str) -> bool:
    """Delete availability record for a given diagnostician and date."""
    with _conn() as con:
        res = con.execute(
            "DELETE FROM availability WHERE diagnostician_id = ? AND date = ?",
            (diagnostician_id, date),
        )
        return res.rowcount > 0


def get_absent_diagnostician_ids(date: str) -> set[int]:
    """Return IDs of diagnosticians who are on leave on the given date."""
    with _conn() as con:
        rows = con.execute(
            "SELECT diagnostician_id FROM availability WHERE date = ? AND status = 'on_leave'",
            (date,),
        ).fetchall()
    return {r["diagnostician_id"] for r in rows}


def get_exclusive_partnerships() -> dict[str, dict]:
    """Returns dict mapping issuing_doctor_id (str) -> partnership dict for active exclusive partnerships."""
    with _conn() as con:
        rows = con.execute(
            "SELECT p.issuing_doctor_id, p.issuing_doctor_name, "
            "p.preferred_diagnostician_id, d.name AS preferred_diagnostician_name "
            "FROM partnerships p "
            "JOIN diagnosticians d ON d.id = p.preferred_diagnostician_id "
            "WHERE p.is_active = 1 AND p.exclusive = 1"
        ).fetchall()
    return {str(r["issuing_doctor_id"]): _row_to_dict(r) for r in rows}


# ── Παμμακάριστος Weekly Schedule ──────────────────────────────────────────────

def init_pamakristos_schedule():
    """Ensure pamakristos_schedule table exists and is seeded with defaults."""
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS pamakristos_schedule (
                weekday INTEGER PRIMARY KEY,
                diagnostician_id INTEGER NOT NULL,
                FOREIGN KEY(diagnostician_id) REFERENCES diagnosticians(id)
            )
            """
        )
        count = con.execute("SELECT COUNT(*) FROM pamakristos_schedule").fetchone()[0]
        if count == 0:
            diags = con.execute("SELECT id FROM diagnosticians WHERE active = 1 ORDER BY id").fetchall()
            if diags:
                diag_ids = [d[0] for d in diags]
                defaults = [(w, diag_ids[w % len(diag_ids)]) for w in range(5)]
                con.executemany(
                    "INSERT INTO pamakristos_schedule (weekday, diagnostician_id) VALUES (?, ?)",
                    defaults
                )


def get_pamakristos_weekly_schedule_db() -> list[dict]:
    """Fetch weekly schedule from DB (returns list for weekdays 0..6)."""
    init_pamakristos_schedule()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT ps.weekday, ps.diagnostician_id, d.name AS diagnostician_name
            FROM pamakristos_schedule ps
            JOIN diagnosticians d ON d.id = ps.diagnostician_id
            ORDER BY ps.weekday
            """
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_pamakristos_weekly_schedule_db(schedule_items: list[dict]):
    """Update or insert weekly schedule entries for specified weekdays."""
    init_pamakristos_schedule()
    with _conn() as con:
        con.execute("DELETE FROM pamakristos_schedule")
        for item in schedule_items:
            w = int(item["weekday"])
            d_id = item.get("diagnostician_id")
            if d_id is not None and str(d_id).strip() != "":
                con.execute(
                    "INSERT INTO pamakristos_schedule (weekday, diagnostician_id) VALUES (?, ?)",
                    (w, int(d_id)),
                )


def get_oncall_diagnostician(date_str: str) -> dict | None:
    """Return the diagnostician on Παμμακάριστος on-call for the given date.
    Checks availability table first; falls back to the persistent weekly schedule table (Mon-Fri only).
    """
    with _conn() as con:
        row = con.execute(
            "SELECT a.diagnostician_id, d.name AS diagnostician_name, a.date "
            "FROM availability a "
            "JOIN diagnosticians d ON d.id = a.diagnostician_id "
            "WHERE a.date = ? AND a.is_pamakristos_oncall = 1",
            (date_str,),
        ).fetchone()
    if row:
        return _row_to_dict(row)

    try:
        from datetime import date as dt_date
        dt = dt_date.fromisoformat(date_str)
        weekday = dt.weekday()
        if weekday in (5, 6):
            return None  # Saturday & Sunday have no oncall diagnostician
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






# ── Doctors ───────────────────────────────────────────────────────────────────

def _normalize_greek_str(s: str) -> str:
    if not s:
        return ""
    import unicodedata
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.upper().strip()


def get_all_doctors(q: str = "", skip: int = 0, limit: int = 50) -> dict:
    with _conn() as con:
        rows = con.execute("""
            SELECT doc.id, doc.name, GROUP_CONCAT(diag.name, ', ') as partner_name 
            FROM doctors doc
            LEFT JOIN partnerships p ON doc.id = p.issuing_doctor_id
            LEFT JOIN diagnosticians diag ON p.preferred_diagnostician_id = diag.id
            GROUP BY doc.id, doc.name
            ORDER BY doc.name
        """).fetchall()

    all_items = [_row_to_dict(r) for r in rows]

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
    with _conn() as con:
        con.execute(
            "INSERT INTO doctors (id, name) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name",
            (doctor_id, name),
        )
        row = con.execute(
            "SELECT id, name FROM doctors WHERE id = ?", (doctor_id,)
        ).fetchone()
    return _row_to_dict(row)


def delete_doctor(doctor_id: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
    return cur.rowcount > 0


# ── Local Assignments ─────────────────────────────────────────────────────────

def upsert_local_assignment(exammoreid: int, diagnostician_id: int, diagnostician_name: str, assigned_at: str, modality: str | None = None, extracode: str | None = None, is_auto: bool = False, rule_desc: str | None = None) -> dict:
    with _conn() as con:
        con.execute(
            "INSERT INTO local_assignments (exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto, rule_desc, extracode) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(exammoreid) DO UPDATE SET diagnostician_id=excluded.diagnostician_id, diagnostician_name=excluded.diagnostician_name, assigned_at=excluded.assigned_at, is_auto=excluded.is_auto, rule_desc=excluded.rule_desc, extracode=excluded.extracode",
            (exammoreid, diagnostician_id, diagnostician_name, assigned_at, int(is_auto), rule_desc, extracode),
        )
        con.execute(
            "INSERT OR REPLACE INTO assignment_log (exammoreid, diagnostician_id, assigned_at, modality, extracode) VALUES (?, ?, ?, ?, ?)",
            (exammoreid, diagnostician_id, assigned_at, modality, extracode),
        )
        row = con.execute(
            "SELECT exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto, rule_desc, extracode FROM local_assignments WHERE exammoreid = ?", (exammoreid,)
        ).fetchone()
    return _row_to_dict(row)

def get_all_local_assignments() -> dict[int, dict]:
    with _conn() as con:
        rows = con.execute("SELECT exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto, rule_desc, extracode FROM local_assignments").fetchall()
        return {r["exammoreid"]: _row_to_dict(r) for r in rows}

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

def delete_local_assignment(exammoreid: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM local_assignments WHERE exammoreid = ?", (exammoreid,))
        return cur.rowcount > 0

def log_assignment(exammoreid: int, diagnostician_id: int, assigned_at: str | None = None, modality: str | None = None, extracode: str | None = None) -> None:
    if not assigned_at:
        assigned_at = datetime.now().isoformat()
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO assignment_log (exammoreid, diagnostician_id, assigned_at, modality, extracode) VALUES (?, ?, ?, ?, ?)",
            (exammoreid, diagnostician_id, assigned_at, modality, extracode),
        )

def mark_local_assignment_synced(exammoreid: int, synced_at: str | None = None) -> bool:
    return delete_local_assignment(exammoreid)

def get_exam_dictionary() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT code, name, category FROM exam_dictionary ORDER BY category, code").fetchall()
        return [_row_to_dict(r) for r in rows]

def upsert_exam_dictionary_entry(code: str, name: str, category: str | None = None) -> dict:
    with _conn() as con:
        con.execute(
            "INSERT INTO exam_dictionary (code, name, category) VALUES (?, ?, ?) "
            "ON CONFLICT(code) DO UPDATE SET name=excluded.name, category=COALESCE(excluded.category, exam_dictionary.category)",
            (str(code).strip(), name.strip(), category),
        )
        row = con.execute("SELECT code, name, category FROM exam_dictionary WHERE code = ?", (str(code).strip(),)).fetchone()
    return _row_to_dict(row)

def get_dashboard_data() -> list[dict]:
    with _conn() as con:
        # Fetch active diagnosticians
        diags = con.execute("SELECT id, name FROM diagnosticians WHERE active = 1 ORDER BY name").fetchall()
        
        # Fetch modality quotas
        quota_rows = con.execute("SELECT diagnostician_id, modality, max_count FROM modality_quotas WHERE is_active = 1").fetchall()
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
        local_rows = con.execute(
            """
            SELECT diagnostician_id, exammoreid, extracode, assigned_at
            FROM local_assignments
            """
        ).fetchall()
        for r in local_rows:
            local_assignment_map[r["exammoreid"]] = {
                "diagnostician_id": r["diagnostician_id"],
                "extracode": r["extracode"],
                "assigned_at": r["assigned_at"]
            }

        # 2. Fetch from assignment_log (for today's assignments)
        log_assignment_map = {}
        log_rows = con.execute(
            """
            SELECT diagnostician_id, exammoreid, extracode, modality as category, assigned_at
            FROM assignment_log
            WHERE substr(assigned_at, 1, 10) = ?
            """,
            (today_str,)
        ).fetchall()
        for r in log_rows:
            log_assignment_map[r["exammoreid"]] = {
                "diagnostician_id": r["diagnostician_id"],
                "extracode": r["extracode"],
                "category": r["category"],
                "assigned_at": r["assigned_at"]
            }

    # 3. Fetch from mock_slis.db
    slis_assignment_map = {}
    exam_details = {}
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
            if raw_diag is not None and str(raw_diag).strip() != "" and str(raw_diag).strip() != "0" and str(raw_diag).strip().lower() != "none":
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

def get_all_exam_routing_rules() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            '''SELECT err.id, err.lab_id, err.issuing_doctor_id, err.issuing_doctor_name, err.is_pamakristos, err.exam_codes, err.diagnostician_id, err.description, err.is_active, d.name AS diagnostician_name
               FROM exam_routing_rules err
               JOIN diagnosticians d ON err.diagnostician_id = d.id
               ORDER BY err.id'''
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def create_exam_routing_rule(lab_id: int | None, issuing_doctor_id: str | None, issuing_doctor_name: str | None, is_pamakristos: bool, exam_codes: str, diagnostician_id: int, description: str, is_active: bool = True) -> dict:
    with _conn() as con:
        cur = con.execute(
            '''INSERT INTO exam_routing_rules (lab_id, issuing_doctor_id, issuing_doctor_name, is_pamakristos, exam_codes, diagnostician_id, description, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (lab_id, issuing_doctor_id, issuing_doctor_name, int(is_pamakristos), exam_codes, diagnostician_id, description, int(is_active))
        )
        row = con.execute(
            '''SELECT err.id, err.lab_id, err.issuing_doctor_id, err.issuing_doctor_name, err.is_pamakristos, err.exam_codes, err.diagnostician_id, err.description, err.is_active, d.name AS diagnostician_name
               FROM exam_routing_rules err
               JOIN diagnosticians d ON err.diagnostician_id = d.id
               WHERE err.id = ?''',
            (cur.lastrowid,)
        ).fetchone()
    return _row_to_dict(row)

ALLOWED_EXAM_ROUTING_FIELDS = {
    'lab_id', 'issuing_doctor_id', 'issuing_doctor_name',
    'is_pamakristos', 'exam_codes', 'diagnostician_id', 'description', 'is_active'
}
ALLOWED_EXCLUSIVE_LAB_FIELDS = {'diagnostician_id', 'lab_id', 'lab_name', 'is_active'}
ALLOWED_MODALITY_QUOTA_FIELDS = {'diagnostician_id', 'modality', 'max_count', 'is_active'}

DEFAULT_ADMIN_USERNAME = "admin"
# bcrypt hash of "admin1234" (cost=12). Change via the Admin Panel UI.
DEFAULT_ADMIN_PASSWORD_HASH = "$2b$12$SsLUct5RLmZJBwDQDBQ7xusD4CrjabY8EX9q.gKZjZbch5HZ2Ovly"

DEFAULT_IT_SUPPORT_USERNAME = "it_support"
# bcrypt hash of "it_support1234" (cost=12).
DEFAULT_IT_SUPPORT_PASSWORD_HASH = "$2b$12$dk9gH/KU49ZmcFDnQo8bl.D7q8/wcHT.icrlAFlJ8Kd9E3AjItrFa"

def update_exam_routing_rule(rule_id: int, update_data: dict) -> dict | None:
    if update_data:
        with _conn() as con:
            sets = []
            vals = []
            for k, v in update_data.items():
                if k not in ALLOWED_EXAM_ROUTING_FIELDS:
                    continue
                if k == 'is_pamakristos' or k == 'is_active':
                    v = int(v)
                sets.append(f"{k} = ?")
                vals.append(v)
            if sets:
                vals.append(rule_id)
                con.execute(f"UPDATE exam_routing_rules SET {', '.join(sets)} WHERE id = ?", tuple(vals))
            
    with _conn() as con:
        row = con.execute(
            '''SELECT err.id, err.lab_id, err.issuing_doctor_id, err.issuing_doctor_name, err.is_pamakristos, err.exam_codes, err.diagnostician_id, err.description, err.is_active, d.name AS diagnostician_name
               FROM exam_routing_rules err
               JOIN diagnosticians d ON err.diagnostician_id = d.id
               WHERE err.id = ?''',
            (rule_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None

def delete_exam_routing_rule(rule_id: int) -> bool:
    with _conn() as con:
        cur = con.execute('DELETE FROM exam_routing_rules WHERE id = ?', (rule_id,))
    return cur.rowcount > 0


# ── Advanced Options: Exclusive Lab Rules ─────────────────────────────────────

def get_all_exclusive_lab_rules() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            '''SELECT elr.id, elr.diagnostician_id, elr.lab_id, elr.lab_name, elr.is_active, d.name AS diagnostician_name
               FROM exclusive_lab_rules elr
               JOIN diagnosticians d ON elr.diagnostician_id = d.id
               ORDER BY elr.id'''
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def create_exclusive_lab_rule(diagnostician_id: int, lab_id: int, lab_name: str, is_active: bool = True) -> dict:
    with _conn() as con:
        cur = con.execute(
            '''INSERT INTO exclusive_lab_rules (diagnostician_id, lab_id, lab_name, is_active)
               VALUES (?, ?, ?, ?)''',
            (diagnostician_id, lab_id, lab_name, int(is_active))
        )
        row = con.execute(
            '''SELECT elr.id, elr.diagnostician_id, elr.lab_id, elr.lab_name, elr.is_active, d.name AS diagnostician_name
               FROM exclusive_lab_rules elr
               JOIN diagnosticians d ON elr.diagnostician_id = d.id
               WHERE elr.id = ?''',
            (cur.lastrowid,)
        ).fetchone()
    return _row_to_dict(row)

def update_exclusive_lab_rule(rule_id: int, update_data: dict) -> dict | None:
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
                con.execute(f"UPDATE exclusive_lab_rules SET {', '.join(sets)} WHERE id = ?", tuple(vals))
            
    with _conn() as con:
        row = con.execute(
            '''SELECT elr.id, elr.diagnostician_id, elr.lab_id, elr.lab_name, elr.is_active, d.name AS diagnostician_name
               FROM exclusive_lab_rules elr
               JOIN diagnosticians d ON elr.diagnostician_id = d.id
               WHERE elr.id = ?''',
            (rule_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None

def delete_exclusive_lab_rule(rule_id: int) -> bool:
    with _conn() as con:
        cur = con.execute('DELETE FROM exclusive_lab_rules WHERE id = ?', (rule_id,))
    return cur.rowcount > 0


# ── Advanced Options: Modality Quotas ─────────────────────────────────────────

def get_all_modality_quotas() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            '''SELECT mq.id, mq.diagnostician_id, mq.modality, mq.max_count, mq.is_active, d.name AS diagnostician_name
               FROM modality_quotas mq
               JOIN diagnosticians d ON mq.diagnostician_id = d.id
               ORDER BY mq.id'''
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def create_modality_quota(diagnostician_id: int, modality: str, max_count: int, is_active: bool = True) -> dict:
    with _conn() as con:
        cur = con.execute(
            '''INSERT INTO modality_quotas (diagnostician_id, modality, max_count, is_active)
               VALUES (?, ?, ?, ?)''',
            (diagnostician_id, modality, max_count, int(is_active))
        )
        row = con.execute(
            '''SELECT mq.id, mq.diagnostician_id, mq.modality, mq.max_count, mq.is_active, d.name AS diagnostician_name
               FROM modality_quotas mq
               JOIN diagnosticians d ON mq.diagnostician_id = d.id
               WHERE mq.id = ?''',
            (cur.lastrowid,)
        ).fetchone()
    return _row_to_dict(row)

def update_modality_quota(rule_id: int, update_data: dict) -> dict | None:
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
                con.execute(f"UPDATE modality_quotas SET {', '.join(sets)} WHERE id = ?", tuple(vals))
            
    with _conn() as con:
        row = con.execute(
            '''SELECT mq.id, mq.diagnostician_id, mq.modality, mq.max_count, mq.is_active, d.name AS diagnostician_name
               FROM modality_quotas mq
               JOIN diagnosticians d ON mq.diagnostician_id = d.id
               WHERE mq.id = ?''',
            (rule_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None

def delete_modality_quota(quota_id: int) -> bool:
    with _conn() as con:
        cur = con.execute('DELETE FROM modality_quotas WHERE id = ?', (quota_id,))
    return cur.rowcount > 0

# ── System Settings (Scoring Weights & Admin Credentials) ─────────────────────

def _ensure_admin_users_table(con):
    con.execute(
        "CREATE TABLE IF NOT EXISTS admin_users ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "username TEXT UNIQUE NOT NULL, "
        "password_hash TEXT NOT NULL, "
        "role TEXT NOT NULL DEFAULT 'admin', "
        "is_active INTEGER NOT NULL DEFAULT 1)"
    )

    # Ensure 'admin' account exists
    admin_row = con.execute("SELECT id FROM admin_users WHERE username = 'admin'").fetchone()
    if not admin_row:
        con.execute(
            "INSERT OR IGNORE INTO admin_users (username, password_hash, role, is_active) VALUES (?, ?, 'admin', 1)",
            (DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD_HASH)
        )

    # Ensure 'it_support' account exists
    it_row = con.execute("SELECT id FROM admin_users WHERE username = 'it_support'").fetchone()
    if not it_row:
        con.execute(
            "INSERT OR IGNORE INTO admin_users (username, password_hash, role, is_active) VALUES (?, ?, 'it_support', 1)",
            (DEFAULT_IT_SUPPORT_USERNAME, DEFAULT_IT_SUPPORT_PASSWORD_HASH)
        )

    con.commit()

def get_admin_user_by_username(username: str) -> dict | None:
    with _conn() as con:
        _ensure_admin_users_table(con)
        row = con.execute("SELECT * FROM admin_users WHERE username = ?", (username,)).fetchone()
    return _row_to_dict(row) if row else None

def get_admin_user_by_id(user_id: int) -> dict | None:
    with _conn() as con:
        _ensure_admin_users_table(con)
        row = con.execute("SELECT * FROM admin_users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_dict(row) if row else None

def get_all_admin_users() -> list[dict]:
    with _conn() as con:
        _ensure_admin_users_table(con)
        rows = con.execute("SELECT id, username, role, is_active FROM admin_users ORDER BY id").fetchall()
    return [_row_to_dict(r) for r in rows]

def create_admin_user(username: str, password_hash: str, role: str) -> dict:
    with _conn() as con:
        _ensure_admin_users_table(con)
        cur = con.execute(
            "INSERT INTO admin_users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role)
        )
        row = con.execute("SELECT id, username, role, is_active FROM admin_users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_dict(row)

def update_admin_user(user_id: int, username: str | None = None, password_hash: str | None = None, role: str | None = None, is_active: bool | None = None) -> dict | None:
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
            con.execute(f"UPDATE admin_users SET {','.join(fields)} WHERE id=?", tuple(params))
        row = con.execute("SELECT id, username, role, is_active FROM admin_users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_dict(row) if row else None

def delete_admin_user(user_id: int) -> bool:
    with _conn() as con:
        _ensure_admin_users_table(con)
        cur = con.execute("DELETE FROM admin_users WHERE id = ?", (user_id,))
    return cur.rowcount > 0


def get_system_weights() -> dict:
    """Returns the current AI scoring weights from the DB."""
    with _conn() as con:
        # Create table if it somehow doesn't exist
        con.execute(
            "CREATE TABLE IF NOT EXISTS system_settings ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        rows = con.execute("SELECT key, value FROM system_settings").fetchall()
    
    # Defaults matching scoring.py and frontend admin.js
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
        except ValueError:
            pass
            
    return weights

def update_system_weights(new_weights: dict) -> dict:
    """Updates the AI scoring weights in the DB."""
    with _conn() as con:
        for k, v in new_weights.items():
            con.execute(
                "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
                (k, str(v))
            )
    return get_system_weights()
