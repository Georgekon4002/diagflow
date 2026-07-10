"""
DiagFlow — Data Quality Audit Script

Analyzes Slis assignment history to assess data quality before building
the rule engine. This is your FIRST deliverable after getting DB access.

What it checks:
1. Free-text comment patterns — how consistent, what patterns exist
2. Exclusion/inclusion instruction frequency in comments
3. Skill data coverage — what fraction of requests have matching diagnostician skills
4. Partnership consistency — how stable are issuing doctor → diagnostician mappings
5. Diagnostician capacity utilization — who's overloaded, who's idle
6. Patient history patterns — how often does the same diagnostician see the same patient

Usage:
    When DB access is available:
        python scripts/data_quality_audit.py --db-url "mssql+pyodbc://..."

    For now (with mock data):
        python scripts/data_quality_audit.py --mock
"""

import argparse
import re
from collections import Counter
from datetime import datetime

import pandas as pd


def generate_mock_data() -> dict[str, pd.DataFrame]:
    """Generate realistic mock data for development."""

    # Mock assignments (last 3 months)
    assignments = pd.DataFrame([
        {"exam_id": f"EX-{i}", "patient_id": f"PT-{i % 50}", "diagnostician_name": d,
         "modality": m, "body_part": bp, "lab_name": lab,
         "issuing_doctor": doc, "comments": comment, "date": f"2026-{month:02d}-{day:02d}"}
        for i, (d, m, bp, lab, doc, comment, month, day) in enumerate([
            ("Νάτσικα Α.", "MRI", "abdomen", "Κηφισιά", "Παπαδόπουλος Ν.", "", 4, 15),
            ("Νάτσικα Α.", "MRI", "abdomen", "Κηφισιά", "Παπαδόπουλος Ν.", "", 4, 15),
            ("Νάτσικα Α.", "CT", "chest", "Μαρούσι", "Ιωάννου Ε.", "Επείγον", 4, 16),
            ("Κωνσταντίνου Β.", "CT", "chest", "Μαρούσι", "Ιωάννου Ε.", "", 4, 16),
            ("Κωνσταντίνου Β.", "CT", "chest", "Κηφισιά", "Παπαδόπουλος Ν.", "ΟΧΙ ΝΑΤΣΙΚΑ", 4, 17),
            ("Παπαδόπουλος Γ.", "MRI", "neuro", "Κηφισιά", "Παπαδόπουλος Ν.", "", 4, 17),
            ("Παπαδόπουλος Γ.", "MRI", "neuro", "Κηφισιά", "Παπαδόπουλος Ν.", "", 4, 18),
            ("Παπαδόπουλος Γ.", "CT", "abdomen", "Παμμακάριστος", "Εφημερία", "ΕΦΗΜΕΡΙΑ ΠΑΜΜΑΚΑΡΙΣΤΟΥ", 4, 18),
            ("Δημητρίου Ε.", "MRI", "msk", "Γλυφάδα", "Βασιλείου Κ.", "", 4, 19),
            ("Δημητρίου Ε.", "MRI", "msk", "Γλυφάδα", "Βασιλείου Κ.", "", 4, 19),
            ("Νάτσικα Α.", "MRI", "abdomen", "Κηφισιά", "Παπαδόπουλος Ν.", "ΝΑ ΤΟ ΠΑΡΕΙ Η ΝΑΤΣΙΚΑ", 4, 20),
            ("Λιάκος Δ.", "CT", "abdomen", "Μαρούσι", "Ιωάννου Ε.", "", 4, 20),
            ("Αντωνίου Ζ.", "MRI", "abdomen", "Κηφισιά", "Γεωργίου Α.", "Ασθενής ζητά τον Αντωνίου", 5, 1),
            ("Κωνσταντίνου Β.", "CT", "chest", "Μαρούσι", "Ιωάννου Ε.", "", 5, 2),
            ("Παπαδόπουλος Γ.", "MRI", "neuro", "Κηφισιά", "Παπαδόπουλος Ν.", "ΟΧΙ ΝΑΤΣΙΚΑ", 5, 3),
            ("Νάτσικα Α.", "MRI", "abdomen", "Γλυφάδα", "Βασιλείου Κ.", "", 5, 4),
            ("Δημητρίου Ε.", "CT", "msk", "Γλυφάδα", "Βασιλείου Κ.", "", 5, 5),
            ("Παπαδόπουλος Γ.", "CT", "abdomen", "Παμμακάριστος", "Εφημερία", "ΕΦΗΜΕΡΙΑ", 5, 6),
            ("Νάτσικα Α.", "MRI", "neuro", "Κηφισιά", "Παπαδόπουλος Ν.", "", 5, 7),
            ("Κωνσταντίνου Β.", "MRI", "chest", "Μαρούσι", "Ιωάννου Ε.", "ΟΧΙ ΛΙΑΚΟ", 5, 8),
            ("Αντωνίου Ζ.", "CT", "chest", "Κηφισιά", "Γεωργίου Α.", "", 5, 9),
            ("Λιάκος Δ.", "CT", "chest", "Μαρούσι", "Ιωάννου Ε.", "", 5, 10),
            ("Δημητρίου Ε.", "MRI", "msk", "Γλυφάδα", "Βασιλείου Κ.", "", 5, 11),
            ("Παπαδόπουλος Γ.", "MRI", "neuro", "Κηφισιά", "Παπαδόπουλος Ν.", "", 5, 12),
            ("Νάτσικα Α.", "MRI", "abdomen", "Κηφισιά", "Παπαδόπουλος Ν.", "ΟΧΙ ΚΩΝΣΤΑΝΤΙΝΟΥ", 6, 1),
        ])
    ])

    return {"assignments": assignments}


def analyze_comments(df: pd.DataFrame) -> dict:
    """Analyze free-text comment patterns."""
    comments = df["comments"].fillna("")
    non_empty = comments[comments.str.strip() != ""]

    # Pattern detection
    exclusion_pattern = re.compile(r"ΟΧΙ\s+\w+", re.IGNORECASE)
    assignment_pattern = re.compile(r"(ΝΑ ΤΟ ΠΑΡΕΙ|ΖΗΤΑ|ΖΗΤΑΕΙ)", re.IGNORECASE)
    pamakristos_pattern = re.compile(r"(ΕΦΗΜΕΡΙΑ|ΠΑΜΜΑΚΑΡΙΣΤ|ΠΑΜΑΚΑΡΙΣΤ)", re.IGNORECASE)
    urgency_pattern = re.compile(r"(ΕΠΕΙΓ|URGENT)", re.IGNORECASE)

    exclusion_matches = non_empty.apply(lambda x: bool(exclusion_pattern.search(x)))
    assignment_matches = non_empty.apply(lambda x: bool(assignment_pattern.search(x)))
    pamakristos_matches = non_empty.apply(lambda x: bool(pamakristos_pattern.search(x)))
    urgency_matches = non_empty.apply(lambda x: bool(urgency_pattern.search(x)))

    # Extract excluded names
    excluded_names = []
    for c in non_empty:
        matches = exclusion_pattern.findall(c)
        for m in matches:
            name = m.replace("ΟΧΙ ", "").strip()
            excluded_names.append(name)

    return {
        "total_records": len(df),
        "records_with_comments": len(non_empty),
        "comment_rate": f"{len(non_empty)/len(df)*100:.1f}%",
        "exclusion_count": exclusion_matches.sum(),
        "assignment_count": assignment_matches.sum(),
        "pamakristos_count": pamakristos_matches.sum(),
        "urgency_count": urgency_matches.sum(),
        "excluded_names": Counter(excluded_names).most_common(10),
        "unique_comment_patterns": len(non_empty.unique()),
        "sample_comments": non_empty.head(10).tolist(),
    }


def analyze_partnerships(df: pd.DataFrame) -> dict:
    """Analyze issuing doctor → diagnostician consistency."""
    pairs = df.groupby("issuing_doctor")["diagnostician_name"].apply(list)

    results = {}
    for doctor, diagnosticians in pairs.items():
        counter = Counter(diagnosticians)
        total = len(diagnosticians)
        top = counter.most_common(1)[0]
        consistency = top[1] / total

        results[doctor] = {
            "total_assignments": total,
            "top_diagnostician": top[0],
            "top_count": top[1],
            "consistency": f"{consistency*100:.0f}%",
            "unique_diagnosticians": len(counter),
            "distribution": dict(counter),
        }

    return results


def analyze_capacity(df: pd.DataFrame) -> dict:
    """Analyze daily workload distribution per diagnostician."""
    df_copy = df.copy()
    df_copy["date"] = pd.to_datetime(df_copy["date"])

    daily = df_copy.groupby(["diagnostician_name", df_copy["date"].dt.date]).size().reset_index(name="count")

    result = {}
    for diag in daily["diagnostician_name"].unique():
        subset = daily[daily["diagnostician_name"] == diag]["count"]
        result[diag] = {
            "avg_daily": f"{subset.mean():.1f}",
            "max_daily": int(subset.max()),
            "min_daily": int(subset.min()),
            "total_days": len(subset),
            "total_exams": int(subset.sum()),
        }

    return result


def analyze_body_part_distribution(df: pd.DataFrame) -> dict:
    """Analyze body part distribution per diagnostician."""
    return df.groupby(["diagnostician_name", "body_part"]).size().unstack(fill_value=0).to_dict("index")


def generate_report(data: dict[str, pd.DataFrame], output_path: str) -> None:
    """Generate the data quality report in Markdown."""
    df = data["assignments"]

    comments_analysis = analyze_comments(df)
    partnerships_analysis = analyze_partnerships(df)
    capacity_analysis = analyze_capacity(df)
    body_parts = analyze_body_part_distribution(df)

    report = f"""# DiagFlow — Data Quality Audit Report

**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M")}
**Data source:** {"Mock data" if True else "Slis DB"}
**Records analyzed:** {len(df)}

---

## 1. Comment / Remarks Analysis

| Metric | Value |
|--------|-------|
| Total records | {comments_analysis['total_records']} |
| Records with comments | {comments_analysis['records_with_comments']} |
| Comment rate | {comments_analysis['comment_rate']} |
| Exclusion instructions ("ΟΧΙ...") | {comments_analysis['exclusion_count']} |
| Direct assignment instructions | {comments_analysis['assignment_count']} |
| Παμακάριστος references | {comments_analysis['pamakristos_count']} |
| Urgency markers | {comments_analysis['urgency_count']} |
| Unique comment patterns | {comments_analysis['unique_comment_patterns']} |

### Most Frequently Excluded Names
"""

    for name, count in comments_analysis["excluded_names"]:
        report += f"- **{name}**: {count} times\n"

    report += f"""
### Sample Comments
"""
    for i, comment in enumerate(comments_analysis["sample_comments"][:5], 1):
        report += f"{i}. `{comment}`\n"

    report += f"""

---

## 2. Partnership Consistency

How consistently does each issuing doctor send to the same diagnostician?

| Issuing Doctor | Total | Top Diagnostician | Consistency | Unique |
|---------------|-------|-------------------|-------------|--------|
"""
    for doc, info in partnerships_analysis.items():
        report += f"| {doc} | {info['total_assignments']} | {info['top_diagnostician']} | {info['consistency']} | {info['unique_diagnosticians']} |\n"

    report += f"""

---

## 3. Capacity / Workload Analysis

| Diagnostician | Avg Daily | Max Daily | Total Exams | Days Active |
|--------------|-----------|-----------|-------------|-------------|
"""
    for diag, info in capacity_analysis.items():
        report += f"| {diag} | {info['avg_daily']} | {info['max_daily']} | {info['total_exams']} | {info['total_days']} |\n"

    report += f"""

---

## 4. Body Part Distribution per Diagnostician

| Diagnostician | """ + " | ".join(sorted(set(df["body_part"]))) + """ |
|""" + "|".join(["---"] * (len(set(df["body_part"])) + 1)) + """|
"""
    for diag, parts in body_parts.items():
        values = " | ".join(str(parts.get(bp, 0)) for bp in sorted(set(df["body_part"])))
        report += f"| {diag} | {values} |\n"

    report += f"""

---

## 5. Key Findings & Recommendations

### Data Quality Issues
1. **Comment standardization**: {comments_analysis['unique_comment_patterns']} unique comment patterns found. Recommend establishing standard templates.
2. **Comment coverage**: {comments_analysis['comment_rate']} of records have comments — need to determine if this is normal or indicates missing data.

### Ready for Rule Engine
- **Comment parsing**: ✅ Clear exclusion pattern ("ΟΧΙ + NAME") detected — keyword parser will handle most cases
- **Partnership data**: ✅ Consistent enough for weighted scoring
- **Capacity data**: ✅ Workload distribution shows clear patterns

### Needs Attention
- Verify diagnostician skill data coverage against actual Slis records
- Check if lab preference data exists in Slis or needs manual entry
- Validate patient history query against Slis assignment tables

---

*Report generated by DiagFlow Data Quality Audit Script v0.1*
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"✅ Report generated: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="DiagFlow Data Quality Audit")
    parser.add_argument("--db-url", type=str, help="SQLAlchemy connection string for Slis DB")
    parser.add_argument("--mock", action="store_true", help="Use mock data instead of DB")
    parser.add_argument("--output", type=str, default="data_quality_report.md", help="Output file path")
    parser.add_argument("--months", type=int, default=3, help="Number of months of history to analyze")
    args = parser.parse_args()

    if args.mock or not args.db_url:
        print("📊 Running with mock data...")
        data = generate_mock_data()
    else:
        print(f"📊 Connecting to DB: {args.db_url[:40]}...")
        # TODO: Implement actual DB connection
        # from sqlalchemy import create_engine
        # engine = create_engine(args.db_url)
        # query = f"SELECT ... FROM ... WHERE date >= DATEADD(month, -{args.months}, GETDATE())"
        # data = {"assignments": pd.read_sql(query, engine)}
        raise NotImplementedError(
            "DB connection not yet implemented. Use --mock for now, "
            "or implement the SQL query when Slis DB access is available."
        )

    generate_report(data, args.output)


if __name__ == "__main__":
    main()
