import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

def check_data():
    conn = sqlite3.connect('db/mock_slis.db')
    cursor = conn.cursor()
    
    print("Labs:")
    cursor.execute("SELECT DISTINCT labcodeid, laboratoryname FROM slis_exams")
    for r in cursor.fetchall():
        print(f"{r[0]}: {r[1]}")
        
    print("\nOne Row from slis_exams:")
    cursor.execute("SELECT * FROM slis_exams LIMIT 1")
    row = cursor.fetchone()
    col_names = [d[0] for d in cursor.description]
    if row:
        for c, v in zip(col_names, row):
            print(f"{c}: {v}")

    print("\nMax exammoreid:")
    cursor.execute("SELECT MAX(exammoreid) FROM slis_exams")
    print(cursor.fetchone()[0])
    
if __name__ == '__main__':
    check_data()
