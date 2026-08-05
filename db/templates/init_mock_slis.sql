-- Mock SLIS Database Initialization & Template Data Script
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
(1, 'ΑΛΕΞΙΟΥ ΑΛΕΞΑΝΔΡΟΣ', 15, 1, 1, 1, 15, 1, 15, 1, 15, 1, 15, 1, 15, 0, 0, 1, 1, 0),
(2, 'ΒΑΡΔΑΣ ΒΑΣΙΛΕΙΟΣ', 15, 1, 1, 1, 15, 1, 15, 1, 15, 1, 15, 1, 15, 0, 0, 1, 1, 1),
(3, 'ΓΕΩΡΓΙΑΔΟΥ ΓΕΩΡΓΙΑ', 15, 1, 1, 1, 15, 1, 15, 1, 15, 1, 15, 1, 15, 0, 0, 2, 1, 0),
(4, 'ΔΗΜΟΥ ΔΗΜΗΤΡΙΟΣ', 12, 0, 1, 1, 12, 1, 12, 1, 12, 1, 12, 1, 12, 0, 0, 1, 1, 0),
(5, 'ΕΥΑΓΓΕΛΑΤΟΣ ΕΥΑΓΓΕΛΟΣ', 12, 1, 0, 1, 12, 1, 12, 1, 12, 1, 12, 1, 12, 0, 0, 2, 1, 0),
(6, 'ΖΑΧΑΡΗ ΖΩΗ', 15, 1, 1, 1, 15, 1, 15, 1, 15, 1, 15, 1, 15, 0, 0, 1, 1, 0);

-- Doctors (SLIS mirror)
INSERT INTO doctors (DOCTORID, CODE, DOCNAME, SPECIALID, RELATEDDOC, ISENABLED) VALUES
(101, 101, 'ΔΡ. ΚΩΝΣΤΑΝΤΙΝΟΥ ΜΙΧΑΗΛ', 1, NULL, 1),
(102, 102, 'ΔΡ. ΘΕΟΔΩΡΟΥ ΣΟΦΙΑ', 2, NULL, 1),
(103, 103, 'ΔΡ. ΑΝΤΩΝΙΟΥ ΑΝΔΡΕΑΣ', 3, NULL, 1),
(104, 104, 'ΔΡ. ΝΙΚΟΛΑΟΥ ΕΛΕΝΗ', 4, NULL, 1);

-- SLIS Exams (Comprehensive Demo Dataset covering all Use Cases)
INSERT INTO slis_exams (exammoreid, extracode, fname, lname, examnumcode, examname, category, visitdate, labcodeid, laboratoryname, wcode, wname, diagnostis, notes, oldpers, olddiagnostis) VALUES
-- 1. Unassigned CT Chest (Order 5001 — Part 1)
(1001, 5001, 'ΜΑΡΙΑ', 'ΑΝΤΩΝΙΟΥ', 22140, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ', 'CT', '2026-08-05', 1, 'Κηφισιά', 'DOC104', 'ΔΡ. ΝΙΚΟΛΑΟΥ ΕΛΕΝΗ', NULL, NULL, NULL, NULL),

-- 2. Unassigned CT Abdomen (Order 5001 — Part 2: Shared Order ID demo)
(1003, 5001, 'ΜΑΡΙΑ', 'ΑΝΤΩΝΙΟΥ', 22141, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΚΟΙΛΙΑΣ', 'CT', '2026-08-05', 1, 'Κηφισιά', 'DOC104', 'ΔΡ. ΝΙΚΟΛΑΟΥ ΕΛΕΝΗ', NULL, NULL, NULL, NULL),

-- 3. Unassigned MRI Brain (Order 5002 — Part 1)
(1002, 5002, 'ΓΕΩΡΓΙΟΣ', 'ΚΩΝΣΤΑΝΤΙΝΟΥ', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '2026-08-05', 2, 'Αμπελόκηποι', 'DOC104', 'ΔΡ. ΝΙΚΟΛΑΟΥ ΕΛΕΝΗ', NULL, NULL, NULL, NULL),

-- 4. Unassigned MRI Spine (Order 5002 — Part 2: Shared Order ID demo)
(1008, 5002, 'ΓΕΩΡΓΙΟΣ', 'ΚΩΝΣΤΑΝΤΙΝΟΥ', 22151, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ', 'MRI', '2026-08-05', 2, 'Αμπελόκηποι', 'DOC102', 'ΔΡ. ΘΕΟΔΩΡΟΥ ΣΟΦΙΑ', NULL, 'ΠΡΟΤΙΜΗΣΗ: ΓΕΩΡΓΙΑΔΟΥ', NULL, NULL),

-- 5. Exclusive Partnership Auto-Assignment (Doctor DOC101 -> Diagnostician 1 Αλεξίου)
(1004, 5003, 'ΙΩΑΝΝΗΣ', 'ΝΙΚΟΛΑΟΥ', 22140, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ', 'CT', '2026-08-05', 1, 'Κηφισιά', 'DOC101', 'ΔΡ. ΚΩΝΣΤΑΝΤΙΝΟΥ ΜΙΧΑΗΛ', NULL, NULL, NULL, NULL),

-- 6. Dynamic Routing Rule Auto-Assignment (22705 Pamakristos -> Diagnostician 3 Γεωργιάδου)
(1005, 5004, 'ΕΛΕΝΗ', 'ΒΑΣΙΛΕΙΟΥ', 22705, 'ΜΑΓΝΗΤΙΚΗ ΦΑΣΜΑΤΟΣΚΟΠΙΑ (MRS)', 'MRI', '2026-08-05', 1, 'Κηφισιά', 'PAM01', 'ΠΑΜΜΑΚΑΡΙΣΤΟΣ', NULL, NULL, NULL, NULL),

-- 7. Pamakristos General On-Call Auto-Assignment (Ward Pamakristos)
(1006, 5005, 'ΧΡΗΣΤΟΣ', 'ΓΕΩΡΓΙΑΔΗΣ', 22140, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ', 'CT', '2026-08-05', 1, 'Κηφισιά', 'PAM01', 'ΠΑΜΜΑΚΑΡΙΣΤΟΣ', NULL, NULL, NULL, NULL),

-- 8. Constraint Comment Exclusion "ΟΧΙ ΑΛΕΞΙΟΥ" (Rule Engine Exclusion Demo)
(1007, 5006, 'ΑΝΑΣΤΑΣΙΑ', 'ΣΤΑΜΑΤΙΟΥ', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '2026-08-05', 1, 'Κηφισιά', 'DOC104', 'ΔΡ. ΝΙΚΟΛΑΟΥ ΕΛΕΝΗ', NULL, 'ΠΡΟΣΟΧΗ: ΟΧΙ ΑΛΕΞΙΟΥ', NULL, NULL),

-- 9. General Clinical Comment WITHOUT Diagnostician Name (Standard comment display)
(1011, 5007, 'ΕΛΕΝΗ', 'ΚΑΡΑΛΗ', 22140, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ', 'CT', '2026-08-05', 1, 'Κηφισιά', 'DOC104', 'ΔΡ. ΝΙΚΟΛΑΟΥ ΕΛΕΝΗ', NULL, 'ΠΡΟΣΟΧΗ: ΕΠΕΙΓΟΝ - ΑΣΘΕΝΗΣ ΜΕ ΣΚΙΑΓΡΑΦΙΚΟ IV', NULL, NULL),

-- 10. General Clinical Comment WITHOUT Diagnostician Name (Comparison note)
(1012, 5008, 'ΜΙΧΑΗΛ', 'ΠΑΠΑΔΑΚΗΣ', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '2026-08-05', 2, 'Αμπελόκηποι', 'DOC103', 'ΔΡ. ΑΝΤΩΝΙΟΥ ΑΝΔΡΕΑΣ', NULL, 'ΣΥΓΚΡΙΣΗ ΜΕ ΠΡΟΗΓΟΥΜΕΝΗ ΕΞΕΤΑΣΗ ΑΠΟ 15/05/2026 - ΘΑ ΣΤΑΛΕΙ ΜΕ EMAIL', NULL, NULL),

-- 11. Patient History Match (oldpers=3 ΓΕΩΡΓΙΑΔΟΥ ΓΕΩΡΓΙΑ — Skilled & Available)
(1013, 5009, 'ΔΗΜΗΤΡΑ', 'ΣΠΑΝΟΥ', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '2026-08-05', 2, 'Αμπελόκηποι', 'DOC104', 'ΔΡ. ΝΙΚΟΛΑΟΥ ΕΛΕΝΗ', NULL, 'ΕΠΑΝΕΛΕΓΧΟΣ ΜΕΤΑ ΑΠΟ 6 ΜΗΝΕΣ', 3, 'ΓΕΩΡΓΙΑΔΟΥ'),

-- 12. Patient History Match (oldpers=1 ΑΛΕΞΙΟΥ ΑΛΕΞΑΝΔΡΟΣ — Skilled & Available)
(1014, 5010, 'ΑΘΑΝΑΣΙΟΣ', 'ΦΩΤΙΟΥ', 22140, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ', 'CT', '2026-08-05', 1, 'Κηφισιά', 'DOC103', 'ΔΡ. ΑΝΤΩΝΙΟΥ ΑΝΔΡΕΑΣ', NULL, 'ΕΠΑΝΕΛΕΓΧΟΣ CT ΘΩΡΑΚΑ', 1, 'ΑΛΕΞΙΟΥ'),

-- 13. Non-Exclusive Preferred Doctor Partnership (Doctor DOC102 -> Diagnostician 3 Γεωργιάδου)
(1015, 5011, 'ΣΟΦΙΑ', 'ΚΩΝΣΤΑΝΤΙΝΙΔΟΥ', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '2026-08-05', 2, 'Αμπελόκηποι', 'DOC102', 'ΔΡ. ΘΕΟΔΩΡΟΥ ΣΟΦΙΑ', NULL, NULL, NULL, NULL),

-- 14. Dynamic Lab Routing Rule (Lab 2 MRI Spine -> Diagnostician 5 Ευαγγελάτος)
(1016, 5012, 'ΚΩΝΣΤΑΝΤΙΝΟΣ', 'ΡΑΠΤΗΣ', 22151, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ', 'MRI', '2026-08-05', 2, 'Αμπελόκηποι', 'DOC103', 'ΔΡ. ΑΝΤΩΝΙΟΥ ΑΝΔΡΕΑΣ', NULL, NULL, NULL, NULL),

-- 15. Additional CT Abdomen
(1009, 5013, 'ΑΙΚΑΤΕΡΙΝΗ', 'ΜΑΚΡΗ', 22141, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΚΟΙΛΙΑΣ', 'CT', '2026-08-04', 1, 'Κηφισιά', 'DOC103', 'ΔΡ. ΑΝΤΩΝΙΟΥ ΑΝΔΡΕΑΣ', NULL, NULL, NULL, NULL),

-- 16. Additional MRI Brain
(1010, 5014, 'ΣΠΥΡΙΔΩΝ', 'ΑΛΕΞΙΟΥ', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '2026-08-04', 2, 'Αμπελόκηποι', 'DOC104', 'ΔΡ. ΝΙΚΟΛΑΟΥ ΕΛΕΝΗ', NULL, NULL, NULL, NULL),

-- Already Assigned / Synced Exams (Capacity & History Demo with Order Grouping)
(2001, 6001, 'ΕΥΑΓΓΕΛΙΑ', 'ΔΗΜΟΥ', 22140, 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΘΩΡΑΚΑ', 'CT', '2026-08-05', 1, 'Κηφισιά', 'DOC103', 'ΔΡ. ΑΝΤΩΝΙΟΥ ΑΝΔΡΕΑΣ', 1, NULL, NULL, NULL),
(2002, 6002, 'ΝΙΚΟΛΑΟΣ', 'ΚΑΡΑΓΙΑΝΝΗΣ', 22150, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΕΓΚΕΦΑΛΟΥ', 'MRI', '2026-08-05', 2, 'Αμπελόκηποι', 'DOC104', 'ΔΡ. ΝΙΚΟΛΑΟΥ ΕΛΕΝΗ', 2, NULL, NULL, NULL),
(2004, 6002, 'ΝΙΚΟΛΑΟΣ', 'ΚΑΡΑΓΙΑΝΝΗΣ', 22151, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ', 'MRI', '2026-08-05', 2, 'Αμπελόκηποι', 'DOC104', 'ΔΡ. ΝΙΚΟΛΑΟΥ ΕΛΕΝΗ', 2, NULL, NULL, NULL),
(2003, 6003, 'ΜΑΡΙΝΑ', 'ΡΑΠΤΗ', 22151, 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ ΣΠΟΝΔΥΛΙΚΗΣ ΣΤΗΛΗΣ', 'MRI', '2026-08-05', 2, 'Αμπελόκηποι', 'DOC102', 'ΔΡ. ΘΕΟΔΩΡΟΥ ΣΟΦΙΑ', 5, NULL, NULL, NULL);

COMMIT;
