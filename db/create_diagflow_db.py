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
    exclusive                   INTEGER NOT NULL DEFAULT 0,
    is_active                   INTEGER NOT NULL DEFAULT 1
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
        (119, "Αθανασάκος",        1, 0, 1, 5),
        (69,  "Κρεζία",            1, 0, 1, 30),
        (189, "Λιόντος",           1, 0, 1, 20),
        (97,  "Τριανταφύλλου",     1, 1, 1, 999),
        (269, "Παπαδάκης",         1, 0, 1, 15),
        (222, "WEB",               1, 0, 1, 15),
        (67,  "Αλεξόπουλος",       1, 1, 1, 999),
        (143, "Στεργίου Πηνελόπη", 1, 1, 1, 999),
        (74,  "Νικολακόπουλος",    1, 1, 0, 35),
        (79,  "Μαντζουράνης",      1, 1, 0, 18),
        (205, "Ανδριώτης",         1, 1, 0, 25),
        (264, "Σιγαλάς",           1, 1, 0, 7),
        (268, "Κοροδήμος",         1, 1, 0, 10),
        (34,  "Κουλογιώργα",       1, 1, 0, 999),
        (270, "Ζαχαρόπουλος",      1, 1, 0, 15),
        (89,  "Κυπριώτης",         1, 1, 1, 22),
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

    # ── Partnerships ─────────────────────────────────────────────────────────
    partnerships = [
        ("574300", "ΤΣΟΥΤΣΑΝΗΣ ΑΘΑΝΑΣΙΟΣ", 41, 1, 0, 1),
        ("20028602439", "ΑΣΛΑΝΙΔΗΣ ΗΛΙΑΣ", 41, 1, 1, 1),
        ("99508289", "ΜΑΖΗΣ ΓΕΩΡΓΙΟΣ", 41, 1, 0, 1),
        ("580798", "ΝΑΤΣΙΟΥΛΑΣ ΝΙΚΟΛΑΟΣ", 41, 1, 0, 1),
        ("580448", "ΠΑΘΙΑΚΗΣ ΣΤ ΙΩΑΝΝΗΣ", 41, 1, 1, 1),
        ("579109", "ΠΕΤΡΙΔΗΣ ΓΕΩΡΓΙΟΣ", 41, 1, 1, 1),
        ("99508557", "ΠΙΣΚΟΠΑΚΗΣ ΑΝΔΡΕΑΣ", 41, 1, 0, 1),
        ("585104", "ΟΙΚΟΝΟΜΟΥ ΛΕΩΝ", 41, 1, 0, 1),
        ("582300", "ΤΖΑΝΕΤΑΚΟΣ ΔΗΜΗΤΡΙΟΣ", 59, 1, 0, 1),
        ("99508856", "ΣΕΡΕΜΕΤΑ ΕΥΜΟΡΦΙΑ", 59, 1, 0, 1),
        ("580256", "ΦΩΤΟΝΙΑΤΑΣ ΙΩΑΝΝΗΣ", 59, 1, 0, 1),
        ("465", "ΜΙΝΩΤΑΚΗΣ ΚΩΝ/ΝΟΣ", 61, 1, 0, 1),
        ("580747", "ΜΑΡΙΝΑΚΗΣ ΕΥΑΓΓΕΛΟΣ", 119, 1, 0, 1),
        ("589504", "ΣΑΛΑΜΑΛΙΚΗΣ ΝΙΚΟΛΑΟΣ", 14, 1, 0, 1),
        ("589185", "ΚΟΥΤΡΟΥΦΙΝΗΣ-ΤΑΤΑΤΣΗΣ ΑΝΑΣΤΑΣΙΟΣ", 14, 1, 0, 1),
        ("1413", "ΚΑΠΡΑΛΟΣ ΠΕΤΡΟΣ", 14, 1, 0, 0),
        ("2171", "ΚΑΤΣΑΚΟΥ ΠΗΝΕΛΟΠΗ", 14, 1, 0, 0),
        ("577223", "ΚΟΚΚΑΛΗΣ ΖΗΝΩΝΑΣ", 14, 1, 0, 0),
        ("573960", "ΚΟΚΟΡΟΓΙΑΝΝΗΣ ΔΗΜΟΣΘΕΝΗΣ", 14, 1, 0, 0),
        ("585239", "ΚΩΤΣΑΝΤΗΣ ΙΩΑΝΝΗΣ", 14, 1, 0, 0),
        ("576738", "ΛΑΜΠΡΑΚΗΣ ΑΝΔΡΕΑΣ", 14, 1, 0, 0),
        ("571149", "ΛΙΜΠΙΤΑΚΗ ΓΕΩΡΓΙΑ", 14, 1, 0, 0),
        ("577390", "ΜΙΣΙΤΖΗΣ ΑΔΑΜΑΝΤΙΟΣ", 14, 1, 0, 0),
        ("582234", "ΜΙΣΤΥΛΗΣ ΠΑΝΑΓΙΩΤΗΣ", 14, 1, 0, 0),
        ("575077", "ΜΠΑΔΕΚΑΣ ΑΘΑΝΑΣΙΟΣ", 14, 1, 0, 0),
        ("572773", "ΜΥΡΙΟΚΕΦΑΛΙΤΑΚΗΣ Α. ΕΜΜΑΝΟΥΗΛ", 14, 1, 0, 0),
        ("578547", "ΠΑΙΔΑΚΑΚΟΣ ΝΙΚΟΛΑΟΣ", 14, 1, 0, 0),
        ("515", "ΠΑΥΛΟΓΙΑΝΝΟΠΟΥΛΟΣ ΣΤΥΛΙΑΝΟΣ", 14, 1, 0, 0),
        ("572106", "ΠΟΛΥΖΩΗΣ ΒΑΣΙΛΕΙΟΣ", 14, 1, 0, 0),
        ("2902", "ΠΟΛΥΚΑΡΠΟΥΛΟΣ ΠΑΝΑΓΙΩΤΗΣ", 14, 1, 0, 0),
        ("573206", "ΡΟΙΔΗΣ ΝΙΚΟΛΑΟΣ", 14, 1, 0, 0),
        ("572236", "ΡΩΣΣΙΔΟΥ ΑΝΘΟΥΛΑ", 14, 1, 0, 0),
        ("567", "ΣΙΔΕΡΑΚΗΣ ΓΕΩΡΓΙΟΣ", 14, 1, 0, 0),
        ("598", "ΤΣΑΝΣΙΖΗ ΒΑΣΙΛΙΚΗ", 14, 1, 0, 0),
        ("572111", "ΧΡΥΣΑΝΘΑΚΟΠΟΥΛΟΣ ΠΑΝΑΓΙΩΤΗΣ", 14, 1, 0, 0),
        ("577551", "ΜΑΝΤΑΚΟΣ ΔΗΜΗΤΡΙΟΣ", 14, 1, 0, 0),
        ("569877", "ΑΝΤΩΝΟΓΙΑΝΝΑΚΗΣ ΕΜΜΑΝΟΥΗΛ", 14, 1, 0, 1),
        ("575256", "ΒΛΑΧΟΣ-ΖΟΥΝΕΛΗΣ ΝΙΚΟΛΑΟΣ", 14, 1, 0, 1),
        ("575882", "ΔΩΡΗΣ ΣΤΥΛΙΑΝΟΣ", 14, 1, 0, 1),
        ("570808", "ΖΑΓΟΡΑΙΟΣ ΝΙΚΟΛΑΟΣ", 14, 1, 0, 1),
        ("570859", "ΚΟΥΤΣΕΛΙΝΗΣ NEΚΤΑΡΙΟΣ", 14, 1, 0, 1),
        ("584172", "ΖΑΜΠΕΛΗ ΦΡΑΝΤΖΕΣΚΑ", 14, 1, 0, 1),
        ("358", "ΚΑΤΣΙΟΥΛΑΣ ΚΩΣΤΑΣ", 14, 1, 0, 1),
        ("20102", "ΚΑΤΣΙΦΑΡΑΚΗΣ ΓΕΩΡΓΙΟΣ", 14, 1, 0, 1),
        ("579069", "ΜΠΡΙΛΑΚΗΣ ΕΜΜΑΝΟΥΗΛ", 14, 1, 0, 1),
        ("574473", "ΣΕΙΤΑΡΙΔΗΣ ΣΑΒΒΑΣ", 14, 1, 0, 1),
        ("587951", "ΣΚΥΝΔΙΛΙΑΣ ΙΩΑΝΝΗΣ", 14, 1, 0, 1),
        ("572952", "ΦΑΝΔΡΙΔΗΣ ΕΜΜΑΝΟΥΗΛ", 14, 1, 0, 1),
        ("569785", "ΧΙΣΣΑΣ ΔΙΟΝΥΣΙΟΣ", 14, 1, 0, 1),
        ("584094", "ΑΒΡΑΜΙΔΗΣ ΓΡΗΓΟΡΙΟΣ", 14, 1, 0, 1),
        ("570088", "ΑΛΕΞΑΚΗΣ ΔΗΜΗΤΡΙΟΣ", 14, 1, 0, 1),
        ("570659", "ΑΠΟΣΤΟΛΟΠΟΥΛΟΣ ΕΥΑΓΓΕΛΟΣ", 14, 1, 0, 1),
        ("579460", "ΒΑΣΙΛΟΠΟΥΛΟΣ ΣΑΒΒΑΣ", 14, 1, 0, 1),
        ("571518", "ΒΛΑΜΗΣ ΙΩΑΝΝΗΣ", 14, 1, 0, 1),
        ("577200", "ΓΑΛΑΝΟΠΟΥΛΟΣ ΗΛΙΑΣ", 14, 1, 0, 1),
        ("569854", "ΓΕΩΡΓΙΑΔΟΥ ΠΑΡΑΣΚΕΥΗ", 14, 1, 0, 1),
        ("571062", "ΓΚΕΡΕΚΟΣ ΣΠΥΡΙΔΩΝ", 14, 1, 0, 1),
        ("1746", "ΔΑΝΔΑΚΗΣ ΔΗΜΗΤΡΙΟΣ", 14, 1, 0, 1),
        ("582686", "ΔΑΡΛΗΣ ΝΙΚΟΛΑΟΣ", 14, 1, 0, 1),
        ("572905", "ΔΕΛΗΓΕΩΡΓΗΣ ΑΝΑΣΤΑΣΙΟΣ", 14, 1, 0, 1),
        ("576305", "ΔΡΑΚΟΠΟΥΛΟΥ ΔΑΝΑΗ", 14, 1, 0, 1),
        ("570523", "ΘΕΟΣ ΧΡΗΣΤΟΣ", 14, 1, 0, 1),
        ("576295", "ΙΝΤΖΙΡΤΖΗΣ ΠΑΝΑΓΙΩΤΗΣ", 14, 1, 0, 1),
        ("581433", "ΙΝΤΖΟΓΛΟΥ ΚΩΝΣΤΑΝΤΙΝΟΣ", 14, 1, 0, 1),
        ("574213", "ΚΑΛΑΒΡΥΤΙΝΟΣ ΙΩΑΝΝΗΣ", 14, 1, 0, 1),
        ("570157", "ΚΑΝΔΥΛΗ ΑΝΝΑ", 14, 1, 0, 1),
        ("577347", "ΚΟΡΜΑΣ ΘΕΟΔΩΡΟΣ", 14, 1, 0, 1),
        ("571334", "ΚΟΥΤΣΟΣΤΑΘΗΣ ΣΤΕΦΑΝΟΣ", 14, 1, 0, 1),
        ("576434", "ΚΥΡΙΑΚΙΔΗΣ ΑΘΑΝΑΣΙΟΣ", 14, 1, 0, 1),
        ("569428", "ΚΩΣΤΟΠΟΥΛΟΣ ΔΗΜΗΤΡΙΟΣ", 14, 1, 0, 1),
        ("579145", "ΛΑΛΛΟΣ ΣΤΕΡΓΙΟΣ", 14, 1, 0, 1),
        ("575226", "ΜΑΛΑΧΙΑΣ ΜΙΧΑΗΛ-ΑΛΕΞΑΝΔΡΟΣ", 14, 1, 0, 1),
        ("575608", "ΜΑΡΙΟΛΗΣ-ΣΑΨΑΚΟΣ ΘΕΟΔΩΡΟΣ", 14, 1, 0, 1),
        ("577009", "ΜΑΧΑΙΡΑΣ ΓΕΩΡΓΙΟΣ", 14, 1, 0, 1),
        ("572376", "ΜΑΧΑΙΡΑΣ ΣΤΥΛΙΑΝΟΣ", 14, 1, 0, 1),
        ("573370", "ΜΙΧΑΛΟΣ ΜΙΧΑΗΛ", 14, 1, 0, 1),
        ("576875", "ΜΟΥΖΑΚΗΣ ΒΑΣΙΛΕΙΟΣ", 14, 1, 0, 1),
        ("456231", "ΜΠΕΚΑΣ ΝΙΚΟΛΑΟΣ", 14, 1, 0, 1),
        ("586756", "ΜΠΕΚΑΣ ΓΕΩΡΓΙΟΣ", 14, 1, 0, 1),
        ("1679", "ΜΠΟΥΧΛΗΣ ΓΕΩΡΓΙΟΣ", 14, 1, 0, 1),
        ("572407", "ΝΙΚΟΛΑΡΑΣ ΓΕΩΡΓΙΟΣ", 14, 1, 0, 1),
        ("574646", "ΠΑΞΙΝΟΣ ΟΔΥΣΣΕΑΣ", 14, 1, 0, 1),
        ("570103", "ΠΑΠΑΒΑΣΙΛΕΙΟΥ ΑΘΑΝΑΣΙΟΣ", 14, 1, 0, 1),
        ("571611", "ΠΑΠΑΔΕΑΣ ΑΛΕΞΑΝΔΡΟΣ", 14, 1, 0, 1),
        ("579542", "ΠΑΠΑΠΟΛΥΧΡΟΝΙΟΥ ΘΕΟΔΩΡΟΣ", 14, 1, 0, 1),
        ("576360", "ΠΑΠΑΣΤΕΦΑΝΟΥ ΣΩΤΗΡΙΟΣ", 14, 1, 0, 1),
        ("1228", "ΠΑΤΣΟΠΟΥΛΟΣ ΗΡΑΚΛΗΣ", 14, 1, 0, 1),
        ("580232", "ΠΑΥΛΩΦ ΓΕΩΡΓΙΟΣ", 14, 1, 0, 1),
        ("575386", "ΠΕΤΡΟΠΟΥΛΟΣ ΦΩΤΙΟΣ", 14, 1, 0, 1),
        ("571071", "ΠΙΣΚΟΠΑΚΗΣ ΝΙΚΟΛΑΟΣ", 14, 1, 0, 1),
        ("588672", "ΠΟΥΛΤΣΙΔΗΣ ΛΑΖΑΡΟΣ", 14, 1, 0, 1),
        ("587275", "ΣΑΜΔΑΝΗΣ ΒΑΣΙΛΕΙΟΣ", 14, 1, 0, 1),
        ("582203", "ΣΑΣΑΛΟΣ ΓΡΗΓΟΡΙΟΣ", 14, 1, 0, 1),
        ("571222", "ΣΑΦΟΣ ΓΕΩΡΓΙΟΣ", 14, 1, 0, 1),
        ("579034", "ΣΟΡΑΝΟΓΛΟΥ ΒΑΣΙΛΕΙΟΣ", 14, 1, 0, 1),
        ("582864", "ΣΟΥΡΜΕΛΗΣ ΣΑΒΒΑΣ-ΓΕΩΡΓΙΟΣ", 14, 1, 0, 1),
        ("576105", "ΣΠΥΡΙΔΩΝΟΣ ΣΑΡΑΝΤΗΣ-ΠΕΤΡΟΣ", 14, 1, 0, 1),
        ("584696", "ΣΤΑΘΕΛΛΗΣ ΑΠΟΣΤΟΛΟΣ", 14, 1, 0, 1),
        ("569805", "ΣΤΑΜΑΤΑΚΗΣ ΑΝΤΩΝΙΟΣ", 14, 1, 0, 1),
        ("570337", "ΤΑΤΑΡΗΣ ΝΙΚΟΛΑΟΣ", 14, 1, 0, 1),
        ("122", "ΤΖΑΒΕΛΛΑΣ ΙΩΑΝΝΗΣ", 14, 1, 0, 1),
        ("575196", "ΤΟΚΗΣ ΑΝΑΣΤΑΣΙΟΣ", 14, 1, 0, 1),
        ("570152", "ΤΟΠΑΛΙΔΟΥ ΠΗΝΕΛΟΠΗ", 14, 1, 0, 1),
        ("587949", "ΤΡΕΛΛΟΠΟΥΛΟΣ ΑΓΓΕΛΟΣ", 14, 1, 0, 1),
        ("574185", "ΤΡΙΑΝΤΑΦΥΛΛΟΥ ΧΡΗΣΤΟΣ", 14, 1, 0, 1),
        ("570854", "ΤΣΑΠΑΚΙΔΗΣ ΙΩΑΝΝΗΣ", 14, 1, 0, 1),
        ("578038", "ΤΣΙΑΜΠΑ ΒΑΣΙΛΙΚΗ", 14, 1, 0, 1),
        ("569465", "ΤΣΙΚΑ ΟΥΡΑΝΙΑ", 14, 1, 0, 1),
        ("576320", "ΤΣΟΥΚΑΣ ΔΗΜΗΤΡΙΟΣ", 14, 1, 0, 1),
        ("2006", "ΤΣΟΥΤΣΑΝΗΣ ΓΕΩΡΓΙΟΣ", 14, 1, 0, 1),
        ("574172", "ΤΣΩΛΟΣ ΙΩΑΝΝΗΣ", 14, 1, 0, 1),
        ("571452", "ΧΑΡΟΠΟΥΛΟΣ ΙΩΑΝΝΗΣ", 14, 1, 0, 1),
        ("2056", "ΧΡΟΝΟΠΟΥΛΟΣ ΕΥΣΤΑΘΙΟΣ", 14, 1, 0, 1),
        ("574638", "ΧΡΥΣΟΧΟΥ ΑΙΚΑΤΕΡΙΝΗ", 14, 1, 0, 1),
    ]

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


    # Insert partnerships
    cur.executemany(
        "INSERT INTO partnerships (issuing_doctor_id, issuing_doctor_name, preferred_diagnostician_id, priority, exclusive, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        partnerships,
    )
    print(f"  >> {len(partnerships)} partnerships inserted")

    print(f"\n  DB written to: {DIAGFLOW_DB.resolve()}")
    print("  Done. Run the app server and the real diagnostician data is live.")


if __name__ == "__main__":
    seed()
