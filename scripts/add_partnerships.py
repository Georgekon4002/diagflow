import sys
from pathlib import Path
import pandas as pd

# Add src to path so we can import diagflow
src_dir = Path(r"c:\Users\georg\Desktop\internship\diagflow\src")
sys.path.append(str(src_dir))

from diagflow.db.diagflow_db import get_all_diagnosticians, create_partnership

def main():
    # Load diagnosticians
    diags = get_all_diagnosticians()
    
    # Create mapping of name -> id
    diag_map = {}
    for d in diags:
        diag_map[d['name'].upper()] = d['id']
        
    def get_diag_id(name):
        for k, v in diag_map.items():
            if name in k:
                return v
        raise ValueError(f"Could not find diagnostician {name}")

    id_natsika = get_diag_id('ΝΑΤΣΙΚΑ')
    id_papoutsi = get_diag_id('ΠΑΠΟΥΤΣΗ')
    id_mperetis = get_diag_id('ΜΠΕΡΕΤΗΣ')

    print(f"Found IDs: Natsika={id_natsika}, Papoutsi={id_papoutsi}, Mperetis={id_mperetis}")

    # Load doctors
    df = pd.read_excel(r'c:\Users\georg\Desktop\internship\diagflow\docs\db.xlsx', sheet_name='ΣΥΣΤΗΣΑΝΤΕΣ')
    
    # Clean string columns, handle possible float representation '.0'
    df['CODE'] = df['CODE'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    df['DOCTORID'] = df['DOCTORID'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    
    def find_doctor(code_str):
        # try code
        match = df[df['CODE'] == code_str]
        if not match.empty:
            return str(match.iloc[0]['CODE']), str(match.iloc[0]['DOCNAME'])
        # try doctorid
        match = df[df['DOCTORID'] == code_str]
        if not match.empty:
            return str(match.iloc[0]['DOCTORID']), str(match.iloc[0]['DOCNAME'])
        return None, None

    requests = [
        # Natsika active
        (id_natsika, True, ["578327", "574736", "579426", "569584", "569624", "580210", "338", "587608", "579563", "1610", "1258", "572505", "588328", "1233", "589514", "1241", "99513466", "570467", "2725", "1270"]),
        # Natsika inactive
        (id_natsika, False, ["1151", "1497"]),
        # Papoutsi active
        (id_papoutsi, True, ["2983", "99507053", "588472", "581484", "571719", "99508293", "811", "579497"]),
        # Mperetis active
        (id_mperetis, True, ["669"])
    ]

    added_names = []

    for diag_id, is_active, codes in requests:
        for code in codes:
            doc_id, doc_name = find_doctor(code)
            if doc_id is None:
                print(f"WARNING: Could not find doctor with code {code}")
                continue
            
            try:
                # create partnership
                create_partnership(doc_id, doc_name, diag_id, priority=1, exclusive=False, is_active=is_active)
                added_names.append(f"{code}: {doc_name}")
            except Exception as e:
                if 'UNIQUE constraint failed' in str(e):
                    # It's already there
                    added_names.append(f"{code}: {doc_name} (Already existed)")
                else:
                    print(f"Error inserting {code} {doc_name}: {e}")

    # Write output to file with utf-8 encoding to avoid Windows console errors
    with open("scripts/added_doctors_output.txt", "w", encoding="utf-8") as f:
        f.write("--- Added Doctors ---\n")
        for msg in added_names:
            f.write(msg + "\n")
    print("Done. Check scripts/added_doctors_output.txt for results.")

if __name__ == "__main__":
    main()
