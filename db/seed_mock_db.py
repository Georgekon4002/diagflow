"""
DiagFlow — Mock Slis DB Seeder
==============================
Reads db/init_mock_slis.sql and populates db/mock_slis.db (SQLite).

Usage:
    python db/seed_mock_db.py

Run from the project root (the diagflow/ workspace folder).
Re-running is safe — it drops and re-creates the tables each time.
"""

import sqlite3
from pathlib import Path

# ── Locate files relative to this script ──────────────────────────
SCRIPT_DIR   = Path(__file__).parent
DB_PATH      = SCRIPT_DIR / "mock_slis.db"
INIT_SQL     = SCRIPT_DIR / "init_mock_slis.sql"


# ── Seed the database ─────────────────────────────────────────────
def seed(db_path: Path, init_sql: Path):
    print(f"Seeding {db_path} from {init_sql} ...")

    if not init_sql.exists():
        fallback_sql = SCRIPT_DIR / "templates" / "init_mock_slis.sql"
        if fallback_sql.exists():
            init_sql = fallback_sql
        else:
            print(f"Error: {init_sql} not found.")
            return

    if db_path.exists():
        try:
            db_path.unlink()
        except PermissionError:
            pass

    # Connect to SQLite
    con = sqlite3.connect(db_path, timeout=10.0)
    cur = con.cursor()

    # Drop existing tables so re-runs are idempotent (in case unlink failed)
    cur.execute("DROP TABLE IF EXISTS slis_exams")
    cur.execute("DROP TABLE IF EXISTS exam_categories")
    cur.execute("DROP INDEX IF EXISTS idx_slis_exams_diagnostis")
    cur.execute("DROP INDEX IF EXISTS idx_slis_exams_visitdate")
    cur.execute("DROP INDEX IF EXISTS idx_slis_exams_examnumcode")
    cur.execute("DROP INDEX IF EXISTS idx_slis_exams_extracode")
    con.commit()

    with open(init_sql, 'r', encoding='utf-8') as f:
        sql_script = f.read()

    print("Executing SQL script ...")
    import time
    for attempt in range(5):
        try:
            cur.executescript(sql_script)
            con.commit()
            break
        except sqlite3.OperationalError as e:
            if attempt == 4:
                print(f"Warning: Database is locked by another process ({e}). Run seeding when app is idle.")
                con.close()
                return
            time.sleep(1.0)

    # Seed realistic patient history (oldpers & olddiagnostis) into recent pending exams
    diags_pool = [
        (14, 'ΝΑΤΣΙΚΑ ΜΑΡΓΑΡΙΤΑ'),
        (34, 'ΚΟΥΛΟΓΙΩΡΓΑ ΔΗΜΗΤΡΑ'),
        (41, 'ΠΑΠΟΥΤΣΗ ΔΗΜΗΤΡΑ'),
        (59, 'ΜΠΕΡΕΤΗΣ ΓΕΩΡΓΙΟΣ'),
        (61, 'ΑΝΘΙΜΟΥ ΣΠΥΡΙΔΩΝ'),
        (67, 'ΑΛΕΞΟΠΟΥΛΟΣ ΝΙΚΟΛΑΟΣ'),
        (69, 'ΚΡΕΖΙΑ ΜΑΡΙΑΝΝΑ'),
        (74, 'ΝΙΚΟΛΑΚΟΠΟΥΛΟΣ ΙΩΑΝΝΗΣ'),
        (89, 'ΚΥΠΡΙΩΤΗΣ ΔΗΜΟΣΘΕΝΗΣ'),
        (189, 'ΛΙΟΝΤΟΣ ΠΟΛΥΧΡΟΝΗΣ'),
        (205, 'ΑΝΔΡΙΩΤΗΣ ΕΥΘΥΜΙΟΣ'),
        (264, 'ΣΙΓΑΛΑΣ ΑΝΤΩΝΙΟΣ'),
        (268, 'ΚΟΡΟΔΗΜΟΣ ΠΑΝΑΓΙΩΤΗΣ'),
        (269, 'ΠΑΠΑΔΑΚΗΣ ΣΤΥΛΙΑΝΟΣ'),
        (270, 'ΖΑΧΑΡΟΠΟΥΛΟΣ ΒΑΣΙΛΕΙΟΣ'),
    ]
    cur.execute("SELECT exammoreid FROM slis_exams WHERE diagnostis IS NULL ORDER BY exammoreid ASC")
    pending_ids = [r[0] for r in cur.fetchall()]
    for i, eid in enumerate(pending_ids):
        if i % 4 == 0:
            did, dname = diags_pool[(i // 4) % len(diags_pool)]
            cur.execute(
                "UPDATE slis_exams SET oldpers = ?, olddiagnostis = ?, oldvisit = 1, oldorder = '2026-07-15' WHERE exammoreid = ?",
                (did, dname, eid)
            )
    con.commit()

    cur.execute("SELECT COUNT(*) FROM slis_exams")
    rows_inserted = cur.fetchone()[0]
    print(f"  >> {rows_inserted} unique exam rows in DB")

    print(f"  DB written to : {db_path.resolve()}")
    con.close()


if __name__ == "__main__":
    seed(DB_PATH, INIT_SQL)
