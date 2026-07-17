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
    aa              INTEGER,        -- Sequential number (omittable)
    extracode       INTEGER PRIMARY KEY,  -- Unique order code shown to secretariat
    visitid         INTEGER,        -- Visit ID (omittable; extracode is the key)
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

    -- ── Unique exam instance ──
    exammoreid      INTEGER,        -- Globally-unique exam instance ID

    -- ── Category (derived from exam_categories, not from xlsx CATEGORY column) ──
    -- 'CT' | 'MRI' | 'MRA'
    category        TEXT,

    FOREIGN KEY (examnumcode) REFERENCES exam_categories (examnumcode)
);

-- Index to speed up the most common query (pending = diagnostis IS NULL)
CREATE INDEX IF NOT EXISTS idx_slis_exams_diagnostis ON slis_exams (diagnostis);
CREATE INDEX IF NOT EXISTS idx_slis_exams_visitdate   ON slis_exams (visitdate);
CREATE INDEX IF NOT EXISTS idx_slis_exams_examnumcode ON slis_exams (examnumcode);
