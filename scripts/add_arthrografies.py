import sqlite3
import datetime

def insert_exams():
    conn = sqlite3.connect('db/mock_slis.db')
    cursor = conn.cursor()
    
    # get a base row
    cursor.execute("SELECT * FROM slis_exams LIMIT 1")
    base_row = cursor.fetchone()
    col_names = [d[0] for d in cursor.description]
    
    # max exammoreid
    cursor.execute("SELECT MAX(exammoreid) FROM slis_exams")
    max_id = cursor.fetchone()[0]
    # start from a clean number >= 30000000 to keep it easily distinguishable
    current_id = max(max_id, 30000000)
    
    exams_to_add = [
        {"code": 21850, "lab": "ΙΛΙΟΝ", "lab_id": 7},
    ]
    
    now_str = datetime.datetime.now().isoformat()
    
    for i, e in enumerate(exams_to_add):
        row_dict = dict(zip(col_names, base_row))
        current_id += 1
        row_dict["exammoreid"] = current_id
        row_dict["extracode"] = current_id + 100000 # Just something unique-ish
        row_dict["examnumcode"] = e["code"]
        row_dict["examname"] = f"ΑΡΘΡΟΓΡΑΦΙΑ {e['code']}"
        row_dict["category"] = "Αρθρογραφίες"
        row_dict["labcodeid"] = e["lab_id"]
        row_dict["laboratoryname"] = e["lab"]
        row_dict["visitdate"] = now_str
        
        # clear diagnostician fields
        row_dict["diagnostis"] = None
        row_dict["code"] = None
        row_dict["name"] = None
        
        cols = ", ".join(row_dict.keys())
        placeholders = ", ".join(["?"] * len(row_dict))
        values = tuple(row_dict.values())
        
        cursor.execute(f"INSERT INTO slis_exams ({cols}) VALUES ({placeholders})", values)
        
    conn.commit()
    conn.close()
    print("Exam added to mock_slis.db")

if __name__ == '__main__':
    insert_exams()
