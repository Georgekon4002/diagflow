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

// ══════════════════════════════════════════════
//  Auth Guard & Init
// ══════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', async () => {
    if (!adminToken) {
        // Not logged in — redirect back
        showToast('Απαιτείται σύνδεση διαχειριστή.', 'error');
        setTimeout(() => window.location.href = 'index.html', 1500);
        return;
    }

    // Set today's date defaults
    const today = new Date().toISOString().split('T')[0];
    
    const fpConfig = {
        dateFormat: "Y-m-d",
        altInput: true,
        altFormat: "d/m/Y",
        defaultDate: today,
        firstDayOfWeek: 1, // Monday
        locale: "gr"
    };
    
    flatpickr("#oncall-date", fpConfig);
    flatpickr("#avail-date", {
        ...fpConfig,
        mode: "range",
        defaultDate: [today, today]
    });

    await loadAll();
    showSection('oncall');
});

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
    ]);
}

async function loadExamCategories() {
    try {
        const data = await apiCall('/admin/exam-categories');
        if (data) {
            data.forEach(ex => {
                EXAM_CODE_MAP[String(ex.examnumcode)] = ex.name;
            });
        }
    } catch {
        console.warn("Could not load exam categories");
    }
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
        if (response.status === 403) {
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
    availability: 'Διαθεσιμότητα',
    skills: 'Δεξιότητες & Χωρητικότητα',
    partnerships: 'Συνεργασίες Ιατρών',
    doctors: 'Ιατροί',
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
    showToast('Συγχρονισμός διαγνωστών...', 'info');
    const res = await apiCall('/admin/sync-diagnosticians', 'POST');
    if (res && res.synced !== undefined) {
        showToast(`Συγχρονίστηκαν ${res.synced} διαγνώστες από το Slis.`, 'success');
        await loadDiagnosticians();
    } else {
        showToast('Σφάλμα κατά τον συγχρονισμό.', 'error');
    }
}

async function syncDoctors() {
    showToast('Συγχρονισμός ιατρών...', 'info');
    const res = await apiCall('/admin/sync-doctors', 'POST');
    if (res && res.synced !== undefined) {
        showToast(`Συγχρονίστηκαν ${res.synced} ιατροί από το Slis.`, 'success');
        await loadDoctors(0);
    } else {
        showToast('Σφάλμα κατά τον συγχρονισμό.', 'error');
    }
}

async function loadDiagnosticians() {
    const data = await apiCall('/admin/diagnosticians');
    diagnosticians = data || getMockDiagnosticians();
    renderDiagnosticians();
    populateDiagnosticianSelects();
    renderAvailability();
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
            mock = mock.filter(d => d.name.toLowerCase().includes(lowerQ) || String(d.id).includes(lowerQ));
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
    const oncall = data || { diagnostician_name: 'Παπαδόπουλος Γ.', date: new Date().toISOString().split('T')[0] };
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

        let options = '<option value="">— Επιλέξτε —</option>';
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
    const selects = ['oncall-diag-select', 'avail-diag', 'skill-diag', 'part-diag', 'schedule-diag'];
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

function renderDiagnosticians() {
    const tbody = document.getElementById('diag-tbody');
    
    let filteredDiags = diagnosticians;
    if (diagSearchQuery) {
        const lowerQ = diagSearchQuery.toLowerCase();
        filteredDiags = filteredDiags.filter(d => d.name.toLowerCase().includes(lowerQ));
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
                    <option value="8" ${d.preferred_lab_id === 8 ? 'selected' : ''}>ΧΑΛΚΙΔΟΣ (8)</option>
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
    showToast(`Η ικανότητα CT ενημερώθηκε: ${d.name}`, 'success');
}

async function toggleDiagMRI(id, newCanMRI) {
    const d = diagnosticians.find(x => x.id === id);
    if (!d) return;
    d.can_mri = newCanMRI;
    try { await apiCall(`/admin/diagnosticians/${id}`, 'PUT', d); } catch { /* mock mode */ }
    showToast(`Η ικανότητα MRI ενημερώθηκε: ${d.name}`, 'success');
}

function renderAvailability() {
    const tbody = document.getElementById('avail-tbody');
    if (!tbody) return;

    // Filter only today and future dates, excluding entries marked as 'available'
    const todayStr = new Date().toISOString().split('T')[0];
    const filteredAvailability = availability.filter(a => a.date >= todayStr && a.status !== 'available');

    const statusLabel = { available: 'Διαθέσιμος/η', on_leave: 'Άδεια', half_day: 'Μισή Μέρα' };
    const statusClass = { available: 'active', on_leave: 'on-leave', half_day: 'inactive' };

    const rows = [];

    // 1. Add diagnosticians on leave
    filteredAvailability.forEach(a => {
        rows.push({
            diagnostician_id: a.diagnostician_id,
            diagnostician_name: a.diagnostician_name,
            date: a.date,
            statusBadge: `<span class="status-badge ${statusClass[a.status] || 'on-leave'}">${statusLabel[a.status] || 'Άδεια'}</span>`,
            notes: a.notes || '—'
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
        const hasLeaveToday = rows.some(r => r.diagnostician_id === d.id && r.date === todayStr);
        if (!hasLeaveToday) {
            rows.push({
                diagnostician_id: d.id,
                diagnostician_name: d.name,
                date: todayStr,
                statusBadge: `<span class="status-badge inactive">Όχι σήμερα</span>`,
                notes: ''
            });
        }
    });

    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="4" style="color:var(--text-tertiary);text-align:center;padding:20px;">Δεν υπάρχουν εγγραφές</td></tr>';
        return;
    }

    // Sort rows by date ascending
    rows.sort((a, b) => a.date.localeCompare(b.date));

    tbody.innerHTML = rows.map(r => `
        <tr>
            <td style="font-weight:500;">${r.diagnostician_name}</td>
            <td class="date-cell">${formatDate(r.date)}</td>
            <td>${r.statusBadge}</td>
            <td style="color:var(--text-tertiary);">${r.notes}</td>
        </tr>
    `).join('');
}

function renderTodayOffSchedules() {
    renderAvailability();
}



function renderSkills() {
    const tbody = document.getElementById('skills-tbody');
    if (!skills.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-tertiary);text-align:center;padding:20px;">Δεν υπάρχουν δεδομένα δεξιοτήτων</td></tr>';
        return;
    }

    // Group by diagnostician
    const grouped = {};
    skills.forEach(s => {
        if (!grouped[s.diagnostician_name]) grouped[s.diagnostician_name] = [];
        grouped[s.diagnostician_name].push(s);
    });

    let html = '';
    for (const [diagName, diagSkills] of Object.entries(grouped)) {
        // Main collapsible row
        const diagIdForCollapse = diagSkills[0].diagnostician_id || diagName.replace(/\s+/g, '');
        html += `
            <tr style="cursor:pointer; background:var(--surface-color); border-bottom:1px solid var(--border-color);" onclick="toggleSkillsRow('${diagIdForCollapse}')">
                <td colspan="5" style="font-weight:600; padding:12px;">
                    <span id="icon-${diagIdForCollapse}" style="display:inline-block; width:20px; transition:transform 0.2s;">▶</span> 
                    ${diagName} <span style="color:var(--text-tertiary); font-weight:normal; font-size:13px;">(${diagSkills.length} δεξιότητες)</span>
                </td>
            </tr>
        `;
        
        // Children rows
        diagSkills.forEach((s, index) => {
            const isPreferred = s.is_preferred || false;
            const examCode = s.exam_code || '—';
            const examTitle = s.exam_title || s.body_part || EXAM_CODE_MAP[s.exam_code] || '—';
            
            html += `<tr class="skills-row-${diagIdForCollapse}" style="display:none; background:#fafafa;">
                <td style="padding-left:32px;"></td>
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
}

// Helper to toggle skills display
function toggleSkillsRow(diagId) {
    const rows = document.querySelectorAll('.skills-row-' + diagId);
    const icon = document.getElementById('icon-' + diagId);
    let isHidden = false;
    rows.forEach(r => {
        if (r.style.display === 'none') {
            r.style.display = 'table-row';
            isHidden = true;
        } else {
            r.style.display = 'none';
        }
    });
    if (icon) {
        icon.style.transform = isHidden ? 'rotate(90deg)' : 'rotate(0deg)';
    }
}

function togglePartnershipsRow(diagId) {
    const rows = document.querySelectorAll('.part-row-' + diagId);
    const icon = document.getElementById('part-icon-' + diagId);
    let isHidden = false;
    rows.forEach(r => {
        if (r.style.display === 'none') {
            r.style.display = 'table-row';
            isHidden = true;
        } else {
            r.style.display = 'none';
        }
    });
    if (icon) {
        icon.style.transform = isHidden ? 'rotate(90deg)' : 'rotate(0deg)';
    }
}

function renderPartnerships() {
    const tbody = document.getElementById('part-tbody');
    if (!partnerships.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-tertiary);text-align:center;padding:20px;">Δεν υπάρχουν συνεργασίες</td></tr>';
        return;
    }

    // Group by diagnostician
    const grouped = {};
    partnerships.forEach(p => {
        if (!grouped[p.preferred_diagnostician_name]) grouped[p.preferred_diagnostician_name] = [];
        grouped[p.preferred_diagnostician_name].push(p);
    });

    let html = '';
    for (const [diagName, diagPartners] of Object.entries(grouped)) {
        // Main collapsible row
        const diagIdForCollapse = diagPartners[0].preferred_diagnostician_id || diagName.replace(/\s+/g, '');
        html += `
            <tr style="cursor:pointer; background:var(--surface-color); border-bottom:1px solid var(--border-color);" onclick="togglePartnershipsRow('${diagIdForCollapse}')">
                <td colspan="5" style="font-weight:600; padding:12px;">
                    <span id="part-icon-${diagIdForCollapse}" style="display:inline-block; width:20px; transition:transform 0.2s;">▶</span> 
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
            
            html += `<tr class="part-row-${diagIdForCollapse}" style="display:none; background:#fafafa;">
                <td style="padding-left:32px;"></td>
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
}

function renderDoctors() {
    const tbody = document.getElementById('doc-tbody');
    tbody.innerHTML = doctors.map(d => `
        <tr>
            <td style="color:var(--text-tertiary);font-size:var(--font-size-xs);">${d.id}</td>
            <td style="font-weight:500;">${d.name}</td>
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
                datesToSave.push(current.toISOString().split('T')[0]);
                current.setDate(current.getDate() + 1);
            }
        } else {
            datesToSave.push(fpInstance.selectedDates[0].toISOString().split('T')[0]);
        }
    } else {
        const rawVal = document.getElementById('avail-date').value;
        if (rawVal) datesToSave.push(rawVal);
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
    const exam_code = document.getElementById('skill-exam-code').value.trim();
    const is_preferred = document.getElementById('skill-preferred').checked;

    if (!diagId) { showToast('Επιλέξτε διαγνώστη', 'warning'); return; }
    if (!exam_code) { showToast('Εισάγετε κωδικό εξέτασης', 'warning'); return; }

    // Build title from code map
    const exam_title = EXAM_CODE_MAP[exam_code] || `Εξέταση ${exam_code}`;

    const record = { diagnostician_id: diagId, diagnostician_name: diagName, exam_code, exam_title, is_preferred };

    try {
        const result = await apiCall('/admin/skills', 'POST', record);
        skills = skills.filter(s => !(s.diagnostician_id === diagId && s.exam_code === exam_code));
        if (result) skills.push(result);
        else skills.push({ id: Date.now(), ...record });
    } catch {
        skills = skills.filter(s => !(s.diagnostician_id === diagId && s.exam_code === exam_code));
        skills.push({ id: Date.now(), ...record });
    }

    renderSkills();
    showToast(`✅ Δεξιότητα ενημερώθηκε: ${diagName} — ${exam_code}`, 'success');
}

async function deleteSkill(id) {
    try {
        await apiCall(`/admin/skills/${id}`, 'DELETE');
    } catch { /* mock mode */ }
    skills = skills.filter(s => s.id !== id);
    renderSkills();
    showToast('Η δεξιότητα διαγράφηκε', 'info');
}

async function toggleSkillPreference(id, newPreference) {
    const s = skills.find(x => x.id === id);
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
        await loadData();
    } catch (err) {
        // mock fallback
        partnerships = partnerships.filter(p => p.id !== id);
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
        await loadData();
    } catch (err) {
        // mock fallback
        const p = partnerships.find(x => x.id === id);
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

function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        const d = new Date(dateStr + 'T00:00:00');
        return d.toLocaleDateString('el-GR', { day: '2-digit', month: '2-digit', year: 'numeric' });
    } catch { return dateStr; }
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
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
        { id: 'DR-101', name: 'Παπαδόπουλος Ν.', specialty: 'Ορθοπεδική' },
        { id: 'DR-205', name: 'Ιωάννου Ε.', specialty: 'Καρδιολογία' },
        { id: 'DR-310', name: 'Βασιλείου Κ.', specialty: 'Νευρολογία' },
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
    const today = new Date().toISOString().split('T')[0];
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
