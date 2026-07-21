/**
 * DiagFlow — Secretariat Review Dashboard
 *
 * Handles:
 * - Loading pending & assigned exams
 * - Two-tab layout (Εκκρεμείς / Ανατεθειμένες)
 * - Search bar and filters (modality, lab, date)
 * - Generating and displaying assignment suggestions
 * - Alternatives list including hard-filtered (eliminated) diagnosticians
 * - Confirm/override workflow
 * - Admin login / logout flow
 * - Toast notifications
 */

// ── Configuration ──
const API_BASE = '/api';

// ── State ──
let pendingExams = [];
let assignedExams = [];
let currentSuggestion = null;
let currentExamId = null;
let diagnosticians = [];
let currentTab = 'pending';   // 'pending' | 'assigned'
let filterOnlyComments = false;
let filterOnlyHistory = false;
let sortConfig = { key: null, direction: null };
let selectedExams = new Set();           // pending tab selections
let selectedAssignedExams = new Set();   // assigned tab selections for Slis push

let currentPendingPage = 0;
let currentAssignedPage = 0;
const examsPageSize = 20;

let dateRangePicker = null;

// Admin session
let adminToken = sessionStorage.getItem('adminToken') || null;


// ══════════════════════════════════════════════
//  Initialization
// ══════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', async () => {
    restoreAdminState();

    // Initialize date range picker
    dateRangePicker = flatpickr("#filter-date-range", {
        mode: "range",
        dateFormat: "d/m/Y",
        locale: "gr",
        firstDayOfWeek: 1, // Start on Monday
        onChange: function (selectedDates, dateStr, instance) {
            applyFilters();
        }
    });

    await loadDiagnosticians();
    await Promise.all([
        loadPendingExams(),
        loadAssignedExams(),
        loadOncall(),
    ]);
});


// ══════════════════════════════════════════════
//  API Calls
// ══════════════════════════════════════════════

async function apiCall(endpoint, method = 'GET', body = null, extraHeaders = {}) {
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json',
            ...extraHeaders,
        },
    };
    if (adminToken) options.headers['X-Admin-Token'] = adminToken;
    if (body) options.body = JSON.stringify(body);

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, options);
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        return await response.json();
    } catch (err) {
        if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
            console.warn('API not available — using mock mode');
            return null;
        }
        throw err;
    }
}


// ══════════════════════════════════════════════
//  Load Data
// ══════════════════════════════════════════════

async function loadPendingExams() {
    try {
        const data = await apiCall('/exams/pending');
        pendingExams = data || getMockPendingExams();
    } catch {
        pendingExams = getMockPendingExams();
    }
    // Build the dynamic lab filter from real data
    buildLabDropdown(pendingExams);
    updateTabCounts();
    applyFilters();
}

async function loadAssignedExams() {
    try {
        const data = await apiCall('/exams/assigned');
        assignedExams = data || getMockAssignedExams();
    } catch {
        assignedExams = getMockAssignedExams();
    }
    updateTabCounts();
    applyFilters();
}

async function loadDiagnosticians() {
    try {
        const data = await apiCall('/diagnosticians');
        diagnosticians = data || getMockDiagnosticians();
    } catch {
        diagnosticians = getMockDiagnosticians();
    }
}

async function loadOncall() {
    try {
        const data = await apiCall('/pamakristos/oncall');
        document.getElementById('oncall-name').textContent =
            data ? data.diagnostician_name : 'Παπαδόπουλος Γ.';
    } catch {
        document.getElementById('oncall-name').textContent = '—';
    }
}

function refreshCurrentTab() {
    if (currentTab === 'pending') loadPendingExams();
    else loadAssignedExams();
}


// ══════════════════════════════════════════════
//  Tab Switching
// ══════════════════════════════════════════════

function switchTab(tab) {
    currentTab = tab;

    document.getElementById('tab-pending').classList.toggle('active', tab === 'pending');
    document.getElementById('tab-assigned').classList.toggle('active', tab === 'assigned');

    const pendingContent = document.getElementById('tab-content-pending');
    const assignedContent = document.getElementById('tab-content-assigned');
    pendingContent.classList.toggle('active', tab === 'pending');
    assignedContent.classList.toggle('active', tab === 'assigned');
    pendingContent.style.display = tab === 'pending' ? 'block' : 'none';
    assignedContent.style.display = tab === 'assigned' ? 'block' : 'none';

    const titleEl = document.getElementById('section-title-text');
    const countEl = document.getElementById('section-count');

    if (tab === 'pending') {
        titleEl.textContent = 'Εκκρεμείς Εξετάσεις';
        countEl.textContent = `${pendingExams.length} σύνολο`;
    } else {
        titleEl.textContent = 'Ανατεθειμένες (εκκρεμής ενημέρωση Slis)';
        countEl.textContent = `${assignedExams.length} σύνολο`;
    }

    // Show/hide the 'Update Slis' all-button based on tab
    const updateSlisBtn = document.getElementById('btn-update-slis-all');
    if (updateSlisBtn) {
        updateSlisBtn.style.display = tab === 'assigned' ? 'inline-flex' : 'none';
    }

    clearFilters(false); // Reset filters without re-rendering
    applyFilters();
}

function updateTabCounts() {
    document.getElementById('tab-count-pending').textContent = pendingExams.length;
    document.getElementById('tab-count-assigned').textContent = assignedExams.length;

    const countEl = document.getElementById('section-count');
    if (currentTab === 'pending') {
        countEl.textContent = `${pendingExams.length} σύνολο`;
    } else {
        countEl.textContent = `${assignedExams.length} σύνολο`;
    }
}


// ══════════════════════════════════════════════
//  Filters & Search
// ══════════════════════════════════════════════

// Helper to strip Greek accents
function normalizeGreek(str) {
    if (!str) return '';
    return String(str).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase();
}

function applyFilters() {
    const search = normalizeGreek(document.getElementById('search-input').value.trim());
    // Read modality from checkboxes
    const selectedModalities = Array.from(document.querySelectorAll('#modality-dropdown input[type="checkbox"]:checked')).map(cb => cb.value);
    const selectedLabs = Array.from(document.querySelectorAll('#lab-dropdown input[type="checkbox"]:checked')).map(cb => cb.value);

    let dateFrom = null;
    let dateTo = null;

    if (dateRangePicker && dateRangePicker.selectedDates.length > 0) {
        const fromDate = dateRangePicker.selectedDates[0];
        dateFrom = fromDate.getFullYear() + '-' + String(fromDate.getMonth() + 1).padStart(2, '0') + '-' + String(fromDate.getDate()).padStart(2, '0');
        if (dateRangePicker.selectedDates.length === 2) {
            const toDate = dateRangePicker.selectedDates[1];
            dateTo = toDate.getFullYear() + '-' + String(toDate.getMonth() + 1).padStart(2, '0') + '-' + String(toDate.getDate()).padStart(2, '0');
        } else {
            dateTo = dateFrom;
        }
    }

    const hasFilters = search || selectedModalities.length > 0 || selectedLabs.length > 0 || dateFrom || dateTo || filterOnlyComments || filterOnlyHistory || sortConfig.key;
    document.getElementById('btn-clear-filters').style.display = hasFilters ? 'flex' : 'none';

    // Update modality button label
    const modalityBtn = document.getElementById('modality-filter-btn');
    if (modalityBtn) {
        const labelEl = document.getElementById('modality-filter-label');
        if (selectedModalities.length === 0) {
            labelEl.textContent = '🩻 Κατηγορία';
            modalityBtn.classList.remove('has-selection');
        } else if (selectedModalities.length === 1) {
            labelEl.textContent = selectedModalities[0];
            modalityBtn.classList.add('has-selection');
        } else {
            labelEl.textContent = selectedModalities.join(', ');
            modalityBtn.classList.add('has-selection');
        }
    }

    // Update lab button label
    const labBtn = document.getElementById('lab-filter-btn');
    if (labBtn) {
        const labelEl = document.getElementById('lab-filter-label');
        if (selectedLabs.length === 0) {
            labelEl.textContent = '🧪 Εργαστήριο';
            labBtn.classList.remove('has-selection');
        } else if (selectedLabs.length === 1) {
            const labNames = { 'LAB-KIF': 'Κηφισιά', 'LAB-MAR': 'Μαρούσι', 'LAB-GLY': 'Γλυφάδα', 'LAB-PAM': 'Παμμακάριστος' };
            labelEl.textContent = labNames[selectedLabs[0]] || selectedLabs[0];
            labBtn.classList.add('has-selection');
        } else {
            labelEl.textContent = `${selectedLabs.length} εργαστήρια`;
            labBtn.classList.add('has-selection');
        }
    }

    if (currentTab === 'pending') {
        let filtered = pendingExams.filter(e => matchesFilters(e, search, selectedModalities, selectedLabs, dateFrom, dateTo));
        filtered = sortExams(filtered);
        
        // Pagination logic
        const start = currentPendingPage * examsPageSize;
        const sliced = filtered.slice(start, start + examsPageSize);
        
        renderPendingRows(sliced);
        updatePendingPagination(filtered.length);
        
        document.getElementById('section-count').textContent =
            filtered.length === pendingExams.length
                ? `${pendingExams.length} σύνολο`
                : `${filtered.length} από ${pendingExams.length}`;
    } else {
        let filtered = assignedExams.filter(e => matchesFilters(e, search, selectedModalities, selectedLabs, dateFrom, dateTo));
        filtered = sortExams(filtered);
        
        // Pagination logic
        const start = currentAssignedPage * examsPageSize;
        const sliced = filtered.slice(start, start + examsPageSize);
        
        renderAssignedRows(sliced);
        updateAssignedPagination(filtered.length);
        
        document.getElementById('section-count').textContent =
            filtered.length === assignedExams.length
                ? `${assignedExams.length} σύνολο`
                : `${filtered.length} από ${assignedExams.length}`;
    }
}

function isPammakristos(exam) {
    const wname = (exam.wname || exam.issuing_doctor_name || '').toUpperCase();
    const lab = (exam.lab_name || exam.laboratoryname || '').toUpperCase();
    return wname.includes('ΠΑΜΜΑΚΑΡΙΣΤΟΣ') || lab.includes('ΠΑΜΜΑΚΑΡΙΣΤΟΣ');
}

function sortExams(exams) {
    let sorted = [...exams];

    if (sortConfig.key && sortConfig.direction) {
        sorted.sort((a, b) => {
            let valA, valB;
            switch(sortConfig.key) {
                case 'extracode':
                    valA = a.extracode || a.exam_id || '';
                    valB = b.extracode || b.exam_id || '';
                    break;
                case 'date':
                    valA = a.visitdate || a.request_date || '';
                    valB = b.visitdate || b.request_date || '';
                    break;
                case 'lab':
                    valA = a.lab_name || a.laboratoryname || '';
                    valB = b.lab_name || b.laboratoryname || '';
                    break;
                case 'patient':
                    valA = (a.patient_name || `${a.fname || ''} ${a.lname || ''}`).trim();
                    valB = (b.patient_name || `${b.fname || ''} ${b.lname || ''}`).trim();
                    break;
                case 'examcode':
                    valA = a.examnumcode || '';
                    valB = b.examnumcode || '';
                    break;
                case 'doctor':
                    valA = a.wname || a.issuing_doctor_name || '';
                    valB = b.wname || b.issuing_doctor_name || '';
                    break;
                default:
                    valA = ''; valB = '';
            }
            
            if (typeof valA === 'string') valA = valA.toLowerCase();
            if (typeof valB === 'string') valB = valB.toLowerCase();
            
            if (valA < valB) return sortConfig.direction === 'asc' ? -1 : 1;
            if (valA > valB) return sortConfig.direction === 'asc' ? 1 : -1;
            return 0;
        });
    }

    // Always keep Pammakristos at the top, regardless of sort
    sorted.sort((a, b) => {
        const aIsPam = isPammakristos(a) ? 1 : 0;
        const bIsPam = isPammakristos(b) ? 1 : 0;
        return bIsPam - aIsPam;
    });

    return sorted;
}

function applyFiltersModality() {
    applyFilters();
}

function toggleModalityDropdown(event) {
    event.stopPropagation();
    const wrap = document.getElementById('modality-filter-wrap');
    const isOpen = wrap.classList.contains('open');
    // Close all dropdowns first
    document.querySelectorAll('.lab-filter-wrap.open').forEach(el => el.classList.remove('open'));
    if (!isOpen) wrap.classList.add('open');
}

function matchesFilters(exam, search, selectedModalities, selectedLabs, dateFrom, dateTo) {
    // Category / modality filter — multi-select
    if (selectedModalities.length > 0) {
        const examCat = exam.category || exam.modality || '';
        if (!selectedModalities.includes(examCat)) return false;
    }

    // Lab filter — compare against lab_name (from DB) or lab_id (legacy)
    if (selectedLabs.length > 0) {
        const labName = (exam.lab_name || exam.laboratoryname || '').trim();
        const labId = exam.lab_id || '';
        const match = selectedLabs.some(sel => labName === sel || labId === sel);
        if (!match) return false;
    }

    // Date range filter — use visitdate field
    const examDate = exam.visitdate || exam.request_date || '';
    if (dateFrom && examDate < dateFrom) return false;
    if (dateTo && examDate > dateTo) return false;

    if (filterOnlyComments) {
        const notes = exam.notes || exam.comments || '';
        if (!notes || EMPTY_NOTES_RE.test(notes)) return false;
    }

    if (filterOnlyHistory) {
        const ov = exam.oldvisit;
        if (!ov || ov === 0) return false;
    }

    // Full-text search
    if (search) {
        const patName = exam.patient_name || `${exam.fname || ''} ${exam.lname || ''}`.trim();
        const notesStr = exam.notes || exam.comments || '';
        const haystackRaw = [
            String(exam.extracode || exam.exam_id || ''),
            patName,
            exam.wname || exam.issuing_doctor_name || '',
            exam.lab_name || exam.laboratoryname || '',
            cleanExamName(exam.examname || exam.exam_title || ''),
            exam.examname || '',
            String(exam.demogid || exam.patient_id || ''),
            String(exam.examnumcode || ''),
            exam.code || exam.diagnostician_name || exam.assigned_diagnostician_name || '',
            notesStr
        ].join(' ');
        const haystack = normalizeGreek(haystackRaw);
        if (!haystack.includes(search)) return false;
    }
    return true;
}

function clearFilters(rerender = true) {
    document.getElementById('search-input').value = '';

    if (dateRangePicker) {
        dateRangePicker.clear();
    }

    // Uncheck all modality checkboxes
    document.querySelectorAll('#modality-dropdown input[type="checkbox"]').forEach(cb => cb.checked = false);
    const modalityLabelEl = document.getElementById('modality-filter-label');
    if (modalityLabelEl) modalityLabelEl.textContent = '🩻 Κατηγορία';
    const modalityBtn = document.getElementById('modality-filter-btn');
    if (modalityBtn) modalityBtn.classList.remove('has-selection');

    // Uncheck all lab checkboxes
    document.querySelectorAll('#lab-dropdown input[type="checkbox"]').forEach(cb => cb.checked = false);
    document.getElementById('btn-clear-filters').style.display = 'none';
    // Reset lab label
    const labelEl = document.getElementById('lab-filter-label');
    if (labelEl) labelEl.textContent = '🧪 Εργαστήριο';
    const labBtn = document.getElementById('lab-filter-btn');
    if (labBtn) labBtn.classList.remove('has-selection');

    // Reset comments filter
    filterOnlyComments = false;
    const commentsBtn = document.getElementById('btn-filter-comments');
    if (commentsBtn) {
        commentsBtn.style.background = 'var(--bg-tertiary)';
        commentsBtn.style.borderColor = 'var(--border-color)';
        commentsBtn.style.color = 'var(--text-primary)';
    }

    // Reset history filter
    filterOnlyHistory = false;
    const historyBtn = document.getElementById('btn-filter-history');
    if (historyBtn) {
        historyBtn.style.background = 'var(--bg-tertiary)';
        historyBtn.style.borderColor = 'var(--border-color)';
        historyBtn.style.color = 'var(--text-primary)';
    }

    // Reset sorting
    sortConfig = { key: null, direction: null };
    updateSortIcons();

    if (rerender) applyFilters();
}

function toggleCommentsFilter() {
    filterOnlyComments = !filterOnlyComments;
    const btn = document.getElementById('btn-filter-comments');
    if (filterOnlyComments) {
        btn.style.background = 'rgba(99, 102, 241, 0.08)';
        btn.style.borderColor = 'var(--accent-primary)';
        btn.style.color = 'var(--accent-primary)';
    } else {
        btn.style.background = 'var(--bg-tertiary)';
        btn.style.borderColor = 'var(--border-color)';
        btn.style.color = 'var(--text-primary)';
    }
    applyFilters();
}

function toggleHistoryFilter() {
    filterOnlyHistory = !filterOnlyHistory;
    const btn = document.getElementById('btn-filter-history');
    if (filterOnlyHistory) {
        btn.style.background = 'rgba(99, 102, 241, 0.08)';
        btn.style.borderColor = 'var(--accent-primary)';
        btn.style.color = 'var(--accent-primary)';
    } else {
        btn.style.background = 'var(--bg-tertiary)';
        btn.style.borderColor = 'var(--border-color)';
        btn.style.color = 'var(--text-primary)';
    }
    applyFilters();
}

function handleSort(key) {
    if (sortConfig.key === key) {
        if (sortConfig.direction === 'asc') sortConfig.direction = 'desc';
        else if (sortConfig.direction === 'desc') {
            sortConfig.direction = null;
            sortConfig.key = null;
        }
    } else {
        sortConfig.key = key;
        sortConfig.direction = 'asc';
    }
    updateSortIcons();
    applyFilters();
}

function updateSortIcons() {
    const keys = ['extracode', 'date', 'lab', 'patient', 'examcode', 'doctor'];
    keys.forEach(k => {
        // Update both pending and assigned icons if they exist
        const iconPending = document.getElementById(`sort-icon-${k}`);
        const iconAssigned = document.getElementById(`sort-icon-${k}-assigned`);
        
        const setIcon = (el) => {
            if (!el) return;
            if (sortConfig.key === k) {
                el.textContent = sortConfig.direction === 'asc' ? '▲' : '▼';
                el.style.opacity = '1';
                el.style.color = 'white';
            } else {
                el.textContent = '↕️';
                el.style.opacity = '0.5';
                el.style.color = 'inherit';
            }
        };
        
        setIcon(iconPending);
        setIcon(iconAssigned);
    });
}


// ══════════════════════════════════════════════
//  Render — Pending Table
// ══════════════════════════════════════════════

function renderPendingTable() {
    renderPendingRows(pendingExams);
}

function renderPendingRows(exams) {
    const tbody = document.getElementById('tbody-pending');
    const emptyState = document.getElementById('empty-state-pending');

    if (exams.length === 0) {
        tbody.innerHTML = '';
        emptyState.style.display = 'flex';
        return;
    }

    emptyState.style.display = 'none';

    // Calculate rowspans for grouping exams of the same order
    const rowSpans = new Array(exams.length).fill(1);
    for (let i = exams.length - 1; i > 0; i--) {
        const curr = exams[i];
        const prev = exams[i - 1];
        if (
            (curr.extracode || curr.exam_id) === (prev.extracode || prev.exam_id) &&
            (curr.visitdate || curr.request_date) === (prev.visitdate || prev.request_date) &&
            (curr.lab_name || curr.laboratoryname) === (prev.lab_name || prev.laboratoryname) &&
            (curr.demogid || curr.patient_id) === (prev.demogid || prev.patient_id)
        ) {
            rowSpans[i - 1] += rowSpans[i];
            rowSpans[i] = 0;
        }
    }

    tbody.innerHTML = exams.map((exam, i) => {
        const hasSuggestion = exam.suggestion != null;
        const dateStr = formatDateDMY(exam.visitdate || exam.request_date);
        const cleanName = cleanExamName(exam.examname || exam.exam_title || '');
        const catClass = (exam.category || exam.modality || '').toLowerCase();
        const patientName = exam.patient_name || `${exam.fname || ''} ${exam.lname || ''}`.trim() || '—';
        const notesHtml = buildNotesCell(exam.notes || exam.comments || '');
        const oldVisitHtml = buildOldVisitCell(exam);

        const isSelected = selectedExams.has(exam.exam_id) ? 'checked' : '';
        const rowClass = isSelected ? 'selected-row' : '';
        const pamClass = isPammakristos(exam) ? 'pammakristos-row' : '';
        const span = rowSpans[i];
        const groupedCols = span > 0 ? `
                <td class="extracode-cell frozen-col-2" rowspan="${span}"><span class="extracode-badge">${exam.extracode || exam.exam_id}</span></td>
                <td class="date-cell" rowspan="${span}">${dateStr}</td>
                <td rowspan="${span}">${exam.lab_name || exam.laboratoryname || '—'}</td>
                <td class="demogid-cell" style="border-left: 1px solid rgba(255, 255, 255, 0.2);" rowspan="${span}">${exam.demogid || exam.patient_id || '—'}</td>
                <td style="border-right: 1px solid rgba(255, 255, 255, 0.2);" rowspan="${span}">${patientName}</td>` : '';

        return `
            <tr id="row-${exam.exam_id}" class="${rowClass} ${pamClass}">
                <td class="frozen-col-1" style="width: 48px; min-width: 48px; padding: 0; text-align: center;">
                    <input type="checkbox" class="row-checkbox" value="${exam.exam_id}" onchange="toggleSelectExam('${exam.exam_id}')" ${isSelected}>
                </td>
${groupedCols}
                <td style="border-left: 1px solid rgba(255, 255, 255, 0.2);">
                    <span class="modality-badge ${catClass}">${exam.category || exam.modality || '—'}</span>
                </td>
                <td class="examnumcode-cell">${exam.examnumcode || '—'}</td>
                <td class="exam-name-cell" style="border-right: 1px solid rgba(255, 255, 255, 0.2);"><span class="body-part-tag" title="${escapeHtmlFull(exam.examname || '')}">${cleanName || '—'}</span></td>
                <td>${exam.wname || exam.issuing_doctor_name || '—'}</td>
                <td class="comment-cell">${notesHtml}</td>
                <td class="comment-cell">${oldVisitHtml}</td>
                <td class="suggestion-cell">
                    ${hasSuggestion
                ? `<span class="suggested-name">${exam.suggestion.suggested_diagnostician_name}</span>
                           <span class="suggested-score">${Math.round(exam.suggestion.confidence_score * 100)}%</span>`
                : '<span class="no-suggestion" id="sugg-status-' + exam.exam_id + '">—</span>'
            }
                </td>
                <td>
                    <div class="btn-group">
                        ${hasSuggestion
                ? `<button class="btn btn-view" onclick="viewSuggestion('${exam.exam_id}')">Προβολή</button>`
                : `<button class="btn btn-suggest" id="sugg-btn-${exam.exam_id}" onclick="getSuggestion('${exam.exam_id}')">
                                <span class="btn-text">Πρόταση</span>
                               </button>`
            }
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    // Background fetch suggestions for visible exams that lack one
    fetchVisibleSuggestions(exams);
}

function fetchVisibleSuggestions(exams) {
    const missing = exams.filter(e => !e.suggestion && !e._fetchingSuggestion);
    if (missing.length === 0) return;
    
    missing.forEach(async exam => {
        exam._fetchingSuggestion = true;
        try {
            const btn = document.getElementById(`sugg-btn-${exam.exam_id}`);
            if (btn) btn.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;margin:auto;"></span>';
            
            let suggestion = await apiCall('/assignments/suggest', 'POST', { exam_id: exam.exam_id });
            if (!suggestion) suggestion = getMockSuggestion(exam.exam_id);
            exam.suggestion = suggestion;
            
            // Re-render if it's still visible
            if (currentTab === 'pending') {
                const tr = document.getElementById(`row-${exam.exam_id}`);
                if (tr) {
                    const rowSelected = selectedExams.has(exam.exam_id);
                    // To avoid full re-render, we just re-run applyFilters which is fast
                    applyFilters();
                }
            }
        } catch (e) {
            exam._fetchingSuggestion = false;
            const btn = document.getElementById(`sugg-btn-${exam.exam_id}`);
            if (btn) btn.innerHTML = '<span class="btn-text">Πρόταση</span>';
        }
    });
}


// ══════════════════════════════════════════════
//  Render — Assigned Table
// ══════════════════════════════════════════════

function renderAssignedTable() {
    renderAssignedRows(assignedExams);
}

function renderAssignedRows(exams) {
    const tbody = document.getElementById('tbody-assigned');
    const emptyState = document.getElementById('empty-state-assigned');

    if (exams.length === 0) {
        tbody.innerHTML = '';
        emptyState.style.display = 'flex';
        return;
    }

    emptyState.style.display = 'none';

    // Calculate rowspans for grouping exams of the same order
    const rowSpans = new Array(exams.length).fill(1);
    for (let i = exams.length - 1; i > 0; i--) {
        const curr = exams[i];
        const prev = exams[i - 1];
        if (
            (curr.extracode || curr.exam_id) === (prev.extracode || prev.exam_id) &&
            (curr.visitdate || curr.request_date) === (prev.visitdate || prev.request_date) &&
            (curr.lab_name || curr.laboratoryname) === (prev.lab_name || prev.laboratoryname) &&
            (curr.demogid || curr.patient_id) === (prev.demogid || prev.patient_id)
        ) {
            rowSpans[i - 1] += rowSpans[i];
            rowSpans[i] = 0;
        }
    }

    tbody.innerHTML = exams.map((exam, i) => {
        const dateStr = formatDateDMY(exam.visitdate || exam.request_date);
        const cleanName = cleanExamName(exam.examname || exam.exam_title || '');
        const catClass = (exam.category || exam.modality || '').toLowerCase();
        const patientName = exam.patient_name || `${exam.fname || ''} ${exam.lname || ''}`.trim() || '—';
        const diagName = exam.code || exam.diagnostician_name || exam.assigned_diagnostician_name || '—';
        const notesHtml = buildNotesCell(exam.notes || exam.comments || '');
        const oldVisitHtml = buildOldVisitCell(exam);
        const isSelected = selectedAssignedExams.has(exam.exam_id);
        const rowClass = isSelected ? 'selected-row' : '';
        const pamClass = isPammakristos(exam) ? 'pammakristos-row' : '';
        const exammoreid = exam.exammoreid || '';
        
        const span = rowSpans[i];
        const groupedCols = span > 0 ? `
                <td class="extracode-cell" rowspan="${span}"><span class="extracode-badge">${exam.extracode || exam.exam_id}</span></td>
                <td class="date-cell" rowspan="${span}">${dateStr}</td>
                <td rowspan="${span}">${exam.lab_name || exam.laboratoryname || '—'}</td>
                <td class="demogid-cell" style="border-left: 1px solid rgba(255, 255, 255, 0.2);" rowspan="${span}">${exam.demogid || exam.patient_id || '—'}</td>
                <td style="border-right: 1px solid rgba(255, 255, 255, 0.2);" rowspan="${span}">${patientName}</td>` : '';

        return `
            <tr id="assigned-row-${exam.exam_id}" class="${rowClass} ${pamClass}">
                <td style="width: 48px; min-width: 48px; padding: 0; text-align: center;">
                    <input type="checkbox" class="assigned-row-checkbox" value="${exam.exam_id}"
                        data-exammoreid="${exammoreid}"
                        onchange="toggleSelectAssignedExam('${exam.exam_id}')" ${isSelected ? 'checked' : ''}>
                </td>
${groupedCols}
                <td style="border-left: 1px solid rgba(255, 255, 255, 0.2);">
                    <span class="modality-badge ${catClass}">${exam.category || exam.modality || '—'}</span>
                </td>
                <td class="examnumcode-cell">${exam.examnumcode || '—'}</td>
                <td class="exam-name-cell" style="border-right: 1px solid rgba(255, 255, 255, 0.2);"><span class="body-part-tag" title="${escapeHtmlFull(exam.examname || '')}">${cleanName || '—'}</span></td>
                <td>${exam.wname || exam.issuing_doctor_name || '—'}</td>
                <td class="comment-cell">${notesHtml}</td>
                <td class="comment-cell">${oldVisitHtml}</td>
                <td><span class="assigned-name">${diagName}</span></td>
                <td>
                    <div class="btn-group">
                        <button class="btn btn-slis-update btn-sm" onclick="updateExamOnSlis('${exam.exam_id}', ${exammoreid || 'null'})">
                            Update on Slis
                        </button>
                        <button class="btn btn-secondary btn-sm" onclick="changeAssignment('${exam.exam_id}')">
                            Αλλαγή
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}


// ══════════════════════════════════════════════
//  Suggestion Flow
// ══════════════════════════════════════════════

async function getSuggestion(examId) {
    const btn = event.target.closest('.btn');
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '<span class="loading-spinner"></span>';
    btn.disabled = true;

    try {
        let suggestion = await apiCall('/assignments/suggest', 'POST', { exam_id: examId });
        if (!suggestion) suggestion = getMockSuggestion(examId);

        const exam = pendingExams.find(e => e.exam_id === examId);
        if (exam) exam.suggestion = suggestion;

        renderPendingTable();
        applyFilters();
        openSuggestionModal(examId, suggestion);

    } catch (err) {
        showToast(`Σφάλμα: ${err.message}`, 'error');
        btn.innerHTML = originalHTML;
        btn.disabled = false;
    }
}

function viewSuggestion(examId) {
    let exam = pendingExams.find(e => e.exam_id === examId);
    if (!exam) exam = assignedExams.find(e => e.exam_id === examId);
    if (exam && exam.suggestion) openSuggestionModal(examId, exam.suggestion);
}

async function changeAssignment(examId) {
    const btn = event.target.closest('.btn');
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '<span class="loading-spinner"></span>';
    btn.disabled = true;

    try {
        let suggestion = await apiCall('/assignments/suggest', 'POST', { exam_id: examId });
        if (!suggestion) suggestion = getMockSuggestion(examId);

        const exam = assignedExams.find(e => e.exam_id === examId);
        if (exam) exam.suggestion = suggestion;

        openSuggestionModal(examId, suggestion);

    } catch (err) {
        showToast(`Σφάλμα: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = originalHTML;
        btn.disabled = false;
    }
}


// ══════════════════════════════════════════════
//  Suggestion Modal
// ══════════════════════════════════════════════

function openSuggestionModal(examId, suggestion) {
    currentExamId = examId;
    currentSuggestion = suggestion;
    let exam = pendingExams.find(e => e.exam_id === examId);
    if (!exam) exam = assignedExams.find(e => e.exam_id === examId);

    // Exam summary
    document.getElementById('modal-exam-summary').innerHTML = `
        <strong>${exam.exam_id}</strong> — ${exam.patient_name}<br>
        <strong>Τύπος:</strong> ${exam.modality} ${translateBodyPart(exam.body_part)} &nbsp;|&nbsp;
        <strong>Εργαστήριο:</strong> ${exam.lab_name} &nbsp;|&nbsp;
        <strong>Ιατρός:</strong> ${exam.issuing_doctor_name}
        ${exam.comments ? `<br><strong>Σχόλια:</strong> <span style="color:var(--accent-warning);">${exam.comments}</span>` : ''}
    `;

    // Suggestion card
    document.getElementById('suggestion-name').textContent = suggestion.suggested_diagnostician_name;
    document.getElementById('suggestion-score').textContent = `${Math.round(suggestion.confidence_score * 100)}%`;

    const tagEl = document.getElementById('suggestion-tag');
    if (suggestion.is_direct_assignment) {
        tagEl.textContent = `⚡ ${suggestion.direct_assignment_reason}`;
        tagEl.style.color = 'var(--accent-warning)';
    } else {
        tagEl.textContent = `Κανόνες: ${suggestion.rules_fired.map(r => translateRule(r)).join(', ')}`;
        tagEl.style.color = 'var(--accent-success)';
    }

    // Score breakdown
    const breakdownList = document.getElementById('breakdown-list');
    breakdownList.innerHTML = suggestion.score_breakdown.map(comp => {
        const scoreClass = comp.weighted_score > 0 ? 'positive' : comp.weighted_score < 0 ? 'negative' : 'neutral';
        const barWidth = Math.abs(comp.raw_score) * 100;
        return `
            <div class="breakdown-item">
                <span class="rule-name">${comp.display_name}</span>
                <span class="rule-explanation">${comp.explanation}</span>
                <span class="rule-score ${scoreClass}">${comp.weighted_score > 0 ? '+' : ''}${comp.weighted_score.toFixed(3)}</span>
                <div class="score-bar">
                    <div class="score-bar-fill" style="width:${barWidth}%"></div>
                </div>
            </div>
        `;
    }).join('');

    // Alternatives — including eliminated (red) ones
    const altList = document.getElementById('alternatives-list');
    const altSection = document.getElementById('alternatives-section');
    const alternatives = suggestion.alternatives || [];

    if (alternatives.length > 0) {
        altSection.style.display = 'block';
        let rankCounter = 2; // Suggestion is #1

        altList.innerHTML = alternatives.map(alt => {
            if (alt.eliminated) {
                // Eliminated by hard filter — shown with red background
                return `
                    <div class="alternative-item eliminated" onclick="selectAlternative(${alt.id}, '${escapeHtml(alt.name)}', true)">
                        <span class="alt-rank">—</span>
                        <span class="alt-name">${alt.name}</span>
                        <span class="alt-eliminated-badge">⛔ Εξαιρέθηκε</span>
                        <span class="alt-elimination-reason">${alt.elimination_reason || ''}</span>
                    </div>
                `;
            } else if (Math.round(alt.score * 100) === 0) {
                return `
                    <div class="alternative-item eliminated" onclick="selectAlternative(${alt.id}, '${escapeHtml(alt.name)}', true)">
                        <span class="alt-rank">—</span>
                        <span class="alt-name">${alt.name}</span>
                        <span class="alt-eliminated-badge">⛔ 0% Βαθμολογία</span>
                        <span class="alt-elimination-reason">Δεν πληροί κανένα κριτήριο προτίμησης</span>
                    </div>
                `;
            } else {
                const rank = rankCounter++;
                return `
                    <div class="alternative-item" onclick="selectAlternative(${alt.id}, '${escapeHtml(alt.name)}', false)">
                        <span class="alt-rank">#${rank}</span>
                        <span class="alt-name">${alt.name}</span>
                        <span class="alt-score">${Math.round(alt.score * 100)}%</span>
                    </div>
                `;
            }
        }).join('');
    } else {
        altSection.style.display = 'none';
    }

    // Override dropdown — include eliminated ones with a label
    const overrideSelect = document.getElementById('override-select');
    overrideSelect.innerHTML = '<option value="">— Επιλέξτε εναλλακτικό —</option>';

    // Non-eliminated alternatives
    const scored = alternatives.filter(a => !a.eliminated && Math.round(a.score * 100) > 0);
    if (scored.length) {
        const grp1 = document.createElement('optgroup');
        grp1.label = 'Αξιολογημένοι';
        scored.forEach(alt => {
            grp1.innerHTML += `<option value="${alt.id}">${alt.name} (${Math.round(alt.score * 100)}%)</option>`;
        });
        overrideSelect.appendChild(grp1);
    }

    // Eliminated alternatives (can still be manually chosen)
    const eliminated = alternatives.filter(a => a.eliminated || Math.round(a.score * 100) === 0);
    if (eliminated.length) {
        const grp2 = document.createElement('optgroup');
        grp2.label = 'Εξαιρεθέντες (χειροκίνητη παράκαμψη)';
        eliminated.forEach(alt => {
            const badge = alt.eliminated ? 'Εξαιρέθηκε' : '0%';
            grp2.innerHTML += `<option value="${alt.id}">${alt.name} ⛔ ${badge}</option>`;
        });
        overrideSelect.appendChild(grp2);
    }

    document.getElementById('suggestion-modal').style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    document.getElementById('suggestion-modal').style.display = 'none';
    document.body.style.overflow = '';
    currentExamId = null;
    currentSuggestion = null;
    // Bug fix: re-enable buttons for next use
    const btnConfirm = document.getElementById('btn-confirm');
    const btnOverride = document.getElementById('btn-override');
    if (btnConfirm) { btnConfirm.disabled = false; btnConfirm.innerHTML = '✓ Επιβεβαίωση'; }
    if (btnOverride) { btnOverride.disabled = false; btnOverride.innerHTML = 'Αλλαγή'; }
}

function selectAlternative(id, name, isEliminated) {
    const select = document.getElementById('override-select');
    select.value = id.toString();
    if (isEliminated) {
        // Pre-fill a reason prompt for eliminated ones
        const reasonInput = document.getElementById('override-reason');
        if (!reasonInput.value) reasonInput.placeholder = 'Αιτιολογία παράκαμψης κανόνα (απαιτείται)';
    }
    document.getElementById('override-section').scrollIntoView({ behavior: 'smooth' });
}


// ══════════════════════════════════════════════
//  Confirm / Override
// ══════════════════════════════════════════════

async function confirmAssignment() {
    if (!currentExamId || !currentSuggestion) return;

    const btn = document.getElementById('btn-confirm');
    btn.innerHTML = '<span class="loading-spinner"></span>';
    btn.disabled = true;

    try {
        await apiCall('/assignments/confirm', 'POST', {
            exam_id: currentExamId,
            diagnostician_id: currentSuggestion.suggested_diagnostician_id,
        });
    } catch { /* Continue in mock mode */ }

    // Handle moving or updating exam state
    let exam = pendingExams.find(e => e.exam_id === currentExamId);
    let wasPending = true;
    if (!exam) {
        exam = assignedExams.find(e => e.exam_id === currentExamId);
        wasPending = false;
    }

    if (exam) {
        const updatedExam = {
            ...exam,
            status: 'assigned',
            assigned_diagnostician_id: currentSuggestion.suggested_diagnostician_id,
            assigned_diagnostician_name: currentSuggestion.suggested_diagnostician_name,
            code: currentSuggestion.suggested_diagnostician_name,
            diagnostis: currentSuggestion.suggested_diagnostician_id,
            assigned_at: new Date().toISOString(),
        };

        if (wasPending) {
            pendingExams = pendingExams.filter(e => e.exam_id !== currentExamId);
        }
        assignedExams = assignedExams.filter(e => e.exam_id !== currentExamId);
        assignedExams.unshift(updatedExam);
    }

    renderPendingTable();
    renderAssignedTable();
    updateTabCounts();

    showToast(`✅ Ανατέθηκε στον/στην ${currentSuggestion.suggested_diagnostician_name}`, 'success');
    closeModal();
}

async function overrideAssignment() {
    if (!currentExamId || !currentSuggestion) return;

    const select = document.getElementById('override-select');
    const reason = document.getElementById('override-reason').value;

    if (!select.value) {
        showToast('Επιλέξτε εναλλακτικό ακτινοδιαγνώστη', 'warning');
        return;
    }

    const overrideId = parseInt(select.value);
    const optText = select.options[select.selectedIndex].text;
    const overrideName = optText.split(' (')[0].replace(' ⛔ Εξαιρέθηκε', '');

    const btn = document.getElementById('btn-override');
    btn.innerHTML = '<span class="loading-spinner"></span>';
    btn.disabled = true;

    try {
        await apiCall('/assignments/override', 'POST', {
            exam_id: currentExamId,
            original_diagnostician_id: currentSuggestion.suggested_diagnostician_id,
            override_diagnostician_id: overrideId,
            reason,
        });
    } catch { /* Continue in mock mode */ }

    // Handle moving or updating exam state
    let exam = pendingExams.find(e => e.exam_id === currentExamId);
    let wasPending = true;
    if (!exam) {
        exam = assignedExams.find(e => e.exam_id === currentExamId);
        wasPending = false;
    }

    if (exam) {
        const updatedExam = {
            ...exam,
            status: 'assigned',
            assigned_diagnostician_id: overrideId,
            assigned_diagnostician_name: overrideName,
            code: overrideName,
            diagnostis: overrideId,
            assigned_at: new Date().toISOString(),
        };

        if (wasPending) {
            pendingExams = pendingExams.filter(e => e.exam_id !== currentExamId);
        }
        assignedExams = assignedExams.filter(e => e.exam_id !== currentExamId);
        assignedExams.unshift(updatedExam);
    }

    renderPendingTable();
    renderAssignedTable();
    updateTabCounts();

    showToast(
        `⚠️ Αλλαγή → ${overrideName} (αντί ${currentSuggestion.suggested_diagnostician_name})`,
        'warning'
    );
    closeModal();
}


// ══════════════════════════════════════════════
//  Admin Auth
// ══════════════════════════════════════════════

function restoreAdminState() {
    if (adminToken) showAdminLoggedIn();
    else showAdminLoggedOut();
}

function openLoginModal() {
    document.getElementById('login-modal').style.display = 'flex';
    document.body.style.overflow = 'hidden';
    setTimeout(() => document.getElementById('login-username').focus(), 100);
}

function closeLoginModal() {
    document.getElementById('login-modal').style.display = 'none';
    document.body.style.overflow = '';
    document.getElementById('login-error').style.display = 'none';
}

async function doLogin() {
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    const errorEl = document.getElementById('login-error');
    const btn = document.getElementById('btn-do-login');

    if (!username || !password) {
        errorEl.textContent = 'Συμπληρώστε όνομα χρήστη και κωδικό.';
        errorEl.style.display = 'block';
        return;
    }

    btn.innerHTML = '<span class="loading-spinner"></span>';
    btn.disabled = true;
    errorEl.style.display = 'none';

    try {
        const data = await apiCall('/admin/auth/login', 'POST', { username, password });
        if (data && data.token) {
            adminToken = data.token;
            sessionStorage.setItem('adminToken', adminToken);
            showAdminLoggedIn();
            closeLoginModal();
            showToast('✅ Συνδεθήκατε ως Διαχειριστής', 'success');
        } else {
            // Mock mode: accept admin/admin1234
            if (username === 'admin' && password === 'admin1234') {
                adminToken = 'mock-token-' + Date.now();
                sessionStorage.setItem('adminToken', adminToken);
                showAdminLoggedIn();
                closeLoginModal();
                showToast('✅ Συνδεθήκατε ως Διαχειριστής (mock)', 'success');
            } else {
                throw new Error('Λάθος στοιχεία σύνδεσης');
            }
        }
    } catch (err) {
        errorEl.textContent = err.message || 'Λάθος στοιχεία σύνδεσης.';
        errorEl.style.display = 'block';
    } finally {
        btn.textContent = 'Σύνδεση';
        btn.disabled = false;
    }
}

function adminLogout() {
    adminToken = null;
    sessionStorage.removeItem('adminToken');
    showAdminLoggedOut();
    showToast('Αποσυνδεθήκατε από το Admin Panel', 'info');
}

function showAdminLoggedIn() {
    document.getElementById('btn-admin-login').style.display = 'none';
    document.getElementById('admin-logged-in').style.display = 'flex';
}

function showAdminLoggedOut() {
    document.getElementById('btn-admin-login').style.display = 'flex';
    document.getElementById('admin-logged-in').style.display = 'none';
}

function goToAdmin() {
    window.location.href = 'admin.html';
}


// ══════════════════════════════════════════════
//  Toast Notifications
// ══════════════════════════════════════════════

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const icons = { success: '✅', warning: '⚠️', error: '❌', info: 'ℹ️' };

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type]}</span>
        <span class="toast-message">${message}</span>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'toastOut var(--transition-base) forwards';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}


// ══════════════════════════════════════════════
//  Helpers
// ══════════════════════════════════════════════

// ── Exam name cleaning ──
/**
 * Strip boilerplate prefixes from Greek exam names.
 * Removes: ΜΑΓΝΗΤΙΚΗ, ΑΞΟΝΙΚΗ, ΑΓΓΕΙΟΓΡΑΦΙΑ, ΤΟΜΟΓΡΑΦΙΑ, (MRI), (MRA)
 * then collapses multiple spaces and trims.
 */
function cleanExamName(raw) {
    if (!raw) return '';
    return raw
        .replace(/\(MRI\)/gi, '')
        .replace(/\(MRA\)/gi, '')
        .replace(/ΜΑΓΝΗΤΙΚΗ\s*/gi, '')
        .replace(/ΑΞΟΝΙΚΗ\s*/gi, '')
        .replace(/ΑΓΓΕΙΟΓΡΑΦΙΑ\s*/gi, '')
        .replace(/ΤΟΜΟΓΡΑΦΙΑ\s*/gi, '')
        .replace(/\s{2,}/g, ' ')
        .trim();
}

// ── Notes cell builder ──
/**
 * Returns the HTML for the Σχόλια cell.
 * Shows a 💬 button on hover only if notes are non-empty
 * (empty = null | '' | ' *  * ').
 */
const EMPTY_NOTES_RE = /^\s*\*\s*\*\s*$/;

function buildNotesCell(notes) {
    if (!notes || EMPTY_NOTES_RE.test(notes)) {
        return '<span style="color:var(--text-tertiary)">—</span>';
    }
    // Strip the trailing ' *  * ' separator and trim
    const display = notes.replace(/\*\s*\*\s*$/, '').trim();
    if (!display) return '<span style="color:var(--text-tertiary)">—</span>';

    let isRed = false;
    
    const displayUpper = normalizeGreek(display);
    const surnames = ["ΠΑΠΟΥΤΣΗ", "ΝΑΤΣΙΚΑ"];
    
    if (typeof diagnosticians !== 'undefined' && diagnosticians.length > 0) {
        diagnosticians.forEach(d => {
            if (d.active && d.name) {
                const surname = d.name.trim().split(/\s+/)[0];
                if (surname.length > 3) {
                    let s = normalizeGreek(surname);
                    // Handle Greek grammatical cases by stripping terminal Σ
                    if (s.endsWith('Σ') || s.endsWith('S')) {
                        s = s.slice(0, -1);
                    }
                    surnames.push(s);
                    // Add a 7-character prefix for abbreviated names
                    if (s.length > 7) {
                        surnames.push(s.substring(0, 7));
                    }
                }
            }
        });
    }
    
    for (const surname of surnames) {
        if (displayUpper.includes(surname)) {
            isRed = true;
            break;
        }
    }

    const btnClass = isRed ? 'comment-btn comment-btn-alert' : 'comment-btn';

    return `<div class="comment-btn-wrap">
        <button class="${btnClass}">💬 Σχόλιο</button>
        <div class="comment-popup">${escapeHtmlFull(display)}</div>
    </div>`;
}

// ── Old visit cell builder ──
/**
 * Returns the HTML for the Τελ. Επίσκεψη cell.
 * Shows a 🕐 button on hover only if OLDVISIT ≠ 0.
 */
function buildOldVisitCell(exam) {
    const ov = exam.oldvisit;
    if (!ov || ov === 0) {
        return '<span style="color:var(--text-tertiary)">—</span>';
    }
    const lines = [
        exam.oldorder ? `Ημ/νία: ${formatDateDMY(exam.oldorder)}` : null,
        exam.olddiagnostis && exam.olddiagnostis !== '-' ? `Διαγνώστης: ${exam.olddiagnostis}` : null,
    ].filter(Boolean).join('<br>');
    return `<div class="comment-btn-wrap">
        <button class="comment-btn" style="background:rgba(59,130,246,0.12);color:var(--accent-info);border:1px solid rgba(59,130,246,0.3);">🕐 Ιστορικό</button>
        <div class="comment-popup">${lines || '—'}</div>
    </div>`;
}

// ── Lab filter ── dynamically populated from loaded data ──
function buildLabDropdown(exams) {
    const labDropdown = document.getElementById('lab-dropdown');
    if (!labDropdown) return;

    // Collect unique lab names
    const labs = new Map();
    exams.forEach(e => {
        const name = (e.lab_name || e.laboratoryname || '').trim();
        if (name) labs.set(name, name);
    });
    [...assignedExams].forEach(e => {
        const name = (e.lab_name || e.laboratoryname || '').trim();
        if (name) labs.set(name, name);
    });

    if (labs.size === 0) return;

    labDropdown.innerHTML = [...labs.entries()].sort((a, b) => a[0].localeCompare(b[0], 'el')).map(([name]) => {
        const id = `lab-${name.replace(/\s+/g, '-').toLowerCase()}`;
        return `<label class="lab-option">
            <input type="checkbox" id="${id}" value="${escapeHtmlFull(name)}" onchange="applyFilters()">
            <label for="${id}">${escapeHtmlFull(name)}</label>
        </label>`;
    }).join('');
}


function translateBodyPart(part) {
    const map = {
        abdomen: 'Κοιλία',
        chest: 'Θώρακας',
        neuro: 'Εγκέφαλος',
        msk: 'Μυοσκελετικό',
        spine: 'Σπονδυλική Στήλη',
        pelvis: 'Πύελος',
    };
    return map[part?.toLowerCase()] || part || '—';
}

function translateRule(rule) {
    const map = {
        capacity: 'Χωρητικότητα',
        skills: 'Εξειδίκευση',
        partnership: 'Συνεργασία',
        patient_history: 'Ιστορικό',
        lab_preference: 'Εργαστήριο',
        comment_exclusion: 'Σχόλια',
        subcategory_load: 'Φόρτος',
    };
    return map[rule] || rule;
}

function formatDateDMY(dateStr) {
    if (!dateStr) return '—';
    try {
        // Handles 'YYYY-MM-DD' or datetime strings
        const d = new Date(dateStr + (dateStr.length === 10 ? 'T00:00:00' : ''));
        if (isNaN(d)) return dateStr;
        const dd = String(d.getDate()).padStart(2, '0');
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const yyyy = d.getFullYear();
        return `${dd}-${mm}-${yyyy}`;
    } catch { return dateStr; }
}

function formatDate(dateStr) {
    return formatDateDMY(dateStr);
}

function formatTime(isoStr) {
    if (!isoStr) return '—';
    try {
        const d = new Date(isoStr);
        return d.toLocaleTimeString('el-GR', { hour: '2-digit', minute: '2-digit' });
    } catch { return isoStr; }
}

function escapeHtml(str) {
    return String(str).replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

function escapeHtmlFull(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ── Lab dropdown toggle ──
function toggleLabDropdown(event) {
    event.stopPropagation();
    const wrap = document.getElementById('lab-filter-wrap');
    wrap.classList.toggle('open');
}

// Close lab dropdown when clicking outside
document.addEventListener('click', function (e) {
    const wrap = document.getElementById('lab-filter-wrap');
    if (wrap && !wrap.contains(e.target)) {
        wrap.classList.remove('open');
    }
});


// ══════════════════════════════════════════════
//  Mock Data
// ══════════════════════════════════════════════

function getMockPendingExams() {
    return [
        {
            exam_id: '2783481', extracode: 2783481, visitid: 2798982,
            demogid: 525331, patient_id: '525331',
            fname: 'ΠΑΝΑΓΙΩΤΑ', lname: 'ΜΠΕΚΡΗ',
            patient_name: 'ΠΑΝΑΓΙΩΤΑ ΜΠΕΚΡΗ',
            examnumcode: 22642, examname: 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ (MRI) ΔΕΞΙΑΣ ΠΟΔΟΚΝΗΜΙΚΗΣ',
            modality: 'MRI', category: 'MRI', body_part: '',
            visitdate: '2026-07-13', request_date: '2026-07-13',
            labcodeid: 6, lab_id: 'ΑΝΩ ΠΑΤΗΣΙΑ', lab_name: 'ΑΝΩ ΠΑΤΗΣΙΑ',
            wcode: '2015', wname: 'ΜΠΡΑΝΤΖΙΚΟΣ ΤΑΞΙΑΡΧΗΣ',
            issuing_doctor_id: '2015', issuing_doctor_name: 'ΜΠΡΑΝΤΖΙΚΟΣ ΤΑΞΙΑΡΧΗΣ',
            diagnostis: null, code: null, diagnostician_name: '',
            notes: ' *  * ', comments: '',
            oldvisit: 0, oldorder: '', olddiagnostis: '',
            status: 'pending', suggestion: null, is_pamakristos: false,
        },
        {
            exam_id: '2783486', extracode: 2783486, visitid: 2798987,
            demogid: 789636, patient_id: '789636',
            fname: 'ΙΩΑΝΝΗΣ', lname: 'ΧΑΡΗΣ',
            patient_name: 'ΙΩΑΝΝΗΣ ΧΑΡΗΣ',
            examnumcode: 22140, examname: 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ (MRI) ΟΣΦΥΪΚΗΣ ΜΟΙΡΑΣ Σ.Σ.',
            modality: 'MRI', category: 'MRI', body_part: '',
            visitdate: '2026-07-13', request_date: '2026-07-13',
            labcodeid: 7, lab_id: 'ΙΛΙΟΝ', lab_name: 'ΙΛΙΟΝ',
            wcode: '569352', wname: 'ΑΝΔΡΕΟΠΟΥΛΟΣ ΑΣΗΜΑΚΗΣ',
            issuing_doctor_id: '569352', issuing_doctor_name: 'ΑΝΔΡΕΟΠΟΥΛΟΣ ΑΣΗΜΑΚΗΣ',
            diagnostis: null, code: null, diagnostician_name: '',
            notes: 'ΘΑ ΠΑΡΕΙ CD--ΕΜΑΙΛ *  * ', comments: 'ΘΑ ΠΑΡΕΙ CD--ΕΜΑΙΛ',
            oldvisit: 0, oldorder: '', olddiagnostis: '',
            status: 'pending', suggestion: null, is_pamakristos: false,
        },
    ];
}

function getMockAssignedExams() {
    return [
        {
            exam_id: '2783481', extracode: 2783481, visitid: 2798982,
            demogid: 525331, patient_id: '525331',
            fname: 'ΠΑΝΑΓΙΩΤΑ', lname: 'ΜΠΕΚΡΗ',
            patient_name: 'ΠΑΝΑΓΙΩΤΑ ΜΠΕΚΡΗ',
            examnumcode: 22642, examname: 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ (MRI) ΔΕΞΙΑΣ ΠΟΔΟΚΝΗΜΙΚΗΣ',
            modality: 'MRI', category: 'MRI', body_part: '',
            visitdate: '2026-07-13', request_date: '2026-07-13',
            labcodeid: 6, lab_id: 'ΑΝΩ ΠΑΤΗΣΙΑ', lab_name: 'ΑΝΩ ΠΑΤΗΣΙΑ',
            wcode: '2015', wname: 'ΜΠΡΑΝΤΖΙΚΟΣ ΤΑΞΙΑΡΧΗΣ',
            issuing_doctor_id: '2015', issuing_doctor_name: 'ΜΠΡΑΝΤΖΙΚΟΣ ΤΑΞΙΑΡΧΗΣ',
            diagnostis: 189, code: 'ΛΙΟΝΤΟΣ', diagnostician_name: 'ΛΙΟΝΤΟΣ',
            assigned_diagnostician_name: 'ΛΙΟΝΤΟΣ',
            notes: ' *  * ', comments: '',
            oldvisit: 0, oldorder: '', olddiagnostis: '',
            status: 'assigned', suggestion: null, is_pamakristos: false,
        },
    ];
}

function getMockDiagnosticians() {
    return [
        { id: 1, name: 'Νάτσικα Α.', can_ct: true, can_mri: true, daily_quota: 15, current_day_count: 5, available: true },
        { id: 2, name: 'Κωνσταντίνου Β.', can_ct: true, can_mri: true, daily_quota: 12, current_day_count: 3, available: true },
        { id: 3, name: 'Παπαδόπουλος Γ.', can_ct: true, can_mri: true, daily_quota: 18, current_day_count: 8, available: true },
        { id: 4, name: 'Λιάκος Δ.', can_ct: true, can_mri: false, daily_quota: 10, current_day_count: 4, available: true },
        { id: 5, name: 'Δημητρίου Ε.', can_ct: true, can_mri: true, daily_quota: 14, current_day_count: 6, available: true },
        { id: 6, name: 'Αντωνίου Ζ.', can_ct: true, can_mri: true, daily_quota: 16, current_day_count: 0, available: false },
    ];
}

function getMockSuggestion(examId) {
    const exam = pendingExams.find(e => e.exam_id === examId);

    const suggestions = {
        'EX-2026-001': {
            exam_id: examId, patient_id: 'PT-5432',
            exam_summary: 'MRI Κοιλία — Dr. Παπαδόπουλος Ν. — Lab Κηφισιά',
            suggested_diagnostician_id: 1,
            suggested_diagnostician_name: 'Νάτσικα Α.',
            confidence_score: 0.847,
            score_breakdown: [
                { rule: 'capacity', display_name: 'Χωρητικότητα', raw_score: 0.667, weight: 0.30, weighted_score: 0.200, explanation: 'Υπόλοιπο: 10/15 εξετάσεις' },
                { rule: 'partnership', display_name: 'Συνεργασία Ιατρού', raw_score: 0.0, weight: 0.25, weighted_score: 0.0, explanation: 'Δεν υπάρχει συνεργασία με τον ιατρό' },
                { rule: 'skills', display_name: 'Εξειδίκευση', raw_score: 0.9, weight: 0.15, weighted_score: 0.135, explanation: 'Εξειδίκευση στο \'abdomen\' (MRI): 90%' },
                { rule: 'lab_preference', display_name: 'Προτίμηση Εργαστηρίου', raw_score: 1.0, weight: 0.10, weighted_score: 0.10, explanation: 'Αποδέχεται εξετάσεις από \'Κηφισιά\'' },
                { rule: 'patient_history', display_name: 'Ιστορικό Ασθενή', raw_score: 0.9, weight: 0.15, weighted_score: 0.135, explanation: 'Η Νάτσικα Α. έχει αξιολογήσει 3 παρόμοιες εξετάσεις αυτού του ασθενή' },
                { rule: 'subcategory_load', display_name: 'Ποινή Υποκατηγορίας', raw_score: 0.6, weight: 0.05, weighted_score: -0.030, explanation: 'Φόρτος κατηγορίας \'abdomen\': 3/5 (ήπιο όριο)' },
            ],
            // Alternatives include one eliminated by hard filter
            alternatives: [
                { id: 3, name: 'Παπαδόπουλος Γ.', score: 0.612, eliminated: false, elimination_reason: null },
                { id: 5, name: 'Δημητρίου Ε.', score: 0.498, eliminated: false, elimination_reason: null },
                { id: 2, name: 'Κωνσταντίνου Β.', score: 0.321, eliminated: false, elimination_reason: null },
                { id: 6, name: 'Αντωνίου Ζ.', score: 0.0, eliminated: true, elimination_reason: 'Ο/Η Αντωνίου Ζ. δεν είναι διαθέσιμος/η σήμερα' },
                { id: 4, name: 'Λιάκος Δ.', score: 0.0, eliminated: true, elimination_reason: 'Ο/Η Λιάκος Δ. δεν αξιολογεί μαγνητικές τομογραφίες (MRI)' },
            ],
            rules_fired: ['capacity', 'skills', 'patient_history'],
            solver_status: 'GREEDY', is_direct_assignment: false, direct_assignment_reason: '',
            pipeline_timestamp: new Date().toISOString(),
        },
        'EX-2026-002': {
            exam_id: examId, patient_id: 'PT-8821',
            exam_summary: 'CT Θώρακας — Dr. Ιωάννου Ε. — Lab Μαρούσι',
            suggested_diagnostician_id: 2,
            suggested_diagnostician_name: 'Κωνσταντίνου Β.',
            confidence_score: 0.921,
            score_breakdown: [
                { rule: 'capacity', display_name: 'Χωρητικότητα', raw_score: 0.75, weight: 0.30, weighted_score: 0.225, explanation: 'Υπόλοιπο: 9/12 εξετάσεις' },
                { rule: 'partnership', display_name: 'Συνεργασία Ιατρού', raw_score: 1.0, weight: 0.25, weighted_score: 0.25, explanation: 'Προτίμηση ιατρού \'Ιωάννου Ε.\' → Κωνσταντίνου Β. (προτεραιότητα: 4)' },
                { rule: 'skills', display_name: 'Εξειδίκευση', raw_score: 0.95, weight: 0.15, weighted_score: 0.143, explanation: 'Εξειδίκευση στο \'chest\' (CT): 95%' },
                { rule: 'lab_preference', display_name: 'Προτίμηση Εργαστηρίου', raw_score: 1.0, weight: 0.10, weighted_score: 0.10, explanation: 'Αποδέχεται εξετάσεις από \'Μαρούσι\'' },
                { rule: 'patient_history', display_name: 'Ιστορικό Ασθενή', raw_score: 0.0, weight: 0.15, weighted_score: 0.0, explanation: 'Δεν υπάρχει ιστορικό' },
                { rule: 'subcategory_load', display_name: 'Ποινή Υποκατηγορίας', raw_score: 0.5, weight: 0.05, weighted_score: -0.025, explanation: 'Φόρτος κατηγορίας \'chest\': 2/4 (ήπιο όριο)' },
            ],
            alternatives: [
                { id: 4, name: 'Λιάκος Δ.', score: 0.689, eliminated: false, elimination_reason: null },
                { id: 1, name: 'Νάτσικα Α.', score: 0.423, eliminated: false, elimination_reason: null },
                { id: 6, name: 'Αντωνίου Ζ.', score: 0.0, eliminated: true, elimination_reason: 'Ο/Η Αντωνίου Ζ. δεν είναι διαθέσιμος/η σήμερα' },
            ],
            rules_fired: ['capacity', 'partnership', 'skills'],
            solver_status: 'GREEDY', is_direct_assignment: false, direct_assignment_reason: '',
            pipeline_timestamp: new Date().toISOString(),
        },
    };

    return suggestions[examId] || {
        exam_id: examId, patient_id: exam?.patient_id || '',
        exam_summary: `${exam?.modality || ''} ${translateBodyPart(exam?.body_part)} — ${exam?.lab_name || ''}`,
        suggested_diagnostician_id: 3,
        suggested_diagnostician_name: 'Παπαδόπουλος Γ.',
        confidence_score: 0.72,
        score_breakdown: [
            { rule: 'capacity', display_name: 'Χωρητικότητα', raw_score: 0.556, weight: 0.30, weighted_score: 0.167, explanation: 'Υπόλοιπο: 10/18 εξετάσεις' },
            { rule: 'partnership', display_name: 'Συνεργασία Ιατρού', raw_score: 0.0, weight: 0.25, weighted_score: 0.0, explanation: 'Δεν υπάρχει συνεργασία' },
            { rule: 'skills', display_name: 'Εξειδίκευση', raw_score: 0.7, weight: 0.15, weighted_score: 0.105, explanation: 'Εξειδίκευση: 70%' },
            { rule: 'lab_preference', display_name: 'Προτίμηση Εργαστηρίου', raw_score: 1.0, weight: 0.10, weighted_score: 0.10, explanation: 'Αποδέχεται εξετάσεις' },
            { rule: 'patient_history', display_name: 'Ιστορικό Ασθενή', raw_score: 0.0, weight: 0.15, weighted_score: 0.0, explanation: 'Δεν υπάρχει ιστορικό' },
            { rule: 'subcategory_load', display_name: 'Ποινή Υποκατηγορίας', raw_score: 0.0, weight: 0.05, weighted_score: 0.0, explanation: 'Χωρίς φόρτο' },
        ],
        alternatives: [
            { id: 1, name: 'Νάτσικα Α.', score: 0.65, eliminated: false, elimination_reason: null },
            { id: 5, name: 'Δημητρίου Ε.', score: 0.58, eliminated: false, elimination_reason: null },
            { id: 6, name: 'Αντωνίου Ζ.', score: 0.0, eliminated: true, elimination_reason: 'Ο/Η Αντωνίου Ζ. δεν είναι διαθέσιμος/η σήμερα' },
        ],
        rules_fired: ['capacity', 'skills'],
        solver_status: 'GREEDY', is_direct_assignment: false, direct_assignment_reason: '',
        pipeline_timestamp: new Date().toISOString(),
    };
}

// ══════════════════════════════════════════════
//  Bulk Assignment Logic
// ══════════════════════════════════════════════

function toggleSelectAll() {
    const selectAllCb = document.getElementById('selectAllCheckbox');
    const isChecked = selectAllCb.checked;
    const checkboxes = document.querySelectorAll('.row-checkbox');
    
    checkboxes.forEach(cb => {
        cb.checked = isChecked;
        if (isChecked) {
            selectedExams.add(cb.value);
            document.getElementById(`row-${cb.value}`).classList.add('selected-row');
        } else {
            selectedExams.delete(cb.value);
            document.getElementById(`row-${cb.value}`).classList.remove('selected-row');
        }
    });
    updateBulkActionsUI();
}

function toggleSelectExam(examId) {
    const cb = document.querySelector(`.row-checkbox[value="${examId}"]`);
    if (cb && cb.checked) {
        selectedExams.add(examId);
        document.getElementById(`row-${examId}`).classList.add('selected-row');
    } else {
        selectedExams.delete(examId);
        document.getElementById(`row-${examId}`).classList.remove('selected-row');
    }
    
    // Update select all checkbox state
    const selectAllCb = document.getElementById('selectAllCheckbox');
    const checkboxes = document.querySelectorAll('.row-checkbox');
    selectAllCb.checked = checkboxes.length > 0 && selectedExams.size === checkboxes.length;
    
    updateBulkActionsUI();
}

function clearSelection() {
    selectedExams.clear();
    const selectAllCb = document.getElementById('selectAllCheckbox');
    if (selectAllCb) selectAllCb.checked = false;
    
    document.querySelectorAll('.row-checkbox').forEach(cb => {
        cb.checked = false;
    });
    document.querySelectorAll('.selected-row').forEach(row => {
        row.classList.remove('selected-row');
    });
    
    updateBulkActionsUI();
}

function updateBulkActionsUI() {
    const fab = document.getElementById('floating-action-bar');
    const countEl = document.getElementById('fab-selected-count');
    
    if (selectedExams.size > 0 && currentTab === 'pending') {
        countEl.textContent = `${selectedExams.size} επιλεγμένα`;
        fab.style.display = 'flex';
        populateFabDropdown();
    } else {
        fab.style.display = 'none';
        closeFabDropdown();
    }
}

async function bulkAssignToProposed() {
    if (selectedExams.size === 0) return;
    
    const examIds = Array.from(selectedExams);
    
    try {
        const results = await apiCall('/assignments/bulk-confirm', 'POST', { exam_ids: examIds });
        showToast(`${results.length} εξετάσεις ανατέθηκαν επιτυχώς.`, 'success');
        clearSelection();
        loadPendingExams();
        loadAssignedExams();
    } catch (err) {
        showToast(`Σφάλμα: ${err.message}`, 'error');
    }
}

function toggleFabDropdown(event) {
    event.stopPropagation();
    const menu = document.getElementById('fab-dropdown-menu');
    menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
    if (menu.style.display === 'block') {
        document.getElementById('fab-diag-search').focus();
    }
}

function closeFabDropdown() {
    const menu = document.getElementById('fab-dropdown-menu');
    if (menu) menu.style.display = 'none';
}

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
    const wrap = e.target.closest('.fab-dropdown-wrap');
    if (!wrap) {
        closeFabDropdown();
    }
});

function populateFabDropdown() {
    const list = document.getElementById('fab-diag-list');
    list.innerHTML = diagnosticians
        .filter(d => d.available)
        .map(d => `
            <div class="fab-diag-item" onclick="bulkAssignToSpecific(${d.id}, '${escapeHtmlFull(d.name)}')" style="padding: 8px; cursor: pointer; border-radius: 4px; border-bottom: 1px solid var(--border-color); color: var(--text-primary);">
                ${d.name} <span style="opacity: 0.5; font-size: 11px;">(${d.current_day_count}/${d.daily_quota})</span>
            </div>
        `).join('');
}

function filterFabDiagnosticians() {
    const search = normalizeGreek(document.getElementById('fab-diag-search').value);
    const list = document.getElementById('fab-diag-list');
    list.innerHTML = diagnosticians
        .filter(d => d.available && normalizeGreek(d.name).includes(search))
        .map(d => `
            <div class="fab-diag-item" onclick="bulkAssignToSpecific(${d.id}, '${escapeHtmlFull(d.name)}')" style="padding: 8px; cursor: pointer; border-radius: 4px; border-bottom: 1px solid var(--border-color); color: var(--text-primary);">
                ${d.name} <span style="opacity: 0.5; font-size: 11px;">(${d.current_day_count}/${d.daily_quota})</span>
            </div>
        `).join('');
}

async function bulkAssignToSpecific(diagId, diagName) {
    if (selectedExams.size === 0) return;
    
    const examIds = Array.from(selectedExams);
    closeFabDropdown();
    
    try {
        const results = await apiCall('/assignments/bulk-override', 'POST', { 
            exam_ids: examIds,
            override_diagnostician_id: diagId,
            reason: 'Bulk assignment via UI'
        });
        showToast(`${results.length} εξετάσεις ανατέθηκαν επιτυχώς σε ${diagName}.`, 'success');
        clearSelection();
        loadPendingExams();
        loadAssignedExams();
    } catch (err) {
        showToast(`Σφάλμα: ${err.message}`, 'error');
    }
}

// Pagination functions
function changePendingPage(dir) {
    currentPendingPage += dir;
    if (currentPendingPage < 0) currentPendingPage = 0;
    applyFilters();
}

function changeAssignedPage(dir) {
    currentAssignedPage += dir;
    if (currentAssignedPage < 0) currentAssignedPage = 0;
    applyFilters();
}

function updatePendingPagination(total) {
    const info = document.getElementById('pending-pagination-info');
    if (!info) return;
    const start = currentPendingPage * examsPageSize + 1;
    const end = Math.min((currentPendingPage + 1) * examsPageSize, total);
    info.textContent = `Εμφάνιση ${total === 0 ? 0 : start}-${end} από ${total}`;
    
    document.getElementById('btn-pending-prev').disabled = currentPendingPage === 0;
    document.getElementById('btn-pending-next').disabled = (currentPendingPage + 1) * examsPageSize >= total;
}

function updateAssignedPagination(total) {
    const info = document.getElementById('assigned-pagination-info');
    if (!info) return;
    const start = currentAssignedPage * examsPageSize + 1;
    const end = Math.min((currentAssignedPage + 1) * examsPageSize, total);
    info.textContent = `Εμφάνιση ${total === 0 ? 0 : start}-${end} από ${total}`;
    
    document.getElementById('btn-assigned-prev').disabled = currentAssignedPage === 0;
    document.getElementById('btn-assigned-next').disabled = (currentAssignedPage + 1) * examsPageSize >= total;
}


// ══════════════════════════════════════════════
//  Slis Sync Functions
// ══════════════════════════════════════════════

/**
 * Called by the Ανανέωση button.
 * On the assigned tab it also triggers a Slis pull (expire + refresh).
 * On the pending tab it simply reloads from the DB.
 */
async function handleRefreshClick() {
    const btn = document.getElementById('btn-refresh');
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '<span class="loading-spinner"></span>';
    btn.disabled = true;

    try {
        if (currentTab === 'assigned') {
            // Trigger the Slis pull/expire cycle
            await apiCall('/slis/pull', 'POST');
            await loadAssignedExams();
            showToast('🔄 Τα δεδομένα ανανεώθηκαν από το Slis', 'info');
        } else {
            await loadPendingExams();
        }
    } catch (err) {
        showToast(`Σφάλμα ανανέωσης: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = originalHTML;
        btn.disabled = false;
    }
}

/**
 * Update a SINGLE exam on Slis using its exammoreid.
 */
async function updateExamOnSlis(examId, exammoreid) {
    if (!exammoreid) {
        showToast('Δεν βρέθηκε exammoreid για αυτή την εξέταση', 'error');
        return;
    }
    try {
        const result = await apiCall('/slis/push-selected', 'POST', {
            exammoreid_list: [exammoreid]
        });
        if (result && result.succeeded && result.succeeded.length > 0) {
            // Remove this exam from the local assignedExams list
            assignedExams = assignedExams.filter(e => e.exam_id !== examId);
            renderAssignedTable();
            updateTabCounts();
            showToast(`✅ Εξέταση ${examId} ενημερώθηκε στο Slis`, 'success');
        } else {
            const err = result?.failed?.[0]?.error || 'Άγνωστο σφάλμα';
            showToast(`❌ Αποτυχία ενημέρωσης: ${err}`, 'error');
        }
    } catch (err) {
        showToast(`Σφάλμα: ${err.message}`, 'error');
    }
}

/**
 * Update ALL assigned-not-yet-synced exams on Slis.
 */
async function updateAllToSlis() {
    if (assignedExams.length === 0) {
        showToast('Δεν υπάρχουν εξετάσεις για ενημέρωση', 'info');
        return;
    }

    const btn = document.getElementById('btn-update-slis-all');
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '<span class="loading-spinner"></span>';
    btn.disabled = true;

    try {
        const result = await apiCall('/slis/push-all', 'POST');
        const ok = result?.succeeded?.length || 0;
        const fail = result?.failed?.length || 0;

        if (ok > 0) {
            await loadAssignedExams();
            showToast(`✅ ${ok} εξετάσεις ενημερώθηκαν στο Slis${fail > 0 ? ` (${fail} αποτυχίες)` : ''}`, 'success');
        } else if (fail > 0) {
            showToast(`❌ Αποτυχία ενημέρωσης ${fail} εξετάσεων`, 'error');
        } else {
            showToast('Δεν υπάρχουν εξετάσεις για ενημέρωση', 'info');
        }
    } catch (err) {
        showToast(`Σφάλμα: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = originalHTML;
        btn.disabled = false;
    }
}

/**
 * Update SELECTED assigned exams on Slis.
 */
async function updateSelectedToSlis() {
    if (selectedAssignedExams.size === 0) {
        showToast('Επιλέξτε εξετάσεις για ενημέρωση', 'warning');
        return;
    }

    // Collect exammoreid values for selected exams
    const exammoreidList = [];
    const examIdList = Array.from(selectedAssignedExams);
    examIdList.forEach(examId => {
        const exam = assignedExams.find(e => e.exam_id === examId);
        if (exam && exam.exammoreid) exammoreidList.push(exam.exammoreid);
    });

    if (exammoreidList.length === 0) {
        showToast('Δεν βρέθηκαν exammoreid για τις επιλεγμένες εξετάσεις', 'error');
        return;
    }

    try {
        const result = await apiCall('/slis/push-selected', 'POST', {
            exammoreid_list: exammoreidList
        });
        const ok = result?.succeeded?.length || 0;
        const fail = result?.failed?.length || 0;

        if (ok > 0) {
            // Remove successfully synced exams from the local list
            const syncedExammoreidSet = new Set(result.succeeded);
            assignedExams = assignedExams.filter(e => !syncedExammoreidSet.has(e.exammoreid));
            clearAssignedSelection();
            renderAssignedTable();
            updateTabCounts();
            showToast(`✅ ${ok} εξετάσεις ενημερώθηκαν στο Slis${fail > 0 ? ` (${fail} αποτυχίες)` : ''}`, 'success');
        } else {
            showToast(`❌ Αποτυχία ενημέρωσης`, 'error');
        }
    } catch (err) {
        showToast(`Σφάλμα: ${err.message}`, 'error');
    }
}

// ── Assigned tab checkbox helpers ──

function toggleSelectAllAssigned() {
    const selectAllCb = document.getElementById('selectAllAssignedCheckbox');
    const isChecked = selectAllCb.checked;
    const checkboxes = document.querySelectorAll('.assigned-row-checkbox');

    checkboxes.forEach(cb => {
        cb.checked = isChecked;
        const rowEl = document.getElementById(`assigned-row-${cb.value}`);
        if (isChecked) {
            selectedAssignedExams.add(cb.value);
            if (rowEl) rowEl.classList.add('selected-row');
        } else {
            selectedAssignedExams.delete(cb.value);
            if (rowEl) rowEl.classList.remove('selected-row');
        }
    });
    updateAssignedBulkUI();
}

function toggleSelectAssignedExam(examId) {
    const cb = document.querySelector(`.assigned-row-checkbox[value="${examId}"]`);
    const rowEl = document.getElementById(`assigned-row-${examId}`);
    if (cb && cb.checked) {
        selectedAssignedExams.add(examId);
        if (rowEl) rowEl.classList.add('selected-row');
    } else {
        selectedAssignedExams.delete(examId);
        if (rowEl) rowEl.classList.remove('selected-row');
    }

    const selectAllCb = document.getElementById('selectAllAssignedCheckbox');
    const allCbs = document.querySelectorAll('.assigned-row-checkbox');
    if (selectAllCb) {
        selectAllCb.checked = allCbs.length > 0 && selectedAssignedExams.size === allCbs.length;
    }
    updateAssignedBulkUI();
}

function clearAssignedSelection() {
    selectedAssignedExams.clear();
    const selectAllCb = document.getElementById('selectAllAssignedCheckbox');
    if (selectAllCb) selectAllCb.checked = false;
    document.querySelectorAll('.assigned-row-checkbox').forEach(cb => cb.checked = false);
    document.querySelectorAll('[id^="assigned-row-"]').forEach(row => row.classList.remove('selected-row'));
    updateAssignedBulkUI();
}

function updateAssignedBulkUI() {
    const bar = document.getElementById('assigned-bulk-slis-bar');
    const countEl = document.getElementById('assigned-selected-count');
    if (bar) {
        if (selectedAssignedExams.size > 0) {
            bar.style.display = 'flex';
            if (countEl) countEl.textContent = `${selectedAssignedExams.size} επιλεγμένα`;
        } else {
            bar.style.display = 'none';
        }
    }
}
