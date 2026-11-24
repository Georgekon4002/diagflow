-- =============================================================================
-- DiagFlow — Central MSSQL Database Incremental Migration Script (Idempotent)
-- =============================================================================
-- Safe to run multiple times on an existing mid-August DiagFlow central DB.
-- =============================================================================

-- 1. Add visitdate column to df_local_assignments and df_assignment_log (if missing)
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('df_local_assignments') AND name = 'visitdate'
)
    ALTER TABLE df_local_assignments ADD visitdate NVARCHAR(50) NULL;

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('df_assignment_log') AND name = 'visitdate'
)
    ALTER TABLE df_assignment_log ADD visitdate NVARCHAR(50) NULL;

-- 2. Create df_dismissed_auto_assignments table (if missing)
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'df_dismissed_auto_assignments')
BEGIN
    CREATE TABLE df_dismissed_auto_assignments (
        exammoreid   INT          PRIMARY KEY,
        dismissed_at NVARCHAR(50) NOT NULL
    );
    PRINT 'Created table df_dismissed_auto_assignments';
END
GO

-- 3. One-time backfill of visitdate (YYYY-MM-DD) for existing rows where it is NULL
UPDATE L
SET L.visitdate = CONVERT(VARCHAR(10), COALESCE(V.DATE, E.ORDERDATE), 23)
FROM df_local_assignments L
INNER JOIN LISKOSMO.DBO.EXAMMORE E ON E.EXAMMOREID = L.exammoreid
INNER JOIN LISKOSMO.DBO.VISIT V    ON V.VISITID    = E.VISITID
WHERE L.visitdate IS NULL;

UPDATE A
SET A.visitdate = CONVERT(VARCHAR(10), COALESCE(V.DATE, E.ORDERDATE), 23)
FROM df_assignment_log A
INNER JOIN LISKOSMO.DBO.EXAMMORE E ON E.EXAMMOREID = A.exammoreid
INNER JOIN LISKOSMO.DBO.VISIT V    ON V.VISITID    = E.VISITID
WHERE A.visitdate IS NULL;

-- 4. Indexes on visitdate for fast date-based Dashboard and quota queries
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'idx_df_assignlog_visitdate' AND object_id = OBJECT_ID('df_assignment_log')
)
    CREATE INDEX idx_df_assignlog_visitdate ON df_assignment_log(visitdate);

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'idx_df_localassign_visitdate' AND object_id = OBJECT_ID('df_local_assignments')
)
    CREATE INDEX idx_df_localassign_visitdate ON df_local_assignments(visitdate);
GO
