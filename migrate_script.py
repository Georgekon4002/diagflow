import sys, sqlite3, re
from datetime import datetime, timedelta
import random

sys.stdout.reconfigure(encoding='utf-8')

# 1. Update init_diagflow.sql
sql_file = 'db/init_diagflow.sql'
with open(sql_file, 'r', encoding='utf-8') as f:
    content = f.read()

# Map skills from old IDs to new IDs
content = content.replace('INSERT INTO "diagnostician_skills" VALUES(97,', 'INSERT INTO "diagnostician_skills" VALUES(316,')
content = content.replace('INSERT INTO "diagnostician_skills" VALUES(143,', 'INSERT INTO "diagnostician_skills" VALUES(330,')

# Add modality and extracode to assignment_log schema
content = content.replace(
    'CREATE TABLE assignment_log (exammoreid INTEGER PRIMARY KEY, diagnostician_id INTEGER NOT NULL, assigned_at TEXT NOT NULL);',
    'CREATE TABLE assignment_log (exammoreid INTEGER PRIMARY KEY, diagnostician_id INTEGER NOT NULL, assigned_at TEXT NOT NULL, modality TEXT, extracode TEXT);'
)

# Update existing assignment_log inserts in the script to match the new schema
content = re.sub(
    r'(INSERT INTO "assignment_log" VALUES\(\d+,\d+,[^\)]+)\);',
    r'\1, NULL, NULL);',
    content
)

with open(sql_file, 'w', encoding='utf-8') as f:
    f.write(content)

# 2. Update mock_slis.db
conn = sqlite3.connect('db/mock_slis.db')
cur = conn.cursor()

# Clear assignments
cur.execute("UPDATE slis_exams SET diagnostis = NULL")

# Randomize dates to last 3 days (July 22, 23, 24)
cur.execute("SELECT exammoreid FROM slis_exams")
rows = cur.fetchall()
for r in rows:
    days_ago = random.randint(0, 2)
    dt = datetime(2026, 7, 24) - timedelta(days=days_ago)
    date_str = dt.strftime('%Y-%m-%d %H:%M:%S.000')
    cur.execute("UPDATE slis_exams SET visitdate = ? WHERE exammoreid = ?", (date_str, r[0]))

conn.commit()
conn.close()

print('Data updated successfully.')
