-- ============================================================
-- DiagFlow — Mock Slis Database Initialisation Script
-- ============================================================
-- Compatible with: SQLite (dev) and SQL Server (production)
-- Run order: 1) this file  2) seed_mock_db.py (populates data)
--
-- Tables:
--   slis_exams       — mirrors the #TMP_LIST result set from Slis
--   exam_categories  — lookup: EXAMNUMCODE → category (CT/MRI/MRA)
-- ============================================================


-- ------------------------------------------------------------
--  exam_categories
--  Populated from exam_codes.xlsx
--  KATEGORYID mapping:  18 → CT  |  22 → MRI  |  21 → MRA
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS exam_categories (
    examnumcode   INTEGER PRIMARY KEY,  -- Exam type code (matches slis_exams.examnumcode)
    name          TEXT    NOT NULL,     -- Full exam name from Slis catalogue
    category      TEXT    NOT NULL      -- 'CT' | 'MRI' | 'MRA'
);


-- ------------------------------------------------------------
--  slis_exams
--  One row per exam order (visit can contain multiple exams).
--  Column names preserved exactly as they come from the Slis
--  stored procedure / #TMP_LIST temp table so that mapping to
--  the real DB later requires only a connection-string change.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS slis_exams (

    -- ── "OLD" fields: last time the same exam type was done ──
    oldexam         INTEGER,        -- Last Exam Type ID for same examnumcode
    oldvisit        INTEGER,        -- Last Visit ID (0 = never done before)
    oldorder        TEXT,           -- Last Visit Date (ISO-8601 in SQLite)
    oldpers         INTEGER,        -- Diagnostician ID from last same-type visit
    olddiagnostis   TEXT,           -- Diagnostician name from last same-type visit

    -- ── Visit identifiers ──
    aa              INTEGER,        -- Sequential number
    extracode       INTEGER,        -- Order code (NOT unique per exam — one order can have many exams)
    visitid         INTEGER,        -- Visit ID
    demogid         INTEGER,        -- Patient's demographic/ID number

    -- ── Patient ──
    fname           TEXT,           -- Patient first name
    lname           TEXT,           -- Patient last name

    -- ── Exam type ──
    examid          INTEGER,        -- Omittable internal ID
    examnumcode     INTEGER,        -- Exam type code (FK → exam_categories)
    examname        TEXT,           -- Full exam name from Slis

    -- ── Visit logistics ──
    visitdate       TEXT,           -- Visit/order date (ISO-8601)
    labcodeid       INTEGER,        -- Lab numeric ID
    laboratoryname  TEXT,           -- Lab display name (e.g. 'ΑΝΩ ΠΑΤΗΣΙΑ')

    -- ── Issuing doctor ──
    wardid          INTEGER,        -- Omittable
    wcode           TEXT,           -- Issuing doctor ID
    wname           TEXT,           -- Issuing doctor full name

    -- ── Assignment ──
    diagnostis      INTEGER,        -- Assigned diagnostician ID (NULL = unassigned)
    personelid      INTEGER,        -- Same as diagnostis (omittable)
    code            TEXT,           -- Diagnostician surname/code
    name            TEXT,           -- Diagnostician full name (omittable duplicate)

    -- ── Notes ──
    -- Format: "free text *  * " — three fields joined by ' * '
    -- Empty/null is stored as ' *  * ' (two spaces between asterisks)
    notes           TEXT,

    -- ── Unique exam instance (TRUE PRIMARY KEY) ──
    -- One order (extracode) can contain multiple exams; exammoreid
    -- is the globally-unique ID for each individual exam instance.
    exammoreid      INTEGER PRIMARY KEY,

    -- ── Category (derived from exam_categories, not from xlsx CATEGORY column) ──
    -- 'CT' | 'MRI' | 'MRA'
    category        TEXT,

    -- ── Slis sync tracking ──
    -- NULL  = exam is assigned locally but NOT yet pushed to the real Slis DB
    -- value = ISO-8601 timestamp of when the Slis update was confirmed
    --         (exam will be removed from the app DB on the next pull cycle)
    slis_synced_at  TEXT DEFAULT NULL,

    FOREIGN KEY (examnumcode) REFERENCES exam_categories (examnumcode)
);

-- Index to speed up the most common queries
CREATE INDEX IF NOT EXISTS idx_slis_exams_diagnostis  ON slis_exams (diagnostis);
CREATE INDEX IF NOT EXISTS idx_slis_exams_visitdate    ON slis_exams (visitdate);
CREATE INDEX IF NOT EXISTS idx_slis_exams_extracode    ON slis_exams (extracode);  -- order ID lookup
CREATE INDEX IF NOT EXISTS idx_slis_exams_examnumcode  ON slis_exams (examnumcode);
