import sqlite3
from pathlib import Path

db_path = Path(r"c:\Users\georg\Desktop\internship\diagflow\db\diagflow.db")

def main():
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Find duplicates based on issuing_doctor_id and preferred_diagnostician_id
    # We want to keep the one with the highest ID (most recently added)
    query = """
    DELETE FROM partnerships
    WHERE id NOT IN (
        SELECT MAX(id)
        FROM partnerships
        GROUP BY issuing_doctor_id, preferred_diagnostician_id
    );
    """
    
    # First let's check how many duplicates we have
    cur.execute("""
        SELECT issuing_doctor_id, preferred_diagnostician_id, COUNT(*)
        FROM partnerships
        GROUP BY issuing_doctor_id, preferred_diagnostician_id
        HAVING COUNT(*) > 1
    """)
    duplicates = cur.fetchall()
    print(f"Found {len(duplicates)} duplicate pairs.")
    for d in duplicates:
        print(f"Doctor ID: {d[0]}, Diag ID: {d[1]} -> Count: {d[2]}")
        
    cur.execute(query)
    deleted = cur.rowcount
    print(f"Deleted {deleted} duplicate records.")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
