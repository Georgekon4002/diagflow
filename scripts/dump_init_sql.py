import sqlite3
from pathlib import Path

db_path = Path("db/diagflow.db")
sql_path = Path("db/init_diagflow.sql")

print("Dumping db/diagflow.db to db/init_diagflow.sql...")
con = sqlite3.connect(str(db_path))
con.row_factory = sqlite3.Row

# Get list of all tables
tables_res = con.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;").fetchall()

sql_lines = [
    "BEGIN TRANSACTION;",
]

# We don't dump INSERT rows for these runtime/transient tables:
SKIP_DATA_TABLES = {"local_assignments", "assignment_log"}

for t_row in tables_res:
    t_name = t_row["name"]
    create_sql = t_row["sql"]
    
    if not create_sql:
        continue
        
    sql_lines.append(f"{create_sql};")
    
    if t_name in SKIP_DATA_TABLES:
        continue

    # Fetch rows
    rows = con.execute(f"SELECT * FROM [{t_name}];").fetchall()
    if rows:
        cols = rows[0].keys()
        col_list = ", ".join([f'"{c}"' for c in cols])
        for r in rows:
            vals = []
            for col in cols:
                v = r[col]
                if v is None:
                    vals.append("NULL")
                elif isinstance(v, (int, float)):
                    vals.append(str(v))
                else:
                    # Escape single quotes
                    escaped = str(v).replace("'", "''")
                    vals.append(f"'{escaped}'")
            val_str = ", ".join(vals)
            sql_lines.append(f'INSERT INTO "{t_name}" VALUES({val_str});')

# Also dump indices
indices = con.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY name;").fetchall()
for idx in indices:
    sql_lines.append(f"{idx['sql']};")

# Dump sqlite_sequence if any
seq_rows = con.execute("SELECT * FROM sqlite_sequence;").fetchall()
if seq_rows:
    sql_lines.append('DELETE FROM "sqlite_sequence";')
    for r in seq_rows:
        sql_lines.append(f'INSERT INTO "sqlite_sequence" VALUES(\'{r["name"]}\',{r["seq"]});')

sql_lines.append("COMMIT;")

with open(sql_path, "w", encoding="utf-8") as f:
    f.write("\n".join(sql_lines) + "\n")

con.close()
print(f"Successfully re-dumped init_diagflow.sql ({sql_path.stat().st_size} bytes).")
