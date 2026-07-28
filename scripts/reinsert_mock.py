import sqlite3
import datetime
import sys

def reinsert_exam():
    # 1. Delete specific exam 30000001
    try:
        conn = sqlite3.connect('db/mock_slis.db')
        conn.execute("DELETE FROM slis_exams WHERE exammoreid = 30000001")
        conn.commit()
    except Exception as e:
        print("Error with mock_slis.db:", e)
        return
        
    try:
        conn2 = sqlite3.connect('db/diagflow.db')
        conn2.execute("DELETE FROM local_assignments WHERE exammoreid = 30000001")
        conn2.execute("DELETE FROM assignment_log WHERE exammoreid = 30000001") # Just in case it was added here
        conn2.commit()
        conn2.close()
    except Exception as e:
        pass
    
    # 2. Add new exam
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM slis_exams LIMIT 1")
    base_row = cursor.fetchone()
    col_names = [d[0] for d in cursor.description]
    
    exams_to_add = [
        {"code": 22705, "cat": "Φασματοσκοπίες", "wname": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ ΝΕΥΡΟΛΟΓΙΚΗ", "lab": "ΙΛΙΟΝ", "lab_id": 7, "exammoreid": 30000001},
    ]
    
    now_str = datetime.datetime.now().isoformat()
    
    for i, e in enumerate(exams_to_add):
        row_dict = dict(zip(col_names, base_row))
        current_id = e["exammoreid"]
        row_dict["exammoreid"] = current_id
        row_dict["extracode"] = current_id + 100000
        row_dict["examnumcode"] = e["code"]
        row_dict["examname"] = f"ΦΑΣΜΑΤΟΣΚΟΠΙΑ {e['code']}"
        row_dict["category"] = e["cat"]
        row_dict["labcodeid"] = e["lab_id"]
        row_dict["laboratoryname"] = e["lab"]
        row_dict["visitdate"] = now_str
        row_dict["wname"] = e["wname"]
        
        row_dict["diagnostis"] = None
        row_dict["code"] = None
        row_dict["name"] = None
        
        cols = ", ".join(row_dict.keys())
        placeholders = ", ".join(["?"] * len(row_dict))
        values = tuple(row_dict.values())
        
        cursor.execute(f"INSERT INTO slis_exams ({cols}) VALUES ({placeholders})", values)
        
    conn.commit()
    conn.close()
    print("Re-inserted exam 30000001 successfully!")

if __name__ == '__main__':
    reinsert_exam()
