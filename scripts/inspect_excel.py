import pandas as pd
import sys

try:
    df = pd.read_excel(r'c:\Users\georg\Desktop\internship\diagflow\docs\db.xlsx', sheet_name='ΣΥΣΤΗΣΑΝΤΕΣ')
    print("Columns:", df.columns.tolist())
    print("First few rows:")
    print(df.head())
except Exception as e:
    print(f"Error: {e}")
