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


def test_frontend_priority_preserved_with_filters_and_disabled_on_sort():
    """
    Verify frontend/js/app.js keeps Emergency (stat=2), Stat (stat=1), and Pammakaristos
    exams at the top even when filters (e.g. MRI/MRA) are active, and only drops that
    prioritization when the user explicitly sorts by a column.
    """
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node_bin = shutil.which("node")
    if not node_bin:
        return

    app_js = Path(__file__).resolve().parent.parent / "frontend" / "js" / "app.js"
    script = r"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync(process.argv[1], 'utf8');

let slisRendered = [];
const sandbox = {
  console,
  Map, Set, Array, Object, Number, String, Boolean, Date, RegExp, JSON, Math, Promise,
  setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  sessionStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  window: { addEventListener: () => {}, location: { pathname: '/', search: '', hash: '' } },
  document: {
    addEventListener: () => {},
    getElementById: (id) => ({
      value: id === 'search-input' || id === 'slis-search-patient' ? 'active-filter' : '',
      style: {},
      classList: { add(){}, remove(){}, contains(){ return false; } },
      innerHTML: '',
      textContent: '',
    }),
    querySelectorAll: (sel) =>
      sel.includes('modality-dropdown')
        ? [{ value: 'MRI', checked: true }, { value: 'MRA', checked: true }]
        : [],
    querySelector: () => null,
  },
  navigator: { userAgent: '' },
  fetch: async () => ({ ok: true, json: async () => [] }),
};
sandbox.globalThis = sandbox;
vm.runInNewContext(code, sandbox);
sandbox.renderSlisSearchResults = (res) => { slisRendered = res; };

const exams = [
  { exam_id: '1', extracode: '101', demogid: '1', category: 'MRI', visitdate: '2026-11-24', stat: 0, wname: 'DR A', lab_name: 'KIF', patient_name: 'Alpha' },
  { exam_id: '2', extracode: '102', demogid: '2', category: 'MRA', visitdate: '2026-11-20', stat: 1, wname: 'DR B', lab_name: 'KIF', patient_name: 'Beta' },
  { exam_id: '3', extracode: '103', demogid: '3', category: 'MRI', visitdate: '2026-11-19', stat: 2, wname: 'DR C', lab_name: 'KIF', patient_name: 'Gamma' },
  { exam_id: '4', extracode: '104', demogid: '4', category: 'MRI', visitdate: '2026-11-21', stat: 0, wname: 'Παμμακάριστος', lab_name: 'PAM', patient_name: 'Delta' },
  { exam_id: '5', extracode: '105', demogid: '5', category: 'CT',  visitdate: '2026-11-18', stat: 2, wname: 'DR E', lab_name: 'KIF', patient_name: 'Epsilon' },
];

const mriMra = exams.filter(e => sandbox.matchesFilters(e, '', ['MRI', 'MRA'], [], null, null));

// 1. MRI/MRA filter on, no column sort -> Emergency(3), Stat(2), Pammakaristos(4), Normal(1)
vm.runInContext('sortConfig = { key: null, direction: null };', sandbox);
const filteredNoSort = sandbox.sortExams(mriMra).map(e => e.exam_id);

// 2. MRI/MRA filter on, sorted by date DESC -> Normal(1: Nov 24) first, Emergency(3: Nov 19) last
vm.runInContext('sortConfig = { key: "date", direction: "desc" };', sandbox);
const filteredDateDesc = sandbox.sortExams(mriMra).map(e => e.exam_id);

// 3. MRI/MRA filter on, sorted by patient ASC -> Alpha(1), Beta(2), Delta(4), Gamma(3)
vm.runInContext('sortConfig = { key: "patient", direction: "asc" };', sandbox);
const filteredPatientAsc = sandbox.sortExams(mriMra).map(e => e.exam_id);

// 4. Slis Search with active search filter, no column sort -> ordered ONLY by date DESC (no priority override)
vm.runInContext(
  'rawSlisSearchResults = ' + JSON.stringify(mriMra) + '; slisSearchSortConfig = { key: null, direction: null }; sortAndRenderSlisSearchResults();',
  sandbox
);
const slisNoSort = slisRendered.map(e => e.exam_id);

// 5. Slis Search sorted by date DESC -> Normal(1: Nov 24) first, NOT forced to bottom
vm.runInContext(
  'slisSearchSortConfig = { key: "date", direction: "desc" }; sortAndRenderSlisSearchResults();',
  sandbox
);
const slisDateDesc = slisRendered.map(e => e.exam_id);

// 6. STAT badge uses '❗ STAT' instead of '⚡ STAT'
const statBadge = sandbox.getStatInfo({ stat: 1 }).badge;

// 7. Emoji filter toggles (Pammakaristos, STAT=1, STAT=2, Auto-assigned on assigned tab only)
const filterSamples = [
  { exam_id: '10', category: 'MRI', visitdate: '2026-11-24', stat: 0, wname: 'DR A', lab_name: 'KIF', is_auto_assigned: false },
  { exam_id: '11', category: 'MRI', visitdate: '2026-11-24', stat: 0, wname: 'Παμμακάριστος', lab_name: 'PAM', is_auto_assigned: true },
  { exam_id: '12', category: 'MRI', visitdate: '2026-11-24', stat: 1, wname: 'DR B', lab_name: 'KIF', is_auto_assigned: false },
  { exam_id: '13', category: 'MRI', visitdate: '2026-11-24', stat: 2, wname: 'DR C', lab_name: 'KIF', is_auto_assigned: true },
];
const runFilter = () => filterSamples.filter(e => sandbox.matchesFilters(e, '', [], [], null, null)).map(e => e.exam_id);

vm.runInContext('currentTab = "pending"; filterOnlyPammakaristos = true; filterOnlyStat = false; filterOnlyEmergency = false; filterOnlyAutoAssigned = false;', sandbox);
const onlyPam = runFilter();

vm.runInContext('filterOnlyPammakaristos = false; filterOnlyStat = true; filterOnlyEmergency = false;', sandbox);
const onlyStat = runFilter();

vm.runInContext('filterOnlyStat = false; filterOnlyEmergency = true;', sandbox);
const onlyEmergency = runFilter();

vm.runInContext('filterOnlyStat = true; filterOnlyEmergency = true;', sandbox);
const statAndEmergency = runFilter();

// Auto-assigned filter should NOT restrict pending tab, only assigned tab
vm.runInContext('filterOnlyStat = false; filterOnlyEmergency = false; filterOnlyAutoAssigned = true; currentTab = "pending";', sandbox);
const autoOnPending = runFilter();

vm.runInContext('currentTab = "assigned";', sandbox);
const autoOnAssigned = runFilter();

console.log(JSON.stringify({
  filteredNoSort,
  filteredDateDesc,
  filteredPatientAsc,
  slisNoSort,
  slisDateDesc,
  statBadge,
  onlyPam,
  onlyStat,
  onlyEmergency,
  statAndEmergency,
  autoOnPending,
  autoOnAssigned,
}));
"""
    proc = subprocess.run(
        [node_bin, "-e", script, str(app_js)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    results = json.loads(proc.stdout.strip())
    assert results["filteredNoSort"] == ["3", "2", "4", "1"]
    assert results["filteredDateDesc"] == ["1", "4", "2", "3"]
    assert results["filteredPatientAsc"] == ["1", "2", "4", "3"]
    assert results["slisNoSort"] == ["1", "4", "2", "3"]
    assert results["slisDateDesc"] == ["1", "4", "2", "3"]
    assert "❗ STAT" in results["statBadge"]
    assert "⚡" not in results["statBadge"]
    assert results["onlyPam"] == ["11"]
    assert results["onlyStat"] == ["12"]
    assert results["onlyEmergency"] == ["13"]
    assert results["statAndEmergency"] == ["12", "13"]
    assert results["autoOnPending"] == ["10", "11", "12", "13"]
    assert results["autoOnAssigned"] == ["11", "13"]


