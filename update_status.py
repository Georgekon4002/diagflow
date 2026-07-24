import sys, re
sys.stdout.reconfigure(encoding='utf-8')
sql_file = 'db/init_diagflow.sql'
with open(sql_file, 'r', encoding='utf-8') as f:
    content = f.read()

# Make 97 inactive, 316 active
content = re.sub(
    r'(INSERT INTO "diagnosticians" VALUES\(97,\'ΤΡΙΑΝΤΑΦΥΛΛΟΥ ΔΗΜΗΤΡΗΣ\',)(1)',
    r'\g<1>0',
    content
)
content = re.sub(
    r'(INSERT INTO "diagnosticians" VALUES\(316,\'ΤΡΙΑΝΤΑΦΥΛΛΟΥ ΜΑΡΙΑ\',)(0)',
    r'\g<1>1',
    content
)
# Make 143 inactive, 330 active
content = re.sub(
    r'(INSERT INTO "diagnosticians" VALUES\(143,\'ΣΤΕΡΓΙΟΥ ΛΕΩΝΙΔΑΣ\',)(1)',
    r'\g<1>0',
    content
)
content = re.sub(
    r'(INSERT INTO "diagnosticians" VALUES\(330,\'ΣΤΕΡΓΙΟΥ ΠΗΝΕΛΟΠΗ\',)(0)',
    r'\g<1>1',
    content
)

with open(sql_file, 'w', encoding='utf-8') as f:
    f.write(content)
