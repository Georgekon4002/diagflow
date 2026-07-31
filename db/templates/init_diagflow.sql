-- DiagFlow Configuration Database Initialization & Mock Template Data Script
BEGIN TRANSACTION;

-- Schema Definition
CREATE TABLE IF NOT EXISTS local_assignments (
    exammoreid          INTEGER PRIMARY KEY,
    diagnostician_id    INTEGER NOT NULL,
    diagnostician_name  TEXT    NOT NULL,
    assigned_at         TEXT    NOT NULL,
    is_auto             INTEGER NOT NULL DEFAULT 0,
    rule_desc           TEXT
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
(1, 'ΑΛΕΞΙΟΥ ΑΛΕΞΑΝΔΡΟΣ', 1, 1, 1, 15, 15, 15, 15, 15, 0, 0, 1),
(2, 'ΒΑΡΔΑΣ ΒΑΣΙΛΕΙΟΣ', 1, 1, 1, 15, 15, 15, 15, 15, 0, 0, 1),
(3, 'ΓΕΩΡΓΙΑΔΟΥ ΓΕΩΡΓΙΑ', 1, 1, 1, 15, 15, 15, 15, 15, 0, 0, 2),
(4, 'ΔΗΜΟΥ ΔΗΜΗΤΡΙΟΣ', 1, 1, 0, 12, 12, 12, 12, 12, 0, 0, 1),
(5, 'ΕΥΑΓΓΕΛΑΤΟΣ ΕΥΑΓΓΕΛΟΣ', 1, 0, 1, 12, 12, 12, 12, 12, 0, 0, 2),
(6, 'ΖΑΧΑΡΗ ΖΩΗ', 1, 1, 1, 15, 15, 15, 15, 15, 0, 0, 1);

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
('DOC101', 'ΔΡ. ΚΩΝΣΤΑΝΤΙΝΟΥ ΜΙΧΑΗΛ'),
('DOC102', 'ΔΡ. ΘΕΟΔΩΡΟΥ ΣΟΦΙΑ'),
('DOC103', 'ΔΡ. ΑΝΤΩΝΙΟΥ ΑΝΔΡΕΑΣ'),
('DOC104', 'ΔΡ. ΝΙΚΟΛΑΟΥ ΕΛΕΝΗ');

-- Partnerships (Exclusive & Preferred)
INSERT INTO partnerships (issuing_doctor_id, issuing_doctor_name, preferred_diagnostician_id, priority, exclusive, is_active) VALUES
('DOC101', 'ΔΡ. ΚΩΝΣΤΑΝΤΙΝΟΥ ΜΙΧΑΗΛ', 1, 1, 1, 1),
('DOC102', 'ΔΡ. ΘΕΟΔΩΡΟΥ ΣΟΦΙΑ', 3, 1, 0, 1);

-- Weekly Pamakristos Schedule (Weekdays 0..6)
INSERT INTO pamakristos_schedule (weekday, diagnostician_id) VALUES
(0, 3), -- Δευτέρα: ΓΕΩΡΓΙΑΔΟΥ ΓΕΩΡΓΙΑ
(1, 4), -- Τρίτη: ΔΗΜΟΥ ΔΗΜΗΤΡΙΟΣ
(2, 5), -- Τετάρτη: ΕΥΑΓΓΕΛΑΤΟΣ ΕΥΑΓΓΕΛΟΣ
(3, 6), -- Πέμπτη: ΖΑΧΑΡΗ ΖΩΗ
(4, 2), -- Παρασκευή: ΒΑΡΔΑΣ ΒΑΣΙΛΕΙΟΣ
(5, 1), -- Σάββατο: ΑΛΕΞΙΟΥ ΑΛΕΞΑΝΔΡΟΣ
(6, 3); -- Κυριακή: ΓΕΩΡΓΙΑΔΟΥ ΓΕΩΡΓΙΑ

-- Availability Records
INSERT INTO availability (diagnostician_id, date, status, is_pamakristos_oncall, notes) VALUES
(1, '2026-07-31', 'available', 0, NULL),
(2, '2026-07-31', 'available', 1, 'Εφημερία Παμμακάριστος'),
(3, '2026-07-31', 'available', 0, NULL),
(4, '2026-07-31', 'absent', 0, 'Άδεια'),
(5, '2026-07-31', 'available', 0, NULL),
(6, '2026-07-31', 'available', 0, NULL);

-- Exam Routing Rules
INSERT INTO exam_routing_rules (lab_id, is_pamakristos, exam_codes, diagnostician_id, description, issuing_doctor_id, issuing_doctor_name, is_active) VALUES
(NULL, 1, '22705', 3, 'Παμμακάριστος - Μαγνητική Φασματοσκοπία σε Γεωργιάδου', NULL, NULL, 1),
(2, 0, '22151', 5, 'MRI Σπονδυλικής Αμπελοκήπων σε Ευαγγελάτο', NULL, NULL, 1);

-- Exclusive Lab Rules
INSERT INTO exclusive_lab_rules (diagnostician_id, lab_id, lab_name, is_active) VALUES
(5, 2, 'Αμπελόκηποι', 1);

-- Modality Quotas
INSERT INTO modality_quotas (diagnostician_id, modality, max_count, is_active) VALUES
(4, 'CT', 8, 1);

-- System Settings (Scoring Weights)
INSERT INTO system_settings (key, value) VALUES
('w_capacity', '0.20'),
('w_fairness', '0.20'),
('w_speed', '0.15'),
('w_partnership', '0.10'),
('w_pamakristos', '0.10');

-- Admin Users (Admin & IT Support)
INSERT INTO admin_users (username, password_hash, role, is_active) VALUES
('admin', '$2b$12$0qxEPV2WtZ00AhsmOgAbJOQuiessOk/m5jq4x55CB/c680fNiW13i', 'admin', 1),
('it_support', '$2b$12$6klwZqROtRrIi2RwZgIwKuaGpapOHqUFCQJfWsR1rSLG40X31RnPG', 'it_support', 1);

COMMIT;
