-- =============================================================================
-- DiagFlow — Central Database Schema Creation Script (MSSQL / T-SQL)
-- =============================================================================
-- This script creates all DiagFlow configuration and operational tables
-- in the central database (e.g. SlisDB) with the "df_" prefix.
--
-- Tables created:
--   1.  df_admin_users             — Admin & IT support credentials
--   2.  df_diagnosticians          — Diagnostician master list & daily quotas
--   3.  df_diagnostician_skills     — Exam codes & specialty preferences per diagnostician
--   4.  df_availability            — Daily availability, leaves, and on-call markers
--   5.  df_doctors                 — Issuing / ward doctors
--   6.  df_partnerships            — Doctor-diagnostician preference & exclusive partnerships
--   7.  df_exam_dictionary         — Exam code catalogue & modality mapping
--   8.  df_exam_routing_rules      — Dynamic rule-based assignment routing
--   9.  df_exclusive_lab_rules     — Hard exclusive laboratory routing rules
--   10. df_modality_quotas         — Daily CT/MRI per-diagnostician sub-caps
--   11. df_pamakristos_schedule    — Weekly default Παμμακάριστος on-call schedule
--   12. df_system_settings         — Scoring engine weights and tuneable thresholds
--   13. df_assignment_log          — Audit trail of pushed exam assignments
--   14. df_local_assignments       — Staged/pending assignments shared across all PCs
-- =============================================================================

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

-- -----------------------------------------------------------------------------
-- 1. df_admin_users
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_admin_users')
BEGIN
    CREATE TABLE df_admin_users (
        id            INT IDENTITY(1,1) PRIMARY KEY,
        username      NVARCHAR(100) NOT NULL UNIQUE,
        password_hash NVARCHAR(255) NOT NULL,
        role          NVARCHAR(50)  NOT NULL DEFAULT 'admin',
        is_active     BIT           NOT NULL DEFAULT 1
    );
    PRINT 'Created table df_admin_users';
END
GO

-- -----------------------------------------------------------------------------
-- 2. df_diagnosticians
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_diagnosticians')
BEGIN
    CREATE TABLE df_diagnosticians (
        id               INT PRIMARY KEY,              -- Matches Slis personelid
        name             NVARCHAR(200) NOT NULL,
        active           BIT           NOT NULL DEFAULT 1,
        can_ct           BIT           NOT NULL DEFAULT 0,
        can_mri          BIT           NOT NULL DEFAULT 0,
        quota_monday     INT           NOT NULL DEFAULT 15,
        quota_tuesday    INT           NOT NULL DEFAULT 15,
        quota_wednesday  INT           NOT NULL DEFAULT 15,
        quota_thursday   INT           NOT NULL DEFAULT 15,
        quota_friday     INT           NOT NULL DEFAULT 15,
        quota_saturday   INT           NOT NULL DEFAULT 0,
        quota_sunday     INT           NOT NULL DEFAULT 0,
        preferred_lab_id INT           NULL,
        created_at       DATETIME2     NOT NULL DEFAULT GETDATE()
    );
    PRINT 'Created table df_diagnosticians';
END
GO

-- -----------------------------------------------------------------------------
-- 3. df_diagnostician_skills
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_diagnostician_skills')
BEGIN
    CREATE TABLE df_diagnostician_skills (
        id                INT IDENTITY(1,1) PRIMARY KEY,
        diagnostician_id  INT           NOT NULL,
        exam_code         NVARCHAR(50)  NOT NULL,
        is_preferred      BIT           NOT NULL DEFAULT 0,
        CONSTRAINT FK_df_skills_diag FOREIGN KEY (diagnostician_id) 
            REFERENCES df_diagnosticians(id) ON DELETE CASCADE,
        CONSTRAINT UQ_df_skills_diag_code UNIQUE (diagnostician_id, exam_code)
    );
    CREATE INDEX idx_df_skills_diag ON df_diagnostician_skills(diagnostician_id);
    CREATE INDEX idx_df_skills_code ON df_diagnostician_skills(exam_code);
    PRINT 'Created table df_diagnostician_skills';
END
GO

-- -----------------------------------------------------------------------------
-- 4. df_availability
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_availability')
BEGIN
    CREATE TABLE df_availability (
        id                    INT IDENTITY(1,1) PRIMARY KEY,
        diagnostician_id      INT           NOT NULL,
        [date]                DATE          NOT NULL,
        [status]              NVARCHAR(50)  NOT NULL DEFAULT 'available',
        is_pamakristos_oncall BIT           NOT NULL DEFAULT 0,
        notes                 NVARCHAR(500) NULL,
        CONSTRAINT FK_df_avail_diag FOREIGN KEY (diagnostician_id) 
            REFERENCES df_diagnosticians(id) ON DELETE CASCADE,
        CONSTRAINT UQ_df_avail_diag_date UNIQUE (diagnostician_id, [date])
    );
    CREATE INDEX idx_df_avail_diag ON df_availability(diagnostician_id);
    CREATE INDEX idx_df_avail_date ON df_availability([date]);
    PRINT 'Created table df_availability';
END
GO

-- -----------------------------------------------------------------------------
-- 5. df_doctors
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_doctors')
BEGIN
    CREATE TABLE df_doctors (
        id   NVARCHAR(50)  PRIMARY KEY,   -- Matches Slis doctor code (wcode)
        name NVARCHAR(200) NOT NULL
    );
    PRINT 'Created table df_doctors';
END
GO

-- -----------------------------------------------------------------------------
-- 6. df_partnerships
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_partnerships')
BEGIN
    CREATE TABLE df_partnerships (
        id                         INT IDENTITY(1,1) PRIMARY KEY,
        issuing_doctor_id          NVARCHAR(50)  NOT NULL,
        issuing_doctor_name        NVARCHAR(200) NOT NULL,
        preferred_diagnostician_id INT           NOT NULL,
        priority                   INT           NOT NULL DEFAULT 1,
        exclusive                  BIT           NOT NULL DEFAULT 0,
        is_active                  BIT           NOT NULL DEFAULT 1,
        CONSTRAINT FK_df_partner_diag FOREIGN KEY (preferred_diagnostician_id) 
            REFERENCES df_diagnosticians(id) ON DELETE CASCADE
    );
    CREATE INDEX idx_df_partner_doctor ON df_partnerships(issuing_doctor_id);
    PRINT 'Created table df_partnerships';
END
GO

-- -----------------------------------------------------------------------------
-- 7. df_exam_dictionary
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_exam_dictionary')
BEGIN
    CREATE TABLE df_exam_dictionary (
        code     NVARCHAR(50)  PRIMARY KEY,
        name     NVARCHAR(200) NOT NULL,
        category NVARCHAR(50)  NULL
    );
    PRINT 'Created table df_exam_dictionary';
END
GO

-- -----------------------------------------------------------------------------
-- 8. df_exam_routing_rules
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_exam_routing_rules')
BEGIN
    CREATE TABLE df_exam_routing_rules (
        id                  INT IDENTITY(1,1) PRIMARY KEY,
        lab_id              INT            NULL,
        is_pamakristos      BIT            NOT NULL DEFAULT 0,
        exam_codes          NVARCHAR(MAX)  NOT NULL,
        diagnostician_id    INT            NOT NULL,
        description         NVARCHAR(500)  NULL,
        issuing_doctor_id   NVARCHAR(50)   NULL,
        issuing_doctor_name NVARCHAR(200)  NULL,
        is_active           BIT            NOT NULL DEFAULT 1,
        CONSTRAINT FK_df_routing_diag FOREIGN KEY (diagnostician_id) 
            REFERENCES df_diagnosticians(id)
    );
    PRINT 'Created table df_exam_routing_rules';
END
GO

-- -----------------------------------------------------------------------------
-- 9. df_exclusive_lab_rules
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_exclusive_lab_rules')
BEGIN
    CREATE TABLE df_exclusive_lab_rules (
        id               INT IDENTITY(1,1) PRIMARY KEY,
        diagnostician_id INT           NOT NULL,
        lab_id           INT           NOT NULL,
        lab_name         NVARCHAR(200) NULL,
        is_active        BIT           NOT NULL DEFAULT 1,
        CONSTRAINT FK_df_labrule_diag FOREIGN KEY (diagnostician_id) 
            REFERENCES df_diagnosticians(id)
    );
    PRINT 'Created table df_exclusive_lab_rules';
END
GO

-- -----------------------------------------------------------------------------
-- 10. df_modality_quotas
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_modality_quotas')
BEGIN
    CREATE TABLE df_modality_quotas (
        id               INT IDENTITY(1,1) PRIMARY KEY,
        diagnostician_id INT          NOT NULL,
        modality         NVARCHAR(50) NOT NULL,
        max_count        INT          NOT NULL,
        is_active        BIT          NOT NULL DEFAULT 1,
        CONSTRAINT FK_df_modquota_diag FOREIGN KEY (diagnostician_id) 
            REFERENCES df_diagnosticians(id)
    );
    PRINT 'Created table df_modality_quotas';
END
GO

-- -----------------------------------------------------------------------------
-- 11. df_pamakristos_schedule
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_pamakristos_schedule')
BEGIN
    CREATE TABLE df_pamakristos_schedule (
        weekday          INT PRIMARY KEY,  -- 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday
        diagnostician_id INT NOT NULL,
        CONSTRAINT FK_df_pamakristos_diag FOREIGN KEY (diagnostician_id) 
            REFERENCES df_diagnosticians(id)
    );
    PRINT 'Created table df_pamakristos_schedule';
END
GO

-- -----------------------------------------------------------------------------
-- 12. df_system_settings
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_system_settings')
BEGIN
    CREATE TABLE df_system_settings (
        [key]   NVARCHAR(100) PRIMARY KEY,
        [value] NVARCHAR(255) NOT NULL
    );
    PRINT 'Created table df_system_settings';
END
GO

-- -----------------------------------------------------------------------------
-- 13. df_assignment_log
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_assignment_log')
BEGIN
    CREATE TABLE df_assignment_log (
        exammoreid       INT           PRIMARY KEY,
        diagnostician_id INT           NOT NULL,
        assigned_at      NVARCHAR(50)  NOT NULL,
        modality         NVARCHAR(50)  NULL,
        extracode        NVARCHAR(100) NULL
    );
    CREATE INDEX idx_df_assignlog_diag ON df_assignment_log(diagnostician_id);
    CREATE INDEX idx_df_assignlog_date ON df_assignment_log(assigned_at);
    PRINT 'Created table df_assignment_log';
END
GO

-- -----------------------------------------------------------------------------
-- 14. df_local_assignments
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'df_local_assignments')
BEGIN
    CREATE TABLE df_local_assignments (
        exammoreid         INT           PRIMARY KEY,
        diagnostician_id   INT           NOT NULL,
        diagnostician_name NVARCHAR(200) NOT NULL,
        assigned_at        NVARCHAR(50)  NOT NULL,
        is_auto            BIT           NOT NULL DEFAULT 0,
        rule_desc          NVARCHAR(500) NULL,
        extracode          NVARCHAR(100) NULL,
        modality           NVARCHAR(50)  NULL
    );
    CREATE INDEX idx_df_localassign_diag ON df_local_assignments(diagnostician_id);
    PRINT 'Created table df_local_assignments';
END
GO

PRINT '=======================================================';
PRINT 'DiagFlow tables creation script completed successfully.';
PRINT '=======================================================';
