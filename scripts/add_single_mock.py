import sqlite3
import datetime
import sys

def insert_exam():
    try:
        conn = sqlite3.connect('db/mock_slis.db')
        
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(exammoreid) FROM slis_exams")
        max_id = cursor.fetchone()[0]
        current_id = max(max_id or 0, 30000000)
    except Exception as e:
        print("Error with mock_slis.db:", e)
        return
    
    cursor.execute("SELECT * FROM slis_exams LIMIT 1")
    base_row = cursor.fetchone()
    col_names = [d[0] for d in cursor.description]
    
    exam = {"code": 22336, "cat": "SomeCat", "wname": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ ΝΕΥΡΟΛΟΓΙΚΗ", "wcode": "", "lab": "ΙΛΙΟΝ", "lab_id": 7}
    now_str = datetime.datetime.now().isoformat()
    
    row_dict = dict(zip(col_names, base_row))
    current_id += 1
    
    extracode = current_id + 100000
    row_dict["exammoreid"] = current_id
    row_dict["extracode"] = extracode
    row_dict["examnumcode"] = exam["code"]
    row_dict["examname"] = f"ΕΞΕΤΑΣΗ {exam['code']}"
    row_dict["category"] = exam["cat"]
    row_dict["labcodeid"] = exam["lab_id"]
    row_dict["laboratoryname"] = exam["lab"]
    row_dict["visitdate"] = now_str
    row_dict["wname"] = exam["wname"]
    row_dict["wcode"] = exam["wcode"]
    
    row_dict["diagnostis"] = None
    row_dict["code"] = None
    row_dict["name"] = None
    
    cols = ", ".join(row_dict.keys())
    placeholders = ", ".join(["?"] * len(row_dict))
    values = tuple(row_dict.values())
    
    cursor.execute(f"INSERT INTO slis_exams ({cols}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()
    
    print(f"Added Exam {exam['code']} | Doc: {exam['wname']} with Order ID {extracode}")

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    insert_exam()
