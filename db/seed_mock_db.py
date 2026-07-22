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
        print(f"Error: {init_sql} not found.")
        return

    if db_path.exists():
        try:
            db_path.unlink()
        except PermissionError:
            pass

    # Connect to SQLite
    con = sqlite3.connect(db_path)
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
    cur.executescript(sql_script)
    con.commit()

    cur.execute("SELECT COUNT(*) FROM slis_exams")
    rows_inserted = cur.fetchone()[0]
    print(f"  >> {rows_inserted} unique exam rows in DB")

    print(f"  DB written to : {db_path.resolve()}")
    con.close()


if __name__ == "__main__":
    seed(DB_PATH, INIT_SQL)
