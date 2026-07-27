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
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# Resolve db/ relative to the project root.
# When running as a PyInstaller EXE, __file__ points inside a temp dir,
# so we fall back to the directory containing the EXE.
if getattr(sys, "frozen", False):
    _PROJECT_ROOT = Path(sys.executable).parent
else:
    _PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# Path → db/diagflow.db
_DB_PATH = _PROJECT_ROOT / "db" / "diagflow.db"


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
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
        if diagnostician_id is not None:
            rows = con.execute(
                "SELECT ds.id, ds.diagnostician_id, d.name AS diagnostician_name, "
                "ds.exam_code, ds.is_preferred "
                "FROM diagnostician_skills ds "
                "JOIN diagnosticians d ON d.id = ds.diagnostician_id "
                "WHERE ds.diagnostician_id = ? "
                "ORDER BY ds.exam_code",
                (diagnostician_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT ds.id, ds.diagnostician_id, d.name AS diagnostician_name, "
                "ds.exam_code, ds.is_preferred "
                "FROM diagnostician_skills ds "
                "JOIN diagnosticians d ON d.id = ds.diagnostician_id "
                "ORDER BY d.name, ds.exam_code",
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def upsert_skill(diagnostician_id: int, exam_code: str,
                 is_preferred: bool = False) -> dict:
    with _conn() as con:
        con.execute(
            "INSERT INTO diagnostician_skills (diagnostician_id, exam_code, is_preferred) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(diagnostician_id, exam_code) DO UPDATE SET is_preferred=excluded.is_preferred",
            (diagnostician_id, exam_code, int(is_preferred)),
        )
        row = con.execute(
            "SELECT ds.id, ds.diagnostician_id, d.name AS diagnostician_name, "
            "ds.exam_code, ds.is_preferred "
            "FROM diagnostician_skills ds "
            "JOIN diagnosticians d ON d.id = ds.diagnostician_id "
            "WHERE ds.diagnostician_id = ? AND ds.exam_code = ?",
            (diagnostician_id, exam_code),
        ).fetchone()
    return _row_to_dict(row)


def delete_skill(skill_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM diagnostician_skills WHERE id = ?", (skill_id,))
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
            defaults = [
                (0, 59),   # Δευτέρα: ΜΠΕΡΕΤΗΣ ΓΕΩΡΓΙΟΣ
                (1, 61),   # Τρίτη: ΑΝΘΙΜΟΥ ΣΠΥΡΙΔΩΝ
                (2, 316),  # Τετάρτη: ΤΡΙΑΝΤΑΦΥΛΛΟΥ ΜΑΡΙΑ
                (3, 189),  # Πέμπτη: ΛΙΟΝΤΟΣ ΠΟΛΥΧΡΟΝΗΣ
                (4, 14),   # Παρασκευή: ΝΑΤΣΙΚΑ ΜΑΡΓΑΡΙΤΑ
            ]
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
        for item in schedule_items:
            w = int(item["weekday"])
            d_id = int(item["diagnostician_id"])
            con.execute(
                """
                INSERT INTO pamakristos_schedule (weekday, diagnostician_id)
                VALUES (?, ?)
                ON CONFLICT(weekday) DO UPDATE SET diagnostician_id = excluded.diagnostician_id
                """,
                (w, d_id),
            )


def get_oncall_diagnostician(date_str: str) -> dict | None:
    """Return the diagnostician on Παμμακάριστος on-call for the given date.
    Checks availability table first; falls back to the persistent weekly schedule table.
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

def get_all_doctors(q: str = "", skip: int = 0, limit: int = 50) -> dict:
    with _conn() as con:
        if q:
            like_q = f"%{q}%"
            total = con.execute("SELECT count(*) FROM doctors WHERE name LIKE ? OR id LIKE ?", (like_q, like_q)).fetchone()[0]
            rows = con.execute(
                "SELECT id, name, specialty FROM doctors WHERE name LIKE ? OR id LIKE ? ORDER BY name LIMIT ? OFFSET ?",
                (like_q, like_q, limit, skip)
            ).fetchall()
        else:
            total = con.execute("SELECT count(*) FROM doctors").fetchone()[0]
            rows = con.execute(
                "SELECT id, name, specialty FROM doctors ORDER BY name LIMIT ? OFFSET ?",
                (limit, skip)
            ).fetchall()
    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": total
    }


def upsert_doctor(doctor_id: str, name: str, specialty: str = "") -> dict:
    with _conn() as con:
        con.execute(
            "INSERT INTO doctors (id, name, specialty) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, specialty=excluded.specialty",
            (doctor_id, name, specialty),
        )
        row = con.execute(
            "SELECT id, name, specialty FROM doctors WHERE id = ?", (doctor_id,)
        ).fetchone()
    return _row_to_dict(row)


def delete_doctor(doctor_id: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
    return cur.rowcount > 0


# ── Local Assignments ─────────────────────────────────────────────────────────

def upsert_local_assignment(exammoreid: int, diagnostician_id: int, diagnostician_name: str, assigned_at: str, modality: str | None = None, extracode: str | None = None, is_auto: bool = False) -> dict:
    with _conn() as con:
        con.execute(
            "INSERT INTO local_assignments (exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(exammoreid) DO UPDATE SET diagnostician_id=excluded.diagnostician_id, diagnostician_name=excluded.diagnostician_name, assigned_at=excluded.assigned_at, is_auto=excluded.is_auto",
            (exammoreid, diagnostician_id, diagnostician_name, assigned_at, int(is_auto)),
        )
        con.execute(
            "INSERT OR REPLACE INTO assignment_log (exammoreid, diagnostician_id, assigned_at, modality, extracode) VALUES (?, ?, ?, ?, ?)",
            (exammoreid, diagnostician_id, assigned_at, modality, extracode),
        )
        row = con.execute(
            "SELECT exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto FROM local_assignments WHERE exammoreid = ?", (exammoreid,)
        ).fetchone()
    return _row_to_dict(row)

def get_all_local_assignments() -> dict[int, dict]:
    with _conn() as con:
        rows = con.execute("SELECT exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto FROM local_assignments").fetchall()
        return {r["exammoreid"]: _row_to_dict(r) for r in rows}

def get_daily_assignment_counts() -> dict[int, dict]:
    with _conn() as con:
        # We join with slis_exams to get the category (modality) for MRI/CT counts.
        rows = con.execute(
            """
            SELECT diagnostician_id,
                   COUNT(*) as total_cnt,
                   SUM(CASE WHEN UPPER(modality) = 'MRI' THEN 1 ELSE 0 END) as mri_cnt,
                   SUM(CASE WHEN UPPER(modality) = 'CT' THEN 1 ELSE 0 END) as ct_cnt
            FROM assignment_log
            WHERE substr(assigned_at, 1, 10) = date('now', 'localtime')
            GROUP BY diagnostician_id
            """
        ).fetchall()
    return {r["diagnostician_id"]: {"total": r["total_cnt"], "mri": r["mri_cnt"] or 0, "ct": r["ct_cnt"] or 0} for r in rows}

def delete_local_assignment(exammoreid: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM local_assignments WHERE exammoreid = ?", (exammoreid,))
        return cur.rowcount > 0

def get_dashboard_data() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """
            SELECT d.id as diagnostician_id, d.name as diagnostician_name,
                   al.exammoreid, al.extracode, al.modality as category
            FROM assignment_log al
            JOIN diagnosticians d ON al.diagnostician_id = d.id
            WHERE substr(al.assigned_at, 1, 10) = date('now', 'localtime')
            ORDER BY d.name, al.extracode
            """
        ).fetchall()
        
    dashboard_map = {}
    for r in rows:
        d_id = r["diagnostician_id"]
        if d_id not in dashboard_map:
            dashboard_map[d_id] = {
                "diagnostician_id": d_id,
                "diagnostician_name": r["diagnostician_name"],
                "assigned_orders": []
            }
        if r["extracode"]:
            dashboard_map[d_id]["assigned_orders"].append(r["extracode"])
            
    return list(dashboard_map.values())
