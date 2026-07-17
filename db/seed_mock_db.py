"""
DiagFlow — Mock Slis DB Seeder
==============================
Reads data.xlsx and exam_codes.xlsx from the db/ folder and
populates db/mock_slis.db (SQLite) using the schema in init.sql.

Usage:
    python db/seed_mock_db.py

Run from the project root (the diagflow/ workspace folder).
Re-running is safe — it drops and re-creates the tables each time.
"""

import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

# ── Locate files relative to this script ──────────────────────────
SCRIPT_DIR   = Path(__file__).parent
DB_PATH      = SCRIPT_DIR / "mock_slis.db"
INIT_SQL     = SCRIPT_DIR / "init.sql"
DATA_XLSX    = SCRIPT_DIR / "data.xlsx"
CODES_XLSX   = SCRIPT_DIR / "exam_codes.xlsx"

try:
    import openpyxl
except ImportError:
    sys.exit(
        "ERROR: openpyxl is not installed.\n"
        "Install it with:  pip install openpyxl\n"
        "(or activate your venv first)"
    )


# ── Category mapping ──────────────────────────────────────────────
KATEGORYID_MAP = {
    18: "CT",
    22: "MRI",
    21: "MRA",
}


def _iso_date(val) -> str | None:
    """Convert an openpyxl date/datetime cell value to ISO-8601 string."""
    if val is None:
        return None
    if isinstance(val, (date, datetime)):
        return val.date().isoformat() if isinstance(val, datetime) else val.isoformat()
    s = str(val).strip()
    return s if s else None


def _int_or_none(val) -> int | None:
    """Return int or None; handles 'NULL' strings from the xlsx."""
    if val is None or str(val).strip().upper() == "NULL":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _str_or_none(val) -> str | None:
    """Return stripped string or None; handles 'NULL' strings."""
    if val is None:
        return None
    s = str(val).strip()
    return None if s.upper() == "NULL" or s == "" else s


# ── Load exam_codes.xlsx → {examnumcode: category} ───────────────
def load_exam_categories(path: Path) -> dict[int, tuple[str, str]]:
    """Returns {examnumcode: (name, category_str)}."""
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    result: dict[int, tuple[str, str]] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        d = dict(zip(headers, row))
        code = _int_or_none(d.get("EXAMNUMCODE"))
        kid  = _int_or_none(d.get("KATEGORYID"))
        name = _str_or_none(d.get("NAME")) or ""
        if code is not None and kid in KATEGORYID_MAP:
            result[code] = (name, KATEGORYID_MAP[kid])
    print(f"  Loaded {len(result)} exam category mappings")
    return result


# ── Seed the database ─────────────────────────────────────────────
def seed(db_path: Path, init_sql: Path, data_xlsx: Path, codes_xlsx: Path):
    print(f"Seeding {db_path} ...")

    # Load category map first
    print("Loading exam_codes.xlsx ...")
    cat_map = load_exam_categories(codes_xlsx)

    # Connect to SQLite
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # Drop existing tables so re-runs are idempotent
    cur.execute("DROP TABLE IF EXISTS slis_exams")
    cur.execute("DROP TABLE IF EXISTS exam_categories")
    cur.execute("DROP INDEX IF EXISTS idx_slis_exams_diagnostis")
    cur.execute("DROP INDEX IF EXISTS idx_slis_exams_visitdate")
    cur.execute("DROP INDEX IF EXISTS idx_slis_exams_examnumcode")
    con.commit()

    # Create schema directly (avoids SQL comment / semicolon parsing issues)
    print("Creating schema ...")
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS exam_categories (
            examnumcode   INTEGER PRIMARY KEY,
            name          TEXT    NOT NULL,
            category      TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS slis_exams (
            oldexam         INTEGER,
            oldvisit        INTEGER,
            oldorder        TEXT,
            oldpers         INTEGER,
            olddiagnostis   TEXT,
            aa              INTEGER,
            extracode       INTEGER PRIMARY KEY,
            visitid         INTEGER,
            demogid         INTEGER,
            fname           TEXT,
            lname           TEXT,
            examid          INTEGER,
            examnumcode     INTEGER,
            examname        TEXT,
            visitdate       TEXT,
            labcodeid       INTEGER,
            laboratoryname  TEXT,
            wardid          INTEGER,
            wcode           TEXT,
            wname           TEXT,
            diagnostis      INTEGER,
            personelid      INTEGER,
            code            TEXT,
            name            TEXT,
            notes           TEXT,
            exammoreid      INTEGER,
            category        TEXT,
            FOREIGN KEY (examnumcode) REFERENCES exam_categories (examnumcode)
        );

        CREATE INDEX IF NOT EXISTS idx_slis_exams_diagnostis  ON slis_exams (diagnostis);
        CREATE INDEX IF NOT EXISTS idx_slis_exams_visitdate    ON slis_exams (visitdate);
        CREATE INDEX IF NOT EXISTS idx_slis_exams_examnumcode  ON slis_exams (examnumcode);
    """)

    # Insert exam_categories
    print("Inserting exam_categories ...")
    cat_rows = [
        (code, name, category)
        for code, (name, category) in cat_map.items()
    ]
    cur.executemany(
        "INSERT OR REPLACE INTO exam_categories (examnumcode, name, category) VALUES (?, ?, ?)",
        cat_rows,
    )
    con.commit()
    print(f"  >> {len(cat_rows)} category rows inserted")

    # Load and insert slis_exams
    print("Loading data.xlsx ...")
    wb = openpyxl.load_workbook(data_xlsx)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]

    insert_sql = """
        INSERT OR REPLACE INTO slis_exams (
            oldexam, oldvisit, oldorder, oldpers, olddiagnostis,
            aa, extracode, visitid, demogid,
            fname, lname,
            examid, examnumcode, examname,
            visitdate, labcodeid, laboratoryname,
            wardid, wcode, wname,
            diagnostis, personelid, code, name,
            notes, exammoreid, category
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?
        )
    """

    rows_inserted = 0
    skipped = 0
    exam_rows = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        d = dict(zip(headers, row))

        extracode = _int_or_none(d.get("EXTRACODE"))
        if extracode is None:
            skipped += 1
            continue

        examnumcode = _int_or_none(d.get("EXAMNUMCODE"))

        # Derive category from exam_codes.xlsx, fall back to CATEGORY column
        if examnumcode and examnumcode in cat_map:
            category = cat_map[examnumcode][1]
        else:
            raw_cat = _str_or_none(d.get("CATEGORY")) or ""
            if "ΑΞΟΝΙΚΗ" in raw_cat:
                category = "CT"
            elif "ΜΑΓΝΗΤΙΚΗ" in raw_cat:
                category = "MRI"
            else:
                category = raw_cat or None

        # OLDVISIT: the xlsx stores 0 for "never"; keep as integer
        oldvisit = _int_or_none(d.get("OLDVISIT"))
        if oldvisit is None:
            oldvisit = 0

        # OLDORDER: the xlsx uses 1900-01-01 as a sentinel for "no date"
        oldorder_raw = d.get("OLDORDER")
        oldorder = None
        if oldorder_raw:
            iso = _iso_date(oldorder_raw)
            if iso and iso != "1900-01-01":
                oldorder = iso

        # diagnostis: NULL in xlsx means unassigned
        diagnostis = _int_or_none(d.get("DIAGNOSTIS"))

        exam_rows.append((
            _int_or_none(d.get("OLDEXAM")),
            oldvisit,
            oldorder,
            _int_or_none(d.get("OLDPERS")),
            _str_or_none(d.get("OLDDIAGNOSTIS")),

            _int_or_none(d.get("AA")),
            extracode,
            _int_or_none(d.get("VISITID")),
            _int_or_none(d.get("DEMOGID")),

            _str_or_none(d.get("FNAME")),
            _str_or_none(d.get("LNAME")),

            _int_or_none(d.get("EXAMID")),
            examnumcode,
            _str_or_none(d.get("EXAMNAME")),

            _iso_date(d.get("VISITDATE")),
            _int_or_none(d.get("LABCODEID")),
            _str_or_none(d.get("LABORATORYNAME")),

            _int_or_none(d.get("WARDID")),
            _str_or_none(d.get("WCODE")),
            _str_or_none(d.get("WNAME")),

            diagnostis,
            _int_or_none(d.get("PERSONELID")),
            _str_or_none(d.get("CODE")),
            _str_or_none(d.get("NAME")),

            _str_or_none(d.get("NOTES")),
            _int_or_none(d.get("EXAMMOREID")),
            category,
        ))

    cur.executemany(insert_sql, exam_rows)
    con.commit()

    cur.execute("SELECT COUNT(*) FROM slis_exams")
    rows_inserted = cur.fetchone()[0]
    print(f"  >> {rows_inserted} unique exam rows in DB  ({skipped} skipped, {len(exam_rows) - rows_inserted} dupes collapsed)")

    # Summary
    cur.execute("SELECT COUNT(*) FROM slis_exams WHERE diagnostis IS NULL")
    pending = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM slis_exams WHERE diagnostis IS NOT NULL")
    assigned = cur.fetchone()[0]
    cur.execute("SELECT category, COUNT(*) FROM slis_exams GROUP BY category ORDER BY category")
    by_cat = cur.fetchall()

    print()
    print("-- Summary ------------------------------------------")
    print(f"  Total exams   : {rows_inserted}")
    print(f"  Pending       : {pending}")
    print(f"  Assigned      : {assigned}")
    print(f"  By category   : {dict(by_cat)}")
    print(f"  DB written to : {db_path.resolve()}")
    print("-----------------------------------------------------")

    con.close()


if __name__ == "__main__":
    seed(DB_PATH, INIT_SQL, DATA_XLSX, CODES_XLSX)
