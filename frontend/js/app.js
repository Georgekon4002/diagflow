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
        onChange: function(selectedDates, dateStr, instance) {
            applyFilters();
        }
    });

    await Promise.all([
        loadPendingExams(),
        loadAssignedExams(),
        loadDiagnosticians(),
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
    renderPendingTable();
    updateTabCounts();

    // Auto-fetch suggestions in background
    Promise.all(pendingExams.filter(e => !e.suggestion).map(async exam => {
        try {
            let suggestion = await apiCall('/assignments/suggest', 'POST', { exam_id: exam.exam_id });
            if (!suggestion) suggestion = getMockSuggestion(exam.exam_id);
            exam.suggestion = suggestion;
        } catch (e) {}
    })).then(() => {
        if (currentTab === 'pending') {
            renderPendingTable();
            applyFilters();
        }
    });
}

async function loadAssignedExams() {
    try {
        const data = await apiCall('/exams/assigned');
        assignedExams = data || getMockAssignedExams();
    } catch {
        assignedExams = getMockAssignedExams();
    }
    renderAssignedTable();
    updateTabCounts();
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
        titleEl.textContent = 'Ανατεθειμένες Εξετάσεις';
        countEl.textContent = `${assignedExams.length} σύνολο`;
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

function applyFilters() {
    const search = document.getElementById('search-input').value.toLowerCase().trim();
    const modality = document.getElementById('filter-modality').value;
    const selectedLabs = Array.from(document.querySelectorAll('.lab-option input[type="checkbox"]:checked')).map(cb => cb.value);

    let dateFrom = null;
    let dateTo = null;
    
    if (dateRangePicker && dateRangePicker.selectedDates.length > 0) {
        // Flatpickr returns local Date objects. We need to convert them to YYYY-MM-DD for comparison
        const fromDate = dateRangePicker.selectedDates[0];
        dateFrom = fromDate.getFullYear() + '-' + String(fromDate.getMonth() + 1).padStart(2, '0') + '-' + String(fromDate.getDate()).padStart(2, '0');
        
        if (dateRangePicker.selectedDates.length === 2) {
            const toDate = dateRangePicker.selectedDates[1];
            dateTo = toDate.getFullYear() + '-' + String(toDate.getMonth() + 1).padStart(2, '0') + '-' + String(toDate.getDate()).padStart(2, '0');
        } else {
            // If only one date is selected, treat it as both from and to
            dateTo = dateFrom;
        }
    }

    const hasFilters = search || modality || selectedLabs.length > 0 || dateFrom || dateTo;
    document.getElementById('btn-clear-filters').style.display = hasFilters ? 'flex' : 'none';

    // Update lab button label
    const labBtn = document.getElementById('lab-filter-btn');
    if (labBtn) {
        const labelEl = document.getElementById('lab-filter-label');
        if (selectedLabs.length === 0) {
            labelEl.textContent = 'Εργαστήριο (όλα)';
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
        const filtered = pendingExams.filter(e => matchesFilters(e, search, modality, selectedLabs, dateFrom, dateTo));
        renderPendingRows(filtered);
        document.getElementById('section-count').textContent =
            filtered.length === pendingExams.length
                ? `${pendingExams.length} σύνολο`
                : `${filtered.length} από ${pendingExams.length}`;
    } else {
        const filtered = assignedExams.filter(e => matchesFilters(e, search, modality, selectedLabs, dateFrom, dateTo));
        renderAssignedRows(filtered);
        document.getElementById('section-count').textContent =
            filtered.length === assignedExams.length
                ? `${assignedExams.length} σύνολο`
                : `${filtered.length} από ${assignedExams.length}`;
    }
}

function matchesFilters(exam, search, modality, selectedLabs, dateFrom, dateTo) {
    if (modality && exam.modality !== modality) return false;
    if (selectedLabs.length > 0 && !selectedLabs.includes(exam.lab_id)) return false;
    if (dateFrom && exam.request_date < dateFrom) return false;
    if (dateTo && exam.request_date > dateTo) return false;
    if (search) {
        const haystack = [
            exam.exam_id,
            exam.patient_name,
            exam.issuing_doctor_name,
            exam.lab_name,
            exam.exam_title || exam.body_part,
            exam.assigned_diagnostician_name || '',
        ].join(' ').toLowerCase();
        if (!haystack.includes(search)) return false;
    }
    return true;
}

function clearFilters(rerender = true) {
    document.getElementById('search-input').value = '';
    document.getElementById('filter-modality').value = '';
    
    if (dateRangePicker) {
        dateRangePicker.clear();
    }

    // Uncheck all lab checkboxes
    document.querySelectorAll('.lab-dropdown input[type="checkbox"]').forEach(cb => cb.checked = false);
    document.getElementById('btn-clear-filters').style.display = 'none';
    // Reset lab label
    const labelEl = document.getElementById('lab-filter-label');
    if (labelEl) labelEl.textContent = 'Εργαστήριο (όλα)';
    const labBtn = document.getElementById('lab-filter-btn');
    if (labBtn) labBtn.classList.remove('has-selection');
    if (rerender) applyFilters();
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
    tbody.innerHTML = exams.map(exam => {
        const hasComment = exam.comments && exam.comments.trim().length > 0;
        const hasSuggestion = exam.suggestion != null;
        const dateStr = exam.request_date ? formatDate(exam.request_date) : '—';
        const examTitle = exam.exam_title || getExamTitle(exam.exam_code) || exam.body_part || '—';

        return `
            <tr id="row-${exam.exam_id}">
                <td>
                    <span style="font-weight:600; color:var(--text-primary);">${exam.exam_id}</span>
                </td>
                <td>${exam.patient_name}</td>
                <td class="date-cell">${dateStr}</td>
                <td>
                    <span class="modality-badge ${exam.modality.toLowerCase()}">${exam.modality}</span>
                </td>
                <td><span class="body-part-tag">${examTitle}</span></td>
                <td>${exam.lab_name}</td>
                <td>${exam.issuing_doctor_name}</td>
                <td class="comment-cell">
                    ${hasComment
                        ? `<div class="comment-btn-wrap">
                                <button class="comment-btn">💬 Σχόλιο</button>
                                <div class="comment-popup">${escapeHtmlFull(exam.comments)}</div>
                           </div>`
                        : '<span style="color:var(--text-tertiary)">—</span>'
                    }
                </td>
                <td class="suggestion-cell">
                    ${hasSuggestion
                        ? `<span class="suggested-name">${exam.suggestion.suggested_diagnostician_name}</span>
                           <span class="suggested-score">${Math.round(exam.suggestion.confidence_score * 100)}%</span>`
                        : '<span class="no-suggestion">—</span>'
                    }
                </td>
                <td>
                    <div class="btn-group">
                        ${hasSuggestion
                            ? `<button class="btn btn-view" onclick="viewSuggestion('${exam.exam_id}')">Προβολή</button>`
                            : `<button class="btn btn-suggest" onclick="getSuggestion('${exam.exam_id}')">
                                <span class="btn-text">Πρόταση</span>
                               </button>`
                        }
                    </div>
                </td>
            </tr>
        `;
    }).join('');
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
    tbody.innerHTML = exams.map(exam => {
        const dateStr = exam.request_date ? formatDate(exam.request_date) : '—';
        const timeStr = exam.assigned_at ? formatTime(exam.assigned_at) : '—';
        const examTitle = exam.exam_title || getExamTitle(exam.exam_code) || exam.body_part || '—';

        return `
            <tr>
                <td><span style="font-weight:600; color:var(--text-primary);">${exam.exam_id}</span></td>
                <td>${exam.patient_name}</td>
                <td class="date-cell">${dateStr}</td>
                <td>
                    <span class="modality-badge ${exam.modality.toLowerCase()}">${exam.modality}</span>
                </td>
                <td><span class="body-part-tag">${examTitle}</span></td>
                <td>${exam.lab_name}</td>
                <td>${exam.issuing_doctor_name}</td>
                <td><span class="assigned-name">${exam.assigned_diagnostician_name || '—'}</span></td>
                <td class="time-cell">${timeStr}</td>
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
    const exam = pendingExams.find(e => e.exam_id === examId);
    if (exam && exam.suggestion) openSuggestionModal(examId, exam.suggestion);
}


// ══════════════════════════════════════════════
//  Suggestion Modal
// ══════════════════════════════════════════════

function openSuggestionModal(examId, suggestion) {
    currentExamId = examId;
    currentSuggestion = suggestion;
    const exam = pendingExams.find(e => e.exam_id === examId);

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
    const scored = alternatives.filter(a => !a.eliminated);
    if (scored.length) {
        const grp1 = document.createElement('optgroup');
        grp1.label = 'Αξιολογημένοι';
        scored.forEach(alt => {
            grp1.innerHTML += `<option value="${alt.id}">${alt.name} (${Math.round(alt.score * 100)}%)</option>`;
        });
        overrideSelect.appendChild(grp1);
    }

    // Eliminated alternatives (can still be manually chosen)
    const eliminated = alternatives.filter(a => a.eliminated);
    if (eliminated.length) {
        const grp2 = document.createElement('optgroup');
        grp2.label = 'Εξαιρεθέντες (χειροκίνητη παράκαμψη)';
        eliminated.forEach(alt => {
            grp2.innerHTML += `<option value="${alt.id}">${alt.name} ⛔ Εξαιρέθηκε</option>`;
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

    // Move exam from pending to assigned
    const exam = pendingExams.find(e => e.exam_id === currentExamId);
    if (exam) {
        assignedExams.unshift({
            ...exam,
            status: 'assigned',
            assigned_diagnostician_id: currentSuggestion.suggested_diagnostician_id,
            assigned_diagnostician_name: currentSuggestion.suggested_diagnostician_name,
            assigned_at: new Date().toISOString(),
        });
    }

    pendingExams = pendingExams.filter(e => e.exam_id !== currentExamId);
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

    // Move exam from pending to assigned
    const exam = pendingExams.find(e => e.exam_id === currentExamId);
    if (exam) {
        assignedExams.unshift({
            ...exam,
            status: 'assigned',
            assigned_diagnostician_id: overrideId,
            assigned_diagnostician_name: overrideName,
            assigned_at: new Date().toISOString(),
        });
    }

    pendingExams = pendingExams.filter(e => e.exam_id !== currentExamId);
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

// ── Exam code / title lookup ──
const EXAM_CODE_MAP = {
    '22100': 'Αγγειογραφία Αώρτας (CT)',
    '22140': 'CT Θώρακα',
    '21063': 'MRI Εγκεφάλου',
    '22200': 'CT Κοιλίας',
    '21100': 'MRI Κοιλίας',
    '22310': 'CT Σπονδυλικής Στήλης',
    '21200': 'MRI Σπονδυλικής Στήλης',
    '22400': 'CT Πυέλου',
    '21300': 'MRI Πυέλου',
    '22500': 'CT Μυοσκελετικού',
    '21400': 'MRI Μυοσκελετικού',
};

function getExamTitle(code) {
    if (!code) return null;
    return EXAM_CODE_MAP[code] || `Εξέταση ${code}`;
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

function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        const d = new Date(dateStr);
        return d.toLocaleDateString('el-GR', { day: '2-digit', month: '2-digit', year: 'numeric' });
    } catch { return dateStr; }
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
document.addEventListener('click', function(e) {
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
            exam_id: 'EX-2026-001', patient_id: 'PT-5432', patient_name: 'Γεώργιος Κ.',
            modality: 'MRI', exam_code: '21100', exam_title: 'MRI Κοιλίας',
            body_part: 'abdomen', lab_id: 'LAB-KIF', lab_name: 'Κηφισιά',
            issuing_doctor_id: 'DR-101', issuing_doctor_name: 'Παπαδόπουλος Ν.',
            request_date: '2026-07-14', status: 'pending', comments: '', suggestion: null,
        },
        {
            exam_id: 'EX-2026-002', patient_id: 'PT-8821', patient_name: 'Μαρία Α.',
            modality: 'CT', exam_code: '22140', exam_title: 'CT Θώρακα',
            body_part: 'chest', lab_id: 'LAB-MAR', lab_name: 'Μαρούσι',
            issuing_doctor_id: 'DR-205', issuing_doctor_name: 'Ιωάννου Ε.',
            request_date: '2026-07-14', status: 'pending', comments: 'Επείγον', suggestion: null,
        },
        {
            exam_id: 'EX-2026-003', patient_id: 'PT-1190', patient_name: 'Δημήτρης Λ.',
            modality: 'MRI', exam_code: '21063', exam_title: 'MRI Εγκεφάλου',
            body_part: 'neuro', lab_id: 'LAB-KIF', lab_name: 'Κηφισιά',
            issuing_doctor_id: 'DR-101', issuing_doctor_name: 'Παπαδόπουλος Ν.',
            request_date: '2026-07-13', status: 'pending',
            comments: 'ΟΧΙ ΝΑΤΣΙΚΑ, ασθενής ζήτησε συγκεκριμένο ιατρό', suggestion: null,
        },
        {
            exam_id: 'EX-2026-004', patient_id: 'PT-3301', patient_name: 'Ελένη Π.',
            modality: 'CT', exam_code: '22200', exam_title: 'CT Κοιλίας',
            body_part: 'abdomen', lab_id: 'LAB-PAM', lab_name: 'Παμμακάριστος',
            issuing_doctor_id: 'DR-PAM-01', issuing_doctor_name: 'Παμμακάριστος (Εφημερία)',
            request_date: '2026-07-14', status: 'pending',
            comments: 'ΕΦΗΜΕΡΙΑ ΠΑΜΜΑΚΑΡΙΣΤΟΥ', suggestion: null,
        },
        {
            exam_id: 'EX-2026-005', patient_id: 'PT-6677', patient_name: 'Αντώνης Σ.',
            modality: 'MRI', exam_code: '21400', exam_title: 'MRI Μυοσκελετικού',
            body_part: 'msk', lab_id: 'LAB-GLY', lab_name: 'Γλυφάδα',
            issuing_doctor_id: 'DR-310', issuing_doctor_name: 'Βασιλείου Κ.',
            request_date: '2026-07-14', status: 'pending', comments: '', suggestion: null,
        },
    ];
}

function getMockAssignedExams() {
    return [
        {
            exam_id: 'EX-2026-A01', patient_id: 'PT-1001', patient_name: 'Σοφία Μ.',
            modality: 'CT', exam_code: '22140', exam_title: 'CT Θώρακα',
            body_part: 'chest', lab_id: 'LAB-KIF', lab_name: 'Κηφισιά',
            issuing_doctor_id: 'DR-101', issuing_doctor_name: 'Παπαδόπουλος Ν.',
            request_date: '2026-07-14', status: 'assigned',
            assigned_diagnostician_id: 1, assigned_diagnostician_name: 'Νάτσικα Α.',
            assigned_at: '2026-07-14T09:15:00',
        },
        {
            exam_id: 'EX-2026-A02', patient_id: 'PT-2002', patient_name: 'Νίκος Α.',
            modality: 'MRI', exam_code: '21063', exam_title: 'MRI Εγκεφάλου',
            body_part: 'neuro', lab_id: 'LAB-MAR', lab_name: 'Μαρούσι',
            issuing_doctor_id: 'DR-310', issuing_doctor_name: 'Βασιλείου Κ.',
            request_date: '2026-07-14', status: 'assigned',
            assigned_diagnostician_id: 3, assigned_diagnostician_name: 'Παπαδόπουλος Γ.',
            assigned_at: '2026-07-14T10:30:00',
        },
        {
            exam_id: 'EX-2026-A03', patient_id: 'PT-3003', patient_name: 'Ελένη Τ.',
            modality: 'CT', exam_code: '22200', exam_title: 'CT Κοιλίας',
            body_part: 'abdomen', lab_id: 'LAB-GLY', lab_name: 'Γλυφάδα',
            issuing_doctor_id: 'DR-205', issuing_doctor_name: 'Ιωάννου Ε.',
            request_date: '2026-07-13', status: 'assigned',
            assigned_diagnostician_id: 2, assigned_diagnostician_name: 'Κωνσταντίνου Β.',
            assigned_at: '2026-07-13T14:45:00',
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
