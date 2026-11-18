"""
DiagFlow — Comprehensive Fresh Mock Data Seeder
===============================================
Generates fresh mock data in db/mock_slis.db and clears staged assignments in db/diagflow.db.
Includes all requested scenarios:
- Multi-date exams (Today 2026-08-28, Yesterday 2026-08-27, 2026-08-26, 2026-08-03)
- Auto-assigned exams (Exclusive partnerships & Dynamic exam routing rules)
- Παμμακάριστος cases (both rule-routed and on-call)
- Multi-exam orders with same order code (Grouping)
- Pending exams with English / Latin / Greek red comments (e.g. 'NATSIKA', 'BERETIS', 'ΠΑΠΟΥΤΣΗ')
- Exams with patient history (oldpers, olddiagnostis, oldorder)
- Historical assigned exams for 03/08/2026 and pending exams for 03/08/2026
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime, date, timedelta

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
MOCK_DB_PATH = ROOT_DIR / "db" / "mock_slis.db"
DIAGFLOW_DB_PATH = ROOT_DIR / "db" / "diagflow.db"


def seed_all():
    print("=" * 60)
    print("  SEEDING FRESH COMPREHENSIVE MOCK DATA")
    print("=" * 60)

    # 1. Reset diagflow.db staged tables
    if DIAGFLOW_DB_PATH.exists():
        try:
            con_df = sqlite3.connect(str(DIAGFLOW_DB_PATH), timeout=10.0)
            con_df.execute("DELETE FROM local_assignments")
            con_df.execute("DELETE FROM assignment_log")
            con_df.execute("DELETE FROM dismissed_auto_assignments")
            con_df.commit()
            con_df.close()
            print("✓ Cleared local_assignments, assignment_log & dismissed in diagflow.db")
        except Exception as e:
            print(f"Warning clearing diagflow.db: {e}")

    # 2. Reset mock_slis.db
    MOCK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(MOCK_DB_PATH), timeout=10.0)
    con.execute("DROP TABLE IF EXISTS slis_exams")
    con.execute("DROP TABLE IF EXISTS exam_categories")
    con.execute("""
        CREATE TABLE slis_exams (
            exammoreid INTEGER PRIMARY KEY,
            oldexam INTEGER,
            oldvisit INTEGER,
            oldorder TEXT,
            oldpers INTEGER,
            olddiagnostis TEXT,
            aa INTEGER,
            extracode TEXT,
            visitid INTEGER,
            demogid INTEGER,
            fname TEXT,
            lname TEXT,
            age INTEGER,
            examid INTEGER,
            examnumcode TEXT,
            examname TEXT,
            visitdate TEXT,
            labcodeid INTEGER,
            laboratoryname TEXT,
            wardid INTEGER,
            wcode TEXT,
            wname TEXT,
            diagnostis INTEGER,
            personelid INTEGER,
            code TEXT,
            name TEXT,
            notes TEXT,
            category TEXT,
            stat INTEGER DEFAULT 0,
            slis_synced_at TEXT DEFAULT NULL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_slis_exams_visitdate ON slis_exams(visitdate)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_slis_exams_extracode ON slis_exams(extracode)")
    con.commit()

    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    two_days_ago_str = (date.today() - timedelta(days=2)).isoformat()
    three_days_ago_str = (date.today() - timedelta(days=3)).isoformat()
    aug03_str = "2026-08-03"

    exams = []

    # ─────────────────────────────────────────────────────────────────────────────
    # SCENARIO 1: Historical 03/08/2026 Exams (User's specific test case!)
    # ─────────────────────────────────────────────────────────────────────────────
    # 1.1 Unassigned exam on 03/08/2026 -> When assigned & pushed to SLIS, must appear on 03/08 dashboard!
    exams.append({
        "exammoreid": 1001,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 1, "extracode": "ORD-0308-01", "visitid": 5001, "demogid": 8001,
        "fname": "ΑΝΤΩΝΙΟΣ", "lname": "ΠΑΠΑΔΟΠΟΥΛΟΣ", "age": 52,
        "examid": 301, "examnumcode": "22010", "examname": "MRI ΕΓΚΕΦΑΛΟΥ",
        "visitdate": aug03_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 10, "wcode": "DOC-99", "wname": "ΓΕΝΙΚΗ ΚΛΙΝΙΚΗ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Τακτικός επανέλεγχος", "category": "MRI", "slis_synced_at": None
    })

    # 1.2 Already assigned & synced exams on 03/08/2026 (so 03/08 dashboard has base data)
    exams.append({
        "exammoreid": 1002,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 2, "extracode": "ORD-0308-02", "visitid": 5002, "demogid": 8002,
        "fname": "ΕΛΕΝΗ", "lname": "ΚΩΝΣΤΑΝΤΙΝΟΥ", "age": 45,
        "examid": 302, "examnumcode": "21010", "examname": "CT ΘΩΡΑΚΟΣ",
        "visitdate": aug03_str, "labcodeid": 1, "laboratoryname": "ΑΞΟΝΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 64",
        "wardid": 10, "wcode": "DOC-99", "wname": "ΠΑΘΟΛΟΓΙΚΗ",
        "diagnostis": 14, "personelid": 14, "code": "ΝΑΤΣΙΚΑ ΜΑΡΓΑΡΙΤΑ", "name": "ΝΑΤΣΙΚΑ ΜΑΡΓΑΡΙΤΑ",
        "notes": "", "category": "CT", "slis_synced_at": "2026-08-03T10:30:00"
    })
    exams.append({
        "exammoreid": 1003,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 3, "extracode": "ORD-0308-03", "visitid": 5003, "demogid": 8003,
        "fname": "ΝΙΚΟΛΑΟΣ", "lname": "ΓΕΩΡΓΙΟΥ", "age": 60,
        "examid": 303, "examnumcode": "22015", "examname": "MRI ΟΜΣΣ",
        "visitdate": aug03_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 10, "wcode": "DOC-99", "wname": "ΟΡΘΟΠΕΔΙΚΗ",
        "diagnostis": 41, "personelid": 41, "code": "ΠΑΠΟΥΤΣΗ ΔΗΜΗΤΡΑ", "name": "ΠΑΠΟΥΤΣΗ ΔΗΜΗΤΡΑ",
        "notes": "", "category": "MRI", "slis_synced_at": "2026-08-03T11:15:00"
    })
    exams.append({
        "exammoreid": 1004,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 4, "extracode": "ORD-0308-04", "visitid": 5004, "demogid": 8004,
        "fname": "ΔΗΜΗΤΡΙΟΣ", "lname": "ΣΤΑΥΡΟΥ", "age": 38,
        "examid": 304, "examnumcode": "22020", "examname": "MRI ΓΟΝΑΤΟΣ ΔΕ",
        "visitdate": aug03_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 10, "wcode": "DOC-99", "wname": "ΟΡΘΟΠΕΔΙΚΗ",
        "diagnostis": 59, "personelid": 59, "code": "ΜΠΕΡΕΤΗΣ ΓΕΩΡΓΙΟΣ", "name": "ΜΠΕΡΕΤΗΣ ΓΕΩΡΓΙΟΣ",
        "notes": "", "category": "MRI", "slis_synced_at": "2026-08-03T12:00:00"
    })

    # ─────────────────────────────────────────────────────────────────────────────
    # SCENARIO 2: Auto-Assigned Cases (Exclusive Partnerships & Dynamic Rules)
    # ─────────────────────────────────────────────────────────────────────────────
    # 2.1 Exclusive Doctor: ΒΟΪΛΑΣ ΓΕΩΡΓΙΟΣ (wcode: '669') -> Auto-assigned to ΜΠΕΡΕΤΗΣ (59)
    exams.append({
        "exammoreid": 2001,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 1, "extracode": "ORD-AUTO-01", "visitid": 6001, "demogid": 8101,
        "fname": "ΙΩΑΝΝΗΣ", "lname": "ΜΙΧΑΗΛΙΔΗΣ", "age": 64,
        "examid": 305, "examnumcode": "22010", "examname": "MRI ΕΓΚΕΦΑΛΟΥ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 20, "wcode": "669", "wname": "ΒΟΪΛΑΣ ΓΕΩΡΓΙΟΣ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Παραπομπή από ιατρείο Βοΐλα", "category": "MRI", "slis_synced_at": None
    })

    # 2.2 Exclusive Doctor: ΚΟΥΤΣΕΛΙΝΗΣ NEΚΤΑΡΙΟΣ (wcode: '570859') -> Auto-assigned to ΝΑΤΣΙΚΑ (14)
    exams.append({
        "exammoreid": 2002,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 2, "extracode": "ORD-AUTO-02", "visitid": 6002, "demogid": 8102,
        "fname": "ΜΑΡΙΑ", "lname": "ΑΘΑΝΑΣΙΟΥ", "age": 58,
        "examid": 306, "examnumcode": "22030", "examname": "MRI ΑΝΩ ΚΑΙ ΚΑΤΩ ΚΟΙΛΙΑΣ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 21, "wcode": "570859", "wname": "ΚΟΥΤΣΕΛΙΝΗΣ NEΚΤΑΡΙΟΣ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Εξειδικευμένο πρωτόκολλο ήπατος", "category": "MRI", "slis_synced_at": None
    })

    # 2.3 Dynamic Rule: Αρθρογραφίες Άνω Πατήσια (lab_id: 6, code: 21850) -> Auto-assigned to ΝΑΤΣΙΚΑ (14)
    exams.append({
        "exammoreid": 2003,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 3, "extracode": "ORD-AUTO-03", "visitid": 6003, "demogid": 8103,
        "fname": "ΣΠΥΡΙΔΩΝ", "lname": "ΔΗΜΗΤΡΟΠΟΥΛΟΣ", "age": 41,
        "examid": 307, "examnumcode": "21850", "examname": "ΑΡΘΡΟΓΡΑΦΙΑ ΩΜΟΥ",
        "visitdate": today_str, "labcodeid": 6, "laboratoryname": "ΑΝΩ ΠΑΤΗΣΙΑ - ΜΑΓΝΗΤΙΚΟΣ",
        "wardid": 22, "wcode": "DOC-77", "wname": "ΟΡΘΟΠΕΔΙΚΗ ΚΛΙΝΙΚΗ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Άμεση αρθρογραφία", "category": "MRI", "slis_synced_at": None
    })

    # 2.4 Dynamic Rule: Προστάτης (code: 22481) -> Auto-assigned to ΑΝΘΙΜΟΥ (61)
    exams.append({
        "exammoreid": 2004,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 4, "extracode": "ORD-AUTO-04", "visitid": 6004, "demogid": 8104,
        "fname": "ΠΑΝΑΓΙΩΤΗΣ", "lname": "ΚΑΡΑΓΙΑΝΝΗΣ", "age": 67,
        "examid": 308, "examnumcode": "22481", "examname": "ΠΟΛΥΠΑΡΑΜΕΤΡΙΚΗ MRI ΠΡΟΣΤΑΤΗ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 23, "wcode": "DOC-88", "wname": "ΟΥΡΟΛΟΓΙΚΗ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "mpMRI PIRADS", "category": "MRI", "slis_synced_at": None
    })

    # 2.5 Dynamic Rule: Μαστογραφίες (code: 22270) -> Auto-assigned to ΤΡΙΑΝΤΑΦΥΛΛΟΥ (97)
    exams.append({
        "exammoreid": 2005,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 5, "extracode": "ORD-AUTO-05", "visitid": 6005, "demogid": 8105,
        "fname": "ΑΙΚΑΤΕΡΙΝΗ", "lname": "ΒΑΣΙΛΕΙΟΥ", "age": 49,
        "examid": 309, "examnumcode": "22270", "examname": "ΜΑΓΝΗΤΙΚΗ ΜΑΣΤΟΓΡΑΦΙΑ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 24, "wcode": "DOC-99", "wname": "ΜΑΣΤΟΛΟΓΙΚΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Έλεγχος BIRADS", "category": "MRI", "slis_synced_at": None
    })

    # ─────────────────────────────────────────────────────────────────────────────
    # SCENARIO 3: Παμμακάριστος Cases
    # ─────────────────────────────────────────────────────────────────────────────
    # 3.1 Παμμακάριστος Dynamic Rule: Φασματοσκοπία (code: 22705) -> Auto-assigned to ΜΠΕΡΕΤΗΣ (59)
    exams.append({
        "exammoreid": 3001,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 1, "extracode": "ORD-PAM-01", "visitid": 7001, "demogid": 8201,
        "fname": "ΧΑΡΑΛΑΜΠΟΣ", "lname": "ΛΕΚΚΑΣ", "age": 55,
        "examid": 310, "examnumcode": "22705", "examname": "ΜΑΓΝΗΤΙΚΗ ΦΑΣΜΑΤΟΣΚΟΠΙΑ ΕΓΚΕΦΑΛΟΥ",
        "visitdate": today_str, "labcodeid": 3, "laboratoryname": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ - ΑΚΤΙΝΟΔΙΑΓΝΩΣΤΙΚΟ",
        "wardid": 30, "wcode": "PAM-01", "wname": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Ειδικό αίτημα Παμμακαρίστου", "category": "MRI", "slis_synced_at": None
    })

    # 3.2 Παμμακάριστος General Case (On-call routing)
    exams.append({
        "exammoreid": 3002,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 2, "extracode": "ORD-PAM-02", "visitid": 7002, "demogid": 8202,
        "fname": "ΑΝΝΑ", "lname": "ΜΑΚΡΗ", "age": 62,
        "examid": 311, "examnumcode": "21020", "examname": "CT ΚΟΙΛΙΑΣ",
        "visitdate": today_str, "labcodeid": 3, "laboratoryname": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ - ΑΚΤΙΝΟΔΙΑΓΝΩΣΤΙΚΟ",
        "wardid": 30, "wcode": "PAM-02", "wname": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ - ΧΕΙΡΟΥΡΓΙΚΗ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Επείγον Παμμακάριστος", "category": "CT", "slis_synced_at": None
    })

    # ─────────────────────────────────────────────────────────────────────────────
    # SCENARIO 4: Multi-Exam Orders (Order Grouping)
    # Same patient (demogid 8301) and same order code (ORD-GRP-100) with 3 exams!
    # ─────────────────────────────────────────────────────────────────────────────
    exams.append({
        "exammoreid": 4001,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 1, "extracode": "ORD-GRP-100", "visitid": 8001, "demogid": 8301,
        "fname": "ΓΕΩΡΓΙΟΣ", "lname": "ΓΕΩΡΓΙΟΥ", "age": 44,
        "examid": 312, "examnumcode": "22010", "examname": "MRI ΕΓΚΕΦΑΛΟΥ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 10, "wcode": "DOC-10", "wname": "ΝΕΥΡΟΛΟΓΙΚΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Πολυεστιακός έλεγχος (Μέρος 1/3)", "category": "MRI", "slis_synced_at": None
    })
    exams.append({
        "exammoreid": 4002,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 2, "extracode": "ORD-GRP-100", "visitid": 8001, "demogid": 8301,
        "fname": "ΓΕΩΡΓΙΟΣ", "lname": "ΓΕΩΡΓΙΟΥ", "age": 44,
        "examid": 313, "examnumcode": "22012", "examname": "MRI ΑΥΧΕΝΙΚΗΣ ΜΟΙΡΑΣ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ (ΑΜΣΣ)",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 10, "wcode": "DOC-10", "wname": "ΝΕΥΡΟΛΟΓΙΚΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Πολυεστιακός έλεγχος (Μέρος 2/3)", "category": "MRI", "slis_synced_at": None
    })
    exams.append({
        "exammoreid": 4003,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 3, "extracode": "ORD-GRP-100", "visitid": 8001, "demogid": 8301,
        "fname": "ΓΕΩΡΓΙΟΣ", "lname": "ΓΕΩΡΓΙΟΥ", "age": 44,
        "examid": 314, "examnumcode": "22014", "examname": "MRI ΘΩΡΑΚΙΚΗΣ ΜΟΙΡΑΣ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ (ΘΜΣΣ)",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 10, "wcode": "DOC-10", "wname": "ΝΕΥΡΟΛΟΓΙΚΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Πολυεστιακός έλεγχος (Μέρος 3/3)", "category": "MRI", "slis_synced_at": None
    })

    # ─────────────────────────────────────────────────────────────────────────────
    # SCENARIO 5: Comment Name Mentions & 'ΟΧΙ' Exclusions (All requested cases!)
    # ─────────────────────────────────────────────────────────────────────────────
    # 5.1 Exact Greek uppercase: 'ΠΑΡΑΚΑΛΩ ΝΑΤΣΙΚΑ' -> Auto-assigned to ΝΑΤΣΙΚΑ (14)
    exams.append({
        "exammoreid": 5001,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 1, "extracode": "ORD-COMM-01", "visitid": 9001, "demogid": 8401,
        "fname": "ΣΟΦΙΑ", "lname": "ΑΝΤΩΝΙΑΔΟΥ", "age": 36,
        "examid": 315, "examnumcode": "22020", "examname": "MRI ΓΟΝΑΤΟΣ ΑΡ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 15, "wcode": "DOC-55", "wname": "ΟΡΘΟΠΕΔΙΚΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "ΠΑΡΑΚΑΛΩ ΝΑΤΣΙΚΑ - Εξειδίκευση σε μηνίσκους", "category": "MRI", "slis_synced_at": None
    })

    # 5.2 Consonant Skeleton: 'ΝΤΣΚ' -> Auto-assigned to ΝΑΤΣΙΚΑ (14)
    exams.append({
        "exammoreid": 5002,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 2, "extracode": "ORD-COMM-02", "visitid": 9002, "demogid": 8402,
        "fname": "ΚΩΝΣΤΑΝΤΙΝΟΣ", "lname": "ΠΑΠΑΝΙΚΟΛΑΟΥ", "age": 51,
        "examid": 316, "examnumcode": "22010", "examname": "MRI ΕΓΚΕΦΑΛΟΥ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 16, "wcode": "DOC-56", "wname": "ΝΕΥΡΟΧΕΙΡΟΥΡΓΙΚΗ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "ΝΤΣΚ", "category": "MRI", "slis_synced_at": None
    })

    # 5.3 Accented mixed-case: 'Νάτσικα' -> Auto-assigned to ΝΑΤΣΙΚΑ (14)
    exams.append({
        "exammoreid": 5003,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 3, "extracode": "ORD-COMM-03", "visitid": 9003, "demogid": 8403,
        "fname": "ΕΥΑΓΓΕΛΙΑ", "lname": "ΔΗΜΑΚΗ", "age": 53,
        "examid": 317, "examnumcode": "22015", "examname": "MRI ΟΜΣΣ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 17, "wcode": "DOC-57", "wname": "ΦΥΣΙΑΤΡΕΙΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Σχόλιο κλινικού: Να πάει στην Νάτσικα", "category": "MRI", "slis_synced_at": None
    })

    # 5.4 Typo / Fuzzy variation: 'Νατσκα' -> Auto-assigned to ΝΑΤΣΙΚΑ (14)
    exams.append({
        "exammoreid": 5004,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 4, "extracode": "ORD-COMM-04", "visitid": 9004, "demogid": 8404,
        "fname": "ΘΕΟΔΩΡΟΣ", "lname": "ΜΠΑΡΜΠΑΣ", "age": 70,
        "examid": 318, "examnumcode": "22010", "examname": "MRI ΕΓΚΕΦΑΛΟΥ & ΑΓΓΕΙΟΓΡΑΦΙΑ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 16, "wcode": "DOC-56", "wname": "ΝΕΥΡΟΧΕΙΡΟΥΡΓΙΚΗ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Σχόλιο: Νατσκα", "category": "MRI", "slis_synced_at": None
    })

    # 5.5 Consonant skeleton for another diagnostician: 'ΜΠΡΤ' -> Auto-assigned to ΜΠΕΡΕΤΗΣ (59)
    exams.append({
        "exammoreid": 5005,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 5, "extracode": "ORD-COMM-05", "visitid": 9005, "demogid": 8405,
        "fname": "ΑΝΤΩΝΙΑ", "lname": "ΛΙΑΠΗ", "age": 42,
        "examid": 319, "examnumcode": "22010", "examname": "MRI ΕΓΚΕΦΑΛΟΥ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 15, "wcode": "DOC-55", "wname": "ΝΕΥΡΟΛΟΓΙΚΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "ΜΠΡΤ - Άμεση προτεραιότητα", "category": "MRI", "slis_synced_at": None
    })

    # 5.6 Negative exclusion: 'ΟΧΙ ΝΑΤΣΙΚΑ' -> ΝΑΤΣΙΚΑ excluded ('Αποκλείστηκε λόγω σχολίου') + STAT (1)
    exams.append({
        "exammoreid": 5006,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 6, "extracode": "ORD-COMM-06", "visitid": 9006, "demogid": 8406,
        "fname": "ΒΑΣΙΛΕΙΟΣ", "lname": "ΠΑΥΛΟΥ", "age": 63,
        "examid": 320, "examnumcode": "22020", "examname": "MRI ΓΟΝΑΤΟΣ ΔΕ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 18, "wcode": "DOC-70", "wname": "ΟΡΘΟΠΕΔΙΚΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "ΟΧΙ ΝΑΤΣΙΚΑ", "category": "MRI", "stat": 1, "slis_synced_at": None
    })

    # 5.7 Negative exclusion overriding Exclusive Partner + EMERGENCY (2):
    # Doctor ΚΟΥΤΣΕΛΙΝΗΣ (wcode '570859') is exclusive to ΝΑΤΣΙΚΑ (14), BUT comment has 'ΟΧΙ ΝΑΤΣΙΚΑ'
    exams.append({
        "exammoreid": 5007,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 7, "extracode": "ORD-COMM-07", "visitid": 9007, "demogid": 8407,
        "fname": "ΜΑΡΙΑ", "lname": "ΧΡΙΣΤΟΦΟΡΟΥ", "age": 47,
        "examid": 321, "examnumcode": "22030", "examname": "MRI ΑΝΩ ΚΑΙ ΚΑΤΩ ΚΟΙΛΙΑΣ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 21, "wcode": "570859", "wname": "ΚΟΥΤΣΕΛΙΝΗΣ NEΚΤΑΡΙΟΣ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "όχι νάτσικα - ασθενής ζήτησε άλλον ιατρό", "category": "MRI", "stat": 2, "slis_synced_at": None
    })

    # 5.8 Negative exclusion combined with positive match: 'ΟΧΙ ΜΠΕΡΕΤΗΣ - ΝΑΤΣΙΚΑ'
    exams.append({
        "exammoreid": 5008,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 8, "extracode": "ORD-COMM-08", "visitid": 9008, "demogid": 8408,
        "fname": "ΝΙΚΟΛΑΟΣ", "lname": "ΚΑΡΑΛΗΣ", "age": 58,
        "examid": 322, "examnumcode": "22010", "examname": "MRI ΕΓΚΕΦΑΛΟΥ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 16, "wcode": "DOC-56", "wname": "ΝΕΥΡΟΧΕΙΡΟΥΡΓΙΚΗ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "ΟΧΙ ΜΠΕΡΕΤΗΣ - ΝΑΤΣΙΚΑ", "category": "MRI", "slis_synced_at": None
    })

    # 5.9 Consonant skeleton for ΣΙΓΑΛΑΣ: 'ΣΓΛ' -> Auto-assigned to ΣΙΓΑΛΑΣ (264)
    exams.append({
        "exammoreid": 5009,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 9, "extracode": "ORD-COMM-09", "visitid": 9009, "demogid": 8409,
        "fname": "ΗΛΙΑΣ", "lname": "ΣΠΥΡΟΠΟΥΛΟΣ", "age": 39,
        "examid": 323, "examnumcode": "22015", "examname": "MRI ΟΜΣΣ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 17, "wcode": "DOC-57", "wname": "ΦΥΣΙΑΤΡΕΙΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "ΣΓΛ", "category": "MRI", "slis_synced_at": None
    })

    # 5.10 Consonant skeleton for ΚΟΥΛΟΓΙΩΡΓΑ: 'ΚΛΓΡΓ' -> Auto-assigned to ΚΟΥΛΟΓΙΩΡΓΑ (34)
    exams.append({
        "exammoreid": 5010,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 10, "extracode": "ORD-COMM-10", "visitid": 9010, "demogid": 8410,
        "fname": "ΑΓΓΕΛΙΚΗ", "lname": "ΜΑΝΟΥΣΟΥ", "age": 45,
        "examid": 324, "examnumcode": "22020", "examname": "MRI ΓΟΝΑΤΟΣ ΔΕ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 15, "wcode": "DOC-55", "wname": "ΟΡΘΟΠΕΔΙΚΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "ΚΛΓΡΓ", "category": "MRI", "slis_synced_at": None
    })

    # ─────────────────────────────────────────────────────────────────────────────
    # SCENARIO 6: Patient History Cases (oldpers, oldvisit, olddiagnostis)
    # ─────────────────────────────────────────────────────────────────────────────
    # 6.1 Previous diagnosed by ΠΑΠΟΥΤΣΗ (41) on 2026-07-15
    exams.append({
        "exammoreid": 6001,
        "oldvisit": 1, "oldorder": "2026-07-15", "oldpers": 41, "olddiagnostis": "ΠΑΠΟΥΤΣΗ ΔΗΜΗΤΡΑ",
        "aa": 1, "extracode": "ORD-HIST-01", "visitid": 9101, "demogid": 8501,
        "fname": "ΚΩΝΣΤΑΝΤΙΝΑ", "lname": "ΜΩΡΑΪΤΗ", "age": 48,
        "examid": 318, "examnumcode": "22015", "examname": "MRI ΟΜΣΣ (Επανέλεγχος)",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 18, "wcode": "DOC-58", "wname": "ΟΡΘΟΠΕΔΙΚΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Σύγκριση με προηγούμενη εξέταση 15/07", "category": "MRI", "slis_synced_at": None
    })

    # 6.2 Previous diagnosed by ΝΑΤΣΙΚΑ (14) on 2026-06-20
    exams.append({
        "exammoreid": 6002,
        "oldvisit": 1, "oldorder": "2026-06-20", "oldpers": 14, "olddiagnostis": "ΝΑΤΣΙΚΑ ΜΑΡΓΑΡΙΤΑ",
        "aa": 2, "extracode": "ORD-HIST-02", "visitid": 9102, "demogid": 8502,
        "fname": "ΒΑΣΙΛΕΙΟΣ", "lname": "ΚΟΛΟΒΟΣ", "age": 59,
        "examid": 319, "examnumcode": "22020", "examname": "MRI ΓΟΝΑΤΟΣ ΔΕ",
        "visitdate": today_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 18, "wcode": "DOC-58", "wname": "ΟΡΘΟΠΕΔΙΚΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Μετεγχειρητικός έλεγχος", "category": "MRI", "slis_synced_at": None
    })

    # ─────────────────────────────────────────────────────────────────────────────
    # SCENARIO 7: Standard Pending Exams across Yesterday & 2 Days Ago
    # ─────────────────────────────────────────────────────────────────────────────
    exams.append({
        "exammoreid": 7001,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 1, "extracode": "ORD-YEST-01", "visitid": 9201, "demogid": 8601,
        "fname": "ΑΠΟΣΤΟΛΟΣ", "lname": "ΖΑΡΡΑΣ", "age": 61,
        "examid": 320, "examnumcode": "21010", "examname": "CT ΘΩΡΑΚΟΣ",
        "visitdate": yesterday_str, "labcodeid": 1, "laboratoryname": "ΑΞΟΝΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 64",
        "wardid": 10, "wcode": "DOC-12", "wname": "ΠΝΕΥΜΟΝΟΛΟΓΙΚΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "", "category": "CT", "stat": 1, "slis_synced_at": None
    })
    exams.append({
        "exammoreid": 7002,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 2, "extracode": "ORD-YEST-02", "visitid": 9202, "demogid": 8602,
        "fname": "ΜΑΡΙΝΑ", "lname": "ΠΕΤΡΙΔΟΥ", "age": 39,
        "examid": 321, "examnumcode": "22010", "examname": "MRI ΕΓΚΕΦΑΛΟΥ",
        "visitdate": yesterday_str, "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T",
        "wardid": 10, "wcode": "DOC-13", "wname": "ΠΑΘΟΛΟΓΙΚΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "", "category": "MRI", "stat": 2, "slis_synced_at": None
    })
    exams.append({
        "exammoreid": 7003,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 3, "extracode": "ORD-2AGO-01", "visitid": 9203, "demogid": 8603,
        "fname": "ΕΥΣΤΑΘΙΟΣ", "lname": "ΡΑΠΤΗΣ", "age": 73,
        "examid": 322, "examnumcode": "21030", "examname": "CT ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ",
        "visitdate": two_days_ago_str, "labcodeid": 1, "laboratoryname": "ΑΞΟΝΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 64",
        "wardid": 10, "wcode": "DOC-14", "wname": "ΟΡΘΟΠΕΔΙΚΟ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "", "category": "CT", "stat": 0, "slis_synced_at": None
    })
    exams.append({
        "exammoreid": 7004,
        "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
        "aa": 4, "extracode": "ORD-2AGO-02", "visitid": 9204, "demogid": 8604,
        "fname": "ΓΕΩΡΓΙΑ", "lname": "ΠΑΠΑΧΡΗΣΤΟΥ", "age": 68,
        "examid": 323, "examnumcode": "21010", "examname": "CT ΘΩΡΑΚΟΣ",
        "visitdate": two_days_ago_str, "labcodeid": 3, "laboratoryname": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ - ΑΚΤΙΝΟΔΙΑΓΝΩΣΤΙΚΟ",
        "wardid": 30, "wcode": "PAM-03", "wname": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ",
        "diagnostis": None, "personelid": None, "code": None, "name": None,
        "notes": "Επανέλεγχος Παμμακαρίστου", "category": "CT", "stat": 0, "slis_synced_at": None
    })

    # ─────────────────────────────────────────────────────────────────────────────
    # SCENARIO 8: Realistic Bulk Clinical Volume (Pending & Varied Cases)
    # ─────────────────────────────────────────────────────────────────────────────
    bulk_patients = [
        ("ΑΝΑΣΤΑΣΙΟΣ", "ΠΑΠΑΔΑΚΗΣ", 54),
        ("ΔΗΜΗΤΡΑ", "ΟΙΚΟΝΟΜΟΥ", 32),
        ("ΓΕΩΡΓΙΑ", "ΚΑΡΑΓΙΑΝΝΗ", 8),    # Pediatric
        ("ΠΑΝΑΓΙΩΤΗΣ", "ΔΗΜΗΤΡΙΟΥ", 45),
        ("ΚΩΝΣΤΑΝΤΙΝΟΣ", "ΒΑΣΙΛΟΠΟΥΛΟΣ", 14), # Pediatric
        ("ΕΥΑΓΓΕΛΙΑ", "ΣΤΑΥΡΟΠΟΥΛΟΥ", 62),
        ("ΣΟΦΙΑ", "ΜΑΚΡΗ", 28),
        ("ΧΡΗΣΤΟΣ", "ΑΛΕΞΙΟΥ", 17),       # Pediatric
        ("ΜΙΧΑΗΛ", "ΑΝΤΩΝΙΟΥ", 71),
        ("ΙΩΑΝΝΑ", "ΘΕΟΔΩΡΟΥ", 39),
        ("ΑΝΔΡΕΑΣ", "ΣΠΥΡΟΥ", 58),
        ("ΜΑΡΙΑ", "ΚΟΝΤΟΥ", 11),         # Pediatric
        ("ΘΕΟΔΩΡΟΣ", "ΠΑΠΑΪΩΑΝΝΟΥ", 66),
        ("ΚΑΛΛΙΟΠΗ", "ΖΑΧΑΡΙΑΔΟΥ", 43),
        ("ΣΠΥΡΙΔΩΝ", "ΛΑΜΠΡΟΥ", 77),
        ("ΧΡΙΣΤΙΝΑ", "ΜΕΛΑ", 24),
        ("ΔΗΜΗΤΡΙΟΣ", "ΧΑΤΖΗΣ", 52),
        ("ΑΛΕΞΑΝΔΡΑ", "ΒΛΑΧΟΥ", 60),
        ("ΦΩΤΙΟΣ", "ΓΕΩΡΓΑΚΟΠΟΥΛΟΣ", 48),
        ("ΕΛΙΣΑΒΕΤ", "ΡΟΥΣΣΟΥ", 35),
        ("ΝΙΚΟΛΑΟΣ", "ΜΙΧΑΛΟΠΟΥΛΟΣ", 15), # Pediatric
        ("ΕΛΕΝΗ", "ΣΩΤΗΡΟΠΟΥΛΟΥ", 50),
        ("ΠΕΤΡΟΣ", "ΚΑΛΛΕΡΓΗΣ", 69),
        ("ΒΑΣΙΛΙΚΗ", "ΑΠΟΣΤΟΛΙΔΟΥ", 41),
        ("ΙΩΑΝΝΗΣ", "ΜΑΝΩΛΗΣ", 57),
        ("ΜΑΡΓΑΡΙΤΑ", "ΦΩΤΙΟΥ", 16),      # Pediatric
        ("ΑΘΑΝΑΣΙΟΣ", "ΚΩΣΤΟΠΟΥΛΟΣ", 74),
        ("ΕΙΡΗΝΗ", "ΠΑΝΑΓΙΩΤΟΠΟΥΛΟΥ", 38),
        ("ΣΤΕΦΑΝΟΣ", "ΜΑΡΙΝΟΣ", 63),
        ("ΑΓΓΕΛΙΚΗ", "ΔΙΑΜΑΝΤΗ", 29),
        ("ΕΜΜΑΝΟΥΗΛ", "ΤΖΑΝΕΤΟΣ", 55),
        ("ΟΥΡΑΝΙΑ", "ΚΑΡΑΛΗ", 46),
        ("ΛΑΜΠΡΟΣ", "ΧΡΗΣΤΙΔΗΣ", 82),
        ("ΑΦΡΟΔΙΤΗ", "ΣΙΜΟΥ", 33),
        ("ΓΡΗΓΟΡΙΟΣ", "ΚΟΥΡΤΗΣ", 67),
        ("ΕΥΔΟΚΙΑ", "ΠΑΥΛΙΔΟΥ", 51),
        ("ΠΑΥΛΟΣ", "ΜΠΙΛΙΑΣ", 70),
        ("ΖΩΗ", "ΠΑΝΟΥ", 22),
        ("ΛΕΩΝΙΔΑΣ", "ΣΤΑΜΑΤΙΟΥ", 44),
        ("ΜΑΡΘΑ", "ΤΡΙΑΝΤΗ", 59),
        ("ΚΥΡΙΑΚΟΣ", "ΚΑΠΕΤΑΝΙΟΣ", 65),
        ("ΠΗΝΕΛΟΠΗ", "ΑΡΓΥΡΙΟΥ", 37),
        ("ΣΩΤΗΡΙΟΣ", "ΜΠΑΛΑΤΣΟΣ", 76),
        ("ΠΑΡΑΣΚΕΥΗ", "ΜΠΟΤΣΗ", 40),
        ("ΑΝΤΩΝΙΟΣ", "ΓΙΑΝΝΑΚΟΠΟΥΛΟΣ", 53),
        ("ΒΙΚΤΩΡΙΑ", "ΣΑΒΒΑ", 31),
        ("ΣΤΑΥΡΟΣ", "ΓΚΙΚΑΣ", 64),
        ("ΑΣΠΑΣΙΑ", "ΜΑΡΚΟΥ", 10),        # Pediatric
        ("ΓΕΡΑΣΙΜΟΣ", "ΤΣΟΥΚΑΛΑΣ", 72),
        ("ΑΝΝΑ", "ΚΑΡΑΧΑΛΙΟΥ", 27),
    ]

    exam_catalogs = [
        {"examid": 350, "examnumcode": "22010", "examname": "MRI ΕΓΚΕΦΑΛΟΥ", "category": "MRI", "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T"},
        {"examid": 351, "examnumcode": "22015", "examname": "MRI ΟΣΦΥΪΚΗΣ ΜΟΙΡΑΣ (ΟΜΣΣ)", "category": "MRI", "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T"},
        {"examid": 352, "examnumcode": "22020", "examname": "MRI ΓΟΝΑΤΟΣ ΔΕ", "category": "MRI", "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T"},
        {"examid": 353, "examnumcode": "22025", "examname": "MRI ΩΜΟΥ ΑΡ", "category": "MRI", "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T"},
        {"examid": 354, "examnumcode": "22030", "examname": "MRI ΑΝΩ ΚΟΙΛΙΑΣ", "category": "MRI", "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T"},
        {"examid": 355, "examnumcode": "22035", "examname": "MRI ΑΥΧΕΝΙΚΗΣ ΜΟΙΡΑΣ (ΑΜΣΣ)", "category": "MRI", "labcodeid": 2, "laboratoryname": "ΜΑΓΝΗΤΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 1.5T"},
        {"examid": 356, "examnumcode": "22040", "examname": "MRI ΙΣΧΙΩΝ", "category": "MRI", "labcodeid": 6, "laboratoryname": "ΑΝΩ ΠΑΤΗΣΙΑ - ΜΑΓΝΗΤΙΚΟΣ"},
        {"examid": 357, "examnumcode": "21000", "examname": "CT ΕΓΚΕΦΑΛΟΥ", "category": "CT", "labcodeid": 1, "laboratoryname": "ΑΞΟΝΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 64"},
        {"examid": 358, "examnumcode": "21010", "examname": "CT ΘΩΡΑΚΟΣ", "category": "CT", "labcodeid": 1, "laboratoryname": "ΑΞΟΝΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 64"},
        {"examid": 359, "examnumcode": "21020", "examname": "CT ΚΟΙΛΙΑΣ & ΟΠΙΣΘΟΠΕΡΙΤΟΝΑΙΟΥ", "category": "CT", "labcodeid": 1, "laboratoryname": "ΑΞΟΝΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 64"},
        {"examid": 360, "examnumcode": "21030", "examname": "CT ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ", "category": "CT", "labcodeid": 1, "laboratoryname": "ΑΞΟΝΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 64"},
        {"examid": 361, "examnumcode": "21050", "examname": "CT ΤΡΑΧΗΛΟΥ", "category": "CT", "labcodeid": 1, "laboratoryname": "ΑΞΟΝΙΚΟΣ ΤΟΜΟΓΡΑΦΟΣ 64"},
    ]

    ward_catalogs = [
        ("DOC-CLI-01", "ΠΑΘΟΛΟΓΙΚΗ ΚΛΙΝΙΚΗ"),
        ("DOC-CLI-02", "ΧΕΙΡΟΥΡΓΙΚΗ ΚΛΙΝΙΚΗ"),
        ("DOC-CLI-03", "ΟΡΘΟΠΕΔΙΚΟ ΤΜΗΜΑ"),
        ("DOC-CLI-04", "ΝΕΥΡΟΛΟΓΙΚΟ ΤΜΗΜΑ"),
        ("DOC-CLI-05", "ΠΝΕΥΜΟΝΟΛΟΓΙΚΗ ΚΛΙΝΙΚΗ"),
        ("DOC-CLI-06", "ΟΥΡΟΛΟΓΙΚΗ ΚΛΙΝΙΚΗ"),
        ("DOC-CLI-07", "ΠΑΙΔΙΑΤΡΙΚΗ ΚΛΙΝΙΚΗ"),
        ("DOC-CLI-08", "ΓΕΝΙΚΗ ΙΑΤΡΙΚΗ"),
    ]

    notes_catalogs = [
        "Διερεύνηση άλγους",
        "Τακτικός επανέλεγχος",
        "Εμμένουσα κεφαλαλγία",
        "Οσφυαλγία με αντανάκλαση στο κάτω άκρο",
        "Χρόνιος βήχας και δύσπνοια",
        "Μετεγχειρητικός έλεγχος",
        "Πτώση εξ ιδίου ύψους",
        "Εμπύρετο",
        "",
        "",
        "Πυρετός και απώλεια βάρους",
        "Έλεγχος μετά από τραυματισμό",
    ]

    dates_pool = [today_str, today_str, today_str, yesterday_str, yesterday_str, two_days_ago_str]

    curr_eid = 8001
    curr_vid = 10001
    curr_did = 9001
    curr_ord = 100

    # 8.1 Multi-Exam Orders (5 orders = 11 exams)
    multi_specs = [
        (4, [0, 5], 0, today_str),                  # 14yo Pediatric, MRI Brain + MRI Cervical
        (6, [8, 9, 10], 1, yesterday_str),          # 28yo, CT Chest + Abdomen + Spine (STAT 1)
        (12, [1, 2], 2, today_str),                 # 66yo, MRI Lumbar + Knee (EMERGENCY 2)
        (21, [7, 8], 0, two_days_ago_str),          # 50yo, CT Brain + CT Chest
        (27, [0, 4], 1, today_str),                 # 38yo, MRI Brain + MRI Abdomen (STAT 1)
    ]

    for p_idx, cat_indices, order_stat, ord_date in multi_specs:
        p_fname, p_lname, p_age = bulk_patients[p_idx]
        ord_code = f"ORD-MUL-{curr_ord}"
        w_code, w_name = ward_catalogs[curr_ord % len(ward_catalogs)]
        for sub_i, cat_idx in enumerate(cat_indices):
            tmpl = exam_catalogs[cat_idx]
            sub_stat = order_stat if sub_i == 0 else 0
            exams.append({
                "exammoreid": curr_eid,
                "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
                "aa": sub_i + 1,
                "extracode": ord_code,
                "visitid": curr_vid,
                "demogid": curr_did,
                "fname": p_fname, "lname": p_lname, "age": p_age,
                "examid": tmpl["examid"],
                "examnumcode": tmpl["examnumcode"],
                "examname": tmpl["examname"],
                "visitdate": ord_date,
                "labcodeid": tmpl["labcodeid"],
                "laboratoryname": tmpl["laboratoryname"],
                "wardid": 10, "wcode": w_code, "wname": w_name,
                "diagnostis": None, "personelid": None, "code": None, "name": None,
                "notes": notes_catalogs[curr_eid % len(notes_catalogs)],
                "category": tmpl["category"],
                "stat": sub_stat,
                "slis_synced_at": None
            })
            curr_eid += 1
        curr_vid += 1
        curr_did += 1
        curr_ord += 1

    # 8.2 Single-Exam Orders (50 exams)
    for i, (p_fname, p_lname, p_age) in enumerate(bulk_patients):
        tmpl = exam_catalogs[i % len(exam_catalogs)]
        w_code, w_name = ward_catalogs[i % len(ward_catalogs)]
        ex_date = dates_pool[i % len(dates_pool)]

        if i in (2, 9, 20):
            ex_stat = 2 # Emergency
        elif i in (7, 15, 25, 33, 42):
            ex_stat = 1 # Stat
        else:
            ex_stat = 0 # Normal

        exams.append({
            "exammoreid": curr_eid,
            "oldvisit": 0, "oldorder": "", "oldpers": None, "olddiagnostis": None,
            "aa": 1,
            "extracode": f"ORD-SGL-{curr_ord}",
            "visitid": curr_vid,
            "demogid": curr_did,
            "fname": p_fname, "lname": p_lname, "age": p_age,
            "examid": tmpl["examid"],
            "examnumcode": tmpl["examnumcode"],
            "examname": tmpl["examname"],
            "visitdate": ex_date,
            "labcodeid": tmpl["labcodeid"],
            "laboratoryname": tmpl["laboratoryname"],
            "wardid": 10, "wcode": w_code, "wname": w_name,
            "diagnostis": None, "personelid": None, "code": None, "name": None,
            "notes": notes_catalogs[i % len(notes_catalogs)],
            "category": tmpl["category"],
            "stat": ex_stat,
            "slis_synced_at": None
        })
        curr_eid += 1
        curr_vid += 1
        curr_did += 1
        curr_ord += 1

    # Insert all generated mock rows
    for e in exams:
        e.setdefault("stat", 0)
        con.execute("""
            INSERT INTO slis_exams (
                exammoreid, oldexam, oldvisit, oldorder, oldpers, olddiagnostis,
                aa, extracode, visitid, demogid, fname, lname, age,
                examid, examnumcode, examname, visitdate, labcodeid, laboratoryname,
                wardid, wcode, wname, diagnostis, personelid, code, name,
                notes, category, stat, slis_synced_at
            ) VALUES (
                :exammoreid, :oldvisit, :oldvisit, :oldorder, :oldpers, :olddiagnostis,
                :aa, :extracode, :visitid, :demogid, :fname, :lname, :age,
                :examid, :examnumcode, :examname, :visitdate, :labcodeid, :laboratoryname,
                :wardid, :wcode, :wname, :diagnostis, :personelid, :code, :name,
                :notes, :category, :stat, :slis_synced_at
            )
        """, e)

    con.commit()
    count = con.execute("SELECT COUNT(*) FROM slis_exams").fetchone()[0]
    con.close()

    print(f"✓ Inserted {count} diverse mock exams into {MOCK_DB_PATH.resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    seed_all()
