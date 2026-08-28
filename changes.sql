IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('df_local_assignments') AND name = 'visitdate')
    ALTER TABLE df_local_assignments ADD visitdate NVARCHAR(50) NULL;

IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('df_assignment_log') AND name = 'visitdate')
    ALTER TABLE df_assignment_log ADD visitdate NVARCHAR(50) NULL;
