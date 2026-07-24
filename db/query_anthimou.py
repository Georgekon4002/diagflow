import sys
sys.stdout.reconfigure(encoding='utf-8')
import sqlite3

con = sqlite3.connect('db/diagflow.db')
con.row_factory = sqlite3.Row

print("=== ΑΝΘΙΜΟΥ ===")
r = con.execute("SELECT * FROM diagnosticians WHERE name LIKE '%ΑΝΘΙΜ%'").fetchall()
for x in r: print(dict(x))
con.close()
