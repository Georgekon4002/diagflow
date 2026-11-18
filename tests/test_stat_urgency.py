"""
Tests for exam urgency flag ('stat': 0 = normal, 1 = stat, 2 = emergency).
"""
import sqlite3
from diagflow.services.assignment import _row_to_exam_dict
from diagflow.services.slis_sync import ensure_slis_exams_table


def test_row_to_exam_dict_stat():
    """Verify that 'stat' field is correctly mapped into exam dictionary."""
    # Test default/none
    row_default = {"exammoreid": 100, "fname": "ΓΕΩΡΓΙΟΣ", "lname": "ΠΑΠΑΔΟΠΟΥΛΟΣ"}
    d_default = _row_to_exam_dict(row_default)
    assert d_default["stat"] == 0

    # Test stat=1
    row_stat = {"exammoreid": 101, "fname": "ΜΑΡΙΑ", "lname": "ΙΩΑΝΝΟΥ", "stat": 1}
    d_stat = _row_to_exam_dict(row_stat)
    assert d_stat["stat"] == 1

    # Test stat=2 (emergency)
    row_emerg = {"exammoreid": 102, "fname": "ΝΙΚΟΣ", "lname": "ΚΩΝΣΤΑΝΤΙΝΟΥ", "stat": "2"}
    d_emerg = _row_to_exam_dict(row_emerg)
    assert d_emerg["stat"] == 2


def test_ensure_slis_exams_table_migrates_stat(tmp_path):
    """Verify that ensure_slis_exams_table automatically adds 'stat' column to legacy SQLite DBs."""
    db_file = tmp_path / "legacy_mock_slis.db"
    con = sqlite3.connect(str(db_file))
    # Create legacy table without stat column
    con.execute("""
        CREATE TABLE slis_exams (
            exammoreid INTEGER PRIMARY KEY,
            fname TEXT,
            lname TEXT
        )
    """)
    con.commit()

    # Run ensure_slis_exams_table
    ensure_slis_exams_table(con)

    # Check columns
    cols = [r[1] for r in con.execute("PRAGMA table_info(slis_exams)").fetchall()]
    assert "stat" in cols
    con.close()


def test_is_pamakristos_row():
    """Verify that Pammakaristos hospital exams are recognized from wname or laboratoryname."""
    from diagflow.services.assignment import _is_pamakristos_row

    # Standard two M's in doctor/ward name
    assert _is_pamakristos_row({"wname": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ - ΧΕΙΡΟΥΡΓΙΚΗ"}) is True

    # Single M in doctor/ward name
    assert _is_pamakristos_row({"wname": "ΠΑΜΑΚΑΡΙΣΤΟΣ"}) is True

    # In laboratory name
    assert _is_pamakristos_row({"wname": "DOC-1", "laboratoryname": "ΠΑΜΜΑΚΑΡΙΣΤΟΣ - ΑΚΤΙΝΟΔΙΑΓΝΩΣΤΙΚΟ"}) is True

    # Regular exam
    assert _is_pamakristos_row({"wname": "ΠΑΘΟΛΟΓΙΚΟ", "laboratoryname": "ΚΗΦΙΣΙΑ"}) is False

