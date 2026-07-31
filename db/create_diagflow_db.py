"""
DiagFlow — Config DB Seeder
===========================
Creates db/diagflow.db (SQLite) with the real diagnostician & skills data.
Populates it from db/init_diagflow.sql.

Usage (from project root):
    python db/create_diagflow_db.py

Safe to re-run: drops and recreates all config tables each time.
"""
import sqlite3
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
DIAGFLOW_DB = SCRIPT_DIR / "diagflow.db"
INIT_SQL    = SCRIPT_DIR / "init_diagflow.sql"

def seed():
    sql_file = INIT_SQL
    if not sql_file.exists():
        fallback_sql = SCRIPT_DIR / "templates" / "init_diagflow.sql"
        if fallback_sql.exists():
            sql_file = fallback_sql
        else:
            print(f"Error: {INIT_SQL} not found.")
            return

    print(f"\nSeeding {DIAGFLOW_DB} from {sql_file} ...")

    # Try to delete the file, but if it's locked by uvicorn, just drop the tables
    if DIAGFLOW_DB.exists():
        try:
            DIAGFLOW_DB.unlink()
        except PermissionError:
            pass

    con = sqlite3.connect(DIAGFLOW_DB, timeout=10.0)
    cur = con.cursor()

    # Drop existing config tables in case the file couldn't be deleted
    for tbl in ["diagnostician_skills", "availability", "partnerships",
                "doctors", "diagnosticians", "local_assignments", "assignment_log", "system_settings"]:
        cur.execute(f"DROP TABLE IF EXISTS {tbl}")
    
    # Also drop indexes to avoid conflicts if they already exist
    cur.execute("DROP INDEX IF EXISTS idx_skills_diag")
    cur.execute("DROP INDEX IF EXISTS idx_skills_code")
    cur.execute("DROP INDEX IF EXISTS idx_avail_diag")
    cur.execute("DROP INDEX IF EXISTS idx_avail_date")
    cur.execute("DROP INDEX IF EXISTS idx_partner_doctor")
    con.commit()

    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_script = f.read()

    cur.executescript(sql_script)
    con.commit()
    con.close()

    print(f"\n  DB written to: {DIAGFLOW_DB.resolve()}")
    print("  Done. Run the app server and the real diagnostician data is live.")

if __name__ == "__main__":
    seed()
