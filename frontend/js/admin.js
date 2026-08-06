/**
 * DiagFlow — Admin Panel JavaScript
 *
 * Handles all admin CRUD operations:
 * - Εφημερία Παμμακάριστου (on-call override)
 * - Διαγνώστες (list, add, toggle active)
 * - Διαθεσιμότητα (set per-date)
 * - Δεξιότητες (set proficiency per body-part/modality)
 * - Συνεργασίες (partnerships)
 * - Ιατροί (doctors)
 */

const API_BASE = '/api';
let adminToken = sessionStorage.getItem('adminToken');

// ── State ──
let diagnosticians = [];
let partnerships = [];
let doctors = [];
let skills = [];
let availability = [];

let doctorsPage = 0;
const doctorsPageSize = 50;
let totalDoctors = 0;
let docSearchQuery = '';

let diagsPage = 0;
const diagsPageSize = 20;
let totalDiags = 0;
let diagSearchQuery = '';

let EXAM_CODE_MAP = {};
let RAW_EXAM_CATEGORIES = [];

function cleanExamName(raw) {
    if (!raw) return '';
    return raw
        .replace(/\(MRI\)/gi, '')
        .replace(/\(CT\)/gi, '')
        .replace(/\(MRA\)/gi, '')
        .replace(/\b(CT|MRI|MRA)\b/gi, '')
        .replace(/ΜΑΓΝΗΤΙΚΗ\s*/gi, '')
        .replace(/ΑΞΟΝΙΚΗ\s*/gi, '')
        .replace(/ΑΓΓΕΙΟΓΡΑΦΙΑ\s*/gi, '')
        .replace(/ΤΟΜΟΓΡΑΦΙΑ\s*/gi, '')
        .replace(/\s{2,}/g, ' ')
        .trim();
}

function formatSimplifiedExamName(name, category, code) {
    const cleaned = cleanExamName(name);
    return (cleaned || name || code).trim();
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

async function loadExamCategories() {
    try {
        const data = await apiCall('/admin/exam-categories');
        if (data && data.length > 0) {
            RAW_EXAM_CATEGORIES = data;
            data.forEach(ex => {
                const codeKey = String(ex.code || ex.examnumcode || ex.exam_code || '').trim();
                if (codeKey) {
                    EXAM_CODE_MAP[codeKey] = ex.name;
                }
            });
        }
    } catch {
        console.warn("Could not load exam categories");
    }
}

// ── Multi-select Search Dropdown Helpers for Exam Codes ──────────────────────
let selectedSkillExamCodes = new Set();
let selectedRouteExamCodes = new Set();
let openSkillsGroups = new Set();
let openPartnershipsGroups = new Set();

let selectedSkillItemIds = new Set();
let skillsSearchQuery = '';

let selectedPartnershipItemIds = new Set();
let partnershipsSearchQuery = '';

function onSkillsSearchInput(query) {
    skillsSearchQuery = (query || '').toLowerCase().trim();
    renderSkills();
}

function onPartnershipsSearchInput(query) {
    partnershipsSearchQuery = (query || '').toLowerCase().trim();
    renderPartnerships();
}

function onSkillExamSearchInput() {
    renderExamSearchDropdown('skill');
}

function onSkillExamSearchFocus() {
    renderExamSearchDropdown('skill');
}

function onAdvRouteExamSearchInput() {
    renderExamSearchDropdown('route');
}

function onAdvRouteExamSearchFocus() {
    renderExamSearchDropdown('route');
}

function renderExamSearchDropdown(type) {
    const inputId = type === 'skill' ? 'skill-exam-search' : 'adv-route-codes-search';
    const resultsId = type === 'skill' ? 'skill-exam-results' : 'adv-route-codes-results';
    const selectedSet = type === 'skill' ? selectedSkillExamCodes : selectedRouteExamCodes;

    const input = document.getElementById(inputId);
    const results = document.getElementById(resultsId);
    if (!input || !results) return;

    const query = input.value.trim().toLowerCase();
    const normQuery = typeof normalizeGreek === 'function' ? normalizeGreek(query) : query;

    let categories = RAW_EXAM_CATEGORIES || [];
    let filtered = categories;

    if (query) {
        filtered = categories.filter(ex => {
            const code = String(ex.code || ex.examnumcode || ex.exam_code || '').toLowerCase().trim();
            const name = (ex.name || '').toLowerCase();
            const normName = typeof normalizeGreek === 'function' ? normalizeGreek(ex.name || '') : name;
            return code.includes(query) || name.includes(query) || normName.includes(normQuery);
        });
    }

    if (filtered.length === 0) {
        results.innerHTML = '<div style="padding:10px; color:var(--text-secondary); text-align:center; font-size:13px;">Δεν βρέθηκαν εξετάσεις</div>';
        results.style.display = 'block';
        return;
    }

    results.innerHTML = filtered.slice(0, 100).map(ex => {
        const code = String(ex.code || ex.examnumcode || ex.exam_code || '').trim();
        const rawName = ex.name || EXAM_CODE_MAP[code] || '';
        const shortName = typeof cleanExamName === 'function' 
            ? cleanExamName(rawName) 
            : rawName.replace(/^(ΑΞΟΝΙΚΗ|ΜΑΓΝΗΤΙΚΗ)\s+(ΤΟΜΟΓΡΑΦΙΑ|ΑΓΓΕΙΟΓΡΑΦΙΑ)\s*/i, '').trim();
        let cat = (ex.category || '').toUpperCase().trim();
        if (!cat) {
            if (/CT|ΑΞΟΝ/i.test(rawName)) cat = 'CT';
            else if (/MRA|ΑΓΓΕΙΟ/i.test(rawName)) cat = 'MRA';
            else if (/MRI|ΜΑΓΝΗΤ/i.test(rawName)) cat = 'MRI';
            else cat = 'OTHER';
        }
        const isChecked = selectedSet.has(code);

        return `
            <label class="exam-dropdown-item" style="display:flex; align-items:center; gap:10px; padding:8px 12px; cursor:pointer; font-size:13px; border-bottom:1px solid rgba(255,255,255,0.05); user-select:none;" onclick="event.stopPropagation();">
                <input type="checkbox" value="${code}" ${isChecked ? 'checked' : ''} onchange="toggleExamCodeSelection('${type}', '${code}', event)" style="accent-color:var(--accent-primary); width:16px; height:16px; cursor:pointer; flex-shrink:0;">
                <span style="font-weight:700; color:var(--accent-primary); font-family:monospace; font-size:13px; min-width:48px;">${code}</span>
                <span style="color:var(--text-primary); flex:1; font-weight:500;" title="${escapeHtml(rawName)}">${escapeHtml(shortName || rawName)}</span>
                <span class="modality-badge ${cat.toLowerCase()}" style="font-size:10px; padding:2px 6px; flex-shrink:0;">${cat}</span>
            </label>
        `;
    }).join('');

    results.style.display = 'block';
}

function toggleExamCodeSelection(type, code, event) {
    const selectedSet = type === 'skill' ? selectedSkillExamCodes : selectedRouteExamCodes;
    if (event.target.checked) {
        selectedSet.add(code);
    } else {
        selectedSet.delete(code);
    }
    renderExamCodeTags(type);
}

function removeExamCodeSelection(type, code) {
    const selectedSet = type === 'skill' ? selectedSkillExamCodes : selectedRouteExamCodes;
    selectedSet.delete(code);
    renderExamCodeTags(type);
    renderExamSearchDropdown(type);
}

function renderExamCodeTags(type) {
    const tagsId = type === 'skill' ? 'skill-exam-tags' : 'adv-route-codes-tags';
    const selectedSet = type === 'skill' ? selectedSkillExamCodes : selectedRouteExamCodes;
    const tagsContainer = document.getElementById(tagsId);
    if (!tagsContainer) return;

    if (selectedSet.size === 0) {
        tagsContainer.innerHTML = '';
        return;
    }

    tagsContainer.innerHTML = Array.from(selectedSet).map(code => {
        const examObj = (RAW_EXAM_CATEGORIES || []).find(ex => String(ex.code || ex.examnumcode || '').trim() === code);
        const fullName = examObj ? examObj.name : (EXAM_CODE_MAP[code] || '');
        const tooltip = fullName ? `${code} — ${fullName}` : code;
        return `<span title="${escapeHtml(tooltip)}" style="background:rgba(99,102,241,0.15); border:1px solid rgba(99,102,241,0.35); padding:3px 8px 3px 9px; border-radius:20px; font-size:12px; color:var(--accent-primary); font-family:monospace; font-weight:700; display:inline-flex; align-items:center; gap:4px; white-space:nowrap; cursor:default;">${escapeHtml(code)}<button type="button" onclick="removeExamCodeSelection('${type}', '${code}')" title="Αφαίρεση" style="background:none; border:none; color:rgba(99,102,241,0.6); font-size:13px; font-weight:bold; cursor:pointer; line-height:1; padding:0; margin-left:1px;">&times;</button></span>`;
    }).join('');
}

document.addEventListener('click', function(e) {
    const skillWrap = document.getElementById('skill-exam-search')?.parentElement;
    if (skillWrap && !skillWrap.contains(e.target)) {
        const res = document.getElementById('skill-exam-results');
        if (res) res.style.display = 'none';
    }
    const routeWrap = document.getElementById('adv-route-codes-search')?.parentElement;
    if (routeWrap && !routeWrap.contains(e.target)) {
        const res = document.getElementById('adv-route-codes-results');
        if (res) res.style.display = 'none';
    }
});

let dbStatusInfo = { status: 'mock', error: null };

async function checkDbStatus() {
    try {
        const res = await apiCall('/slis/status', 'GET');
        if (res) {
            dbStatusInfo = res;
            updateDbStatusBadge();
        }
    } catch { /* Fallback */ }
}

function updateDbStatusBadge() {
    const badge = document.getElementById('db-status-badge');
    const textEl = document.getElementById('db-status-text');
    if (!badge || !textEl) return;

    badge.classList.remove('mock', 'connected', 'error');
    if (dbStatusInfo.status === 'connected') {
        badge.classList.add('connected');
        textEl.textContent = '🟢 Connected to Slis DB';
        badge.title = 'Συνδέθηκε επιτυχώς στη βάση Slis';
    } else if (dbStatusInfo.status === 'error') {
        badge.classList.add('error');
        textEl.textContent = '🔴 Slis DB Error';
        badge.title = 'Αποτυχία σύνδεσης: ' + (dbStatusInfo.error || 'Άγνωστο σφάλμα') + ' (κάντε κλικ για λεπτομέρειες)';
    } else {
        badge.classList.add('mock');
        textEl.textContent = '🟡 Mock Slis DB';
        badge.title = 'Χρήση τοπικής δοκιμαστικής βάσης (Mock Slis DB)';
    }
}

function showDbStatusDetails() {
    if (dbStatusInfo.status === 'error' && dbStatusInfo.error) {
        showToast(`❌ Σφάλμα Σύνδεσης Slis DB: ${dbStatusInfo.error}`, 'error');
    } else if (dbStatusInfo.status === 'connected') {
        showToast('🟢 Επιτυχής σύνδεση στη βάση Slis DB!', 'success');
    } else {
        showToast('🟡 Χρήση Mock Slis DB (SQLite)', 'info');
    }
}

// ══════════════════════════════════════════════
//  Auth Guard & Init
// ══════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', async () => {
    checkDbStatus();
    if (!adminToken) {
        showToast('Απαιτείται σύνδεση διαχειριστή.', 'error');
        setTimeout(() => window.location.href = 'index.html', 1500);
        return;
    }

    const today = formatDateLocal(new Date());
    
    const fpConfig = {
        dateFormat: "Y-m-d",
        altInput: true,
        altFormat: "d/m/Y",
        defaultDate: today,
        firstDayOfWeek: 1,
        locale: "gr"
    };
    
    if (typeof flatpickr !== 'undefined') {
        const oncallEl = document.getElementById('oncall-date');
        if (oncallEl) flatpickr("#oncall-date", fpConfig);
        const availEl = document.getElementById('avail-date');
        if (availEl) flatpickr("#avail-date", {
            ...fpConfig,
            mode: "range",
            defaultDate: [today, today]
        });
    }

    const adminRole = sessionStorage.getItem('adminRole');
    const roleBadgeNode = document.getElementById('header-role-text');
    if (roleBadgeNode && adminRole === 'it_support') {
        roleBadgeNode.innerText = 'IT Support';
        roleBadgeNode.parentElement.style.backgroundColor = '#f3ebff';
        roleBadgeNode.parentElement.style.color = '#8122FF';
        roleBadgeNode.parentElement.style.borderColor = '#d8b4fe';
    }

    showAdminLoadingModal('⏳ Φόρτωση Πίνακα Διαχείρισης', 'Εκτελούνται εργασίες παρασκηνίου ή φόρτωση δεδομένων. Παρακαλώ περιμένετε λίγο για την πλήρη φόρτωση των στοιχείων.');
    try {
        await loadAll();
    } finally {
        hideAdminLoadingModal();
    }
    showSection('oncall');
});

function showAdminLoadingModal(title = '⏳ Φόρτωση Πίνακα Διαχείρισης', message = 'Εκτελούνται εργασίες παρασκηνίου ή φόρτωση δεδομένων. Παρακαλώ περιμένετε λίγο για την πλήρη φόρτωση των στοιχείων.') {
    const modal = document.getElementById('admin-loading-modal');
    const titleEl = document.getElementById('admin-loading-title');
    const msgEl = document.getElementById('admin-loading-msg');
    if (titleEl) titleEl.innerText = title;
    if (msgEl) msgEl.innerText = message;
    if (modal) {
        modal.style.display = 'flex';
        modal.style.opacity = '1';
    }
}

function hideAdminLoadingModal() {
    const modal = document.getElementById('admin-loading-modal');
    if (modal) {
        modal.style.opacity = '0';
        setTimeout(() => {
            modal.style.display = 'none';
        }, 200);
    }
}

async function loadAll() {
    await loadExamCategories();
    await Promise.all([
        loadDiagnosticians(),
        loadPartnerships(),
        loadDoctors(),
        loadSkills(),
        loadAvailability(),
        loadOncall(),
        loadPamakristosWeeklySchedule(),
        loadAdvancedOptions(),
        loadSystemWeights(),
        loadAdminUsers(),
    ]);
}



// ══════════════════════════════════════════════
//  API Call Helper
// ══════════════════════════════════════════════

let isLoggedOut = false;

async function apiCall(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json',
            'X-Admin-Token': adminToken || '',
        },
    };
    if (body) options.body = JSON.stringify(body);

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, options);
        if (response.status === 401) {
            if (!isLoggedOut) {
                isLoggedOut = true;
                showToast('Η σύνδεση έχει λήξει. Παρακαλώ συνδεθείτε ξανά.', 'error');
                setTimeout(() => window.location.href = 'index.html', 2000);
            }
            return null;
        }
        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(err.detail || `HTTP ${response.status}`);
        }
        return await response.json();
    } catch (err) {
        if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
            console.warn('API not available — mock mode');
            return null;
        }
        throw err;
    }
}


// ══════════════════════════════════════════════
//  Navigation
// ══════════════════════════════════════════════

const SECTION_TITLES = {
    oncall: 'Παμμακάριστος',
    diagnosticians: 'Διαγνώστες',
    availability: 'Άδειες',
    skills: 'Δεξιότητες & Χωρητικότητα',
    partnerships: 'Συνεργασίες Ιατρών',
    doctors: 'Ιατροί',
    exams: 'Εξετάσεις',
    advanced: 'Για Προχωρημένους'
};

function showSection(name) {
    // Hide all sections
    document.querySelectorAll('.admin-section').forEach(s => s.style.display = 'none');
    document.querySelectorAll('.admin-nav-item').forEach(b => b.classList.remove('active'));

    // Show target
    const sec = document.getElementById(`section-${name}`);
    if (sec) sec.style.display = 'block';
    const nav = document.getElementById(`nav-${name}`);
    if (nav) nav.classList.add('active');

    document.getElementById('admin-page-title').textContent = SECTION_TITLES[name] || name;

    if (name === 'exams') {
        renderExamsSection();
    }
}

function goBack() {
    window.location.href = 'index.html';
}

function adminLogout() {
    sessionStorage.removeItem('adminToken');
    window.location.href = 'index.html';
}


// ══════════════════════════════════════════════
//  Load Functions
// ══════════════════════════════════════════════

async function syncDiagnosticians() {
    showAdminLoadingModal('⏳ Συγχρονισμός Διαγνωστών', 'Γίνεται συγχρονισμός διαγνωστών με το σύστημα Slis. Παρακαλώ περιμένετε...');
    try {
        const res = await apiCall('/admin/diagnosticians/sync', 'POST');
        if (res && res.synced !== undefined) {
            showToast(`🔄 Ο συγχρονισμός ολοκληρώθηκε. Προστέθηκαν ${res.synced} νέοι διαγνώστες.`, 'success');
        } else {
            showToast('🔄 Ο συγχρονισμός ολοκληρώθηκε.', 'info');
        }
        await loadDiagnosticians();
    } catch (err) {
        showToast(`Σφάλμα συγχρονισμού: ${err.message}`, 'error');
    } finally {
        hideAdminLoadingModal();
    }
}

async function syncDoctors() {
    showAdminLoadingModal('⏳ Συγχρονισμός Ιατρών', 'Γίνεται συγχρονισμός εκδιδόντων ιατρών με το σύστημα Slis. Παρακαλώ περιμένετε...');
    try {
        const res = await apiCall('/admin/doctors/sync', 'POST');
        if (res && res.synced !== undefined) {
            showToast(`🔄 Ο συγχρονισμός ολοκληρώθηκε. Προστέθηκαν ${res.synced} νέοι ιατροί.`, 'success');
        } else {
            showToast('🔄 Ο συγχρονισμός ολοκληρώθηκε.', 'info');
        }
        await loadDoctors(0);
    } catch (err) {
        showToast(`Σφάλμα συγχρονισμού: ${err.message}`, 'error');
    } finally {
        hideAdminLoadingModal();
    }
}


async function loadDiagnosticians() {
    const data = await apiCall('/admin/diagnosticians');
    diagnosticians = data || getMockDiagnosticians();
    renderDiagnosticians();
    populateDiagnosticianSelects();
    renderAvailability();
    renderWeeklyScheduleGrid();
}

async function loadPartnerships() {
    const data = await apiCall('/admin/partnerships');
    partnerships = data || getMockPartnerships();
    renderPartnerships();
}

async function loadDoctors(page = 0) {
    doctorsPage = page;
    const skip = page * doctorsPageSize;
    const limit = doctorsPageSize;
    
    let data;
    try {
        data = await apiCall(`/admin/doctors?q=${encodeURIComponent(docSearchQuery)}&skip=${skip}&limit=${limit}`);
    } catch {
        data = null;
    }

    if (data && data.items) {
        doctors = data.items;
        totalDoctors = data.total;
    } else {
        let mock = getMockDoctors();
        if (docSearchQuery) {
            const lowerQ = docSearchQuery.toLowerCase();
            mock = mock.filter(d => d.name.toLowerCase().includes(lowerQ) || String(d.id).includes(lowerQ) || (d.partner_name && d.partner_name.toLowerCase().includes(lowerQ)));
        }
        doctors = mock.slice(skip, skip + limit);
        totalDoctors = mock.length;
    }
    renderDoctors();
    updateDoctorPagination();
}

function changeDoctorPage(dir) {
    const newPage = doctorsPage + dir;
    if (newPage < 0 || newPage * doctorsPageSize >= totalDoctors) return;
    loadDoctors(newPage);
    window.scrollTo({ top: 0, behavior: 'smooth' });
    document.querySelectorAll('div[style*="overflow-x: auto"], .main-content').forEach(el => el.scrollTo({ top: 0, behavior: 'smooth' }));
}

function updateDoctorPagination() {
    const info = document.getElementById('doc-pagination-info');
    if (!info) return;
    if (totalDoctors === 0) {
        info.textContent = 'Σελίδα 0 (0 από 0)';
    } else {
        const pageNum = doctorsPage + 1;
        const start = doctorsPage * doctorsPageSize + 1;
        const end = Math.min((doctorsPage + 1) * doctorsPageSize, totalDoctors);
        info.textContent = `Σελίδα ${pageNum} (${start}-${end} από ${totalDoctors})`;
    }
    
    document.getElementById('btn-doc-prev').disabled = doctorsPage === 0;
    document.getElementById('btn-doc-next').disabled = (doctorsPage + 1) * doctorsPageSize >= totalDoctors;
}

async function loadSkills() {
    const data = await apiCall('/admin/skills');
    skills = data || getMockSkills();
    renderSkills();
}

async function loadAvailability() {
    const data = await apiCall('/admin/availability');
    availability = data || getMockAvailability();
    renderAvailability();
}

async function loadOncall() {
    const data = await apiCall('/admin/oncall');
    const oncall = data || { diagnostician_name: 'Παπαδόπουλος Γ.', date: formatDateLocal(new Date()) };
    const el = document.getElementById('oncall-current');
    if (el) {
        el.innerHTML = `
            <strong style="color:var(--text-primary);font-size:var(--font-size-md);">${oncall.diagnostician_name}</strong>
            <span style="margin-left:8px;color:var(--text-tertiary);">(${formatDate(oncall.date)})</span>
        `;
    }
}

let weeklyScheduleData = [];

async function loadPamakristosWeeklySchedule() {
    try {
        const data = await apiCall('/admin/pamakristos/weekly-schedule');
        weeklyScheduleData = data || [];
        renderPamakristosWeeklySchedule();
    } catch (err) {
        console.warn("Could not load Pamakristos weekly schedule", err);
    }
}

function renderPamakristosWeeklySchedule() {
    const tbody = document.getElementById('pamakristos-weekly-tbody');
    if (!tbody) return;

    const days = [
        { weekday: 0, day_name: "Δευτέρα" },
        { weekday: 1, day_name: "Τρίτη" },
        { weekday: 2, day_name: "Τετάρτη" },
        { weekday: 3, day_name: "Πέμπτη" },
        { weekday: 4, day_name: "Παρασκευή" },
        { weekday: 5, day_name: "Σάββατο" },
        { weekday: 6, day_name: "Κυριακή" },
    ];

    tbody.innerHTML = days.map(d => {
        const match = weeklyScheduleData.find(w => w.weekday === d.weekday);
        const selectedId = match ? match.diagnostician_id : "";

        let options = '<option value="">— Κανένας (Χωρίς Υπεύθυνο) —</option>';
        diagnosticians.forEach(diag => {
            if (!diag.active) return;
            const sel = String(diag.id) === String(selectedId) ? 'selected' : '';
            options += `<option value="${diag.id}" ${sel}>${diag.name}</option>`;
        });

        return `
            <tr>
                <td style="font-weight:600; padding:12px;">${d.day_name}</td>
                <td style="padding:8px 12px;">
                    <select class="form-input filter-select pamakristos-schedule-select" data-weekday="${d.weekday}" style="width:100%; max-width:400px;">
                        ${options}
                    </select>
                </td>
            </tr>
        `;
    }).join('');
}

async function savePamakristosWeeklySchedule() {
    const selects = document.querySelectorAll('.pamakristos-schedule-select');
    const items = [];
    selects.forEach(sel => {
        const weekday = parseInt(sel.getAttribute('data-weekday'));
        const val = sel.value;
        if (val) {
            items.push({
                weekday: weekday,
                diagnostician_id: parseInt(val)
            });
        }
    });

    try {
        await apiCall('/admin/pamakristos/weekly-schedule', 'POST', items);
        showToast('✅ Το εβδομαδιαίο πρόγραμμα Παμμακάριστου αποθηκεύτηκε επιτυχώς!', 'success');
        await loadPamakristosWeeklySchedule();
    } catch (err) {
        showToast(`Σφάλμα: ${err.message}`, 'error');
    }
}

function populateDiagnosticianSelects() {
    const selects = ['oncall-diag-select', 'avail-diag', 'skill-diag', 'part-diag', 'schedule-diag', 'adv-route-diag', 'adv-excl-diag', 'adv-quota-diag'];
    selects.forEach(id => {
        const sel = document.getElementById(id);
        if (!sel) return;
        
        let html = '<option value="">— Επιλέξτε —</option>';
        diagnosticians.forEach(d => {
            // Filter out inactive diagnosticians
            if (!d.active) {
                return;
            }
            html += `<option value="${d.id}" data-name="${d.name}">${d.name}</option>`;
        });
        sel.innerHTML = html;
    });
}


// ══════════════════════════════════════════════
//  Render Functions
// ══════════════════════════════════════════════

function filterDiags(q) {
    diagSearchQuery = q;
    diagsPage = 0;
    renderDiagnosticians();
}

function filterDoctors(q) {
    docSearchQuery = q;
    loadDoctors(0);
}

function normalizeGreek(str) {
    if (!str) return '';
    return str.toString()
        .toUpperCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/Ά/g, 'Α').replace(/Έ/g, 'Ε').replace(/Ή/g, 'Η')
        .replace(/Ί/g, 'Ι').replace(/Ό/g, 'Ο').replace(/Ύ/g, 'Υ').replace(/Ώ/g, 'Ω');
}

function renderDiagnosticians() {
    const tbody = document.getElementById('diag-tbody');
    
    let filteredDiags = diagnosticians;
    if (diagSearchQuery) {
        const tokens = normalizeGreek(diagSearchQuery).split(/\s+/).filter(Boolean);
        filteredDiags = filteredDiags.filter(d => {
            const haystack = normalizeGreek(`${d.name || ''} ${d.id || ''}`);
            return tokens.every(t => haystack.includes(t));
        });
    }
    
    // Sort diagnosticians: Active first, then inactive. Sort alphabetically within those groups.
    const sortedDiags = [...filteredDiags].sort((a, b) => {
        if (a.active !== b.active) {
            return a.active ? -1 : 1;
        }
        return a.name.localeCompare(b.name, 'el');
    });

    totalDiags = sortedDiags.length;
    const start = diagsPage * diagsPageSize;
    const paginated = sortedDiags.slice(start, start + diagsPageSize);

    tbody.innerHTML = paginated.map(d => `
        <tr>
            <td style="font-weight:600;">${d.name}</td>
            <td>
                <span class="status-badge ${d.active ? 'active' : 'inactive'}">
                    ${d.active ? '● Ενεργός' : '● Ανενεργός'}
                </span>
            </td>
            <td><input type="checkbox" style="accent-color:var(--accent-primary);" ${d.can_ct ? 'checked' : ''} onchange="toggleDiagCT(${d.id}, this.checked)"></td>
            <td><input type="checkbox" style="accent-color:var(--accent-primary);" ${d.can_mri ? 'checked' : ''} onchange="toggleDiagMRI(${d.id}, this.checked)"></td>
            <td>
                <select class="form-input filter-select" style="width:120px;padding:4px;font-size:12px;" onchange="updatePreferredLab(${d.id}, this.value)">
                    <option value="" ${!d.preferred_lab_id ? 'selected' : ''}>Κανένα</option>
                    <option value="1" ${d.preferred_lab_id === 1 ? 'selected' : ''}>ΚΟΛΙΑΤΣΟΥ (1)</option>
                    <option value="5" ${d.preferred_lab_id === 5 ? 'selected' : ''}>ΣΕΠΟΛΙΑ (5)</option>
                    <option value="6" ${d.preferred_lab_id === 6 ? 'selected' : ''}>ΑΝΩ ΠΑΤΗΣΙΑ (6)</option>
                    <option value="7" ${d.preferred_lab_id === 7 ? 'selected' : ''}>ΙΛΙΟΝ (7)</option>
                </select>
            </td>
            <td>
                <button class="btn btn-sm" style="background-color: ${d.active ? '#ef4444' : '#22c55e'}; color:white; border:none;" onclick="toggleDiagActive(${d.id}, ${!d.active})">
                    ${d.active ? 'Απενεργοποίηση' : 'Ενεργοποίηση'}
                </button>
            </td>
        </tr>
    `).join('');
    
    updateDiagPagination();
}

function changeDiagPage(dir) {
    const newPage = diagsPage + dir;
    if (newPage < 0 || newPage * diagsPageSize >= totalDiags) return;
    diagsPage = newPage;
    renderDiagnosticians();
    window.scrollTo({ top: 0, behavior: 'smooth' });
    document.querySelectorAll('div[style*="overflow-x: auto"], .main-content').forEach(el => el.scrollTo({ top: 0, behavior: 'smooth' }));
}

function updateDiagPagination() {
    const info = document.getElementById('diag-pagination-info');
    if (!info) return;
    if (totalDiags === 0) {
        info.textContent = 'Σελίδα 0 (0 από 0)';
    } else {
        const pageNum = diagsPage + 1;
        const start = diagsPage * diagsPageSize + 1;
        const end = Math.min((diagsPage + 1) * diagsPageSize, totalDiags);
        info.textContent = `Σελίδα ${pageNum} (${start}-${end} από ${totalDiags})`;
    }
    
    const prevBtn = document.getElementById('btn-diag-prev');
    const nextBtn = document.getElementById('btn-diag-next');
    if (prevBtn) prevBtn.disabled = diagsPage === 0;
    if (nextBtn) nextBtn.disabled = (diagsPage + 1) * diagsPageSize >= totalDiags;
}

async function toggleDiagCT(id, newCanCT) {
    const d = diagnosticians.find(x => x.id === id);
    if (!d) return;
    d.can_ct = newCanCT;
    try { await apiCall(`/admin/diagnosticians/${id}`, 'PUT', d); } catch { /* mock mode */ }
    populateDiagnosticianSelects();
    showToast(`Η ικανότητα CT ενημερώθηκε: ${d.name}`, 'success');
}

async function toggleDiagMRI(id, newCanMRI) {
    const d = diagnosticians.find(x => x.id === id);
    if (!d) return;
    d.can_mri = newCanMRI;
    try { await apiCall(`/admin/diagnosticians/${id}`, 'PUT', d); } catch { /* mock mode */ }
    populateDiagnosticianSelects();
    showToast(`Η ικανότητα MRI ενημερώθηκε: ${d.name}`, 'success');
}

function renderAvailability() {
    const tbody = document.getElementById('avail-tbody');
    if (!tbody) return;

    // Filter only today and future dates, excluding entries marked as 'available'
    const todayStr = formatDateLocal(new Date());
    const filteredAvailability = availability
        .filter(a => a.date >= todayStr && a.status !== 'available')
        .sort((a, b) => a.diagnostician_id - b.diagnostician_id || a.date.localeCompare(b.date));

    const statusLabel = { available: 'Διαθέσιμος/η', on_leave: 'Άδεια', half_day: 'Μισή Μέρα' };
    const statusClass = { available: 'active', on_leave: 'on-leave', half_day: 'inactive' };

    const rows = [];

    // Group consecutive dates
    let currentGroup = null;
    filteredAvailability.forEach(a => {
        if (!currentGroup) {
            currentGroup = { ...a, startDate: a.date, endDate: a.date };
        } else if (
            currentGroup.diagnostician_id === a.diagnostician_id &&
            currentGroup.status === a.status &&
            currentGroup.notes === a.notes
        ) {
            // Check if dates are consecutive
            const currDate = new Date(currentGroup.endDate + 'T00:00:00');
            const nextDate = new Date(a.date + 'T00:00:00');
            const diffTime = Math.abs(nextDate - currDate);
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)); 
            
            if (diffDays <= 1) { // 1 day diff or same day
                currentGroup.endDate = a.date;
            } else {
                rows.push(currentGroup);
                currentGroup = { ...a, startDate: a.date, endDate: a.date };
            }
        } else {
            rows.push(currentGroup);
            currentGroup = { ...a, startDate: a.date, endDate: a.date };
        }
    });
    if (currentGroup) rows.push(currentGroup);

    const finalRows = [];

    // 1. Add grouped diagnosticians on leave
    rows.forEach(a => {
        let dateDisplay = formatDate(a.startDate);
        if (a.startDate !== a.endDate) {
            dateDisplay += ` - ${formatDate(a.endDate)}`;
        }
        finalRows.push({
            diagnostician_id: a.diagnostician_id,
            diagnostician_name: a.diagnostician_name,
            sortDate: a.startDate,
            endDate: a.endDate,
            dateDisplay: dateDisplay,
            statusBadge: `<span class="status-badge ${statusClass[a.status] || 'on-leave'}">${statusLabel[a.status] || 'Άδεια'}</span>`,
            notes: a.notes || '—',
            isExplicitLeave: true
        });
    });

    // 2. Add diagnosticians who are not diagnosing today according to their daily quota
    const todayWeekday = new Date().getDay(); // 0 is Sunday, 1 is Monday...
    const pyWeekday = todayWeekday === 0 ? 6 : todayWeekday - 1; // Python weekday: 0 is Monday, 6 is Sunday
    
    const quotaKeys = ['quota_monday', 'quota_tuesday', 'quota_wednesday', 'quota_thursday', 'quota_friday', 'quota_saturday', 'quota_sunday'];
    const todayQuotaKey = quotaKeys[pyWeekday];

    const offToday = diagnosticians.filter(d => d.active && d[todayQuotaKey] === 0);

    offToday.forEach(d => {
        // Skip if this diagnostician already has an explicit leave entry recorded for today
        const hasLeaveToday = filteredAvailability.some(r => r.diagnostician_id === d.id && r.date === todayStr);
        if (!hasLeaveToday) {
            finalRows.push({
                diagnostician_id: d.id,
                diagnostician_name: d.name,
                sortDate: todayStr,
                endDate: todayStr,
                dateDisplay: formatDate(todayStr),
                statusBadge: `<span class="status-badge inactive">Όχι σήμερα</span>`,
                notes: '',
                isExplicitLeave: false
            });
        }
    });

    if (!finalRows.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-tertiary);text-align:center;padding:20px;">Δεν υπάρχουν εγγραφές</td></tr>';
        return;
    }

    // Sort rows by date ascending
    finalRows.sort((a, b) => a.sortDate.localeCompare(b.sortDate));

    tbody.innerHTML = finalRows.map(r => `
        <tr>
            <td style="font-weight:500;">${r.diagnostician_name}</td>
            <td class="date-cell">${r.dateDisplay}</td>
            <td>${r.statusBadge}</td>
            <td style="color:var(--text-tertiary);">${r.notes}</td>
            <td style="text-align:right;">
                ${r.isExplicitLeave ? `
                    <button class="btn btn-ghost btn-sm" style="color:var(--accent-danger, #ef4444); padding: 4px 8px;" 
                            onclick="removeLeave(${r.diagnostician_id}, '${r.sortDate}', '${r.endDate}', '${(r.diagnostician_name || '').replace(/'/g, "\\'")}')"
                            title="Αφαίρεση αδείας">
                        🗑️ Αφαίρεση
                    </button>
                ` : '—'}
            </td>
        </tr>
    `).join('');
}

async function removeLeave(diagId, startDateStr, endDateStr, diagName) {
    if (!diagId || !startDateStr) return;

    const datesToRemove = [];
    let current = new Date(startDateStr + 'T00:00:00');
    let end = new Date((endDateStr || startDateStr) + 'T00:00:00');
    
    while (current <= end) {
        datesToRemove.push(formatDateLocal(current));
        current.setDate(current.getDate() + 1);
    }

    try {
        for (const dateVal of datesToRemove) {
            await apiCall(`/admin/availability/${diagId}/${dateVal}`, 'DELETE');
            availability = availability.filter(a => !(a.diagnostician_id === diagId && a.date === dateVal));
        }
        showToast(`✅ Αφαιρέθηκε η άδεια για: ${diagName}`, 'success');
    } catch (err) {
        for (const dateVal of datesToRemove) {
            availability = availability.filter(a => !(a.diagnostician_id === diagId && a.date === dateVal));
        }
        showToast(`✅ Αφαιρέθηκε η άδεια για: ${diagName}`, 'success');
    }

    renderAvailability();
}

function renderTodayOffSchedules() {
    renderAvailability();
}



function renderSkills() {
    const tbody = document.getElementById('skills-tbody');
    if (!tbody) return;

    if (!skills.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-tertiary);text-align:center;padding:20px;">Δεν υπάρχουν δεδομένα δεξιοτήτων</td></tr>';
        updateSkillsFloatingBar();
        return;
    }

    let filteredSkills = skills;
    if (skillsSearchQuery) {
        const rawQuery = skillsSearchQuery.toLowerCase().trim();
        const normQuery = typeof normalizeGreek === 'function' ? normalizeGreek(skillsSearchQuery) : rawQuery;
        filteredSkills = skills.filter(s => {
            const dName = (s.diagnostician_name || '').toLowerCase();
            const normDName = typeof normalizeGreek === 'function' ? normalizeGreek(dName) : dName;
            const dId = String(s.diagnostician_id || '').toLowerCase();
            const eCode = String(s.exam_code || '').toLowerCase();
            const eTitle = (s.exam_title || s.exam_name || s.body_part || '').toLowerCase();
            const normETitle = typeof normalizeGreek === 'function' ? normalizeGreek(eTitle) : eTitle;
            return dName.includes(rawQuery) || normDName.includes(normQuery) || dId.includes(rawQuery) || eCode.includes(rawQuery) || eTitle.includes(rawQuery) || normETitle.includes(normQuery);
        });
    }

    if (!filteredSkills.length) {
        tbody.innerHTML = `<tr><td colspan="5" style="color:var(--text-tertiary);text-align:center;padding:20px;">Δεν βρέθηκαν δεξιότητες που να ταιριάζουν με "${escapeHtml(skillsSearchQuery)}"</td></tr>`;
        updateSkillsFloatingBar();
        return;
    }

    // Group by diagnostician
    const grouped = {};
    filteredSkills.forEach(s => {
        if (!grouped[s.diagnostician_name]) grouped[s.diagnostician_name] = [];
        grouped[s.diagnostician_name].push(s);
    });

    let html = '';
    for (const [diagName, diagSkills] of Object.entries(grouped)) {
        const diagIdForCollapse = String(diagSkills[0].diagnostician_id || diagName.replace(/\s+/g, ''));
        if (skillsSearchQuery) {
            openSkillsGroups.add(diagIdForCollapse);
        }

        const isOpen = openSkillsGroups.has(diagIdForCollapse);
        const displayStyle = isOpen ? 'table-row' : 'none';
        const iconTransform = isOpen ? 'rotate(90deg)' : 'rotate(0deg)';

        const allDiagChecked = diagSkills.length > 0 && diagSkills.every(s => selectedSkillItemIds.has(String(s.id)));

        html += `
            <tr style="cursor:pointer; background:var(--surface-color); border-bottom:1px solid var(--border-color);" onclick="toggleSkillsRow('${diagIdForCollapse}')">
                <td style="width:40px; text-align:center; padding:12px;" onclick="event.stopPropagation();">
                    <input type="checkbox" class="skill-group-checkbox" id="chk-skill-group-${diagIdForCollapse}" ${allDiagChecked ? 'checked' : ''} onclick="toggleSelectDiagSkills(event, '${diagIdForCollapse}')" style="accent-color:var(--accent-primary); width:16px; height:16px; cursor:pointer;" title="Επιλογή όλων του διαγνώστη">
                </td>
                <td colspan="4" style="font-weight:600; padding:12px;">
                    <span id="icon-${diagIdForCollapse}" style="display:inline-block; width:20px; transition:transform 0.2s; transform:${iconTransform};">▶</span> 
                    ${diagName} <span style="color:var(--text-tertiary); font-weight:normal; font-size:13px;">(${diagSkills.length} δεξιότητες)</span>
                </td>
            </tr>
        `;
        
        // Children rows
        diagSkills.forEach((s) => {
            const isPreferred = s.is_preferred || false;
            const examCode = s.exam_code || '—';
            const rawTitle = s.exam_name || s.exam_title || EXAM_CODE_MAP[examCode] || s.body_part || examCode || '—';
            const examTitle = formatSimplifiedExamName(rawTitle, s.category, examCode);
            const isChecked = selectedSkillItemIds.has(String(s.id));
            const rowClass = isChecked ? 'selected-row' : '';
            
            html += `<tr class="skills-row-${diagIdForCollapse} ${rowClass}" style="display:${displayStyle}; background:#fafafa;">
                <td style="width:40px; text-align:center; padding:8px 12px;">
                    <input type="checkbox" class="row-checkbox skill-chk-item skill-chk-diag-${diagIdForCollapse}" value="${s.id}" ${isChecked ? 'checked' : ''} onchange="toggleSelectSkillItem('${s.id}')">
                </td>
                <td style="font-family:monospace;font-size:var(--font-size-sm);">${examCode}</td>
                <td style="font-size:var(--font-size-sm);">${examTitle}</td>
                <td>
                    <button class="btn btn-sm ${isPreferred ? 'btn-primary' : 'btn-secondary'}" onclick="toggleSkillPreference(${s.id}, ${!isPreferred})" style="padding:4px 8px; font-size:12px;">
                        ${isPreferred ? '★ Προτιμά' : 'Προτίμηση'}
                    </button>
                </td>
                <td>
                    <button class="btn btn-secondary btn-sm" style="color:var(--accent-danger);" onclick="deleteSkill(${s.id})">Διαγραφή</button>
                </td>
            </tr>`;
        });
    }
    tbody.innerHTML = html;
    updateSkillsFloatingBar();
}

function toggleSelectSkillItem(id) {
    const idStr = String(id);
    if (selectedSkillItemIds.has(idStr)) {
        selectedSkillItemIds.delete(idStr);
    } else {
        selectedSkillItemIds.add(idStr);
    }
    renderSkills();
}

function toggleSelectDiagSkills(event, diagId) {
    event.stopPropagation();
    const isChecked = event.target.checked;
    const childChks = document.querySelectorAll('.skill-chk-diag-' + diagId);
    childChks.forEach(chk => {
        chk.checked = isChecked;
        if (isChecked) selectedSkillItemIds.add(String(chk.value));
        else selectedSkillItemIds.delete(String(chk.value));
    });
    renderSkills();
}

function toggleSelectAllSkills(isChecked) {
    const allItemChks = document.querySelectorAll('.skill-chk-item');
    allItemChks.forEach(chk => {
        chk.checked = isChecked;
        if (isChecked) selectedSkillItemIds.add(String(chk.value));
        else selectedSkillItemIds.delete(String(chk.value));
    });
    renderSkills();
}

function updateSkillsFloatingBar() {
    const fab = document.getElementById('skills-floating-bar');
    const countEl = document.getElementById('skills-fab-count');
    const actionsEl = document.getElementById('skills-fab-actions');
    const topChk = document.getElementById('chk-skills-all');
    if (!fab || !countEl) return;

    const size = selectedSkillItemIds.size;
    if (size === 0) {
        fab.style.display = 'none';
        if (topChk) { topChk.checked = false; topChk.indeterminate = false; }
        return;
    }

    fab.style.display = 'flex';
    countEl.textContent = `${size} επιλεγμέν${size === 1 ? 'η δεξιότητα' : 'ες δεξιότητες'}`;

    const selectedItems = skills.filter(s => selectedSkillItemIds.has(String(s.id)));
    const allPreferred = selectedItems.length > 0 && selectedItems.every(s => Boolean(s.is_preferred));
    const allUnpreferred = selectedItems.length > 0 && selectedItems.every(s => !Boolean(s.is_preferred));

    let actionsHtml = '';

    if (allPreferred) {
        actionsHtml += `<button class="btn btn-secondary btn-sm" onclick="bulkSetSkillsPreference(false)">☆ Αφαίρεση Προτίμησης</button>`;
    } else if (allUnpreferred) {
        actionsHtml += `<button class="btn btn-primary btn-sm" onclick="bulkSetSkillsPreference(true)">★ Ορισμός ως Προτιμώμενες</button>`;
    } else {
        actionsHtml += `<button class="btn btn-primary btn-sm" onclick="bulkSetSkillsPreference(true)">★ Ορισμός ως Προτιμώμενες</button>`;
        actionsHtml += `<button class="btn btn-secondary btn-sm" onclick="bulkSetSkillsPreference(false)">☆ Αφαίρεση Προτίμησης</button>`;
    }

    actionsHtml += `<button class="btn btn-danger btn-sm" onclick="bulkDeleteSkills()">🗑️ Διαγραφή</button>`;
    actionsHtml += `<button class="btn btn-ghost btn-sm" onclick="clearSkillsSelection()">✕ Ακύρωση</button>`;

    if (actionsEl) actionsEl.innerHTML = actionsHtml;

    const allItemChks = document.querySelectorAll('.skill-chk-item');
    if (topChk && allItemChks.length > 0) {
        const allChecked = Array.from(allItemChks).every(c => c.checked);
        const someChecked = Array.from(allItemChks).some(c => c.checked);
        topChk.checked = allChecked;
        topChk.indeterminate = !allChecked && someChecked;
    }
}

function clearSkillsSelection() {
    selectedSkillItemIds.clear();
    renderSkills();
}

async function bulkSetSkillsPreference(isPreferred) {
    if (selectedSkillItemIds.size === 0) return;
    const ids = Array.from(selectedSkillItemIds);
    let updatedCount = 0;
    for (const idStr of ids) {
        const skillId = isNaN(Number(idStr)) ? idStr : Number(idStr);
        const s = skills.find(x => String(x.id) === idStr);
        if (!s) continue;
        s.is_preferred = isPreferred;
        try {
            await apiCall(`/admin/skills/${skillId}`, 'PUT', s);
            updatedCount++;
        } catch { /* mock mode */ updatedCount++; }
    }
    renderSkills();
    showToast(`✅ Ενημερώθηκαν ${updatedCount} δεξιότητες (${isPreferred ? 'Προτιμάται' : 'Όχι προτίμηση'})`, 'success');
}

async function bulkDeleteSkills() {
    if (selectedSkillItemIds.size === 0) return;
    if (!confirm(`Διαγραφή ${selectedSkillItemIds.size} επιλεγμένων δεξιοτήτων;`)) return;
    const ids = Array.from(selectedSkillItemIds);
    let deletedCount = 0;
    for (const idStr of ids) {
        const skillId = isNaN(Number(idStr)) ? idStr : Number(idStr);
        try {
            await apiCall(`/admin/skills/${skillId}`, 'DELETE');
        } catch { /* mock mode */ }
        skills = skills.filter(s => String(s.id) !== idStr);
        deletedCount++;
    }
    clearSkillsSelection();
    renderSkills();
    showToast(`🗑️ Διαγράφηκαν ${deletedCount} δεξιότητες`, 'success');
}

// Helper to toggle skills display
function toggleSkillsRow(diagId) {
    const idStr = String(diagId);
    if (openSkillsGroups.has(idStr)) {
        openSkillsGroups.delete(idStr);
    } else {
        openSkillsGroups.add(idStr);
    }
    renderSkills();
}

function togglePartnershipsRow(diagId) {
    const idStr = String(diagId);
    if (openPartnershipsGroups.has(idStr)) {
        openPartnershipsGroups.delete(idStr);
    } else {
        openPartnershipsGroups.add(idStr);
    }
    renderPartnerships();
}

function renderPartnerships() {
    const tbody = document.getElementById('part-tbody');
    if (!tbody) return;

    if (!partnerships.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-tertiary);text-align:center;padding:20px;">Δεν υπάρχουν συνεργασίες</td></tr>';
        updatePartnershipsFloatingBar();
        return;
    }

    let filteredPartnerships = partnerships;
    if (partnershipsSearchQuery) {
        const rawQuery = partnershipsSearchQuery.toLowerCase().trim();
        const normQuery = typeof normalizeGreek === 'function' ? normalizeGreek(partnershipsSearchQuery) : rawQuery;
        filteredPartnerships = partnerships.filter(p => {
            const dName = (p.preferred_diagnostician_name || '').toLowerCase();
            const normDName = typeof normalizeGreek === 'function' ? normalizeGreek(dName) : dName;
            const dId = String(p.preferred_diagnostician_id || '').toLowerCase();
            const docName = (p.issuing_doctor_name || '').toLowerCase();
            const normDocName = typeof normalizeGreek === 'function' ? normalizeGreek(docName) : docName;
            const docId = String(p.issuing_doctor_id || '').toLowerCase();
            return dName.includes(rawQuery) || normDName.includes(normQuery) || dId.includes(rawQuery) || docName.includes(rawQuery) || normDocName.includes(normQuery) || docId.includes(rawQuery);
        });
    }

    if (!filteredPartnerships.length) {
        tbody.innerHTML = `<tr><td colspan="5" style="color:var(--text-tertiary);text-align:center;padding:20px;">Δεν βρέθηκαν συνεργασίες που να ταιριάζουν με "${escapeHtml(partnershipsSearchQuery)}"</td></tr>`;
        updatePartnershipsFloatingBar();
        return;
    }

    // Group by diagnostician
    const grouped = {};
    filteredPartnerships.forEach(p => {
        if (!grouped[p.preferred_diagnostician_name]) grouped[p.preferred_diagnostician_name] = [];
        grouped[p.preferred_diagnostician_name].push(p);
    });

    let html = '';
    for (const [diagName, diagPartners] of Object.entries(grouped)) {
        const diagIdForCollapse = String(diagPartners[0].preferred_diagnostician_id || diagName.replace(/\s+/g, ''));
        if (partnershipsSearchQuery) {
            openPartnershipsGroups.add(diagIdForCollapse);
        }

        const isOpen = openPartnershipsGroups.has(diagIdForCollapse);
        const displayStyle = isOpen ? 'table-row' : 'none';
        const iconTransform = isOpen ? 'rotate(90deg)' : 'rotate(0deg)';

        const allDiagChecked = diagPartners.length > 0 && diagPartners.every(p => selectedPartnershipItemIds.has(String(p.id)));

        html += `
            <tr style="cursor:pointer; background:var(--surface-color); border-bottom:1px solid var(--border-color);" onclick="togglePartnershipsRow('${diagIdForCollapse}')">
                <td style="width:40px; text-align:center; padding:12px;" onclick="event.stopPropagation();">
                    <input type="checkbox" class="part-group-checkbox" id="chk-part-group-${diagIdForCollapse}" ${allDiagChecked ? 'checked' : ''} onclick="toggleSelectDiagPartnerships(event, '${diagIdForCollapse}')" style="accent-color:var(--accent-primary); width:16px; height:16px; cursor:pointer;" title="Επιλογή όλων του διαγνώστη">
                </td>
                <td colspan="4" style="font-weight:600; padding:12px;">
                    <span id="part-icon-${diagIdForCollapse}" style="display:inline-block; width:20px; transition:transform 0.2s; transform:${iconTransform};">▶</span> 
                    <span style="color:var(--accent-primary);">${diagName}</span> <span style="color:var(--text-tertiary); font-weight:normal; font-size:13px;">(${diagPartners.length} συνεργασίες)</span>
                </td>
            </tr>
        `;
        
        // Sort: active first, then inactive, then alphabetically by issuing doctor name
        diagPartners.sort((a, b) => {
            const aActive = a.is_active === undefined ? 1 : a.is_active;
            const bActive = b.is_active === undefined ? 1 : b.is_active;
            if (aActive !== bActive) return bActive - aActive;
            return a.issuing_doctor_name.localeCompare(b.issuing_doctor_name, 'el');
        });
        
        // Children rows
        diagPartners.forEach(p => {
            const isActive = p.is_active === undefined ? true : Boolean(p.is_active);
            const isExclusive = Boolean(p.exclusive);
            const isChecked = selectedPartnershipItemIds.has(String(p.id));
            const rowClass = isChecked ? 'selected-row' : '';
            
            html += `<tr class="part-row-${diagIdForCollapse} ${rowClass}" style="display:${displayStyle}; background:#fafafa;">
                <td style="width:40px; text-align:center; padding:8px 12px;">
                    <input type="checkbox" class="row-checkbox part-chk-item part-chk-diag-${diagIdForCollapse}" value="${p.id}" ${isChecked ? 'checked' : ''} onchange="toggleSelectPartnershipItem('${p.id}')">
                </td>
                <td style="font-weight:500;">${p.issuing_doctor_name} <span style="color:var(--text-tertiary);font-size:11px;">(${p.issuing_doctor_id})</span></td>
                <td>
                    <button class="btn btn-sm ${isActive ? 'btn-primary' : 'btn-secondary'}" onclick="togglePartnershipProperty(${p.id}, 'is_active', ${!isActive})" style="padding:4px 8px; font-size:12px;">
                        ${isActive ? 'Ενεργή' : 'Ανενεργή'}
                    </button>
                </td>
                <td>
                    <button class="btn btn-sm ${isExclusive ? 'btn-primary' : 'btn-secondary'}" onclick="togglePartnershipProperty(${p.id}, 'exclusive', ${!isExclusive})" style="padding:4px 8px; font-size:12px;">
                        ${isExclusive ? '⚡ Αποκλειστική' : 'Όχι'}
                    </button>
                </td>
                <td>
                    <button class="btn btn-secondary btn-sm" style="color:var(--accent-danger);" onclick="deletePartnership(${p.id})">Διαγραφή</button>
                </td>
            </tr>`;
        });
    }
    tbody.innerHTML = html;
    updatePartnershipsFloatingBar();
}

function toggleSelectPartnershipItem(id) {
    const idStr = String(id);
    if (selectedPartnershipItemIds.has(idStr)) {
        selectedPartnershipItemIds.delete(idStr);
    } else {
        selectedPartnershipItemIds.add(idStr);
    }
    renderPartnerships();
}

function toggleSelectDiagPartnerships(event, diagId) {
    event.stopPropagation();
    const isChecked = event.target.checked;
    const childChks = document.querySelectorAll('.part-chk-diag-' + diagId);
    childChks.forEach(chk => {
        chk.checked = isChecked;
        if (isChecked) selectedPartnershipItemIds.add(String(chk.value));
        else selectedPartnershipItemIds.delete(String(chk.value));
    });
    renderPartnerships();
}

function toggleSelectAllPartnerships(isChecked) {
    const allItemChks = document.querySelectorAll('.part-chk-item');
    allItemChks.forEach(chk => {
        chk.checked = isChecked;
        if (isChecked) selectedPartnershipItemIds.add(String(chk.value));
        else selectedPartnershipItemIds.delete(String(chk.value));
    });
    renderPartnerships();
}

function updatePartnershipsFloatingBar() {
    const fab = document.getElementById('partnerships-floating-bar');
    const countEl = document.getElementById('part-fab-count');
    const actionsEl = document.getElementById('part-fab-actions');
    const topChk = document.getElementById('chk-part-all');
    if (!fab || !countEl) return;

    const size = selectedPartnershipItemIds.size;
    if (size === 0) {
        fab.style.display = 'none';
        if (topChk) { topChk.checked = false; topChk.indeterminate = false; }
        return;
    }

    fab.style.display = 'flex';
    countEl.textContent = `${size} επιλεγμέν${size === 1 ? 'η συνεργασία' : 'ες συνεργασίες'}`;

    const selectedItems = partnerships.filter(p => selectedPartnershipItemIds.has(String(p.id)));
    const allActive = selectedItems.length > 0 && selectedItems.every(p => (p.is_active === undefined ? true : Boolean(p.is_active)));
    const allInactive = selectedItems.length > 0 && selectedItems.every(p => (p.is_active !== undefined && !Boolean(p.is_active)));

    const allExclusive = selectedItems.length > 0 && selectedItems.every(p => Boolean(p.exclusive));
    const allNonExclusive = selectedItems.length > 0 && selectedItems.every(p => !Boolean(p.exclusive));

    let actionsHtml = '';

    // Active status action button
    if (allActive) {
        actionsHtml += `<button class="btn btn-danger btn-sm" onclick="bulkSetPartnershipsActive(false)">⚠️ Απενεργοποίηση</button>`;
    } else if (allInactive) {
        actionsHtml += `<button class="btn btn-success btn-sm" onclick="bulkSetPartnershipsActive(true)">✅ Ενεργοποίηση</button>`;
    } else {
        actionsHtml += `<button class="btn btn-success btn-sm" onclick="bulkSetPartnershipsActive(true)">✅ Ενεργοποίηση</button>`;
        actionsHtml += `<button class="btn btn-danger btn-sm" onclick="bulkSetPartnershipsActive(false)">⚠️ Απενεργοποίηση</button>`;
    }

    // Exclusive status action button
    if (allExclusive) {
        actionsHtml += `<button class="btn btn-danger btn-sm" onclick="bulkSetPartnershipsExclusive(false)">🚫 Όχι Αποκλειστική</button>`;
    } else if (allNonExclusive) {
        actionsHtml += `<button class="btn btn-primary btn-sm" onclick="bulkSetPartnershipsExclusive(true)">⚡ Αποκλειστική</button>`;
    } else {
        actionsHtml += `<button class="btn btn-primary btn-sm" onclick="bulkSetPartnershipsExclusive(true)">⚡ Αποκλειστική</button>`;
        actionsHtml += `<button class="btn btn-danger btn-sm" onclick="bulkSetPartnershipsExclusive(false)">🚫 Όχι Αποκλειστική</button>`;
    }

    actionsHtml += `<button class="btn btn-danger btn-sm" onclick="bulkDeletePartnerships()">🗑️ Διαγραφή</button>`;
    actionsHtml += `<button class="btn btn-ghost btn-sm" onclick="clearPartnershipsSelection()">✕ Ακύρωση</button>`;

    if (actionsEl) actionsEl.innerHTML = actionsHtml;

    const allItemChks = document.querySelectorAll('.part-chk-item');
    if (topChk && allItemChks.length > 0) {
        const allChecked = Array.from(allItemChks).every(c => c.checked);
        const someChecked = Array.from(allItemChks).some(c => c.checked);
        topChk.checked = allChecked;
        topChk.indeterminate = !allChecked && someChecked;
    }
}

function clearPartnershipsSelection() {
    selectedPartnershipItemIds.clear();
    renderPartnerships();
}

async function bulkSetPartnershipsActive(isActive) {
    if (selectedPartnershipItemIds.size === 0) return;
    const ids = Array.from(selectedPartnershipItemIds);
    let updatedCount = 0;
    for (const idStr of ids) {
        const partId = isNaN(Number(idStr)) ? idStr : Number(idStr);
        try {
            await apiCall(`/admin/partnerships/${partId}`, 'PATCH', { is_active: isActive });
            updatedCount++;
        } catch {
            const p = partnerships.find(x => String(x.id) === idStr);
            if (p) p.is_active = isActive;
            updatedCount++;
        }
    }
    await loadPartnerships();
    showToast(`✅ Ενημερώθηκαν ${updatedCount} συνεργασίες (${isActive ? 'Ενεργές' : 'Ανενεργές'})`, 'success');
}

async function bulkSetPartnershipsExclusive(isExclusive) {
    if (selectedPartnershipItemIds.size === 0) return;
    const ids = Array.from(selectedPartnershipItemIds);
    let updatedCount = 0;
    for (const idStr of ids) {
        const partId = isNaN(Number(idStr)) ? idStr : Number(idStr);
        try {
            await apiCall(`/admin/partnerships/${idStr}`, 'PATCH', { exclusive: isExclusive });
            updatedCount++;
        } catch {
            const p = partnerships.find(x => String(x.id) === idStr);
            if (p) p.exclusive = isExclusive;
            updatedCount++;
        }
    }
    await loadPartnerships();
    showToast(`✅ Ενημερώθηκαν ${updatedCount} συνεργασίες (${isExclusive ? 'Αποκλειστικές' : 'Όχι αποκλειστικές'})`, 'success');
}

async function bulkDeletePartnerships() {
    if (selectedPartnershipItemIds.size === 0) return;
    if (!confirm(`Διαγραφή ${selectedPartnershipItemIds.size} επιλεγμένων συνεργασιών;`)) return;
    const ids = Array.from(selectedPartnershipItemIds);
    let deletedCount = 0;
    for (const idStr of ids) {
        const partId = isNaN(Number(idStr)) ? idStr : Number(idStr);
        try {
            await apiCall(`/admin/partnerships/${partId}`, 'DELETE');
        } catch {
            partnerships = partnerships.filter(p => String(p.id) !== idStr);
        }
        deletedCount++;
    }
    clearPartnershipsSelection();
    await loadPartnerships();
    showToast(`🗑️ Διαγράφηκαν ${deletedCount} συνεργασίες`, 'success');
}

function renderDoctors() {
    const tbody = document.getElementById('doc-tbody');
    tbody.innerHTML = doctors.map(d => `
        <tr>
            <td style="color:var(--text-tertiary);font-size:var(--font-size-xs);">${d.id}</td>
            <td style="font-weight:500;">${d.name}</td>
            <td style="color:var(--text-secondary);">${d.partner_name || '—'}</td>
        </tr>
    `).join('');
}


// ══════════════════════════════════════════════
//  Actions
// ══════════════════════════════════════════════

async function setOncall() {
    const selEl = document.getElementById('oncall-diag-select');
    const diagId = parseInt(selEl.value);
    const diagName = selEl.options[selEl.selectedIndex]?.dataset?.name || '';
    const dateVal = document.getElementById('oncall-date').value;

    if (!diagId || !dateVal) { showToast('Επιλέξτε διαγνώστη και ημερομηνία', 'warning'); return; }

    try {
        await apiCall('/admin/oncall', 'POST', { diagnostician_id: diagId, diagnostician_name: diagName, date: dateVal });
        showToast(`✅ Εφημερία ορίστηκε: ${diagName} (${formatDate(dateVal)})`, 'success');
        await loadOncall();
    } catch (err) {
        // Mock mode
        document.getElementById('oncall-current').innerHTML =
            `<strong style="color:var(--text-primary);font-size:var(--font-size-md);">${diagName}</strong>
             <span style="margin-left:8px;color:var(--text-tertiary);">(${formatDate(dateVal)})</span>`;
        showToast(`✅ Εφημερία ορίστηκε: ${diagName} (mock)`, 'success');
    }
}

async function addDiagnostician() {
    const name = document.getElementById('new-diag-name').value.trim();
    const quota = parseInt(document.getElementById('new-diag-quota').value);
    const can_ct = document.getElementById('new-diag-ct').checked;
    const can_mri = document.getElementById('new-diag-mri').checked;
    const active = document.getElementById('new-diag-active').checked;

    if (!name) { showToast('Εισάγετε ονοματεπώνυμο', 'warning'); return; }

    try {
        const result = await apiCall('/admin/diagnosticians', 'POST', { name, active, can_ct, can_mri, quota_monday: quota, quota_tuesday: quota, quota_wednesday: quota, quota_thursday: quota, quota_friday: quota, quota_saturday: quota, quota_sunday: quota });
        if (result) diagnosticians.push(result);
        else diagnosticians.push({ id: Date.now(), name, active, can_ct, can_mri, quota_monday: quota, quota_tuesday: quota, quota_wednesday: quota, quota_thursday: quota, quota_friday: quota, quota_saturday: quota, quota_sunday: quota });
    } catch {
        diagnosticians.push({ id: Date.now(), name, active, can_ct, can_mri, quota_monday: quota, quota_tuesday: quota, quota_wednesday: quota, quota_thursday: quota, quota_friday: quota, quota_saturday: quota, quota_sunday: quota });
    }

    renderDiagnosticians();
    populateDiagnosticianSelects();
    renderWeeklyScheduleGrid();
    document.getElementById('new-diag-name').value = '';
    showToast(`✅ Ο/Η ${name} προστέθηκε`, 'success');
}


async function toggleDiagActive(id, newActive) {
    const d = diagnosticians.find(x => x.id === id);
    if (!d) return;
    d.active = newActive;

    try {
        await apiCall(`/admin/diagnosticians/${id}`, 'PUT', { ...d, active: newActive });
    } catch { /* mock mode */ }

    renderDiagnosticians();
    populateDiagnosticianSelects();
    renderWeeklyScheduleGrid();
    showToast(`${newActive ? '✅ Ενεργοποίηση' : '⚠️ Απενεργοποίηση'}: ${d.name}`, newActive ? 'success' : 'warning');
}



async function setAvailability() {
    const selEl = document.getElementById('avail-diag');
    const diagId = parseInt(selEl.value);
    const diagName = selEl.options[selEl.selectedIndex]?.dataset?.name || '';
    
    // Retrieve dates directly from the flatpickr instance
    const fpInstance = document.getElementById('avail-date')._flatpickr;
    let datesToSave = [];
    
    if (fpInstance && fpInstance.selectedDates.length > 0) {
        if (fpInstance.selectedDates.length === 2) {
            let current = new Date(fpInstance.selectedDates[0]);
            let end = new Date(fpInstance.selectedDates[1]);
            while (current <= end) {
                datesToSave.push(formatDateLocal(current));
                current.setDate(current.getDate() + 1);
            }
        } else {
            datesToSave.push(formatDateLocal(fpInstance.selectedDates[0]));
        }
    } else {
        const rawVal = document.getElementById('avail-date').value.trim();
        if (rawVal) {
            if (rawVal.includes(' to ')) {
                const parts = rawVal.split(' to ');
                let current = new Date(parts[0] + 'T00:00:00');
                let end = new Date(parts[1] + 'T00:00:00');
                while (current <= end) {
                    datesToSave.push(formatDateLocal(current));
                    current.setDate(current.getDate() + 1);
                }
            } else {
                datesToSave.push(rawVal);
            }
        }
    }
    
    const notes = document.getElementById('avail-notes').value.trim();
    // Status defaults to 'on_leave' since Κατάσταση was removed
    const status = 'on_leave';

    if (!diagId || datesToSave.length === 0) { showToast('Επιλέξτε διαγνώστη και ημερομηνία', 'warning'); return; }

    for (const dateVal of datesToSave) {
        const record = { diagnostician_id: diagId, diagnostician_name: diagName, date: dateVal, status, notes };
        try {
            const result = await apiCall('/admin/availability', 'POST', record);
            if (result) {
                availability = availability.filter(a => !(a.diagnostician_id === diagId && a.date === dateVal));
                availability.push(result);
            }
        } catch {
            availability = availability.filter(a => !(a.diagnostician_id === diagId && a.date === dateVal));
            availability.push({ id: Date.now(), ...record });
        }
    }

    renderAvailability();
    document.getElementById('avail-notes').value = '';
    showToast(`✅ Άδεια καταγράφηκε: ${diagName} (${datesToSave.length} ημερών)`, 'success');
}

async function updatePreferredLab(id, val) {
    const d = diagnosticians.find(x => x.id === id);
    if (!d) return;
    d.preferred_lab_id = val ? parseInt(val) : null;

    try {
        await apiCall(`/admin/diagnosticians/${id}`, 'PUT', d);
    } catch { /* mock mode */ }

    showToast(`✅ Προτίμηση εργαστηρίου ενημερώθηκε: ${d.name}`, 'success');
}

async function updateWeeklyQuota(diagId, quotaField, value) {
    const newQuota = parseInt(value);
    if (isNaN(newQuota) || newQuota < 0) return;

    const d = diagnosticians.find(x => x.id === diagId);
    if (!d) return;

    d[quotaField] = newQuota;

    renderAvailability();
    renderWeeklyScheduleGrid();

    try {
        await apiCall(`/admin/diagnosticians/${diagId}`, 'PUT', d);
        showToast('✅ Το όριο αποθηκεύτηκε', 'success');
    } catch {
        showToast('Σφάλμα κατά την αποθήκευση του ορίου', 'error');
    }
}

async function setSkill() {
    const selEl = document.getElementById('skill-diag');
    const diagId = parseInt(selEl.value);
    const diagName = selEl.options[selEl.selectedIndex]?.dataset?.name || '';
    const is_preferred = document.getElementById('skill-preferred').checked;

    if (!diagId) { showToast('Επιλέξτε διαγνώστη', 'warning'); return; }

    const codes = Array.from(selectedSkillExamCodes);
    if (codes.length === 0) { showToast('Επιλέξτε τουλάχιστον έναν κωδικό εξέτασης από την αναζήτηση', 'warning'); return; }

    const targetDiag = diagnosticians.find(d => d.id === diagId);

    let addedCount = 0;
    for (const code of codes) {
        const cleanCode = String(code).trim();
        // 1. Check if skill already exists for this diagnostician
        const exists = skills.some(s => String(s.diagnostician_id) === String(diagId) && String(s.exam_code).trim() === cleanCode);
        if (exists) {
            showToast(`⚠️ Η δεξιότητα ${cleanCode} υπάρχει ήδη για τον/την ${diagName}`, 'warning');
            continue;
        }

        // 2. Determine modality of the exam code
        const examObj = (RAW_EXAM_CATEGORIES || []).find(ex => String(ex.examnumcode || ex.code || '').trim() === cleanCode);
        const examName = examObj ? examObj.name : (EXAM_CODE_MAP[cleanCode] || '');
        let cat = (examObj?.category || '').toUpperCase().trim();
        if (!cat) {
            if (/CT|ΑΞΟΝ/i.test(examName) || /^21/.test(cleanCode)) cat = 'CT';
            else if (/MRA|ΑΓΓΕΙΟ/i.test(examName) || /^228/.test(cleanCode)) cat = 'MRA';
            else if (/MRI|ΜΑΓΝΗΤ/i.test(examName) || /^22/.test(cleanCode)) cat = 'MRI';
            else cat = /^21/.test(cleanCode) ? 'CT' : 'MRI';
        }

        // 3. Prohibit adding skill if diagnostician does not evaluate this modality
        if (targetDiag) {
            if (cat === 'CT' && !targetDiag.can_ct) {
                showToast(`❌ Ο/Η ${diagName} δεν πραγματοποιεί Αξονικές (CT). Δεν προστέθηκε ο κωδικός ${cleanCode}.`, 'error');
                continue;
            }
            if ((cat === 'MRI' || cat === 'MRA') && !targetDiag.can_mri) {
                showToast(`❌ Ο/Η ${diagName} δεν πραγματοποιεί Μαγνητικές (MRI/MRA). Δεν προστέθηκε ο κωδικός ${cleanCode}.`, 'error');
                continue;
            }
        }

        const exam_title = examName || `Εξέταση ${cleanCode}`;
        const record = { diagnostician_id: diagId, diagnostician_name: diagName, exam_code: cleanCode, exam_title, is_preferred };
        try {
            const result = await apiCall('/admin/skills', 'POST', record);
            skills = skills.filter(s => !(String(s.diagnostician_id) === String(diagId) && String(s.exam_code).trim() === cleanCode));
            if (result) skills.push(result);
            else skills.push({ id: Date.now() + Math.random(), ...record });
            addedCount++;
        } catch (err) {
            showToast(`❌ Σφάλμα προσθήκης δεξιότητας ${cleanCode}: ${err.message || 'Αποτυχία API'}`, 'error');
        }
    }

    selectedSkillExamCodes.clear();
    renderExamCodeTags('skill');
    if (document.getElementById('skill-exam-search')) document.getElementById('skill-exam-search').value = '';
    if (addedCount > 0) openSkillsGroups.add(String(diagId));
    renderSkills();
    if (addedCount > 0) {
        showToast(`✅ Προστέθηκαν ${addedCount} νέες δεξιότητες για τον/την ${diagName}`, 'success');
    }
}

async function addBulkSkills(targetModality) {
    const selEl = document.getElementById('skill-diag');
    const diagId = parseInt(selEl.value);
    const diagName = selEl.options[selEl.selectedIndex]?.dataset?.name || '';

    if (!diagId) { showToast('Επιλέξτε διαγνώστη πρώτα', 'warning'); return; }

    const targetDiag = diagnosticians.find(d => d.id === diagId);
    if (targetDiag) {
        if (targetModality === 'CT' && !targetDiag.can_ct) {
            showToast(`❌ Ο/Η ${diagName} δεν πραγματοποιεί Αξονικές (CT).`, 'error');
            return;
        }
        if (targetModality === 'MRI' && !targetDiag.can_mri) {
            showToast(`❌ Ο/Η ${diagName} δεν πραγματοποιεί Μαγνητικές (MRI/MRA).`, 'error');
            return;
        }
    }

    let matchingExams = [];
    if (RAW_EXAM_CATEGORIES && RAW_EXAM_CATEGORIES.length > 0) {
        matchingExams = RAW_EXAM_CATEGORIES.filter(ex => {
            const cat = (ex.category || '').toUpperCase();
            if (targetModality === 'CT') return cat === 'CT';
            if (targetModality === 'MRI') return cat === 'MRI' || cat === 'MRA';
            return false;
        });
    } else {
        for (const [code, name] of Object.entries(EXAM_CODE_MAP)) {
            if (targetModality === 'CT' && /CT|ΑΞΟΝ/i.test(name)) matchingExams.push({ examnumcode: code, name, category: 'CT' });
            else if (targetModality === 'MRI' && /MRI|MRA|ΜΑΓΝΗΤ|ΑΓΓΕΙΟ/i.test(name)) matchingExams.push({ examnumcode: code, name, category: 'MRI' });
        }
    }

    if (matchingExams.length === 0) {
        showToast(`Δεν βρέθηκαν εξετάσεις κατηγορίας ${targetModality}`, 'warning');
        return;
    }

    let count = 0;
    let skippedCount = 0;
    for (const ex of matchingExams) {
        const code = String(ex.examnumcode || ex.code || '').trim();
        const exists = skills.some(s => String(s.diagnostician_id) === String(diagId) && String(s.exam_code).trim() === code);
        if (exists) {
            skippedCount++;
            continue;
        }

        const name = ex.name || EXAM_CODE_MAP[code] || `Εξέταση ${code}`;
        const record = { diagnostician_id: diagId, diagnostician_name: diagName, exam_code: code, exam_title: name, is_preferred: false };
        try {
            const result = await apiCall('/admin/skills', 'POST', record);
            skills = skills.filter(s => !(String(s.diagnostician_id) === String(diagId) && String(s.exam_code).trim() === code));
            if (result) skills.push(result);
            else skills.push({ id: Date.now() + Math.random(), ...record });
            count++;
        } catch (err) {
            console.warn(`Bulk skill add error for code ${code}:`, err);
        }
    }

    if (count > 0) openSkillsGroups.add(String(diagId));
    renderSkills();
    if (count > 0) {
        showToast(`✅ Προστέθηκαν ${count} εξετάσεις ${targetModality} ως δεξιότητες στον/στην ${diagName}`, 'success');
    } else if (skippedCount > 0) {
        showToast(`ℹ️ Όλες οι εξετάσεις ${targetModality} υπάρχουν ήδη ως δεξιότητες για τον/την ${diagName}`, 'info');
    }
}

let selectedExamCodes = new Set();
let examsSearchQuery = '';

function filterExamsDictionary(query) {
    examsSearchQuery = (query || '').toLowerCase().trim();
    renderExamsSection();
}

function groupExamByAnatomicalRegion(name, category, code) {
    const c = String(code || '').trim();
    const n = normalizeGreek(name || '');
    const cat = (category || '').toUpperCase().trim();

    // Specific exam code overrides
    if (c) {
        if (cat === 'CT' || /^21/.test(c)) {
            if (['21641', '21405', '21408'].includes(c)) return { key: 'ct_other', title: '📋 Λοιπές Εξετάσεις', order: 99 };
            if (['21680', '21602', '21650'].includes(c)) return { key: 'ct_pelvis', title: '🦴 Λεκάνη', order: 13 };
            if (['21725', '21701'].includes(c)) return { key: 'ct_lower', title: '🦵 Κάτω Άκρα', order: 2, subgroup: { key: 'amfo', title: '(Αμφω)', order: 3 } };
            if (['21102'].includes(c)) return { key: 'ct_abdomen', title: '🩺 Κοιλία', order: 10 };
        } else {
            if (['22056', '22057'].includes(c)) return { key: 'mri_head', title: '👤 Κεφαλή', order: 11 };
            if (['22201'].includes(c)) return { key: 'mri_chest', title: '🫁 Θώρακας', order: 2 };
            if (['22506', '22550', '22551', '22525', '22472'].includes(c)) return { key: 'mri_pelvis', title: '🦴 Λεκάνη', order: 12 };
            if (['22204'].includes(c)) return { key: 'mri_upper', title: '💪 Άνω Άκρα', order: 4, subgroup: { key: 'left', title: '(Αριστερό)', order: 1 } };
            if (['22709', '22481', '22560', '22705', '22708'].includes(c)) return { key: 'mri_other', title: '📋 Λοιπές Εξετάσεις', order: 99 };
        }
    }

    const isRight = /ΔΕΞΙ|ΔΕΞΙΑ|\bΔΕΞ\b/.test(n);
    const isLeft = /ΑΡΙΣΤΕΡ|ΑΡΙΣΤΕΡΑ|\bΑΡΙ\b|\bΑΡ\b/.test(n);
    const isBilateral = /ΑΜΦΩ|ΑΜΦΟΤΕΡ|ΑΜΦ|\bΑΚΡΩΝ\b|\bΑΚΡΑ\b/.test(n);

    if (cat === 'CT') {
        if (/ΑΓΓΕΙΟΓΡΑΦ|ΑΞΑ\b/.test(n)) {
            return { key: 'ct_angio', title: '🩸 Αγγειογραφίες', order: 11 };
        }
        if (/ΚΑΡΔΙ|ΑΟΡΤ|CALCIUM SCORE|ΣΤΕΦΑΝΙΟ|ΦΛΕΒΟΓΡΑΦΙ|TAVI/.test(n)) {
            return { key: 'ct_cardiac', title: '🫀 Καρδιά & Αγγεία', order: 12 };
        }
        if (/Σ\.?Σ\.?|ΣΠΟΝΔΥΛ|ΑΥΧΕΝΙΚ|ΘΩΡΑΚΙΚ|ΟΣΦΥ|ΙΕΡΟΚΟΚΚΥΓ|ΑΜΣΣ|ΘΜΣΣ|ΘΟΜΣΣ|ΟΜΣΣ|ΟΙΜΣΣ|ΙΚΜΣΣ/.test(n)) {
            return { key: 'ct_spine', title: '🦴 Σπονδυλική Στήλη', order: 9 };
        }
        if (/ΩΜ|ΩΜΟΠΛΑΤ|ΜΑΣΧΑΛ|ΒΡΑΧΙΟΝ|ΑΝΤΙΒΡΑΧ|ΑΓΚΩΝ|ΠΗΧΕΟΚΑΡΠ|ΚΑΡΠ|ΑΚΡ.*ΧΕΙΡ|ΣΚΑΦΟΕΙΔ/.test(n)) {
            let sub = { key: 'left', title: '(Αριστερό)', order: 1 };
            if (isBilateral || /ΚΑΤ' ΩΜΩΝ/.test(n)) sub = { key: 'amfo', title: '(Αμφω)', order: 3 };
            else if (isRight) sub = { key: 'right', title: '(Δεξί)', order: 2 };
            return { key: 'ct_upper', title: '💪 Άνω Άκρα', order: 1, subgroup: sub };
        }
        if (/ΜΗΡ|ΓΟΝΑΤ|ΚΝΗΜ|ΠΟΔΟΚΝΗΜ|ΠΔΚΝΜ|ΑΚΡ.*ΠΟΔ|ΑΧΙΛΛ|ΤΑΡΣ|ΠΤΕΡΝ|ΓΛΟΥΤ|ΙΓΝΥΑΚ/.test(n)) {
            let sub = { key: 'left', title: '(Αριστερό)', order: 1 };
            if (isBilateral || /ΚΑΤΩ ΑΚΡΩΝ/.test(n)) sub = { key: 'amfo', title: '(Αμφω)', order: 3 };
            else if (isRight) sub = { key: 'right', title: '(Δεξί)', order: 2 };
            return { key: 'ct_lower', title: '🦵 Κάτω Άκρα', order: 2, subgroup: sub };
        }
        if (/ΘΩΡΑΚ|ΥΠΕΡΚΛΕΙΔ|ΣΤΕΡΝΟΚΛΕΙΔ|ΜΑΣΤΟΕΙΔ|ΜΑΣΤ/.test(n)) {
            return { key: 'ct_chest', title: '🫁 Θώρακας', order: 8 };
        }
        if (/ΕΓΚΕΦΑΛ|ΥΠΟΦΥΣ|ΓΕΦΥΡΟΠΑΡΕΓΚΕΦΑΛ|ΠΡΟΣΩΠ|ΟΦΘΑΛΜ|ΕΣΩ ΑΚΟΥΣΤ|ΛΙΘΟΕΙΔ|ΠΑΡΑΡΡΙΝ|ΣΠΛΑΓΧΝ|ΡΙΝΟΦΑΡΥΓΓ|ΙΓΜΟΡΕΙ|ΥΠΟΓΝΑΘ|ΓΝΑΘ|ΠΑΡΩΤΙΔ|ΤΡΑΧΗΛ|ΚΡΑΝΙ|ΚΡΟΤΑΦΟΓΝΑΘ|ΟΔΟΝΤ|CB\/CT/.test(n)) {
            return { key: 'ct_head', title: '🧠 Κεφαλή', order: 7 };
        }
        if (/ΚΟΙΛΙ|ΟΠΙΣΘΟΠΕΡΙΤ|ΠΥΕΛΟΓΡΑΦΙ|ΟΥΡΟΓΡΑΦΙ|ΚΟΛΟΝΟΣΚΟΠΗΣ|ΝΕΦΡ|ΕΠΙΝΕΦΡ|ΗΠΑΤ/.test(n)) {
            return { key: 'ct_abdomen', title: '🩺 Κοιλία', order: 10 };
        }
        if (/ΛΕΚΑΝ|ΙΣΧΙ|ΤΟΥΡΚΙΚ|ΕΦΙΠΠΙ|ΛΑΓΟΝΙ|ΙΕΡΟΛΑΓΟΝ|ΕΛΑΣΣΟΝ|ΟΣΧΕ|ΒΟΥΒΩΝ|ΠΥΕΛ|FULL BODY/.test(n)) {
            return { key: 'ct_pelvis', title: '🦴 Λεκάνη', order: 13 };
        }
        return { key: 'ct_other', title: '📋 Λοιπές Εξετάσεις', order: 99 };
    } else {
        if (cat === 'MRA' || /MRA|ΑΓΓΕΙΟΓΡΑΦ|MRCP|ΧΟΛΑΓΓΕΙΟ/.test(n)) {
            return { key: 'mri_angio', title: '🩸 Αγγειογραφίες', order: 13 };
        }
        if (/ΑΡΘΡΟΓΡΑΦΙ|ΕΝΤΕΡΟΓΡΑΦΙ|ΠΡΟΣΤΑΤ|ΦΑΣΜΑΤΟΣΚΟΠΙΑ|ΑΓΓΕΙAΚΟΥ ΤΟΙΧΩΜΑΤΟΣ|PERFUSION|ΑΙΜΑΤΩΣΗ|ΦΛΕΒΟΓΡΑΦΙΑ|ΝΕΥΡΟΓΡΑΦΙΑ|ΔΕΣΜΙΔΟΓΡΑΦΙΑ|WHOLE BODY/.test(n)) {
            return { key: 'mri_special', title: '✨ Αρθρογραφίες & Ειδικές', order: 14 };
        }
        if (/Σ\.?Σ\.?|ΣΠΟΝΔΥΛ|ΑΜΣΣ|ΘΜΣΣ|ΑΘΜΣΣ|ΘΟΜΣΣ|ΟΜΣΣ|ΟΙΜΣΣ|ΙΜΣΣ|ΙΚΜΣΣ|ΘΟΙΜΣΣ|ΜΟΙΡΑΣ/.test(n)) {
            return { key: 'mri_spine', title: '🦴 Σπονδυλική Στήλη', order: 3 };
        }
        if (/ΕΓΚΕΦΑΛ|ΥΠΟΦΥΣ|ΓΕΦΥΡΟΠΑΡΕΓΚΕΦΑΛ/.test(n)) {
            return { key: 'mri_brain', title: '🧠 Εγκέφαλος', order: 1 };
        }
        if (/ΑΟΡΤ|ΜΑΣΤ|ΚΑΡΔΙ/.test(n)) {
            return { key: 'mri_aorta_breast', title: '🫀 Αορτή - Μαστοί', order: 9 };
        }
        if (/ΩΜ|ΩΜΟΠΛΑΤ|ΜΑΣΧΑΛ|ΒΡΑΧΙΟΝ|ΑΝΤΙΒΡΑΧ|ΑΓΚΩΝ|ΠΗΧΕΟΚΑΡΠ|ΚΑΡΠ|ΑΚΡ.*ΧΕΙΡ|ΑΚΡ.*ΧΕΡ/.test(n)) {
            let sub = { key: 'left', title: '(Αριστερό)', order: 1 };
            if (isBilateral) sub = { key: 'amfo', title: '(Αμφω)', order: 3 };
            else if (isRight) sub = { key: 'right', title: '(Δεξί)', order: 2 };
            return { key: 'mri_upper', title: '💪 Άνω Άκρα', order: 4, subgroup: sub };
        }
        if (/ΓΛΟΥΤ|ΜΗΡ|ΓΟΝΑΤ|ΚΝΗΜ|ΓΑΣΤΡΟΚΝΗΜ|ΠΟΔΟΚΝΗΜ|ΠΔΚΝΜ|ΤΑΡΣ|ΑΧΙΛΛ|ΑΚΡ.*ΠΟΔ/.test(n)) {
            let sub = { key: 'left', title: '(Αριστερό)', order: 1 };
            if (isBilateral || /ΓΛΟΥΤΩΝ/.test(n)) sub = { key: 'amfo', title: '(Αμφω)', order: 3 };
            else if (isRight) sub = { key: 'right', title: '(Δεξί)', order: 2 };
            return { key: 'mri_lower', title: '🦵 Κάτω Άκρα', order: 5, subgroup: sub };
        }
        if (/ΘΩΡΑΚ|ΜΕΣΟΘΩΡΑΚ|ΗΜΙΘΩΡΑΚ|ΣΤΕΡΝ|ΥΠΟΚΛΕΙΔ|ΥΠΕΡΚΛΕΙΔ|ΡΑΧΕΩΣ/.test(n)) {
            return { key: 'mri_chest', title: '🫁 Θώρακας', order: 2 };
        }
        if (/ΠΑΡΩΤΙΔ|ΕΣΩ ΑΚΟΥΣΤ|ΛΙΘΟΕΙΔ|ΣΦΗΝΟΕΙΔ|ΡΙΝΟΦΑΡΥΓΓ|ΤΡΑΧΗΛ|ΓΝΑΘ|ΚΡΑΝΙ|ΣΠΛΑΓΧΝ|ΟΦΘΑΛΜ/.test(n)) {
            return { key: 'mri_head', title: '👤 Κεφαλή', order: 11 };
        }
        if (/ΚΟΙΛΙ|ΗΠΑΤ|ΠΑΓΚΡΕΑΤ|ΝΕΦΡ|ΕΠΙΝΕΦΡ|ΟΠΙΣΘΟΠΕΡΙΤ|ΠΡΟΣΑΓΩΓ|ΟΡΘΟ|ΠΡΩΚΤ|ΟΣΧΕ|ΠΥΕΛΟΓΡΑΦΙ|ΟΥΡΕΟΓΡΑΦΙ/.test(n)) {
            return { key: 'mri_abdomen', title: '🩺 Κοιλία', order: 10 };
        }
        if (/ΛΕΚΑΝ|ΙΣΧΙ|ΙΕΡΟΥ ΟΣΤΟΥ|ΚΟΚΚΥΓ|ΙΕΡΟΛΑΓΟΝ|ΤΟΥΡΚΙΚ|ΕΦΙΠΠΙ|ΣΥΡΙΓΓΙ|ΕΛΑΣΣΟΝ|ΚΡΟΤΑΦΟΓΝΑΘ|ΜΥΕΛΟΓΡΑΦΙΑ|ΠΕΡΙΝΕΟΥ/.test(n)) {
            return { key: 'mri_pelvis', title: '🦴 Λεκάνη', order: 12 };
        }
        return { key: 'mri_other', title: '📋 Λοιπές Εξετάσεις', order: 99 };
    }
}

function toggleExamsGroup(groupId) {
    const el = document.getElementById('exams-group-body-' + groupId);
    const icon = document.getElementById('exams-group-icon-' + groupId);
    if (!el) return;
    if (el.style.display === 'none') {
        el.style.display = 'block';
        if (icon) icon.style.transform = 'rotate(90deg)';
    } else {
        el.style.display = 'none';
        if (icon) icon.style.transform = 'rotate(0deg)';
    }
}

function toggleExamSelection(code) {
    if (selectedExamCodes.has(code)) {
        selectedExamCodes.delete(code);
    } else {
        selectedExamCodes.add(code);
    }
    updateExamsGroupCheckboxState();
    updateExamsFloatingBar();
}

function toggleSelectAllModalityExams(event, modKey) {
    event.stopPropagation();
    const modCheckbox = document.getElementById('chk-modality-' + modKey);
    const isChecked = modCheckbox ? modCheckbox.checked : false;

    let baseCategories = RAW_EXAM_CATEGORIES || [];
    if (examsSearchQuery) {
        const rawQuery = examsSearchQuery.toLowerCase().trim();
        const normQuery = normalizeGreek(examsSearchQuery);
        baseCategories = baseCategories.filter(ex => {
            const code = String(ex.code || ex.examnumcode || ex.exam_code || ex.id || '').toLowerCase().trim();
            const name = (ex.name || '').toLowerCase();
            const normName = normalizeGreek(ex.name || '');
            return code.includes(rawQuery) || name.includes(rawQuery) || normName.includes(normQuery);
        });
    }

    const modExams = baseCategories.filter(ex => {
        let cat = (ex.category || '').toUpperCase().trim();
        if (!cat) {
            if (/CT|ΑΞΟΝ/i.test(ex.name)) cat = 'CT';
            else if (/MRA|ΑΓΓΕΙΟ/i.test(ex.name)) cat = 'MRA';
            else if (/MRI|ΜΑΓΝΗΤ/i.test(ex.name)) cat = 'MRI';
            else cat = 'OTHER';
        }
        return cat === modKey;
    });

    modExams.forEach(ex => {
        const code = String(ex.code || ex.examnumcode || ex.exam_code || '').trim();
        if (isChecked) {
            selectedExamCodes.add(code);
        } else {
            selectedExamCodes.delete(code);
        }
    });

    const examCheckboxes = document.querySelectorAll('.exam-select-checkbox');
    examCheckboxes.forEach(chk => {
        const code = chk.value;
        if (selectedExamCodes.has(code)) {
            chk.checked = true;
        } else {
            chk.checked = false;
        }
    });

    updateExamsGroupCheckboxState();
    updateExamsFloatingBar();
}

function toggleSelectAllSubgroupExams(event, groupId, subgroupId) {
    event.stopPropagation();
    const subCheckbox = document.getElementById('chk-subgroup-' + subgroupId);
    const isChecked = subCheckbox ? subCheckbox.checked : false;

    const checkboxes = document.querySelectorAll('.exam-chk-subgroup-' + subgroupId);
    checkboxes.forEach(chk => {
        const code = chk.value;
        chk.checked = isChecked;
        if (isChecked) {
            selectedExamCodes.add(code);
        } else {
            selectedExamCodes.delete(code);
        }
    });

    updateExamsGroupCheckboxState();
    updateExamsFloatingBar();
}

function toggleSelectAllGroupExams(event, groupId) {
    event.stopPropagation();
    const groupCheckbox = document.getElementById('chk-group-' + groupId);
    const headerCheckbox = document.getElementById('chk-tbl-header-' + groupId);
    const isChecked = groupCheckbox ? groupCheckbox.checked : (headerCheckbox ? headerCheckbox.checked : false);
    
    if (groupCheckbox) groupCheckbox.checked = isChecked;
    if (headerCheckbox) headerCheckbox.checked = isChecked;

    const checkboxes = document.querySelectorAll('.exam-chk-group-' + groupId);
    checkboxes.forEach(chk => {
        const code = chk.value;
        chk.checked = isChecked;
        if (isChecked) {
            selectedExamCodes.add(code);
        } else {
            selectedExamCodes.delete(code);
        }
    });

    updateExamsGroupCheckboxState();
    updateExamsFloatingBar();
}

function updateExamsGroupCheckboxState() {
    const subgroupCheckboxes = document.querySelectorAll('.subgroup-select-checkbox');
    subgroupCheckboxes.forEach(subChk => {
        const subgroupId = subChk.dataset.subgroupId;
        const examCheckboxes = document.querySelectorAll('.exam-chk-subgroup-' + subgroupId);
        if (examCheckboxes.length === 0) return;
        const allChecked = Array.from(examCheckboxes).every(c => c.checked);
        const someChecked = Array.from(examCheckboxes).some(c => c.checked);
        subChk.checked = allChecked;
        subChk.indeterminate = !allChecked && someChecked;
    });

    const groupCheckboxes = document.querySelectorAll('.group-select-checkbox');
    groupCheckboxes.forEach(groupChk => {
        const groupId = groupChk.dataset.groupId;
        const examCheckboxes = document.querySelectorAll('.exam-chk-group-' + groupId);
        if (examCheckboxes.length === 0) return;
        const allChecked = Array.from(examCheckboxes).every(c => c.checked);
        const someChecked = Array.from(examCheckboxes).some(c => c.checked);
        groupChk.checked = allChecked;
        groupChk.indeterminate = !allChecked && someChecked;

        const headerChk = document.getElementById('chk-tbl-header-' + groupId);
        if (headerChk) {
            headerChk.checked = allChecked;
            headerChk.indeterminate = !allChecked && someChecked;
        }
    });

    const modalityCheckboxes = document.querySelectorAll('.modality-select-checkbox');
    modalityCheckboxes.forEach(modChk => {
        const modKey = modChk.dataset.modality;
        const modExams = (RAW_EXAM_CATEGORIES || []).filter(ex => {
            let cat = (ex.category || '').toUpperCase().trim();
            if (!cat) {
                if (/CT|ΑΞΟΝ/i.test(ex.name)) cat = 'CT';
                else if (/MRA|ΑΓΓΕΙΟ/i.test(ex.name)) cat = 'MRA';
                else if (/MRI|ΜΑΓΝΗΤ/i.test(ex.name)) cat = 'MRI';
                else cat = 'OTHER';
            }
            return cat === modKey;
        });

        if (modExams.length === 0) return;

        const modCodes = modExams.map(ex => String(ex.code || ex.examnumcode || ex.exam_code || ''));
        const allChecked = modCodes.length > 0 && modCodes.every(c => selectedExamCodes.has(c));
        const someChecked = modCodes.some(c => selectedExamCodes.has(c));

        modChk.checked = allChecked;
        modChk.indeterminate = !allChecked && someChecked;
    });
}

function clearExamsSelection() {
    selectedExamCodes.clear();
    const examCheckboxes = document.querySelectorAll('.exam-select-checkbox');
    examCheckboxes.forEach(c => c.checked = false);
    const subgroupCheckboxes = document.querySelectorAll('.subgroup-select-checkbox');
    subgroupCheckboxes.forEach(c => {
        c.checked = false;
        c.indeterminate = false;
    });
    const groupCheckboxes = document.querySelectorAll('.group-select-checkbox');
    groupCheckboxes.forEach(c => {
        c.checked = false;
        c.indeterminate = false;
    });
    const modalityCheckboxes = document.querySelectorAll('.modality-select-checkbox');
    modalityCheckboxes.forEach(c => {
        c.checked = false;
        c.indeterminate = false;
    });
    updateExamsFloatingBar();
}

function updateExamsFloatingBar() {
    const fab = document.getElementById('exams-floating-bar');
    const countEl = document.getElementById('exams-fab-count');
    const selectEl = document.getElementById('exams-fab-diag-select');
    if (!fab || !countEl || !selectEl) return;

    if (selectedExamCodes.size === 0) {
        fab.style.display = 'none';
        return;
    }

    fab.style.display = 'flex';
    countEl.textContent = `${selectedExamCodes.size} επιλεγμέν${selectedExamCodes.size === 1 ? 'η εξέταση' : 'ες εξετάσεις'}`;

    // Determine modalities of selected exams
    let hasCT = false;
    let hasMRI = false;

    selectedExamCodes.forEach(code => {
        let cat = '';
        const examObj = (RAW_EXAM_CATEGORIES || []).find(ex => String(ex.examnumcode || ex.code) === String(code));
        const examName = examObj ? examObj.name : (EXAM_CODE_MAP[code] || '');
        cat = (examObj?.category || '').toUpperCase().trim();
        if (!cat) {
            if (/CT|ΑΞΟΝ/i.test(examName) || /^21/.test(code)) cat = 'CT';
            else if (/MRA|ΑΓΓΕΙΟ/i.test(examName) || /^228/.test(code)) cat = 'MRA';
            else if (/MRI|ΜΑΓΝΗΤ/i.test(examName) || /^22/.test(code)) cat = 'MRI';
            else cat = /^21/.test(code) ? 'CT' : 'MRI';
        }

        if (cat === 'CT') hasCT = true;
        if (cat === 'MRI' || cat === 'MRA') hasMRI = true;
    });

    const currentSelectedDiagId = selectEl.value;

    // Filter active diagnosticians based on capability rules:
    // Selected CT code -> Exclude MRI-only diagnosticians (can_ct == false)
    // Selected MRI code -> Exclude CT-only diagnosticians (can_mri == false)
    // Both CT & MRI selected -> Exclude diagnosticians that don't do both
    const activeDiags = (diagnosticians || []).filter(d => d.active).sort((a, b) => a.name.localeCompare(b.name, 'el'));
    const eligibleDiags = activeDiags.filter(d => {
        if (hasCT && !d.can_ct) return false;
        if (hasMRI && !d.can_mri) return false;
        return true;
    });

    let optionsHtml = '<option value="">— Επιλέξτε —</option>';
    if (eligibleDiags.length === 0) {
        optionsHtml = '<option value="">⚠️ Κανένας διαθέσιμος διαγνώστης (CT/MRI περιορισμοί)</option>';
    } else {
        optionsHtml += eligibleDiags.map(d => {
            let tags = [];
            if (d.can_ct && !d.can_mri) tags.push('CT');
            else if (!d.can_ct && d.can_mri) tags.push('MRI');
            const tagStr = tags.length > 0 ? ` (${tags.join(', ')})` : '';
            return `<option value="${d.id}" data-name="${escapeHtml(d.name)}">${escapeHtml(d.name)}${tagStr}</option>`;
        }).join('');
    }

    selectEl.innerHTML = optionsHtml;
    if (currentSelectedDiagId && eligibleDiags.some(d => String(d.id) === String(currentSelectedDiagId))) {
        selectEl.value = currentSelectedDiagId;
    }
}

async function addSelectedExamsAsSkills() {
    const selectEl = document.getElementById('exams-fab-diag-select');
    const diagId = parseInt(selectEl.value);
    if (!diagId) {
        showToast('Επιλέξτε διαγνώστη', 'warning');
        return;
    }

    const diagName = selectEl.options[selectEl.selectedIndex]?.dataset?.name || '';
    const is_preferred = document.getElementById('exams-fab-preferred').checked;

    if (selectedExamCodes.size === 0) {
        showToast('Δεν έχουν επιλεγεί εξετάσεις', 'warning');
        return;
    }

    const codesToAdd = Array.from(selectedExamCodes);
    let addedCount = 0;
    let skippedCount = 0;

    for (const rawCode of codesToAdd) {
        const code = String(rawCode).trim();
        // Prevent duplicate addition
        const exists = skills.some(s => String(s.diagnostician_id) === String(diagId) && String(s.exam_code).trim() === code);
        if (exists) {
            skippedCount++;
            continue;
        }

        const examObj = (RAW_EXAM_CATEGORIES || []).find(ex => String(ex.examnumcode || ex.code || '').trim() === code);
        const examName = examObj ? examObj.name : (EXAM_CODE_MAP[code] || `Εξέταση ${code}`);

        const record = {
            diagnostician_id: diagId,
            diagnostician_name: diagName,
            exam_code: code,
            exam_title: examName,
            is_preferred: is_preferred
        };

        try {
            const result = await apiCall('/admin/skills', 'POST', record);
            skills = skills.filter(s => !(String(s.diagnostician_id) === String(diagId) && String(s.exam_code).trim() === code));
            if (result) skills.push(result);
            else skills.push({ id: Date.now() + Math.random(), ...record });
            addedCount++;
        } catch (err) {
            showToast(`❌ Αποτυχία προσθήκης δεξιότητας ${code}: ${err.message || 'Σφάλμα API'}`, 'error');
        }
    }

    if (addedCount > 0) openSkillsGroups.add(String(diagId));
    renderSkills();

    if (addedCount > 0 && skippedCount > 0) {
        showToast(`✅ Προστέθηκαν ${addedCount} νέες δεξιότητες στον/στην ${diagName} (${skippedCount} υπήρχαν ήδη)`, 'success');
    } else if (addedCount > 0) {
        showToast(`✅ Προστέθηκαν ${addedCount} νέες δεξιότητες στον/στην ${diagName}`, 'success');
    } else if (skippedCount > 0) {
        showToast(`ℹ️ Όλες οι επιλεγμένες εξετάσεις (${skippedCount}) υπάρχουν ήδη ως δεξιότητες για τον/την ${diagName}`, 'info');
    }

    clearExamsSelection();
}

async function renderExamsSection() {
    const container = document.getElementById('exams-dictionary-container');
    if (!container) return;

    if (!RAW_EXAM_CATEGORIES || RAW_EXAM_CATEGORIES.length === 0) {
        await loadExamCategories();
    }

    if (!RAW_EXAM_CATEGORIES || RAW_EXAM_CATEGORIES.length === 0) {
        if (Object.keys(EXAM_CODE_MAP).length > 0) {
            RAW_EXAM_CATEGORIES = Object.entries(EXAM_CODE_MAP).map(([code, name]) => ({
                examnumcode: code,
                name: name,
                category: /CT|ΑΞΟΝ/i.test(name) ? 'CT' : (/MRA|ΑΓΓΕΙΟ/i.test(name) ? 'MRA' : 'MRI')
            }));
        }
    }

    if (!RAW_EXAM_CATEGORIES || RAW_EXAM_CATEGORIES.length === 0) {
        container.innerHTML = '<div style="color:var(--text-tertiary); padding:20px; text-align:center;">Φόρτωση ή δεν βρέθηκαν εξετάσεις...</div>';
        return;
    }

    let filtered = RAW_EXAM_CATEGORIES;
    if (examsSearchQuery) {
        const rawQuery = examsSearchQuery.toLowerCase().trim();
        const normQuery = normalizeGreek(examsSearchQuery);
        filtered = RAW_EXAM_CATEGORIES.filter(ex => {
            const code = String(ex.code || ex.examnumcode || ex.exam_code || ex.id || '').toLowerCase().trim();
            const name = (ex.name || '').toLowerCase();
            const normName = normalizeGreek(ex.name || '');
            return code.includes(rawQuery) || name.includes(rawQuery) || normName.includes(normQuery);
        });
    }

    if (filtered.length === 0) {
        container.innerHTML = `<div style="color:var(--text-tertiary); padding:20px; text-align:center;">Δεν βρέθηκαν εξετάσεις που να ταιριάζουν με "${escapeHtml(examsSearchQuery)}"</div>`;
        return;
    }

    const modalityGroups = { CT: [], MRI: [], MRA: [], OTHER: [] };
    filtered.forEach(ex => {
        let cat = (ex.category || '').toUpperCase().trim();
        if (!cat) {
            if (/CT|ΑΞΟΝ/i.test(ex.name)) cat = 'CT';
            else if (/MRA|ΑΓΓΕΙΟ/i.test(ex.name)) cat = 'MRA';
            else if (/MRI|ΜΑΓΝΗΤ/i.test(ex.name)) cat = 'MRI';
            else cat = 'OTHER';
        }
        if (modalityGroups[cat]) modalityGroups[cat].push(ex);
        else modalityGroups.OTHER.push(ex);
    });

    let html = '';
    const catLabels = {
        CT: '🩻 Αξονικές Τομογραφίες (CT)',
        MRI: '🧲 Μαγνητικές Τομογραφίες (MRI)',
        MRA: '🩸 Μαγνητικές Αγγειογραφίες (MRA)',
        OTHER: '📋 Λοιπές Εξετάσεις'
    };

    const isAutoExpanded = Boolean(examsSearchQuery);

    for (const [modKey, examsList] of Object.entries(modalityGroups)) {
        if (examsList.length === 0) continue;

        const modCodes = examsList.map(e => String(e.code || e.examnumcode || e.exam_code || ''));
        const allModChecked = modCodes.length > 0 && modCodes.every(c => selectedExamCodes.has(c));

        const anatGroups = {};
        examsList.forEach(ex => {
            const exCode = String(ex.code || ex.examnumcode || ex.exam_code || ex.id || '');
            const region = groupExamByAnatomicalRegion(ex.name, modKey, exCode);
            if (!anatGroups[region.key]) {
                anatGroups[region.key] = {
                    title: region.title,
                    order: region.order,
                    hasSubgroups: Boolean(region.subgroup),
                    subgroups: {},
                    exams: []
                };
            }
            if (region.subgroup) {
                const subKey = region.subgroup.key;
                if (!anatGroups[region.key].subgroups[subKey]) {
                    anatGroups[region.key].subgroups[subKey] = {
                        title: region.subgroup.title,
                        order: region.subgroup.order,
                        exams: []
                    };
                }
                anatGroups[region.key].subgroups[subKey].exams.push(ex);
            } else {
                anatGroups[region.key].exams.push(ex);
            }
        });

        const sortedAnatEntries = Object.entries(anatGroups).sort((a, b) => a[1].order - b[1].order);

        html += `
            <div style="margin-bottom: 28px; border: 1px solid var(--border-color); border-radius: 8px; overflow: hidden; background: var(--bg-primary);">
                <div style="background: var(--surface-color); padding: 12px 16px; font-weight: 700; font-size: 15px; border-bottom: 1px solid var(--border-color); color: var(--accent-primary); display: flex; justify-content: space-between; align-items: center;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <input type="checkbox" id="chk-modality-${modKey}" class="modality-select-checkbox" data-modality="${modKey}" ${allModChecked ? 'checked' : ''} onclick="toggleSelectAllModalityExams(event, '${modKey}')" title="Επιλογή όλων στις ${catLabels[modKey] || modKey}" style="accent-color:var(--accent-primary); width:18px; height:18px; cursor:pointer;">
                        <span>${catLabels[modKey] || modKey}</span>
                    </div>
                    <span style="font-size: 12px; background: var(--bg-tertiary); padding: 2px 8px; border-radius: 12px; font-weight: 600; color: var(--text-secondary);">${examsList.length} εξετάσεις</span>
                </div>
                <div style="padding: 12px 16px;">
        `;

        for (const [key, anat] of sortedAnatEntries) {
            const groupId = `${modKey}_${key}`;
            let groupExamsCodes = [];
            if (anat.hasSubgroups) {
                groupExamsCodes = Object.values(anat.subgroups).flatMap(sg => sg.exams.map(e => String(e.code || e.examnumcode || e.exam_code || '')));
            } else {
                groupExamsCodes = anat.exams.map(e => String(e.code || e.examnumcode || e.exam_code || ''));
            }
            const totalCount = groupExamsCodes.length;
            const allChecked = groupExamsCodes.length > 0 && groupExamsCodes.every(c => selectedExamCodes.has(c));

            html += `
                <div style="margin-bottom: 16px; border: 1px solid var(--border-color); border-radius: 6px; overflow: hidden;">
                    <div onclick="toggleExamsGroup('${groupId}')" 
                         style="cursor:pointer; font-weight: 600; font-size: 13px; color: var(--text-primary); padding: 10px 14px; background: var(--surface-color); display: flex; align-items: center; justify-content: space-between; user-select: none;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span id="exams-group-icon-${groupId}" style="display:inline-block; width:16px; transition:transform 0.2s; ${isAutoExpanded ? 'transform:rotate(90deg);' : ''}">▶</span>
                            <input type="checkbox" id="chk-group-${groupId}" class="group-select-checkbox" data-group-id="${groupId}" ${allChecked ? 'checked' : ''} onclick="toggleSelectAllGroupExams(event, '${groupId}')" title="Επιλογή όλων στην ομάδα" style="accent-color:var(--accent-primary); width:16px; height:16px; cursor:pointer;">
                            <span>${anat.title}</span> 
                            <span style="font-weight:normal; font-size:12px; color:var(--text-tertiary);">(${totalCount})</span>
                        </div>
                    </div>
                    <div id="exams-group-body-${groupId}" style="display: ${isAutoExpanded ? 'block' : 'none'}; padding: 8px 14px 14px 14px; background: var(--bg-primary); border-top: 1px solid var(--border-color);">
            `;

            if (anat.hasSubgroups) {
                const sortedSubgroups = Object.entries(anat.subgroups).sort((a, b) => a[1].order - b[1].order);
                for (const [subKey, sg] of sortedSubgroups) {
                    const subgroupId = `${groupId}_sub_${subKey}`;
                    const subExamsCodes = sg.exams.map(e => String(e.code || e.examnumcode || e.exam_code || ''));
                    const allSubChecked = subExamsCodes.length > 0 && subExamsCodes.every(c => selectedExamCodes.has(c));

                    html += `
                        <div style="margin-top: 10px; margin-bottom: 14px; border: 1px solid var(--border-color); border-radius: 6px; overflow: hidden;">
                            <div style="background: var(--bg-tertiary); padding: 8px 12px; display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 13px; color: var(--text-primary); border-bottom: 1px solid var(--border-color);">
                                <input type="checkbox" id="chk-subgroup-${subgroupId}" class="subgroup-select-checkbox" data-subgroup-id="${subgroupId}" ${allSubChecked ? 'checked' : ''} onclick="toggleSelectAllSubgroupExams(event, '${groupId}', '${subgroupId}')" title="Επιλογή όλων στην υποομάδα ${sg.title}" style="accent-color:var(--accent-primary); width:15px; height:15px; cursor:pointer;">
                                <span>${sg.title}</span>
                                <span style="font-size: 11px; font-weight: normal; color: var(--text-tertiary);">(${sg.exams.length})</span>
                            </div>
                            <table class="admin-table" style="font-size: 13px; margin: 0;">
                                <thead>
                                    <tr>
                                        <th style="width: 40px; text-align: center;"></th>
                                        <th style="width: 110px;">ΚΩΔΙΚΟΣ</th>
                                        <th>ΟΝΟΜΑ ΕΞΕΤΑΣΗΣ</th>
                                        <th style="width: 100px; text-align: center;">ΚΑΤΗΓΟΡΙA</th>
                                    </tr>
                                </thead>
                                <tbody>
                    `;

                    sg.exams.forEach(ex => {
                        const code = String(ex.code || ex.examnumcode || ex.exam_code || '');
                        const fullName = ex.name || '—';
                        const simplified = formatSimplifiedExamName(fullName, modKey, code);
                        const catClass = (modKey || '').toLowerCase();
                        const isChecked = selectedExamCodes.has(code);

                        html += `
                            <tr>
                                <td style="text-align: center;">
                                    <input type="checkbox" class="exam-select-checkbox exam-chk-group-${groupId} exam-chk-subgroup-${subgroupId}" value="${code}" ${isChecked ? 'checked' : ''} onchange="toggleExamSelection('${code}')" style="accent-color:var(--accent-primary); width:15px; height:15px; cursor:pointer;">
                                </td>
                                <td style="font-family: monospace; font-weight: 700; color: #8122FF; font-size: 13px;">${escapeHtml(code)}</td>
                                <td>
                                    <div style="font-weight: 600; color: var(--text-primary);">${escapeHtml(simplified)}</div>
                                    <div style="font-size: 11px; color: var(--text-tertiary);">${escapeHtml(fullName)}</div>
                                </td>
                                <td style="text-align: center;">
                                    <span class="modality-badge ${catClass}">${escapeHtml(modKey)}</span>
                                </td>
                            </tr>
                        `;
                    });

                    html += `
                                </tbody>
                            </table>
                        </div>
                    `;
                }
            } else {
                html += `
                    <table class="admin-table" style="font-size: 13px; margin: 0;">
                        <thead>
                            <tr>
                                <th style="width: 40px; text-align: center;"></th>
                                <th style="width: 110px;">ΚΩΔΙΚΟΣ</th>
                                <th>ΟΝΟΜΑ ΕΞΕΤΑΣΗΣ</th>
                                <th style="width: 100px; text-align: center;">ΚΑΤΗΓΟΡΙA</th>
                            </tr>
                        </thead>
                        <tbody>
                `;

                anat.exams.forEach(ex => {
                    const code = String(ex.code || ex.examnumcode || ex.exam_code || '');
                    const fullName = ex.name || '—';
                    const simplified = formatSimplifiedExamName(fullName, modKey, code);
                    const catClass = (modKey || '').toLowerCase();
                    const isChecked = selectedExamCodes.has(code);

                    html += `
                        <tr>
                            <td style="text-align: center;">
                                <input type="checkbox" class="exam-select-checkbox exam-chk-group-${groupId}" value="${code}" ${isChecked ? 'checked' : ''} onchange="toggleExamSelection('${code}')" style="accent-color:var(--accent-primary); width:15px; height:15px; cursor:pointer;">
                            </td>
                            <td style="font-family: monospace; font-weight: 700; color: #8122FF; font-size: 13px;">${escapeHtml(code)}</td>
                            <td>
                                <div style="font-weight: 600; color: var(--text-primary);">${escapeHtml(simplified)}</div>
                                <div style="font-size: 11px; color: var(--text-tertiary);">${escapeHtml(fullName)}</div>
                            </td>
                            <td style="text-align: center;">
                                <span class="modality-badge ${catClass}">${escapeHtml(modKey)}</span>
                            </td>
                        </tr>
                    `;
                });

                html += `
                        </tbody>
                    </table>
                `;
            }

            html += `
                    </div>
                </div>
            `;
        }

        html += `
                </div>
            </div>
        `;
    }

    container.innerHTML = html;
    updateExamsGroupCheckboxState();
    updateExamsFloatingBar();
}

async function deleteSkill(id) {
    try {
        await apiCall(`/admin/skills/${id}`, 'DELETE');
    } catch { /* mock mode */ }
    skills = skills.filter(s => String(s.id) !== String(id));
    renderSkills();
    showToast('Η δεξιότητα διαγράφηκε', 'info');
}

async function toggleSkillPreference(id, newPreference) {
    const s = skills.find(x => String(x.id) === String(id));
    if (!s) return;
    s.is_preferred = newPreference;

    try {
        await apiCall(`/admin/skills/${id}`, 'PUT', s);
    } catch { /* mock mode */ }

    renderSkills();
    showToast(`✅ Προτίμηση ενημερώθηκε`, 'success');
}

async function addPartnership() {
    const doctorId = document.getElementById('part-doctor-id').value;
    const doctorName = document.getElementById('part-doctor-search').value.split(' (')[0];
    const diagSelEl = document.getElementById('part-diag');
    const diagId = parseInt(diagSelEl.value);
    const diagName = diagSelEl.options[diagSelEl.selectedIndex]?.dataset?.name || '';
    const exclusive = document.getElementById('part-exclusive').checked;

    if (!doctorId || !doctorName || !diagId) {
        showToast('Συμπληρώστε όλα τα στοιχεία', 'warning');
        return;
    }

    const record = {
        issuing_doctor_id: doctorId,
        issuing_doctor_name: doctorName,
        preferred_diagnostician_id: diagId,
        preferred_diagnostician_name: diagName,
        exclusive,
    };

    try {
        const result = await apiCall('/admin/partnerships', 'POST', record);
        partnerships.push(result || { id: Date.now(), ...record });
    } catch {
        partnerships.push({ id: Date.now(), ...record });
    }

    if (diagId) openPartnershipsGroups.add(String(diagId));
    renderPartnerships();
    document.getElementById('part-doctor-search').value = '';
    document.getElementById('part-doctor-id').value = '';
    document.getElementById('part-exclusive').checked = false;
    showToast(`✅ Συνεργασία αποθηκεύτηκε`, 'success');
}

async function deletePartnership(id) {
    if (!confirm('Διαγραφή συνεργασίας;')) return;
    try {
        await apiCall(`/admin/partnerships/${id}`, 'DELETE');
        showToast('Η συνεργασία διαγράφηκε', 'success');
        await loadPartnerships();
    } catch (err) {
        // mock fallback
        partnerships = partnerships.filter(p => String(p.id) !== String(id));
        renderPartnerships();
        showToast('Η συνεργασία διαγράφηκε (Mock)', 'success');
    }
}

async function togglePartnershipProperty(id, property, newValue) {
    try {
        const payload = {};
        payload[property] = newValue;
        await apiCall(`/admin/partnerships/${id}`, 'PATCH', payload);
        const propName = property === 'is_active' ? 'Η κατάσταση' : 'Η αποκλειστικότητα';
        showToast(`${propName} της συνεργασίας ενημερώθηκε`, 'success');
        await loadPartnerships();
    } catch (err) {
        // mock fallback
        const p = partnerships.find(x => String(x.id) === String(id));
        if (p) {
            p[property] = newValue;
        }
        renderPartnerships();
        showToast(`Ενημερώθηκε (Mock)`, 'success');
    }
}
async function addDoctor() {
    const name = document.getElementById('new-doc-name').value.trim();

    if (!name) { showToast('Εισάγετε ονοματεπώνυμο', 'warning'); return; }

    try {
        const result = await apiCall('/admin/doctors', 'POST', { name });
        doctors.push(result || { id: `DR-${Date.now()}`, name });
    } catch {
        doctors.push({ id: `DR-${Date.now()}`, name });
    }

    renderDoctors();
    document.getElementById('new-doc-name').value = '';
    showToast(`✅ Ο/Η ${name} προστέθηκε στη λίστα ιατρών`, 'success');
}


// ══════════════════════════════════════════════
//  Helpers
// ══════════════════════════════════════════════

function formatDateLocal(d) {
    if (!d || isNaN(d.getTime())) return '';
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        const d = new Date(dateStr + 'T00:00:00');
        return d.toLocaleDateString('el-GR', { day: '2-digit', month: '2-digit', year: 'numeric' });
    } catch { return dateStr; }
}

function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    const icons = { success: '✅', warning: '⚠️', error: '❌', info: 'ℹ️' };
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || 'ℹ️'}</span>
        <span class="toast-message">${message}</span>
    `;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'toastOut 250ms forwards';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}


// ══════════════════════════════════════════════
//  Mock Data
// ══════════════════════════════════════════════

function getMockDiagnosticians() {
    return [
        { id: 1, name: 'Νάτσικα Α.', active: true, can_ct: true, can_mri: true, daily_quota: 15 },
        { id: 2, name: 'Κωνσταντίνου Β.', active: true, can_ct: true, can_mri: true, daily_quota: 12 },
        { id: 3, name: 'Παπαδόπουλος Γ.', active: true, can_ct: true, can_mri: true, daily_quota: 18 },
        { id: 4, name: 'Λιάκος Δ.', active: true, can_ct: true, can_mri: false, daily_quota: 10 },
        { id: 5, name: 'Δημητρίου Ε.', active: true, can_ct: true, can_mri: true, daily_quota: 14 },
        { id: 6, name: 'Αντωνίου Ζ.', active: false, can_ct: true, can_mri: true, daily_quota: 16 },
    ];
}

function getMockPartnerships() {
    return [
        { id: 1, issuing_doctor_id: 'DR-101', issuing_doctor_name: 'Παπαδόπουλος Ν.', preferred_diagnostician_id: 3, preferred_diagnostician_name: 'Παπαδόπουλος Γ.', priority: 5, exclusive: true },
        { id: 2, issuing_doctor_id: 'DR-205', issuing_doctor_name: 'Ιωάννου Ε.', preferred_diagnostician_id: 2, preferred_diagnostician_name: 'Κωνσταντίνου Β.', priority: 4, exclusive: false },
    ];
}

function getMockDoctors() {
    return [
        { id: 'DR-101', name: 'Παπαδόπουλος Ν.' },
        { id: 'DR-205', name: 'Ιωάννου Ε.' },
        { id: 'DR-310', name: 'Βασιλείου Κ.' },
    ];
}

function getMockSkills() {
    return [
        { id: 1, diagnostician_id: 1, diagnostician_name: 'Νάτσικα Α.', exam_code: '21100', exam_title: 'MRI Κοιλίας', is_preferred: true },
        { id: 2, diagnostician_id: 1, diagnostician_name: 'Νάτσικα Α.', exam_code: '22140', exam_title: 'CT Θώρακα', is_preferred: false },
        { id: 3, diagnostician_id: 2, diagnostician_name: 'Κωνσταντίνου Β.', exam_code: '22140', exam_title: 'CT Θώρακα', is_preferred: true },
        { id: 4, diagnostician_id: 3, diagnostician_name: 'Παπαδόπουλος Γ.', exam_code: '21063', exam_title: 'MRI Εγκεφάλου', is_preferred: true },
    ];
}

function getMockAvailability() {
    const today = formatDateLocal(new Date());
    return [
        { id: 1, diagnostician_id: 6, diagnostician_name: 'Αντωνίου Ζ.', date: today, status: 'on_leave', notes: 'Άδεια' },
    ];
}

// ══════════════════════════════════════════════
//  Autocomplete for Doctor Search
// ══════════════════════════════════════════════
let doctorSearchTimeout = null;

function debounceDoctorSearch() {
    const q = document.getElementById('part-doctor-search').value.trim();
    if (q.length < 2) {
        document.getElementById('part-doctor-results').style.display = 'none';
        return;
    }
    clearTimeout(doctorSearchTimeout);
    doctorSearchTimeout = setTimeout(async () => {
        const data = await apiCall(`/admin/doctors?q=${encodeURIComponent(q)}&limit=15`);
        const resDiv = document.getElementById('part-doctor-results');
        if (!data || !data.items || data.items.length === 0) {
            resDiv.innerHTML = '<div style="padding:8px; color:var(--text-tertiary);">Δεν βρέθηκαν αποτελέσματα</div>';
            resDiv.style.display = 'block';
            return;
        }
        resDiv.innerHTML = data.items.map(d => `
            <div style="padding:8px; cursor:pointer; border-bottom:1px solid var(--border-color);"
                 onclick="selectDoctor('${d.id}', '${d.name.replace(/'/g, "\\'")}')" 
                 onmouseover="this.style.background='var(--bg-tertiary)'"
                 onmouseout="this.style.background='transparent'">
                 ${d.name} <span style="color:var(--text-tertiary);font-size:0.85em;">(${d.id})</span>
            </div>
        `).join('');
        resDiv.style.display = 'block';
    }, 300);
}

function selectDoctor(id, name) {
    document.getElementById('part-doctor-id').value = id;
    document.getElementById('part-doctor-search').value = `${name} (${id})`;
    document.getElementById('part-doctor-results').style.display = 'none';
}

document.addEventListener('click', (e) => {
    const res = document.getElementById('part-doctor-results');
    if (res && e.target.id !== 'part-doctor-search') {
        res.style.display = 'none';
    }
});

function renderWeeklyScheduleGrid() {
    const tbody = document.getElementById('weekly-schedule-tbody');
    if (!tbody) return;

    const activeDiags = diagnosticians.filter(d => d.active).sort((a, b) => a.name.localeCompare(b.name, 'el'));

    if (!activeDiags.length) {
        tbody.innerHTML = '<tr><td colspan="8" style="color:var(--text-tertiary);text-align:center;padding:20px;">Δεν υπάρχουν ενεργοί διαγνώστες</td></tr>';
        return;
    }

    const quotaKeys = ['quota_monday', 'quota_tuesday', 'quota_wednesday', 'quota_thursday', 'quota_friday', 'quota_saturday', 'quota_sunday'];

    tbody.innerHTML = activeDiags.map(d => {
        let cells = `<td style="font-weight:500;">${d.name}</td>`;
        for (let day = 0; day < 7; day++) {
            const quotaVal = d[quotaKeys[day]] || 0;
            cells += `
                <td style="text-align:center;">
                    <input type="number" 
                           class="form-input"
                           style="width:50px;padding:4px;text-align:center;${quotaVal === 0 ? 'background-color:#ffe4e6;color:#e11d48;font-weight:bold;' : ''}" 
                           value="${quotaVal}"
                           min="0"
                           onchange="updateWeeklyQuota(${d.id}, '${quotaKeys[day]}', this.value)">
                </td>
            `;
        }
        return `<tr>${cells}</tr>`;
    }).join('');
}

// ══════════════════════════════════════════════
//  Advanced Options Logic
// ══════════════════════════════════════════════

let advRoutingRules = [];
let advExclusiveRules = [];
let advModalityQuotas = [];
let advDoctorsList = [];

async function loadAdvancedOptions() {
    try {
        const [routing, exclusive, quotas] = await Promise.all([
            apiCall('/admin/advanced/exam-routing-rules'),
            apiCall('/admin/advanced/exclusive-lab-rules'),
            apiCall('/admin/advanced/modality-quotas'),
            
        ]);
        advRoutingRules = routing || [];
        advExclusiveRules = exclusive || [];
        advModalityQuotas = quotas || [];
        
        renderAdvancedOptions();
    } catch (e) {
        console.error("Failed to load advanced options", e);
    }
}

function renderAdvancedOptions() {
    const getLabName = (id) => {
        if (!id) return 'Όλα';
        if (id === 1) return 'ΚΟΛΙΑΤΣΟΥ';
        if (id === 6) return 'ΑΝΩ ΠΑΤΗΣΙΑ';
        if (id === 7) return 'ΙΛΙΟΝ';
        if (id === 5) return 'ΣΕΠΟΛΙΑ';
        return `Εργ. ${id}`;
    };

    // 1. Exam Routing Rules
    const routingTbody = document.getElementById('adv-route-tbody');
    if (routingTbody) {
        routingTbody.innerHTML = advRoutingRules.map(r => `
            <tr>
                <td>${getLabName(r.lab_id)}</td>
                <td>${r.is_pamakristos ? 'ΠΑΜΜΑΚΑΡΙΣΤΟΣ' : (r.issuing_doctor_name || '-')}</td>
                <td class="wrap-text">${r.exam_codes}</td>
                <td>${r.diagnostician_name}</td>
                <td class="wrap-text">${r.description || '-'}</td>
                <td>
                    <button class="btn ${r.is_active ? 'btn-danger' : 'btn-success'} btn-sm" onclick="toggleAdvancedRule('routing', ${r.id}, ${!r.is_active})">
                        ${r.is_active ? 'Απενεργοποίηση' : 'Ενεργοποίηση'}
                    </button>
                </td>
                <td>
                    <button class="btn btn-secondary btn-sm" onclick="editExamRoutingRule(${r.id})" style="margin-right:4px;" title="Επεξεργασία">✏️</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteExamRoutingRule(${r.id})" title="Διαγραφή">🗑️</button>
                </td>
            </tr>
        `).join('');
    }

    

    // 2. Exclusive Labs
    const exclTbody = document.getElementById('adv-excl-tbody');
    if (exclTbody) {
        exclTbody.innerHTML = advExclusiveRules.map(r => `
            <tr>
                <td>${r.diagnostician_name}</td>
                <td>${r.lab_name}</td>
                <td>
                    <button class="btn ${r.is_active ? 'btn-danger' : 'btn-success'} btn-sm" onclick="toggleAdvancedRule('exclusive', ${r.id}, ${!r.is_active})">
                        ${r.is_active ? 'Απενεργοποίηση' : 'Ενεργοποίηση'}
                    </button>
                </td>
                <td>
                    <button class="btn btn-secondary btn-sm" onclick="editExclusiveLabRule(${r.id})" style="margin-right:4px;" title="Επεξεργασία">✏️</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteExclusiveLabRule(${r.id})" title="Διαγραφή">🗑️</button>
                </td>
            </tr>
        `).join('');
    }

    // 3. Modality Quotas
    const quotaTbody = document.getElementById('adv-quota-tbody');
    if (quotaTbody) {
        quotaTbody.innerHTML = advModalityQuotas.map(r => `
            <tr>
                <td>${r.diagnostician_name}</td>
                <td>${r.modality}</td>
                <td>${r.max_count}</td>
                <td>
                    <button class="btn ${r.is_active ? 'btn-danger' : 'btn-success'} btn-sm" onclick="toggleAdvancedRule('quota', ${r.id}, ${!r.is_active})">
                        ${r.is_active ? 'Απενεργοποίηση' : 'Ενεργοποίηση'}
                    </button>
                </td>
                <td>
                    <button class="btn btn-secondary btn-sm" onclick="editModalityQuota(${r.id})" style="margin-right:4px;" title="Επεξεργασία">✏️</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteModalityQuota(${r.id})" title="Διαγραφή">🗑️</button>
                </td>
            </tr>
        `).join('');
    }
}

function updateAdvRouteMutualExclusion() {
    const docSearch = document.getElementById('adv-route-doc-search');
    const pam = document.getElementById('adv-route-pam');
    if (!docSearch || !pam) return;

    if (pam.checked) {
        docSearch.disabled = true;
    } else {
        docSearch.disabled = false;
    }

    if (docSearch.value.trim() !== '') {
        pam.disabled = true;
    } else {
        pam.disabled = false;
    }
}

function checkRoutingRuleOverlap(payload, editId = null) {
    const payloadCodes = payload.exam_codes.split(',').map(c => c.trim());
    for (let r of advRoutingRules) {
        if (!r.is_active) continue;
        if (editId && r.id === editId) continue;
        
        const labMatch = r.lab_id == null || payload.lab_id == null || r.lab_id == payload.lab_id;
        const pamIntersect = (!r.is_pamakristos) || (!payload.is_pamakristos) || (!!r.is_pamakristos === !!payload.is_pamakristos);
        const docMatch = r.issuing_doctor_id == null || payload.issuing_doctor_id == null || r.issuing_doctor_id == payload.issuing_doctor_id;
        const rCodes = (r.exam_codes || '').split(',').map(c => c.trim());
        const codeIntersect = payloadCodes.some(c => rCodes.includes(c));
        
        if (labMatch && pamIntersect && docMatch && codeIntersect) {
            return r;
        }
    }
    return null;
}

async function addExamRoutingRule() {
    const labId = document.getElementById('adv-route-lab').value;
    const isPam = document.getElementById('adv-route-pam').checked;
    const diagId = document.getElementById('adv-route-diag').value;
    const docId = document.getElementById('adv-route-doc').value;
    const docSearch = document.getElementById('adv-route-doc-search').value;
    const docName = docSearch ? docSearch.split(' (')[0] : null;
    const desc = document.getElementById('adv-route-desc').value.trim();

    const codes = Array.from(selectedRouteExamCodes).join(',');
    
    if (!codes || !diagId || !desc) {
        showToast('Συμπληρώστε κωδικούς, διαγνώστη και περιγραφή.', 'warning');
        return;
    }

    if (Object.keys(EXAM_CODE_MAP).length > 0) {
        const invalidCodes = codes.split(',').map(c => c.trim()).filter(c => c && !EXAM_CODE_MAP[c.trim()]);
        if (invalidCodes.length > 0) {
            showToast(`Οι παρακάτω κωδικοί εξέτασης δεν υπάρχουν: ${invalidCodes.join(', ')}`, 'warning');
            return;
        }
    }

    const payload = {
        lab_id: labId ? parseInt(labId) : null,
        issuing_doctor_id: docId || null,
        issuing_doctor_name: docName || null,
        is_pamakristos: isPam,
        exam_codes: codes,
        diagnostician_id: parseInt(diagId),
        description: desc || (isPam ? "Από Παμμακάριστο" : (labId ? `Εργ. ${labId}` : "Γενικός κανόνας"))
    };

    const overlap = checkRoutingRuleOverlap(payload);
    if (overlap) {
        if (!confirm(`Προσοχή: Ο νέος κανόνας επικαλύπτεται με τον ενεργό κανόνα "${overlap.description}".\nΕξετάσεις που πληρούν και τα δύο κριτήρια θα πηγαίνουν στον πρώτο κανόνα που θα ελεγχθεί.\n\nΘέλετε σίγουρα να συνεχίσετε;`)) {
            return;
        }
    }

    const data = await apiCall('/admin/advanced/exam-routing-rules', 'POST', payload);
    if (data) {
        showToast('Ο κανόνας προστέθηκε.');
        selectedRouteExamCodes.clear();
        renderExamCodeTags('route');
        document.getElementById('adv-route-lab').value = '';
        if (document.getElementById('adv-route-codes-search')) document.getElementById('adv-route-codes-search').value = '';
        document.getElementById('adv-route-doc').value = '';
        document.getElementById('adv-route-doc-search').value = '';
        document.getElementById('adv-route-desc').value = '';
        document.getElementById('adv-route-pam').checked = false;
        updateAdvRouteMutualExclusion();
        await loadAdvancedOptions();
    }
}
async function deleteExamRoutingRule(id) {
    if(!confirm("Διαγραφή κανόνα;")) return;
    const res = await apiCall(`/admin/advanced/exam-routing-rules/${id}`, 'DELETE');
    if(res) {
        showToast('Διαγράφηκε.');
        await loadAdvancedOptions();
    }
}

async function addExclusiveLabRule() {
    const diagId = document.getElementById('adv-excl-diag').value;
    const labSelect = document.getElementById('adv-excl-lab');
    const labId = labSelect.value;
    
    if(!diagId || !labId) {
        showToast('Συμπληρώστε διαγνώστη και εργαστήριο.', 'warning');
        return;
    }
    const name = labSelect.options[labSelect.selectedIndex].text;
    const data = await apiCall('/admin/advanced/exclusive-lab-rules', 'POST', {
        diagnostician_id: parseInt(diagId),
        lab_id: parseInt(labId),
        lab_name: name
    });
    if(data) {
        showToast('Ο κανόνας προστέθηκε.');
        labSelect.value = '';
        await loadAdvancedOptions();
    }
}
async function deleteExclusiveLabRule(id) {
    if(!confirm("Διαγραφή κανόνα;")) return;
    const res = await apiCall(`/admin/advanced/exclusive-lab-rules/${id}`, 'DELETE');
    if(res) {
        showToast('Διαγράφηκε.');
        await loadAdvancedOptions();
    }
}

async function addModalityQuota() {
    const diagId = document.getElementById('adv-quota-diag').value;
    const mod = document.getElementById('adv-quota-modality').value;
    const count = document.getElementById('adv-quota-count').value;
    if(!diagId || !count) {
        showToast('Συμπληρώστε διαγνώστη και όριο.', 'warning');
        return;
    }
    const data = await apiCall('/admin/advanced/modality-quotas', 'POST', {
        diagnostician_id: parseInt(diagId),
        modality: mod,
        max_count: parseInt(count)
    });
    if(data) {
        showToast('Ο κανόνας προστέθηκε.');
        document.getElementById('adv-quota-count').value = '';
        await loadAdvancedOptions();
    }
}
async function deleteModalityQuota(id) {
    if(!confirm("Διαγραφή κανόνα;")) return;
    const res = await apiCall(`/admin/advanced/modality-quotas/${id}`, 'DELETE');
    if(res) {
        showToast('Διαγράφηκε.');
        await loadAdvancedOptions();
    }
}

async function toggleAdvancedRule(type, id, newStatus) {
    let endpoint = '';
    if (type === 'routing') endpoint = `/admin/advanced/exam-routing-rules/${id}`;
    if (type === 'exclusive') endpoint = `/admin/advanced/exclusive-lab-rules/${id}`;
    if (type === 'quota') endpoint = `/admin/advanced/modality-quotas/${id}`;
    
    const res = await apiCall(endpoint, 'PUT', { is_active: newStatus });
    if (res) {
        showToast(newStatus ? 'Ενεργοποιήθηκε' : 'Απενεργοποιήθηκε');
        await loadAdvancedOptions();
    }
}

// Inline Editing Logic (Populate form)
function editExamRoutingRule(id) {
    const r = advRoutingRules.find(x => x.id === id);
    if (!r) return;
    document.getElementById('adv-route-lab').value = r.lab_id || '';
    document.getElementById('adv-route-doc').value = r.issuing_doctor_id || '';
    document.getElementById('adv-route-doc-search').value = r.issuing_doctor_name ? `${r.issuing_doctor_name} (${r.issuing_doctor_id})` : '';
    document.getElementById('adv-route-pam').checked = r.is_pamakristos;
    
    selectedRouteExamCodes.clear();
    if (r.exam_codes) {
        r.exam_codes.split(',').map(c => c.trim()).filter(Boolean).forEach(c => selectedRouteExamCodes.add(c));
    }
    renderExamCodeTags('route');
    if (document.getElementById('adv-route-codes-search')) document.getElementById('adv-route-codes-search').value = '';

    document.getElementById('adv-route-diag').value = r.diagnostician_id;
    document.getElementById('adv-route-desc').value = r.description || '';
    
    updateAdvRouteMutualExclusion();
    
    const btn = document.getElementById('adv-route-lab').closest('.admin-form').querySelector('button.btn-primary');
    btn.textContent = 'Αποθήκευση';
    btn.onclick = async () => {
        const labId = document.getElementById('adv-route-lab').value;
        const docId = document.getElementById('adv-route-doc').value;
        const docSearch = document.getElementById('adv-route-doc-search').value;
        const docName = docSearch ? docSearch.split(' (')[0] : null;
        const desc = document.getElementById('adv-route-desc').value.trim();
        
        const searchInputVal = document.getElementById('adv-route-codes-search')?.value?.trim() || '';
        const codeList = Array.from(selectedRouteExamCodes);
        if (searchInputVal) {
            const manualCodes = searchInputVal.split(/[\s,]+/).map(c => c.trim()).filter(Boolean);
            manualCodes.forEach(c => {
                if (!codeList.includes(c)) codeList.push(c);
            });
        }
        const codesValue = codeList.join(',');

        if (!codesValue || !document.getElementById('adv-route-diag').value || !desc) {
             showToast('Συμπληρώστε κωδικούς, διαγνώστη και περιγραφή.', 'warning');
             return;
        }

        if (Object.keys(EXAM_CODE_MAP).length > 0) {
            const invalidCodes = codesValue.split(',').map(c => c.trim()).filter(c => c && !EXAM_CODE_MAP[c.trim()]);
            if (invalidCodes.length > 0) {
                showToast(`Οι παρακάτω κωδικοί εξέτασης δεν υπάρχουν: ${invalidCodes.join(', ')}`, 'warning');
                return;
            }
        }

        const payload = {
             lab_id: labId ? parseInt(labId) : null,
             issuing_doctor_id: docId || null,
             issuing_doctor_name: docName || null,
             is_pamakristos: document.getElementById('adv-route-pam').checked,
             exam_codes: codesValue,
             diagnostician_id: parseInt(document.getElementById('adv-route-diag').value),
             description: desc
        };

        const overlap = checkRoutingRuleOverlap(payload, id);
        if (overlap) {
            if (!confirm(`Προσοχή: Ο κανόνας επικαλύπτεται με τον ενεργό κανόνα "${overlap.description}".\nΕξετάσεις που πληρούν και τα δύο κριτήρια θα πηγαίνουν στον πρώτο κανόνα που θα ελεγχθεί.\n\nΘέλετε σίγουρα να συνεχίσετε;`)) {
                return;
            }
        }

        const data = await apiCall(`/admin/advanced/exam-routing-rules/${id}`, 'PUT', payload);
        if(data) {
             showToast('Αποθηκεύτηκε');
             btn.textContent = 'Προσθήκη';
             btn.onclick = addExamRoutingRule;
             
             document.getElementById('adv-route-lab').value = '';
             document.getElementById('adv-route-doc').value = '';
             document.getElementById('adv-route-doc-search').value = '';
             document.getElementById('adv-route-pam').checked = false;
             document.getElementById('adv-route-codes').value = '';
             document.getElementById('adv-route-desc').value = '';
             updateAdvRouteMutualExclusion();
             await loadAdvancedOptions();
        }
    };
}

function editExclusiveLabRule(id) {
    const r = advExclusiveRules.find(x => x.id === id);
    if (!r) return;
    document.getElementById('adv-excl-diag').value = r.diagnostician_id;
    document.getElementById('adv-excl-lab').value = r.lab_id;
    
    const btn = document.getElementById('adv-excl-lab').closest('.admin-form').querySelector('button.btn-primary');
    btn.textContent = 'Αποθήκευση';
    btn.onclick = async () => {
        const labSelect = document.getElementById('adv-excl-lab');
        const data = await apiCall(`/admin/advanced/exclusive-lab-rules/${id}`, 'PUT', {
             diagnostician_id: parseInt(document.getElementById('adv-excl-diag').value),
             lab_id: parseInt(labSelect.value),
             lab_name: labSelect.options[labSelect.selectedIndex].text
        });
        if(data) {
             showToast('Αποθηκεύτηκε');
             btn.textContent = 'Προσθήκη';
             btn.onclick = addExclusiveLabRule;
             
             labSelect.value = '';
             await loadAdvancedOptions();
        }
    };
}

function editModalityQuota(id) {
    const r = advModalityQuotas.find(x => x.id === id);
    if (!r) return;
    document.getElementById('adv-quota-diag').value = r.diagnostician_id;
    document.getElementById('adv-quota-modality').value = r.modality;
    document.getElementById('adv-quota-count').value = r.max_count;
    
    const btn = document.getElementById('adv-quota-count').closest('.admin-form').querySelector('button.btn-primary');
    btn.textContent = 'Αποθήκευση';
    btn.onclick = async () => {
        const data = await apiCall(`/admin/advanced/modality-quotas/${id}`, 'PUT', {
             diagnostician_id: parseInt(document.getElementById('adv-quota-diag').value),
             modality: document.getElementById('adv-quota-modality').value,
             max_count: parseInt(document.getElementById('adv-quota-count').value)
        });
        if(data) {
             showToast('Αποθηκεύτηκε');
             btn.textContent = 'Προσθήκη';
             btn.onclick = addModalityQuota;
             
             document.getElementById('adv-quota-count').value = '';
             await loadAdvancedOptions();
        }
    };
}

const WEIGHT_KEYS = [
    'pts_partnership', 'pts_history', 
    'pts_skills_pref', 'pts_skills_neut', 'pts_skills_none',
    'pts_lab_pref', 'pts_lab_neut', 'pts_lab_other',
    'pts_capacity'
];

async function loadSystemWeights() {
    try {
        const data = await apiCall('/assignments/weights');
        if (!data) return;
        
        // Populate inputs (API gives absolute points like 0.35, UI displays 35%)
        WEIGHT_KEYS.forEach(k => {
            const el = document.getElementById(k.replaceAll('_', '-')); // e.g. pts_skills_pref -> pts-skills-pref
            if (el && data[k] !== undefined) {
                el.value = (parseFloat(data[k]) * 100).toFixed(1).replace(/\.0$/, '');
            }
        });
        
        updateWeightsTotal();
    } catch (err) {
        console.error('Error loading weights:', err);
    }
}

function updateWeightsTotal() {
    // Only sum the max potential points for validation
    const maxKeys = ['pts-partnership', 'pts-history', 'pts-skills-pref', 'pts-lab-pref', 'pts-capacity'];
    let sum = 0;
    
    maxKeys.forEach(id => {
        const el = document.getElementById(id);
        if (el) sum += parseFloat(el.value || 0);
    });
    
    const display = document.getElementById('weights-total-display');
    const btn = document.getElementById('btn-save-weights');
    const errMsg = document.getElementById('weights-error-message');
    
    if (display) {
        display.textContent = `Σύνολο Max: ${sum.toFixed(1).replace(/\.0$/, '')}%`;
        if (Math.abs(sum - 100) > 0.1) {
            display.style.color = '#ef4444'; // Red
            if (btn) btn.disabled = true;
            if (errMsg) {
                errMsg.style.color = '#ef4444';
                errMsg.style.fontWeight = 'bold';
            }
        } else {
            display.style.color = '#10b981'; // Green
            if (btn) btn.disabled = false;
            if (errMsg) {
                errMsg.style.color = 'var(--text-secondary)';
                errMsg.style.fontWeight = 'normal';
            }
        }
    }
    
    // Live update the table
    const currentWeights = {};
    WEIGHT_KEYS.forEach(k => {
        const id = k.replaceAll('_', '-');
        const el = document.getElementById(id);
        if (el) {
            currentWeights[k] = parseFloat(el.value || 0) / 100;
        }
    });
}

async function saveSystemWeights() {
    const payload = {};
    WEIGHT_KEYS.forEach(k => {
        const id = k.replaceAll('_', '-');
        const el = document.getElementById(id);
        if (el) {
            // Convert back to absolute (0 to 1) for the DB
            payload[k] = (parseFloat(el.value || 0) / 100).toString();
        }
    });
    
    try {
        await apiCall('/assignments/weights', 'PUT', payload);
        
        // Show success
        const btn = document.getElementById('btn-save-weights');
        const origText = btn.textContent;
        btn.textContent = 'Αποθηκεύτηκαν!';
        btn.classList.add('btn-success');
        setTimeout(() => {
            btn.textContent = origText;
            btn.classList.remove('btn-success');
        }, 2000);
        
    } catch (err) {
        alert(err.message);
    }
}

// Add event listeners to all weight inputs to update the total
document.querySelectorAll('.weight-input').forEach(input => {
    input.addEventListener('input', updateWeightsTotal);
    input.addEventListener('change', updateWeightsTotal);
});

// Advanced Routing Doctor Search
let advDoctorSearchTimeout;
async function debounceAdvDoctorSearch() {
    clearTimeout(advDoctorSearchTimeout);
    advDoctorSearchTimeout = setTimeout(searchAdvDoctors, 300);
}

async function searchAdvDoctors() {
    const q = document.getElementById('adv-route-doc-search').value;
    const resEl = document.getElementById('adv-route-doc-results');
    
    if (!q || q.length < 2) {
        resEl.style.display = 'none';
        return;
    }
    
    try {
        const data = await apiCall(`/admin/doctors?q=${encodeURIComponent(q)}&limit=15`);
        if (data && data.items && data.items.length > 0) {
            resEl.innerHTML = data.items.map(d => `
                <div style="padding:8px 12px; cursor:pointer; border-bottom:1px solid var(--border-color);" 
                     onclick="selectAdvDoctor(${d.id}, '${d.name.replace(/'/g, "\'")}')">
                    <strong>${d.name}</strong> <span style="color:var(--text-secondary);font-size:0.85em;">(${d.id})</span>
                </div>
            `).join('');
            resEl.style.display = 'block';
        } else {
            resEl.innerHTML = '<div style="padding:8px 12px; color:var(--text-secondary);">Δεν βρέθηκαν αποτελέσματα</div>';
            resEl.style.display = 'block';
        }
    } catch (e) {
        console.error("Doctor search error", e);
    }
}

function selectAdvDoctor(id, name) {
    document.getElementById('adv-route-doc').value = id;
    document.getElementById('adv-route-doc-search').value = `${name} (${id})`;
    document.getElementById('adv-route-doc-results').style.display = 'none';
    updateAdvRouteMutualExclusion();
}

// Close adv doctor search on outside click
document.addEventListener('click', (e) => {
    const res = document.getElementById('adv-route-doc-results');
    if (res && e.target.id !== 'adv-route-doc-search') {
        res.style.display = 'none';
    }
});

// ── Change Admin Credentials ──────────────────────────────────────────────────
function openChangeCredsModal() {
    document.getElementById('creds-old-pass').value = '';
    document.getElementById('creds-new-user').value = '';
    document.getElementById('creds-new-pass').value = '';
    const msgEl = document.getElementById('creds-modal-msg');
    if (msgEl) {
        msgEl.style.display = 'none';
        msgEl.innerText = '';
    }
    document.getElementById('creds-modal').style.display = 'flex';
}

function closeChangeCredsModal() {
    document.getElementById('creds-modal').style.display = 'none';
    const msgEl = document.getElementById('creds-modal-msg');
    if (msgEl) {
        msgEl.style.display = 'none';
        msgEl.innerText = '';
    }
}

function showCredsModalMessage(text, isSuccess = false) {
    const msgEl = document.getElementById('creds-modal-msg');
    if (!msgEl) return;
    msgEl.innerText = text;
    msgEl.style.display = 'block';
    if (isSuccess) {
        msgEl.style.backgroundColor = '#dcfce7';
        msgEl.style.color = '#166534';
        msgEl.style.border = '1px solid #86efac';
    } else {
        msgEl.style.backgroundColor = '#fee2e2';
        msgEl.style.color = '#991b1b';
        msgEl.style.border = '1px solid #fca5a5';
    }
}

async function submitChangeCreds(e) {
    e.preventDefault();
    const oldPassword = document.getElementById('creds-old-pass').value;
    const newUsername = document.getElementById('creds-new-user').value.trim();
    const newPassword = document.getElementById('creds-new-pass').value;

    if (!oldPassword) {
        const errorMsg = 'Παρακαλώ εισάγετε τον τρέχοντα κωδικό πρόσβασης.';
        showCredsModalMessage(errorMsg, false);
        showToast(errorMsg, 'warning');
        return;
    }

    if (!newUsername && !newPassword) {
        const errorMsg = 'Παρακαλώ συμπληρώστε νέο username ή νέο κωδικό.';
        showCredsModalMessage(errorMsg, false);
        showToast(errorMsg, 'warning');
        return;
    }

    try {
        const payload = {
            old_password: oldPassword,
            new_username: newUsername || null,
            new_password: newPassword || null
        };
        const res = await apiCall('/admin/auth/change-credentials', 'POST', payload);
        const successMsg = res.message || 'Τα στοιχεία σύνδεσης ενημερώθηκαν επιτυχώς.';
        showCredsModalMessage(successMsg, true);
        showToast(successMsg, 'success');
        
        // Reset input fields
        document.getElementById('creds-old-pass').value = '';
        document.getElementById('creds-new-user').value = '';
        document.getElementById('creds-new-pass').value = '';

        // Auto close after 1.5s
        setTimeout(() => {
            closeChangeCredsModal();
        }, 1500);
    } catch (err) {
        const errorMsg = err.message || 'Αποτυχία ενημέρωσης στοιχείων.';
        showCredsModalMessage(errorMsg, false);
        showToast(errorMsg, 'error');
    }
}




// ══════════════════════════════════════════════
//  Admin Users Management
// ══════════════════════════════════════════════

let adminUsers = [];

async function loadAdminUsers() {
    try {
        const users = await apiCall('/admin/users');
        if (users) {
            adminUsers = users;
            const navItem = document.getElementById('nav-users');
            if (navItem) navItem.style.display = 'flex';
            renderAdminUsers();
        } else {
            const navItem = document.getElementById('nav-users');
            if (navItem) navItem.style.display = 'none';
        }
    } catch (e) {
        const navItem = document.getElementById('nav-users');
        if (navItem) navItem.style.display = 'none';
    }
}

function renderAdminUsers() {
    const tbody = document.getElementById('users-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    
    adminUsers.forEach(u => {
        const tr = document.createElement('tr');
        
        let actions = '';
        if (u.role !== 'it_support') {
            const trashSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>';
            actions += `<button class="btn btn-danger btn-sm" style="padding: 6px 10px; display: inline-flex; align-items: center;" onclick="deleteAdminUser(${u.id})">${trashSvg}</button>`;
        }
        if (u.role === 'admin') {
            const toggleClass = u.is_active ? 'btn-danger' : 'btn-success';
            const toggleText = u.is_active ? 'Απενεργοποίηση' : 'Ενεργοποίηση';
            actions += ` <button class="btn ${toggleClass} btn-sm" onclick="toggleAdminUser(${u.id})">${toggleText}</button>`;
            
            actions += ` <button class="btn btn-secondary btn-sm" onclick="resetAdminUser(${u.id})">Επαναφορά (admin/admin1234)</button>`;
        }
        
        let roleBadge = '';
        if (u.role === 'it_support') {
            roleBadge = '<span class="admin-badge" style="background-color: #f3ebff; color: #8122FF; border: 1px solid #d8b4fe;">IT Support</span>';
        } else {
            roleBadge = '<span class="admin-badge">Admin</span>';
        }
            
        tr.innerHTML = `
            <td>${u.username}</td>
            <td>${roleBadge}</td>
            <td>${u.is_active ? '<span style="color:var(--success-color);">Ενεργός</span>' : '<span style="color:var(--error-color);">Ανενεργός</span>'}</td>
            <td style="display:flex; gap:6px;">${actions}</td>
        `;
        tbody.appendChild(tr);
    });
}

async function createAdminUser() {
    const username = document.getElementById('new-user-username').value.trim();
    const password = document.getElementById('new-user-password').value.trim();
    const role = document.getElementById('new-user-role').value;
    
    if (!username || !password) {
        showToast('Συμπληρώστε όνομα χρήστη και κωδικό.', 'warning');
        return;
    }
    
    try {
        const res = await apiCall('/admin/users', 'POST', { username, password, role });
        if (res) {
            showToast('Ο χρήστης δημιουργήθηκε!', 'success');
            document.getElementById('new-user-username').value = '';
            document.getElementById('new-user-password').value = '';
            loadAdminUsers();
        }
    } catch (e) {
        showToast(e.message || 'Σφάλμα δημιουργίας χρήστη', 'error');
    }
}

async function deleteAdminUser(id) {
    if (!confirm('Σίγουρα θέλετε να διαγράψετε αυτόν τον χρήστη;')) return;
    try {
        const res = await apiCall(`/admin/users/${id}`, 'DELETE');
        if (res) {
            showToast('Ο χρήστης διαγράφηκε.', 'success');
            loadAdminUsers();
        }
    } catch (e) {
        showToast(e.message || 'Σφάλμα διαγραφής', 'error');
    }
}

async function resetAdminUser(id) {
    if (!confirm('Είστε σίγουροι ότι θέλετε να επαναφέρετε τα στοιχεία αυτού του διαχειριστή σε admin / admin1234;')) return;
    try {
        const res = await apiCall(`/admin/users/${id}/reset`, 'POST');
        if (res) {
            showToast('Τα στοιχεία επαναφέρθηκαν επιτυχώς.', 'success');
            loadAdminUsers();
        }
    } catch (e) {
        showToast(e.message || 'Σφάλμα επαναφοράς', 'error');
    }
}

async function toggleAdminUser(id) {
    try {
        const res = await apiCall(`/admin/users/${id}/toggle`, 'POST');
        if (res) {
            showToast(res.message, 'success');
            loadAdminUsers();
        }
    } catch (e) {
        showToast(e.message || 'Σφάλμα αλλαγής κατάστασης', 'error');
    }
}
