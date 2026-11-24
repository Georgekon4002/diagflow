SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

-- -----------------------------------------------------------------------------
-- 1. Ensure visitdate column exists on df_local_assignments & df_assignment_log
-- -----------------------------------------------------------------------------
IF EXISTS (SELECT 1 FROM sys.tables WHERE name = 'df_local_assignments')
AND NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('df_local_assignments') AND name = 'visitdate'
)
BEGIN
    ALTER TABLE df_local_assignments ADD visitdate NVARCHAR(50) NULL;
    PRINT 'Added visitdate to df_local_assignments';
END

IF EXISTS (SELECT 1 FROM sys.tables WHERE name = 'df_assignment_log')
AND NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('df_assignment_log') AND name = 'visitdate'
)
BEGIN
    ALTER TABLE df_assignment_log ADD visitdate NVARCHAR(50) NULL;
    PRINT 'Added visitdate to df_assignment_log';
END
GO

-- -----------------------------------------------------------------------------
-- 2. Add visitdate indexes for fast Dashboard and daily quota queries
-- -----------------------------------------------------------------------------
IF EXISTS (SELECT 1 FROM sys.tables WHERE name = 'df_assignment_log')
AND NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'idx_df_assignlog_visitdate' AND object_id = OBJECT_ID('df_assignment_log')
)
BEGIN
    CREATE INDEX idx_df_assignlog_visitdate ON df_assignment_log(visitdate);
    PRINT 'Created index idx_df_assignlog_visitdate';
END

IF EXISTS (SELECT 1 FROM sys.tables WHERE name = 'df_local_assignments')
AND NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'idx_df_localassign_visitdate' AND object_id = OBJECT_ID('df_local_assignments')
)
BEGIN
    CREATE INDEX idx_df_localassign_visitdate ON df_local_assignments(visitdate);
    PRINT 'Created index idx_df_localassign_visitdate';
END
GO

-- -----------------------------------------------------------------------------
-- 3. Ensure df_dismissed_auto_assignments exists (consistent INT primary key)
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'df_dismissed_auto_assignments')
BEGIN
    CREATE TABLE df_dismissed_auto_assignments (
        exammoreid   INT          PRIMARY KEY,
        dismissed_at NVARCHAR(50) NOT NULL
    );
    PRINT 'Created table df_dismissed_auto_assignments';
END
GO

-- -----------------------------------------------------------------------------
-- 4. Add ON DELETE CASCADE to foreign keys referencing df_diagnosticians(id)
--    (Prevents FK constraint failures when deleting a diagnostician)
-- -----------------------------------------------------------------------------
IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_df_routing_diag' AND delete_referential_action = 0)
BEGIN
    ALTER TABLE df_exam_routing_rules DROP CONSTRAINT FK_df_routing_diag;
    ALTER TABLE df_exam_routing_rules
        ADD CONSTRAINT FK_df_routing_diag FOREIGN KEY (diagnostician_id)
        REFERENCES df_diagnosticians(id) ON DELETE CASCADE;
    PRINT 'Updated FK_df_routing_diag with ON DELETE CASCADE';
END

IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_df_labrule_diag' AND delete_referential_action = 0)
BEGIN
    ALTER TABLE df_exclusive_lab_rules DROP CONSTRAINT FK_df_labrule_diag;
    ALTER TABLE df_exclusive_lab_rules
        ADD CONSTRAINT FK_df_labrule_diag FOREIGN KEY (diagnostician_id)
        REFERENCES df_diagnosticians(id) ON DELETE CASCADE;
    PRINT 'Updated FK_df_labrule_diag with ON DELETE CASCADE';
END

IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_df_modquota_diag' AND delete_referential_action = 0)
BEGIN
    ALTER TABLE df_modality_quotas DROP CONSTRAINT FK_df_modquota_diag;
    ALTER TABLE df_modality_quotas
        ADD CONSTRAINT FK_df_modquota_diag FOREIGN KEY (diagnostician_id)
        REFERENCES df_diagnosticians(id) ON DELETE CASCADE;
    PRINT 'Updated FK_df_modquota_diag with ON DELETE CASCADE';
END

IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_df_pamakristos_diag' AND delete_referential_action = 0)
BEGIN
    ALTER TABLE df_pamakristos_schedule DROP CONSTRAINT FK_df_pamakristos_diag;
    ALTER TABLE df_pamakristos_schedule
        ADD CONSTRAINT FK_df_pamakristos_diag FOREIGN KEY (diagnostician_id)
        REFERENCES df_diagnosticians(id) ON DELETE CASCADE;
    PRINT 'Updated FK_df_pamakristos_diag with ON DELETE CASCADE';
END
GO

-- -----------------------------------------------------------------------------
-- 5. Add decision audit trail columns to df_assignment_log
--    (DiagFlow auto-detects these columns — safe before or after running)
-- -----------------------------------------------------------------------------
IF EXISTS (SELECT 1 FROM sys.tables WHERE name = 'df_assignment_log')
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID('df_assignment_log') AND name = 'suggested_diagnostician_id'
    )
        ALTER TABLE df_assignment_log ADD suggested_diagnostician_id INT NULL;

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID('df_assignment_log') AND name = 'was_overridden'
    )
        ALTER TABLE df_assignment_log ADD was_overridden BIT NOT NULL DEFAULT 0;

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID('df_assignment_log') AND name = 'override_reason'
    )
        ALTER TABLE df_assignment_log ADD override_reason NVARCHAR(500) NULL;

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID('df_assignment_log') AND name = 'rules_fired'
    )
        ALTER TABLE df_assignment_log ADD rules_fired NVARCHAR(MAX) NULL;

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID('df_assignment_log') AND name = 'score_breakdown'
    )
        ALTER TABLE df_assignment_log ADD score_breakdown NVARCHAR(MAX) NULL;

    PRINT 'Verified decision audit columns on df_assignment_log';
END
GO

PRINT '=====================================================================';
PRINT 'DiagFlow Final Release migration completed successfully.';
PRINT '=====================================================================';
