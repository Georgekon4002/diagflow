import sys

sys.stdout.reconfigure(encoding='utf-8')
sql_file = 'db/init_diagflow.sql'
with open(sql_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.startswith('INSERT INTO "diagnosticians" VALUES(14,'):
        parts = line.split(',')
        for i in range(4, 11):
            parts[i] = '999'
        line = ','.join(parts)
    elif line.startswith('INSERT INTO "diagnosticians" VALUES(316,'):
        parts = line.split(',')
        for i in range(4, 11):
            parts[i] = '999'
        line = ','.join(parts)
    elif line.startswith('INSERT INTO "diagnosticians" VALUES(330,'):
        parts = line.split(',')
        for i in range(4, 11):
            parts[i] = '999'
        line = ','.join(parts)
    new_lines.append(line)

with open(sql_file, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('Updated init_diagflow.sql successfully.')
