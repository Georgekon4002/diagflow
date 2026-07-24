import sqlite3

con = sqlite3.connect('db/diagflow.db')
with open('db/init_diagflow.sql', 'w', encoding='utf-8') as f:
    for line in con.iterdump():
        f.write(f"{line}\n")
con.close()
print("Dump completed.")
