"""
DiagFlow — Config DB Seeder
===========================
Creates db/diagflow.db (SQLite) with the real diagnostician & skills data.
Queries db/mock_slis.db to resolve category-based skill sets.

Usage (from project root):
    python db/create_diagflow_db.py

Safe to re-run: drops and recreates all config tables each time.
"""
import sqlite3
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
DIAGFLOW_DB = SCRIPT_DIR / "diagflow.db"
SLIS_DB     = SCRIPT_DIR / "mock_slis.db"


# ── Pull exam codes from mock_slis.db ────────────────────────────────────────
def load_exam_code_sets(slis_db: Path) -> tuple[set, set, set]:
    """Return (ct_codes, mri_codes, mra_codes) as sets of strings."""
    con = sqlite3.connect(slis_db)
    cur = con.execute("SELECT examnumcode, category FROM exam_categories")
    ct, mri, mra = set(), set(), set()
    for code, cat in cur.fetchall():
        s = str(code)
        if cat == "CT":  ct.add(s)
        elif cat == "MRI": mri.add(s)
        elif cat == "MRA": mra.add(s)
    con.close()
    print(f"  Loaded {len(ct)} CT codes, {len(mri)} MRI codes, {len(mra)} MRA codes from SLIS DB")
    return ct, mri, mra


# ── Schema ───────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS diagnosticians (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    can_ct      INTEGER NOT NULL DEFAULT 0,
    can_mri     INTEGER NOT NULL DEFAULT 0,
    daily_quota INTEGER NOT NULL DEFAULT 15,
    created_at  TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS diagnostician_skills (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnostician_id  INTEGER NOT NULL REFERENCES diagnosticians(id) ON DELETE CASCADE,
    exam_code         TEXT    NOT NULL,
    is_preferred      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(diagnostician_id, exam_code)
);

CREATE TABLE IF NOT EXISTS partnerships (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    issuing_doctor_id           TEXT    NOT NULL,
    issuing_doctor_name         TEXT    NOT NULL,
    preferred_diagnostician_id  INTEGER NOT NULL REFERENCES diagnosticians(id) ON DELETE CASCADE,
    priority                    INTEGER NOT NULL DEFAULT 1,
    exclusive                   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS availability (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnostician_id        INTEGER NOT NULL REFERENCES diagnosticians(id) ON DELETE CASCADE,
    date                    TEXT    NOT NULL,
    status                  TEXT    NOT NULL DEFAULT 'available',
    is_pamakristos_oncall   INTEGER NOT NULL DEFAULT 0,
    notes                   TEXT,
    UNIQUE(diagnostician_id, date)
);

CREATE TABLE IF NOT EXISTS doctors (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    specialty   TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_skills_diag    ON diagnostician_skills(diagnostician_id);
CREATE INDEX IF NOT EXISTS idx_skills_code    ON diagnostician_skills(exam_code);
CREATE INDEX IF NOT EXISTS idx_avail_diag     ON availability(diagnostician_id);
CREATE INDEX IF NOT EXISTS idx_avail_date     ON availability(date);
CREATE INDEX IF NOT EXISTS idx_partner_doctor ON partnerships(issuing_doctor_id);
"""


def build_skill_rows(diag_id: int, codes: set, is_preferred: bool = False) -> list:
    return [(diag_id, code, 1 if is_preferred else 0) for code in sorted(codes)]


def seed():
    print(f"\nSeeding {DIAGFLOW_DB} …")

    # Load exam code sets from SLIS DB
    if SLIS_DB.exists():
        ct_codes, mri_codes, mra_codes = load_exam_code_sets(SLIS_DB)
    else:
        print("  WARNING: mock_slis.db not found — using empty code sets.")
        ct_codes, mri_codes, mra_codes = set(), set(), set()

    all_codes     = ct_codes | mri_codes | mra_codes
    mri_mra_codes = mri_codes | mra_codes

    # Codes that ΤΡΙΑΝΤΑΦΥΛΛΟΥ is excluded from
    triantafyllou_exclude = {
        "22810", "22055", "22040", "22030", "21061",
        "22340", "22341", "22465", "22505", "22510", "22511", "22512",
        "22641", "22642", "22661", "22662", "22702", "22703", "22704",
    }

    # ── Diagnosticians ───────────────────────────────────────────────────────
    # (id, name, active, can_ct, can_mri, daily_quota)
    diagnosticians = [
        (14,  "Νάτσικα",           1, 1, 1, 20),
        (41,  "Παπούτση",          1, 1, 0, 15),
        (61,  "Ανθίμου",           1, 1, 0, 15),
        (59,  "Μπερέτης",          1, 1, 1, 15),
        (119, "Αθανασάκος",        1, 0, 1, 15),
        (69,  "Κρεζία",            1, 0, 1, 15),
        (189, "Λιόντος",           1, 0, 1, 15),
        (97,  "Τριανταφύλλου",     1, 1, 1, 15),
        (269, "Παπαδάκης",         1, 0, 1, 15),
        (222, "WEB",               1, 0, 1, 15),
        (67,  "Αλεξόπουλος",       1, 1, 1, 10),
        (143, "Στεργίου Πηνελόπη", 1, 1, 1, 10),
        (74,  "Νικολακόπουλος",    1, 1, 0, 15),
        (79,  "Μαντζουράνης",      1, 1, 0, 15),
        (205, "Ανδριώτης",         1, 1, 0, 15),
        (264, "Σιγαλάς",           1, 1, 0, 15),
        (268, "Κοροδήμος",         1, 1, 0, 15),
        (34,  "Κουλογιώργα",       1, 1, 0, 15),
        (270, "Ζαχαρόπουλος",      1, 1, 0, 15),
        (89,  "Κυπριώτης",         1, 1, 1, 15),
    ]

    # ── Skills ───────────────────────────────────────────────────────────────
    # Each entry: (diagnostician_id, exam_code, is_preferred)
    #
    # Logic from the SQL file:
    #   CASE 1  – ΝΑΤΣΙΚΑ (14):       all CT + MRI + MRA
    #   CASE 2  – ΠΑΠΟΥΤΣΗ (41):      specific CT codes
    #   CASE 3  – ΑΝΘΙΜΟΥ (61):       specific CT codes
    #   CASE 4  – ΜΠΕΡΕΤΗΣ (59):      mix CT+MRI codes
    #   CASE 5  – ΑΘΑΝΑΣΑΚΟΣ/ΚΡΕΖΙΑ/ΛΙΟΝΤΟΣ (119/69/189): all MRI+MRA
    #   CASE 6  – ΤΡΙΑΝΤΑΦΥΛΛΟΥ (97): all CT+MRI+MRA MINUS exclusions
    #   CASE 7  – ΠΑΠΑΔΑΚΗΣ (269):    all MRI+MRA
    #   CASE 8  – WEB (222):          all MRI+MRA except 22270
    #   CASE 9  – ΑΛΕΞΟΠΟΥΛΟΣ (67):   3 specific codes
    #   CASE 10 – ΣΤΕΡΓΙΟΥ (143):     3 specific codes
    #   CASE 11 – 7 CT-only diags:    all CT
    #   CASE 12 – ΚΥΠΡΙΩΤΗΣ (89):     all CT + 22100, 22110, 22140

    skill_sets: dict[int, set] = {
        14:  all_codes,
        41:  {"22100","22110","22140","22300","22301","22335","22336",
              "22340","22341","22465","22505","22510","22511","22512",
              "22530","22612","22621","22622","22641","22642","22661",
              "22662","22702","22703","22704"},
        61:  {"22000","22020","22030","22040","22055","22100","22110",
              "22140","22200","22300","22301","22321","22335","22341",
              "22400","22401","22403","22450","22472","22480","22481",
              "22505","22512","22525","22530","22540","22621","22622",
              "22642","22800","22801","22802","22810","22830","22840",
              "22841","22860","22876","22877","22890"},
        59:  {"21061","21062","21063","22000","22001","22005","22020",
              "22030","22040","22055","22100","22110","22140","22200",
              "22400","22401","22540","22705","22707","22800","22801",
              "22802","22807","22810","22890"},
        119: mri_mra_codes,
        69:  mri_mra_codes,
        189: mri_mra_codes,
        97:  all_codes - triantafyllou_exclude,
        269: mri_mra_codes,
        222: mri_mra_codes - {"22270"},
        67:  {"22204","21011","21041"},
        143: {"22204","21011","21041"},
        74:  ct_codes,
        79:  ct_codes,
        205: ct_codes,
        264: ct_codes,
        268: ct_codes,
        34:  ct_codes,
        270: ct_codes,
        89:  ct_codes | {"22100","22110","22140"},
    }

    # ── Write to DB ──────────────────────────────────────────────────────────
    con = sqlite3.connect(DIAGFLOW_DB)
    cur = con.cursor()

    # Drop existing config tables
    for tbl in ["diagnostician_skills", "availability", "partnerships",
                "doctors", "diagnosticians"]:
        cur.execute(f"DROP TABLE IF EXISTS {tbl}")
    cur.execute("DROP INDEX IF EXISTS idx_skills_diag")
    cur.execute("DROP INDEX IF EXISTS idx_skills_code")
    cur.execute("DROP INDEX IF EXISTS idx_avail_diag")
    cur.execute("DROP INDEX IF EXISTS idx_avail_date")
    cur.execute("DROP INDEX IF EXISTS idx_partner_doctor")
    con.commit()

    cur.executescript(SCHEMA)
    con.commit()

    # Insert diagnosticians
    cur.executemany(
        "INSERT INTO diagnosticians (id, name, active, can_ct, can_mri, daily_quota) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        diagnosticians,
    )
    print(f"  >> {len(diagnosticians)} diagnosticians inserted")

    # Insert skills
    skill_rows = []
    for diag_id, codes in skill_sets.items():
        for code in sorted(codes):
            skill_rows.append((diag_id, code, 0))
    cur.executemany(
        "INSERT OR IGNORE INTO diagnostician_skills (diagnostician_id, exam_code, is_preferred) "
        "VALUES (?, ?, ?)",
        skill_rows,
    )
    print(f"  >> {len(skill_rows)} skill rows inserted")

    con.commit()
    con.close()

    print(f"\n  DB written to: {DIAGFLOW_DB.resolve()}")
    print("  Done. Run the app server and the real diagnostician data is live.")


if __name__ == "__main__":
    seed()
