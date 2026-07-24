import sys
sys.stdout.reconfigure(encoding='utf-8')
import sqlite3

con = sqlite3.connect('db/diagflow.db')
con.row_factory = sqlite3.Row

print("=== KEY DIAGNOSTICIANS ===")
for name in ['ΝΑΤΣΙΚΑ', 'ΜΠΕΡΕΤΗ', 'ΑΝΘΙΜΟΥ', 'ΤΡΙΑΝΤΑΦΥΛΛΟΥ', 'ΣΤΕΡΓΙΟΥ', 'ΚΥΠΡΙΩΤ', 'ΠΑΠΟΥΤΣΗ', 'WEB', 'ΑΛΕΞΟΠΟΥΛ']:
    rows = con.execute(f"SELECT * FROM diagnosticians WHERE name LIKE '%{name}%'").fetchall()
    for r in rows:
        print(dict(r))

print("\n=== PARTNERSHIPS BY DIAGNOSTICIAN ===")
for diag_id in [14, 59, 61, 41]:
    rows = con.execute(
        "SELECT id, issuing_doctor_id, issuing_doctor_name, preferred_diagnostician_id, exclusive, is_active "
        "FROM partnerships WHERE preferred_diagnostician_id = ? ORDER BY is_active DESC, issuing_doctor_name",
        (diag_id,)
    ).fetchall()
    print(f"\nDiag ID {diag_id}: {len(rows)} partnerships")
    for r in rows:
        print(f"  {dict(r)}")

print("\n=== LABS IN EXAMS ===")
rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", [r['name'] for r in rows])

print("\n=== DIAGNOSTICIAN SKILLS ===")
rows = con.execute("SELECT * FROM diagnostician_skills WHERE diagnostician_id = 59").fetchall()
print(f"ΜΠΕΡΕΤΗΣ skills: {[dict(r) for r in rows]}")

print("\n=== ΧΑΛΚΙΔΟΣ lab check ===")
# Check if ΧΑΛΚΙΔΟΣ appears anywhere
rows = con.execute("SELECT * FROM diagnosticians WHERE preferred_lab_id IS NOT NULL").fetchall()
print(f"Diagnosticians with lab preferences: {[dict(r) for r in rows]}")

con.close()
