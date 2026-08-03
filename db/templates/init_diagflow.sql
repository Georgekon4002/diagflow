BEGIN TRANSACTION;
CREATE TABLE admin_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'admin',
    is_active     INTEGER NOT NULL DEFAULT 1
);
INSERT INTO "admin_users" VALUES(1,'admin','$2b$12$SsLUct5RLmZJBwDQDBQ7xusD4CrjabY8EX9q.gKZjZbch5HZ2Ovly','admin',1);
INSERT INTO "admin_users" VALUES(2,'it_support','$2b$12$dk9gH/KU49ZmcFDnQo8bl.D7q8/wcHT.icrlAFlJ8Kd9E3AjItrFa','it_support',1);
CREATE TABLE assignment_log (
    exammoreid        INTEGER PRIMARY KEY,
    diagnostician_id  INTEGER NOT NULL,
    assigned_at       TEXT NOT NULL,
    modality          TEXT,
    extracode         TEXT
);
CREATE TABLE availability (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnostician_id        INTEGER NOT NULL REFERENCES diagnosticians(id) ON DELETE CASCADE,
    date                    TEXT    NOT NULL,
    status                  TEXT    NOT NULL DEFAULT 'available',
    is_pamakristos_oncall   INTEGER NOT NULL DEFAULT 0,
    notes                   TEXT,
    UNIQUE(diagnostician_id, date)
);
INSERT INTO "availability" VALUES(1,1,'2026-08-03','available',0,NULL);
INSERT INTO "availability" VALUES(2,2,'2026-08-03','available',1,'Εφημερία Παμμακάριστος');
INSERT INTO "availability" VALUES(3,3,'2026-08-03','available',0,NULL);
INSERT INTO "availability" VALUES(4,4,'2026-08-03','absent',0,'Άδεια');
INSERT INTO "availability" VALUES(5,5,'2026-08-03','available',0,NULL);
INSERT INTO "availability" VALUES(6,6,'2026-08-03','available',0,NULL);
CREATE TABLE diagnostician_skills (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnostician_id  INTEGER NOT NULL REFERENCES diagnosticians(id) ON DELETE CASCADE,
    exam_code         TEXT    NOT NULL,
    is_preferred      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(diagnostician_id, exam_code)
);
INSERT INTO "diagnostician_skills" VALUES(1,1,'22140',1);
INSERT INTO "diagnostician_skills" VALUES(2,1,'22141',1);
INSERT INTO "diagnostician_skills" VALUES(3,1,'22150',0);
INSERT INTO "diagnostician_skills" VALUES(4,2,'22140',0);
INSERT INTO "diagnostician_skills" VALUES(5,2,'22150',1);
INSERT INTO "diagnostician_skills" VALUES(6,2,'22151',1);
INSERT INTO "diagnostician_skills" VALUES(7,3,'22705',1);
INSERT INTO "diagnostician_skills" VALUES(8,3,'22150',1);
INSERT INTO "diagnostician_skills" VALUES(9,3,'22141',0);
INSERT INTO "diagnostician_skills" VALUES(10,4,'22140',1);
INSERT INTO "diagnostician_skills" VALUES(11,4,'22141',1);
INSERT INTO "diagnostician_skills" VALUES(12,5,'22150',1);
INSERT INTO "diagnostician_skills" VALUES(13,5,'22151',1);
INSERT INTO "diagnostician_skills" VALUES(14,6,'22140',0);
INSERT INTO "diagnostician_skills" VALUES(15,6,'22150',0);
CREATE TABLE diagnosticians (
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
INSERT INTO "diagnosticians" VALUES(1,'ΑΛΕΞΙΟΥ ΑΛΕΞΑΝΔΡΟΣ',1,1,1,15,15,15,15,15,0,0,1,'2026-08-03 13:37:59');
INSERT INTO "diagnosticians" VALUES(2,'ΒΑΡΔΑΣ ΒΑΣΙΛΕΙΟΣ',1,1,1,15,15,15,15,15,0,0,1,'2026-08-03 13:37:59');
INSERT INTO "diagnosticians" VALUES(3,'ΓΕΩΡΓΙΑΔΟΥ ΓΕΩΡΓΙΑ',1,1,1,15,15,15,15,15,0,0,2,'2026-08-03 13:37:59');
INSERT INTO "diagnosticians" VALUES(4,'ΔΗΜΟΥ ΔΗΜΗΤΡΙΟΣ',1,1,0,12,12,12,12,12,0,0,1,'2026-08-03 13:37:59');
INSERT INTO "diagnosticians" VALUES(5,'ΕΥΑΓΓΕΛΑΤΟΣ ΕΥΑΓΓΕΛΟΣ',1,0,1,12,12,12,12,12,0,0,2,'2026-08-03 13:37:59');
INSERT INTO "diagnosticians" VALUES(6,'ΖΑΧΑΡΗ ΖΩΗ',1,1,1,15,15,15,15,15,0,0,1,'2026-08-03 13:37:59');
CREATE TABLE doctors (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL
);
INSERT INTO "doctors" VALUES('DOC101','ΔΡ. ΚΩΝΣΤΑΝΤΙΝΟΥ ΜΙΧΑΗΛ');
INSERT INTO "doctors" VALUES('DOC102','ΔΡ. ΘΕΟΔΩΡΟΥ ΣΟΦΙΑ');
INSERT INTO "doctors" VALUES('DOC103','ΔΡ. ΑΝΤΩΝΙΟΥ ΑΝΔΡΕΑΣ');
INSERT INTO "doctors" VALUES('DOC104','ΔΡ. ΝΙΚΟΛΑΟΥ ΕΛΕΝΗ');
CREATE TABLE exam_dictionary (
    code     TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    category TEXT
);
INSERT INTO "exam_dictionary" VALUES('22140','ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ','CT');
INSERT INTO "exam_dictionary" VALUES('22141','ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΚΟΙΛΙΑΣ','CT');
INSERT INTO "exam_dictionary" VALUES('22150','ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ','MRI');
INSERT INTO "exam_dictionary" VALUES('22151','ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ','MRI');
INSERT INTO "exam_dictionary" VALUES('22705','ΜΑΓΝΗΤΙΚΗ ΦΑΣΜΑΤΟΣΚΟΠΙΑ (MRS)','MRI');
CREATE TABLE exam_routing_rules (
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
INSERT INTO "exam_routing_rules" VALUES(1,NULL,1,'22705',3,'Παμμακάριστος - Μαγνητική Φασματοσκοπία σε Γεωργιάδου',NULL,NULL,1);
INSERT INTO "exam_routing_rules" VALUES(2,2,0,'22151',5,'MRI Σπονδυλικής Αμπελοκήπων σε Ευαγγελάτο',NULL,NULL,1);
CREATE TABLE exclusive_lab_rules (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnostician_id  INTEGER NOT NULL,
    lab_id            INTEGER NOT NULL,
    lab_name          TEXT,
    is_active         INTEGER NOT NULL DEFAULT 1
);
INSERT INTO "exclusive_lab_rules" VALUES(1,5,2,'Αμπελόκηποι',1);
CREATE TABLE local_assignments (
    exammoreid          INTEGER PRIMARY KEY,
    diagnostician_id    INTEGER NOT NULL,
    diagnostician_name  TEXT    NOT NULL,
    assigned_at         TEXT    NOT NULL,
    is_auto             INTEGER NOT NULL DEFAULT 0,
    rule_desc           TEXT
);
CREATE TABLE modality_quotas (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnostician_id  INTEGER NOT NULL,
    modality          TEXT NOT NULL,
    max_count         INTEGER NOT NULL,
    is_active         INTEGER NOT NULL DEFAULT 1
);
INSERT INTO "modality_quotas" VALUES(1,4,'CT',8,1);
CREATE TABLE pamakristos_schedule (
    weekday          INTEGER PRIMARY KEY,
    diagnostician_id INTEGER NOT NULL REFERENCES diagnosticians(id)
);
INSERT INTO "pamakristos_schedule" VALUES(0,3);
INSERT INTO "pamakristos_schedule" VALUES(1,4);
INSERT INTO "pamakristos_schedule" VALUES(2,5);
INSERT INTO "pamakristos_schedule" VALUES(3,6);
INSERT INTO "pamakristos_schedule" VALUES(4,2);
CREATE TABLE partnerships (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    issuing_doctor_id           TEXT    NOT NULL,
    issuing_doctor_name         TEXT    NOT NULL,
    preferred_diagnostician_id  INTEGER NOT NULL REFERENCES diagnosticians(id) ON DELETE CASCADE,
    priority                    INTEGER NOT NULL DEFAULT 1,
    exclusive                   INTEGER NOT NULL DEFAULT 0,
    is_active                   INTEGER NOT NULL DEFAULT 1
);
INSERT INTO "partnerships" VALUES(1,'DOC101','ΔΡ. ΚΩΝΣΤΑΝΤΙΝΟΥ ΜΙΧΑΗΛ',1,1,1,1);
INSERT INTO "partnerships" VALUES(2,'DOC102','ΔΡ. ΘΕΟΔΩΡΟΥ ΣΟΦΙΑ',3,1,0,1);
CREATE TABLE system_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO "system_settings" VALUES('pts_partnership','0.20');
INSERT INTO "system_settings" VALUES('pts_history','0.35');
INSERT INTO "system_settings" VALUES('pts_skills_pref','0.20');
INSERT INTO "system_settings" VALUES('pts_skills_neut','0.10');
INSERT INTO "system_settings" VALUES('pts_skills_none','0.00');
INSERT INTO "system_settings" VALUES('pts_lab_pref','0.15');
INSERT INTO "system_settings" VALUES('pts_lab_neut','0.10');
INSERT INTO "system_settings" VALUES('pts_lab_other','0.02');
INSERT INTO "system_settings" VALUES('pts_capacity','0.10');
CREATE INDEX idx_skills_diag    ON diagnostician_skills(diagnostician_id);
CREATE INDEX idx_skills_code    ON diagnostician_skills(exam_code);
CREATE INDEX idx_avail_diag     ON availability(diagnostician_id);
CREATE INDEX idx_avail_date     ON availability(date);
CREATE INDEX idx_partner_doctor ON partnerships(issuing_doctor_id);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('diagnostician_skills',15);
INSERT INTO "sqlite_sequence" VALUES('partnerships',2);
INSERT INTO "sqlite_sequence" VALUES('availability',6);
INSERT INTO "sqlite_sequence" VALUES('exam_routing_rules',2);
INSERT INTO "sqlite_sequence" VALUES('exclusive_lab_rules',1);
INSERT INTO "sqlite_sequence" VALUES('modality_quotas',1);
INSERT INTO "sqlite_sequence" VALUES('admin_users',2);
COMMIT;
