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


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(_DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
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
        exam_name_map = {str(r["code"]): r["name"] for r in dict_rows}

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

    results = []
    for r in rows:
        d = _row_to_dict(r)
        code_str = str(d.get("exam_code") or "")
        d["exam_name"] = exam_name_map.get(code_str, code_str)
        d["exam_title"] = d["exam_name"]
        results.append(d)

    return results


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
            "INSERT INTO local_assignments (exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto, rule_desc) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(exammoreid) DO UPDATE SET diagnostician_id=excluded.diagnostician_id, diagnostician_name=excluded.diagnostician_name, assigned_at=excluded.assigned_at, is_auto=excluded.is_auto, rule_desc=excluded.rule_desc",
            (exammoreid, diagnostician_id, diagnostician_name, assigned_at, int(is_auto), rule_desc),
        )
        con.execute(
            "INSERT OR REPLACE INTO assignment_log (exammoreid, diagnostician_id, assigned_at, modality, extracode) VALUES (?, ?, ?, ?, ?)",
            (exammoreid, diagnostician_id, assigned_at, modality, extracode),
        )
        row = con.execute(
            "SELECT exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto, rule_desc FROM local_assignments WHERE exammoreid = ?", (exammoreid,)
        ).fetchone()
    return _row_to_dict(row)

def get_all_local_assignments() -> dict[int, dict]:
    with _conn() as con:
        rows = con.execute("SELECT exammoreid, diagnostician_id, diagnostician_name, assigned_at, is_auto, rule_desc FROM local_assignments").fetchall()
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

def mark_local_assignment_synced(exammoreid: int, synced_at: str | None = None) -> bool:
    return delete_local_assignment(exammoreid)

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

        # 1. Fetch from local_assignments (ONLY FOR TODAY)
        local_rows = con.execute(
            """
            SELECT diagnostician_id, exammoreid
            FROM local_assignments
            WHERE substr(assigned_at, 1, 10) = date('now', 'localtime')
            """
        ).fetchall()

        # 2. Fetch from assignment_log (ONLY FOR TODAY)
        log_rows = con.execute(
            """
            SELECT diagnostician_id, exammoreid, extracode, modality as category
            FROM assignment_log
            WHERE substr(assigned_at, 1, 10) = date('now', 'localtime')
            """
        ).fetchall()

    # 3. Fetch from mock_slis.db (assigned exams for TODAY only)
    slis_rows = []
    exam_details = {}
    try:
        from diagflow.services.assignment import _get_mock_db
        con_slis = _get_mock_db()
        cur_slis = con_slis.execute("SELECT exammoreid, extracode, category, diagnostis, visitdate FROM slis_exams")
        today_str = date.today().isoformat()
        for r in cur_slis.fetchall():
            eid = r["exammoreid"]
            exam_details[eid] = (r["extracode"], r["category"])
            vdate = r["visitdate"] if "visitdate" in r.keys() else None
            # Count towards today's dashboard ONLY if assigned AND the exam visit date is today
            if r["diagnostis"] is not None and (not vdate or str(vdate)[:10] == today_str):
                slis_rows.append({"diagnostician_id": r["diagnostis"], "exammoreid": eid, "extracode": r["extracode"], "category": r["category"]})
        con_slis.close()
    except Exception:
        pass

    seen_exam_ids = set()

    def process_record(d_id, exammoreid, extracode=None, category=None):
        if d_id not in dashboard_map:
            return
        if exammoreid and exammoreid in seen_exam_ids:
            return
        if exammoreid:
            seen_exam_ids.add(exammoreid)
            dashboard_map[d_id]["assigned_exam_ids"].append(exammoreid)

        if not extracode and exammoreid in exam_details:
            extracode = exam_details[exammoreid][0]
        if not category and exammoreid in exam_details:
            category = exam_details[exammoreid][1]

        order_val = str(extracode) if extracode else (str(exammoreid) if exammoreid else None)
        if order_val:
            dashboard_map[d_id]["assigned_orders"].append(order_val)

        mod = (category or "").upper()
        if mod:
            if mod not in dashboard_map[d_id]["modality_counts"]:
                dashboard_map[d_id]["modality_counts"][mod] = 0
            dashboard_map[d_id]["modality_counts"][mod] += 1

    for r in local_rows:
        process_record(r["diagnostician_id"], r["exammoreid"])

    for r in log_rows:
        process_record(r["diagnostician_id"], r["exammoreid"], r["extracode"], r["category"])

    for r in slis_rows:
        process_record(r["diagnostician_id"], r["exammoreid"], r["extracode"], r["category"])

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
