import sqlite3

def update_db():
    con = sqlite3.connect('db/diagflow.db')
    cur = con.cursor()

    # 1. Update diagnosticians
    cur.execute("UPDATE diagnosticians SET active = 0 WHERE name IN ('ΤΡΙΑΝΤΑΦΥΛΛΟΥ ΔΗΜΗΤΡΗΣ', 'ΣΤΕΡΓΙΟΥ ΛΕΩΝΙΔΑΣ')")
    cur.execute("UPDATE diagnosticians SET active = 1, quota_monday=999, quota_tuesday=999, quota_wednesday=999, quota_thursday=999, quota_friday=999, quota_saturday=999, quota_sunday=999 WHERE name IN ('ΤΡΙΑΝΤΑΦΥΛΛΟΥ ΜΑΡΙΑ', 'ΣΤΕΡΓΙΟΥ ΠΗΝΕΛΟΠΗ')")
    
    # 2. Update partnerships
    # ΝΑΤΣΙΚΑ (id 14) active ones -> exclusive
    cur.execute("UPDATE partnerships SET exclusive = 1 WHERE preferred_diagnostician_id = 14 AND is_active = 1")
    # ΝΑΤΣΙΚΑ inactive ones -> active, non-exclusive
    cur.execute("UPDATE partnerships SET is_active = 1, exclusive = 0 WHERE preferred_diagnostician_id = 14 AND is_active = 0")
    # ΜΠΕΡΕΤΗΣ (id 59) and ΑΝΘΙΜΟΥ (id 61) -> exclusive
    cur.execute("UPDATE partnerships SET exclusive = 1 WHERE preferred_diagnostician_id IN (59, 61)")

    # 3. Lab preferences
    cur.execute("UPDATE diagnosticians SET preferred_lab_id = 6 WHERE preferred_lab_id = 8")

    # 4. Diagnostician skills for ΜΠΕΡΕΤΗΣ
    # First, let's see if the skills already exist
    for exam_code in ['21038', '21061', '21062', '21063']:
        cur.execute("SELECT id FROM diagnostician_skills WHERE diagnostician_id = 59 AND exam_code = ?", (exam_code,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE diagnostician_skills SET is_preferred = 1 WHERE id = ?", (row[0],))
        else:
            cur.execute("INSERT INTO diagnostician_skills (diagnostician_id, exam_code, is_preferred) VALUES (59, ?, 1)", (exam_code,))

    con.commit()
    con.close()
    print("DB updates completed successfully.")

if __name__ == '__main__':
    update_db()
