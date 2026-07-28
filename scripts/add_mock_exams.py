import sqlite3
import datetime
import sys

def insert_exams():
    # 1. Delete old mocks
    try:
        conn = sqlite3.connect('db/mock_slis.db')
        conn.execute("DELETE FROM slis_exams WHERE exammoreid >= 30000000")
        conn.commit()
        
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(exammoreid) FROM slis_exams")
        max_id = cursor.fetchone()[0]
        current_id = max(max_id or 0, 30000000)
    except Exception as e:
        print("Error with mock_slis.db:", e)
        return
        
    try:
        conn2 = sqlite3.connect('db/diagflow.db')
        conn2.execute("DELETE FROM local_assignments WHERE exammoreid >= 30000000")
        conn2.execute("DELETE FROM assignment_log WHERE exammoreid >= 30000000")
        conn2.commit()
        conn2.close()
    except Exception as e:
        pass
    
    # 2. Add new exams
    cursor.execute("SELECT * FROM slis_exams LIMIT 1")
    base_row = cursor.fetchone()
    col_names = [d[0] for d in cursor.description]
    
    exams_to_add = [
        {"code": 21850, "cat": "Cat", "wname": "ANY DOCTOR", "wcode": "123456", "lab": "ΑΝΩ ΠΑΤΗΣΙΑ", "lab_id": 6},
        {"code": 22100, "cat": "Cat", "wname": "ΑΠΟΣΤΟΛΟΠΟΥΛΟΣ ΕΥΑΓΓΕΛ.", "wcode": "570659", "lab": "ΙΛΙΟΝ", "lab_id": 7}
    ]
    
    now_str = datetime.datetime.now().isoformat()
    
    output = []
    
    for i, e in enumerate(exams_to_add):
        row_dict = dict(zip(col_names, base_row))
        current_id += 1
        
        extracode = current_id + 100000
        row_dict["exammoreid"] = current_id
        row_dict["extracode"] = extracode
        row_dict["examnumcode"] = e["code"]
        row_dict["examname"] = f"ΕΞΕΤΑΣΗ {e['code']}"
        row_dict["category"] = e["cat"]
        row_dict["labcodeid"] = e["lab_id"]
        row_dict["laboratoryname"] = e["lab"]
        row_dict["visitdate"] = now_str
        row_dict["wname"] = e["wname"]
        row_dict["wcode"] = e["wcode"]
        
        row_dict["diagnostis"] = None
        row_dict["code"] = None
        row_dict["name"] = None
        
        cols = ", ".join(row_dict.keys())
        placeholders = ", ".join(["?"] * len(row_dict))
        values = tuple(row_dict.values())
        
        cursor.execute(f"INSERT INTO slis_exams ({cols}) VALUES ({placeholders})", values)
        output.append(f"Order ID {extracode}: Exam {e['code']} | Doc: {e['wname']} ({e['wcode']}) | Lab: {e['lab']}")
        
    conn.commit()
    conn.close()
    
    print("New mock exams added successfully!")
    for line in output:
        print(line)

if __name__ == '__main__':
    # Ensure stdout handles greek chars
    sys.stdout.reconfigure(encoding='utf-8')
    insert_exams()
