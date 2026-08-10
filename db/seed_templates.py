"""
DiagFlow — Database Templates Seeder
====================================
Generates db/templates/init_diagflow.sql and db/templates/init_mock_slis.sql,
and initializes db/templates/diagflow.db and db/templates/mock_slis.db
with a rich set of realistic mock data covering all DiagFlow features & use cases.

Uses generic, fictional diagnostician names to ensure clear separation from production databases.

Usage:
    python db/seed_templates.py
"""

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = ROOT_DIR / "db" / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

DIAGFLOW_SQL = TEMPLATES_DIR / "init_diagflow.sql"
DIAGFLOW_DB = TEMPLATES_DIR / "diagflow.db"

MOCK_SLIS_SQL = TEMPLATES_DIR / "init_mock_slis.sql"
MOCK_SLIS_DB = TEMPLATES_DIR / "mock_slis.db"

# Password Hashes (bcrypt cost 12):
# admin -> admin1234
ADMIN_PASS_HASH = "$2b$12$SsLUct5RLmZJBwDQDBQ7xusD4CrjabY8EX9q.gKZjZbch5HZ2Ovly"
# it_support -> it_support1234
IT_SUPPORT_PASS_HASH = "$2b$12$dk9gH/KU49ZmcFDnQo8bl.D7q8/wcHT.icrlAFlJ8Kd9E3AjItrFa"


def build_diagflow_sql() -> str:
    today_iso = date.today().isoformat()
    yesterday_iso = (date.today() - timedelta(days=1)).isoformat()
    tomorrow_iso = (date.today() + timedelta(days=1)).isoformat()

    return f"""-- DiagFlow Configuration Database Initialization & Mock Template Data Script
BEGIN TRANSACTION;

-- Schema Definition
CREATE TABLE IF NOT EXISTS local_assignments (
    exammoreid          INTEGER PRIMARY KEY,
    diagnostician_id    INTEGER NOT NULL,
    diagnostician_name  TEXT    NOT NULL,
    assigned_at         TEXT    NOT NULL,
    is_auto             INTEGER NOT NULL DEFAULT 0,
    rule_desc           TEXT,
    extracode           TEXT
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

CREATE TABLE IF NOT EXISTS diagnostician_skills (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnostician_id  INTEGER NOT NULL REFERENCES diagnosticians(id) ON DELETE CASCADE,
    exam_code         TEXT    NOT NULL,
    is_preferred      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(diagnostician_id, exam_code)
);

CREATE TABLE IF NOT EXISTS diagnosticians (
    id               INTEGER PRIMARY KEY,
    name             TEXT    NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1,
    can_ct           INTEGER NOT NULL DEFAULT 0,
    can_mri          INTEGER NOT NULL DEFAULT 0,
    quota_monday     INTEGER NOT NULL DEFAULT 15,
    quota_tuesday    INTEGER NOT NULL DEFAULT 15,
    quota_wednesday  INTEGER NOT NULL DEFAULT 15,
    quota_thursday   INTEGER NOT NULL DEFAULT 15,
    quota_friday     INTEGER NOT NULL DEFAULT 15,
    quota_saturday   INTEGER NOT NULL DEFAULT 0,
    quota_sunday     INTEGER NOT NULL DEFAULT 0,
    preferred_lab_id INTEGER DEFAULT NULL,
    created_at       TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS doctors (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS assignment_log (
    exammoreid        INTEGER PRIMARY KEY,
    diagnostician_id  INTEGER NOT NULL,
    assigned_at       TEXT NOT NULL,
    modality          TEXT,
    extracode         TEXT
);

CREATE TABLE IF NOT EXISTS exam_routing_rules (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_id              INTEGER,
    is_pamakristos      INTEGER NOT NULL DEFAULT 0,
    exam_codes          TEXT NOT NULL,
    diagnostician_id    INTEGER NOT NULL,
    description         TEXT,
    issuing_doctor_id   TEXT,
    issuing_doctor_name TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS exclusive_lab_rules (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnostician_id  INTEGER NOT NULL,
    lab_id            INTEGER NOT NULL,
    lab_name          TEXT,
    is_active         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS modality_quotas (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnostician_id  INTEGER NOT NULL,
    modality          TEXT NOT NULL,
    max_count         INTEGER NOT NULL,
    is_active         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS system_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exam_dictionary (
    code     TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    category TEXT
);

CREATE TABLE IF NOT EXISTS pamakristos_schedule (
    weekday          INTEGER PRIMARY KEY,
    diagnostician_id INTEGER NOT NULL REFERENCES diagnosticians(id)
);

CREATE TABLE IF NOT EXISTS admin_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'admin',
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_skills_diag    ON diagnostician_skills(diagnostician_id);
CREATE INDEX IF NOT EXISTS idx_skills_code    ON diagnostician_skills(exam_code);
CREATE INDEX IF NOT EXISTS idx_avail_diag     ON availability(diagnostician_id);
CREATE INDEX IF NOT EXISTS idx_avail_date     ON availability(date);
CREATE INDEX IF NOT EXISTS idx_partner_doctor ON partnerships(issuing_doctor_id);

-- Mock Data Population

-- Fictional Mock Diagnosticians
INSERT INTO diagnosticians (id, name, active, can_ct, can_mri, quota_monday, quota_tuesday, quota_wednesday, quota_thursday, quota_friday, quota_saturday, quota_sunday, preferred_lab_id) VALUES
(1, 'ΔΙΑΓΝΩΣΤΗΣ Α', 1, 1, 1, 15, 15, 15, 15, 15, 0, 0, 1),
(2, 'ΔΙΑΓΝΩΣΤΗΣ Β', 1, 1, 1, 15, 15, 15, 15, 15, 0, 0, 1),
(3, 'ΔΙΑΓΝΩΣΤΗΣ Γ', 1, 1, 1, 15, 15, 15, 15, 15, 0, 0, 2),
(4, 'ΔΙΑΓΝΩΣΤΗΣ Δ', 1, 1, 0, 12, 12, 12, 12, 12, 0, 0, 1),
(5, 'ΔΙΑΓΝΩΣΤΗΣ Ε', 1, 0, 1, 12, 12, 12, 12, 12, 0, 0, 2),
(6, 'ΔΙΑΓΝΩΣΤΗΣ Ζ', 1, 1, 1, 15, 15, 15, 15, 15, 0, 0, 1);

-- Diagnostician Skills
INSERT INTO diagnostician_skills (diagnostician_id, exam_code, is_preferred) VALUES
(1, '22140', 1),
(1, '22141', 1),
(1, '22150', 0),
(2, '22140', 0),
(2, '22150', 1),
(2, '22151', 1),
(3, '22705', 1),
(3, '22150', 1),
(3, '22141', 0),
(4, '22140', 1),
(4, '22141', 1),
(5, '22150', 1),
(5, '22151', 1),
(6, '22140', 0),
(6, '22150', 0);

-- Doctors
INSERT INTO doctors (id, name) VALUES
('DOC101', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Α'),
('DOC102', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Β'),
('DOC103', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Γ'),
('DOC104', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Δ');

-- Partnerships (Exclusive & Preferred)
INSERT INTO partnerships (issuing_doctor_id, issuing_doctor_name, preferred_diagnostician_id, priority, exclusive, is_active) VALUES
('DOC101', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Α', 1, 1, 1, 1),
('DOC102', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Β', 3, 1, 0, 1);

-- Weekly Pamakristos Schedule (Mon-Fri only, weekdays 0..4)
INSERT INTO pamakristos_schedule (weekday, diagnostician_id) VALUES
(0, 3), -- Δευτέρα: ΔΙΑΓΝΩΣΤΗΣ Γ
(1, 4), -- Τρίτη: ΔΙΑΓΝΩΣΤΗΣ Δ
(2, 5), -- Τετάρτη: ΔΙΑΓΝΩΣΤΗΣ Ε
(3, 6), -- Πέμπτη: ΔΙΑΓΝΩΣΤΗΣ Ζ
(4, 2); -- Παρασκευή: ΔΙΑΓΝΩΣΤΗΣ Β

-- Availability Records
INSERT INTO availability (diagnostician_id, date, status, is_pamakristos_oncall, notes) VALUES
(1, '{today_iso}', 'available', 0, NULL),
(2, '{today_iso}', 'available', 1, 'Εφημερία Παμμακάριστος'),
(3, '{today_iso}', 'available', 0, NULL),
(4, '{today_iso}', 'absent', 0, 'Άδεια'),
(5, '{today_iso}', 'available', 0, NULL),
(6, '{today_iso}', 'available', 0, NULL);

-- Exam Routing Rules
INSERT INTO exam_routing_rules (lab_id, is_pamakristos, exam_codes, diagnostician_id, description, issuing_doctor_id, issuing_doctor_name, is_active) VALUES
(NULL, 1, '22705', 3, 'Παμμακάριστος - Μαγνητική Φασματοσκοπία σε ΔΙΑΓΝΩΣΤΗ Γ', NULL, NULL, 1),
(2, 0, '22151', 5, 'MRI Σπονδυλικής Αμπελοκήπων σε ΔΙΑΓΝΩΣΤΗ Ε', NULL, NULL, 1);

-- Exclusive Lab Rules
INSERT INTO exclusive_lab_rules (diagnostician_id, lab_id, lab_name, is_active) VALUES
(5, 2, 'Αμπελόκηποι', 1);

-- Modality Quotas
INSERT INTO modality_quotas (diagnostician_id, modality, max_count, is_active) VALUES
(4, 'CT', 8, 1);

-- System Settings (Picture 1 Proposed Scoring Weights)
INSERT INTO system_settings (key, value) VALUES
('pts_partnership', '0.20'),
('pts_history', '0.35'),
('pts_skills_pref', '0.20'),
('pts_skills_neut', '0.10'),
('pts_skills_none', '0.00'),
('pts_lab_pref', '0.15'),
('pts_lab_neut', '0.10'),
('pts_lab_other', '0.02'),
('pts_capacity', '0.10');

-- Admin Users (Admin & IT Support)
INSERT INTO admin_users (username, password_hash, role, is_active) VALUES
('admin', '{ADMIN_PASS_HASH}', 'admin', 1),
('it_support', '{IT_SUPPORT_PASS_HASH}', 'it_support', 1);

COMMIT;
"""


def build_mock_slis_sql() -> str:
    today_iso = date.today().isoformat()
    yesterday_iso = (date.today() - timedelta(days=1)).isoformat()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""-- Mock SLIS Database Initialization & Template Data Script
BEGIN TRANSACTION;

-- Schema Definition
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
    extracode       INTEGER,
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
    exammoreid      INTEGER PRIMARY KEY,
    category        TEXT,
    slis_synced_at  TEXT DEFAULT NULL,
    FOREIGN KEY (examnumcode) REFERENCES exam_categories (examnumcode)
);

CREATE TABLE IF NOT EXISTS diagnosticians (
    PERSONELID     REAL,
    DOCNAME        TEXT,
    MAXEXAMS       REAL,
    ISMR           REAL,
    ISCT           REAL,
    MON            REAL, QMON REAL,
    TUE            REAL, QTUE REAL,
    WED            REAL, QWED REAL,
    THU            REAL, QTHU REAL,
    FRI            REAL, QFRI REAL,
    SAT            REAL, QSAT REAL,
    PREFEREDLAB    REAL,
    ISACTIVE       REAL,
    ISPAMAKARISTO  REAL
);

CREATE TABLE IF NOT EXISTS doctors (
    DOCTORID   REAL,
    CODE       REAL,
    DOCNAME    TEXT,
    SPECIALID  REAL,
    RELATEDDOC REAL,
    ISENABLED  REAL
);

CREATE INDEX IF NOT EXISTS idx_slis_exams_diagnostis  ON slis_exams(diagnostis);
CREATE INDEX IF NOT EXISTS idx_slis_exams_visitdate   ON slis_exams(visitdate);
CREATE INDEX IF NOT EXISTS idx_slis_exams_examnumcode ON slis_exams(examnumcode);
CREATE INDEX IF NOT EXISTS idx_slis_exams_extracode   ON slis_exams(extracode);

-- Mock Data Population

-- Exam Categories
INSERT INTO exam_categories (examnumcode, name, category) VALUES
(22140, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ', 'CT'),
(22141, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΚΟΙΛΙΑΣ', 'CT'),
(22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI'),
(22151, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ', 'MRI'),
(22705, 'ΜΑΓΝΗΤΙΚΗ ΦΑΣΜΑΤΟΣΚΟΠΙΑ (MRS)', 'MRI');

-- Diagnosticians (SLIS mirror)
INSERT INTO diagnosticians (PERSONELID, DOCNAME, MAXEXAMS, ISMR, ISCT, MON, QMON, TUE, QTUE, WED, QWED, THU, QTHU, FRI, QFRI, SAT, QSAT, PREFEREDLAB, ISACTIVE, ISPAMAKARISTO) VALUES
(1, 'ΔΙΑΓΝΩΣΤΗΣ Α', 15, 1, 1, 1, 15, 1, 15, 1, 15, 1, 15, 1, 15, 0, 0, 1, 1, 0),
(2, 'ΔΙΑΓΝΩΣΤΗΣ Β', 15, 1, 1, 1, 15, 1, 15, 1, 15, 1, 15, 1, 15, 0, 0, 1, 1, 1),
(3, 'ΔΙΑΓΝΩΣΤΗΣ Γ', 15, 1, 1, 1, 15, 1, 15, 1, 15, 1, 15, 1, 15, 0, 0, 2, 1, 0),
(4, 'ΔΙΑΓΝΩΣΤΗΣ Δ', 12, 0, 1, 1, 12, 1, 12, 1, 12, 1, 12, 1, 12, 0, 0, 1, 1, 0),
(5, 'ΔΙΑΓΝΩΣΤΗΣ Ε', 12, 1, 0, 1, 12, 1, 12, 1, 12, 1, 12, 1, 12, 0, 0, 2, 1, 0),
(6, 'ΔΙΑΓΝΩΣΤΗΣ Ζ', 15, 1, 1, 1, 15, 1, 15, 1, 15, 1, 15, 1, 15, 0, 0, 1, 1, 0);

-- Doctors (SLIS mirror)
INSERT INTO doctors (DOCTORID, CODE, DOCNAME, SPECIALID, RELATEDDOC, ISENABLED) VALUES
(101, 101, 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Α', 1, NULL, 1),
(102, 102, 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Β', 2, NULL, 1),
(103, 103, 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Γ', 3, NULL, 1),
(104, 104, 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Δ', 4, NULL, 1);

-- SLIS Exams (Comprehensive Demo Dataset covering all Use Cases)
INSERT INTO slis_exams (exammoreid, extracode, fname, lname, examnumcode, examname, category, visitdate, labcodeid, laboratoryname, wcode, wname, diagnostis, notes, oldpers, olddiagnostis) VALUES
-- 1. Unassigned CT Chest (Order 5001 — Part 1)
(1001, 5001, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 01', 22140, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ', 'CT', '{today_iso}', 1, 'Κηφισιά', 'DOC104', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Δ', NULL, NULL, NULL, NULL),

-- 2. Unassigned CT Abdomen (Order 5001 — Part 2: Shared Order ID demo)
(1003, 5001, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 01', 22141, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΚΟΙΛΙΑΣ', 'CT', '{today_iso}', 1, 'Κηφισιά', 'DOC104', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Δ', NULL, NULL, NULL, NULL),

-- 3. Unassigned MRI Brain (Order 5002 — Part 1)
(1002, 5002, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 02', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '{today_iso}', 2, 'Αμπελόκηποι', 'DOC104', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Δ', NULL, NULL, NULL, NULL),

-- 4. Unassigned MRI Spine (Order 5002 — Part 2: Shared Order ID demo)
(1008, 5002, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 02', 22151, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ', 'MRI', '{today_iso}', 2, 'Αμπελόκηποι', 'DOC102', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Β', NULL, 'ΠΡΟΤΙΜΗΣΗ: ΔΙΑΓΝΩΣΤΗΣ Γ', NULL, NULL),

-- 5. Exclusive Partnership Auto-Assignment (Doctor DOC101 -> Diagnostician 1 ΔΙΑΓΝΩΣΤΗΣ Α)
(1004, 5003, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 03', 22140, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ', 'CT', '{today_iso}', 1, 'Κηφισιά', 'DOC101', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Α', NULL, NULL, NULL, NULL),

-- 6. Dynamic Routing Rule Auto-Assignment (22705 Pamakristos -> Diagnostician 3 ΔΙΑΓΝΩΣΤΗΣ Γ)
(1005, 5004, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 04', 22705, 'ΜΑΓΝΗΤΙΚΗ ΦΑΣΜΑΤΟΣΚΟΠΙΑ (MRS)', 'MRI', '{today_iso}', 1, 'Κηφισιά', 'PAM01', 'ΠΑΜΜΑΚΑΡΙΣΤΟΣ', NULL, NULL, NULL, NULL),

-- 7. Pamakristos General On-Call Auto-Assignment (Ward Pamakristos)
(1006, 5005, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 05', 22140, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ', 'CT', '{today_iso}', 1, 'Κηφισιά', 'PAM01', 'ΠΑΜΜΑΚΑΡΙΣΤΟΣ', NULL, NULL, NULL, NULL),

-- 8. Constraint Comment Exclusion "ΟΧΙ ΔΙΑΓΝΩΣΤΗΣ Α" (Rule Engine Exclusion Demo)
(1007, 5006, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 06', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '{today_iso}', 1, 'Κηφισιά', 'DOC104', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Δ', NULL, 'ΠΡΟΣΟΧΗ: ΟΧΙ ΔΙΑΓΝΩΣΤΗΣ Α', NULL, NULL),

-- 9. General Clinical Comment WITHOUT Diagnostician Name (Standard comment display)
(1011, 5007, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 07', 22140, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ', 'CT', '{today_iso}', 1, 'Κηφισιά', 'DOC104', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Δ', NULL, 'ΠΡΟΣΟΧΗ: ΕΠΕΙΓΟΝ - ΑΣΘΕΝΗΣ ΜΕ ΣΚΙΑΓΡΑΦΙΚΟ IV', NULL, NULL),

-- 10. General Clinical Comment WITHOUT Diagnostician Name (Comparison note)
(1012, 5008, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 08', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '{today_iso}', 2, 'Αμπελόκηποι', 'DOC103', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Γ', NULL, 'ΣΥΓΚΡΙΣΗ ΜΕ ΠΡΟΗΓΟΥΜΕΝΗ ΕΞΕΤΑΣΗ ΑΠΟ 15/05/2026 - ΘΑ ΣΤΑΛΕΙ ΜΕ EMAIL', NULL, NULL),

-- 11. Patient History Match (oldpers=3 ΔΙΑΓΝΩΣΤΗΣ Γ — Skilled & Available)
(1013, 5009, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 09', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '{today_iso}', 2, 'Αμπελόκηποι', 'DOC104', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Δ', NULL, 'ΕΠΑΝΕΛΕΓΧΟΣ ΜΕΤΑ ΑΠΟ 6 ΜΗΝΕΣ', 3, 'ΔΙΑΓΝΩΣΤΗΣ Γ'),

-- 12. Patient History Match (oldpers=1 ΔΙΑΓΝΩΣΤΗΣ Α — Skilled & Available)
(1014, 5010, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 10', 22140, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ', 'CT', '{today_iso}', 1, 'Κηφισιά', 'DOC103', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Γ', NULL, 'ΕΠΑΝΕΛΕΓΧΟΣ CT ΘΩΡΑΚΑ', 1, 'ΔΙΑΓΝΩΣΤΗΣ Α'),

-- 13. Non-Exclusive Preferred Doctor Partnership (Doctor DOC102 -> Diagnostician 3 ΔΙΑΓΝΩΣΤΗΣ Γ)
(1015, 5011, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 11', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '{today_iso}', 2, 'Αμπελόκηποι', 'DOC102', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Β', NULL, NULL, NULL, NULL),

-- 14. Dynamic Lab Routing Rule (Lab 2 MRI Spine -> Diagnostician 5 ΔΙΑΓΝΩΣΤΗΣ Ε)
(1016, 5012, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 12', 22151, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ', 'MRI', '{today_iso}', 2, 'Αμπελόκηποι', 'DOC103', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Γ', NULL, NULL, NULL, NULL),

-- 15. Additional CT Abdomen
(1009, 5013, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 13', 22141, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΚΟΙΛΙΑΣ', 'CT', '{yesterday_iso}', 1, 'Κηφισιά', 'DOC103', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Γ', NULL, NULL, NULL, NULL),

-- 16. Additional MRI Brain
(1010, 5014, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 14', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '{yesterday_iso}', 2, 'Αμπελόκηποι', 'DOC104', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Δ', NULL, NULL, NULL, NULL),

-- Already Assigned / Synced Exams (Capacity & History Demo with Order Grouping)
(2001, 6001, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 15', 22140, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ', 'CT', '{today_iso}', 1, 'Κηφισιά', 'DOC103', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Γ', 1, NULL, NULL, NULL),
(2002, 6002, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 16', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '{today_iso}', 2, 'Αμπελόκηποι', 'DOC104', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Δ', 2, NULL, NULL, NULL),
(2004, 6002, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 16', 22151, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ', 'MRI', '{today_iso}', 2, 'Αμπελόκηποι', 'DOC104', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Δ', 2, NULL, NULL, NULL),
(2003, 6003, 'ΔΟΚΙΜΑΣΤΙΚΟΣ', 'ΑΣΘΕΝΗΣ 17', 22151, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ', 'MRI', '{today_iso}', 2, 'Αμπελόκηποι', 'DOC102', 'ΔΡ. ΠΑΡΑΠΕΜΠΩΝ Β', 5, NULL, NULL, NULL);

COMMIT;
"""


def seed_templates():
    print(f"Generating template files in {TEMPLATES_DIR} ...")

    # 1. Write init_mock_slis.sql & build db/templates/mock_slis.db
    slis_sql_content = build_mock_slis_sql()
    MOCK_SLIS_SQL.write_text(slis_sql_content, encoding="utf-8")
    print(f"  [OK] Wrote {MOCK_SLIS_SQL}")

    if MOCK_SLIS_DB.exists():
        try:
            MOCK_SLIS_DB.unlink()
        except PermissionError:
            pass

    con_slis = sqlite3.connect(MOCK_SLIS_DB)
    con_slis.executescript(slis_sql_content)
    con_slis.close()
    print(f"  [OK] Created & Seeded {MOCK_SLIS_DB}")

    # 2. Write init_diagflow.sql & build db/templates/diagflow.db
    diag_sql_content = build_diagflow_sql()

    if DIAGFLOW_DB.exists():
        try:
            DIAGFLOW_DB.unlink()
        except PermissionError:
            pass

    con_diag = sqlite3.connect(DIAGFLOW_DB)
    con_diag.executescript(diag_sql_content)

    # Populate exam_dictionary from mock_slis.db exam_categories
    con_slis_read = sqlite3.connect(MOCK_SLIS_DB)
    dict_rows = con_slis_read.execute("SELECT examnumcode, name, category FROM exam_categories").fetchall()
    con_slis_read.close()

    for r in dict_rows:
        con_diag.execute(
            "INSERT OR REPLACE INTO exam_dictionary (code, name, category) VALUES (?, ?, ?)",
            (str(r[0]), r[1], r[2])
        )
    con_diag.commit()

    # Dump full SQL schema + data to init_diagflow.sql
    with open(DIAGFLOW_SQL, "w", encoding="utf-8") as f:
        for line in con_diag.iterdump():
            f.write(f"{line}\n")

    con_diag.close()
    print(f"  [OK] Wrote {DIAGFLOW_SQL}")
    print(f"  [OK] Created & Seeded {DIAGFLOW_DB}")

    print("\nTemplate database generation complete!")


if __name__ == "__main__":
    seed_templates()
