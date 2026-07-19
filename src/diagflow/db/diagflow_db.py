"""
DiagFlow — Config DB Access Layer
==================================
Raw-SQLite CRUD for diagflow.db (diagnosticians, skills, partnerships,
availability, doctors).  Intentionally kept simple — no ORM, no sessions,
just plain sqlite3 so it behaves identically to the mock_slis.db pattern
already in use.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# Path relative to this file → db/diagflow.db
_DB_PATH = Path(__file__).parent.parent.parent.parent / "db" / "diagflow.db"


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
            "SELECT id, name, active, can_ct, can_mri, daily_quota FROM diagnosticians ORDER BY name"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_diagnostician(diag_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT id, name, active, can_ct, can_mri, daily_quota FROM diagnosticians WHERE id = ?",
            (diag_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def create_diagnostician(name: str, active: bool = True, can_ct: bool = True,
                         can_mri: bool = True, daily_quota: int = 15) -> dict:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO diagnosticians (name, active, can_ct, can_mri, daily_quota) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, int(active), int(can_ct), int(can_mri), daily_quota),
        )
        row = con.execute(
            "SELECT id, name, active, can_ct, can_mri, daily_quota FROM diagnosticians WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return _row_to_dict(row)


def update_diagnostician(diag_id: int, name: str, active: bool,
                         can_ct: bool, can_mri: bool, daily_quota: int) -> dict | None:
    with _conn() as con:
        con.execute(
            "UPDATE diagnosticians SET name=?, active=?, can_ct=?, can_mri=?, daily_quota=? WHERE id=?",
            (name, int(active), int(can_ct), int(can_mri), daily_quota, diag_id),
        )
        row = con.execute(
            "SELECT id, name, active, can_ct, can_mri, daily_quota FROM diagnosticians WHERE id = ?",
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


# ── Partnerships ──────────────────────────────────────────────────────────────

def get_all_partnerships() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT p.id, p.issuing_doctor_id, p.issuing_doctor_name, "
            "p.preferred_diagnostician_id, d.name AS preferred_diagnostician_name, "
            "p.priority, p.exclusive "
            "FROM partnerships p "
            "JOIN diagnosticians d ON d.id = p.preferred_diagnostician_id "
            "ORDER BY p.issuing_doctor_name",
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def create_partnership(issuing_doctor_id: str, issuing_doctor_name: str,
                       preferred_diagnostician_id: int, priority: int = 1,
                       exclusive: bool = False) -> dict:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO partnerships "
            "(issuing_doctor_id, issuing_doctor_name, preferred_diagnostician_id, priority, exclusive) "
            "VALUES (?, ?, ?, ?, ?)",
            (issuing_doctor_id, issuing_doctor_name, preferred_diagnostician_id,
             priority, int(exclusive)),
        )
        row = con.execute(
            "SELECT p.id, p.issuing_doctor_id, p.issuing_doctor_name, "
            "p.preferred_diagnostician_id, d.name AS preferred_diagnostician_name, "
            "p.priority, p.exclusive "
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


def get_partnerships_by_doctor(issuing_doctor_id: str) -> list[dict]:
    """Used by the engine to look up partnerships for an issuing doctor."""
    with _conn() as con:
        rows = con.execute(
            "SELECT preferred_diagnostician_id, priority, exclusive "
            "FROM partnerships WHERE issuing_doctor_id = ? ORDER BY priority DESC",
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


def get_oncall_diagnostician(date: str) -> dict | None:
    """Return the diagnostician on Παμμακάριστος on-call for the given date."""
    with _conn() as con:
        row = con.execute(
            "SELECT a.diagnostician_id, d.name AS diagnostician_name, a.date "
            "FROM availability a "
            "JOIN diagnosticians d ON d.id = a.diagnostician_id "
            "WHERE a.date = ? AND a.is_pamakristos_oncall = 1",
            (date,),
        ).fetchone()
    return _row_to_dict(row) if row else None


# ── Doctors ───────────────────────────────────────────────────────────────────

def get_all_doctors() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT id, name, specialty FROM doctors ORDER BY name"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


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
