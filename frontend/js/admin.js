/**
 * DiagFlow — Admin Panel JavaScript
 *
 * Handles all admin CRUD operations:
 * - Εφημερία Παμμακάριστου (on-call override)
 * - Ακτινοδιαγνώστες (list, add, toggle active)
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
    document.getElementById('oncall-date').value = today;
    document.getElementById('avail-date').value = today;

    await loadAll();
    showSection('oncall');
});

async function loadAll() {
    await Promise.all([
        loadDiagnosticians(),
        loadPartnerships(),
        loadDoctors(),
        loadSkills(),
        loadAvailability(),
        loadOncall(),
    ]);
}


// ══════════════════════════════════════════════
//  API Call Helper
// ══════════════════════════════════════════════

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
            showToast('Η σύνδεση έχει λήξει. Παρακαλώ συνδεθείτε ξανά.', 'error');
            setTimeout(() => window.location.href = 'index.html', 2000);
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
    oncall: 'Εφημερία Παμμακάριστου',
    diagnosticians: 'Ακτινοδιαγνώστες',
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

async function loadDiagnosticians() {
    const data = await apiCall('/admin/diagnosticians');
    diagnosticians = data || getMockDiagnosticians();
    renderDiagnosticians();
    populateDiagnosticianSelects();
}

async function loadPartnerships() {
    const data = await apiCall('/admin/partnerships');
    partnerships = data || getMockPartnerships();
    renderPartnerships();
}

async function loadDoctors() {
    const data = await apiCall('/admin/doctors');
    doctors = data || getMockDoctors();
    renderDoctors();
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
    document.getElementById('oncall-current').innerHTML = `
        <strong style="color:var(--text-primary);font-size:var(--font-size-md);">${oncall.diagnostician_name}</strong>
        <span style="margin-left:8px;color:var(--text-tertiary);">(${formatDate(oncall.date)})</span>
    `;
}

function populateDiagnosticianSelects() {
    const selects = ['oncall-diag-select', 'avail-diag', 'skill-diag', 'part-diag'];
    selects.forEach(id => {
        const sel = document.getElementById(id);
        if (!sel) return;
        sel.innerHTML = '<option value="">— Επιλέξτε —</option>';
        diagnosticians.forEach(d => {
            sel.innerHTML += `<option value="${d.id}" data-name="${d.name}">${d.name}</option>`;
        });
    });
}


// ══════════════════════════════════════════════
//  Render Functions
// ══════════════════════════════════════════════

function renderDiagnosticians() {
    const tbody = document.getElementById('diag-tbody');
    tbody.innerHTML = diagnosticians.map(d => `
        <tr>
            <td style="font-weight:600;">${d.name}</td>
            <td>
                <span class="status-badge ${d.active ? 'active' : 'inactive'}">
                    ${d.active ? '● Ενεργός' : '● Ανενεργός'}
                </span>
            </td>
            <td>${d.can_ct ? '✅' : '—'}</td>
            <td>${d.can_mri ? '✅' : '—'}</td>
            <td>${d.daily_quota} εξετάσεις/ημέρα</td>
            <td>
                <button class="btn btn-secondary btn-sm" onclick="toggleDiagActive(${d.id}, ${!d.active})">
                    ${d.active ? 'Απενεργοποίηση' : 'Ενεργοποίηση'}
                </button>
            </td>
        </tr>
    `).join('');
}

function renderAvailability() {
    const tbody = document.getElementById('avail-tbody');
    if (!availability.length) {
        tbody.innerHTML = '<tr><td colspan="4" style="color:var(--text-tertiary);text-align:center;padding:20px;">Καμία καταγεγραμμένη αποχή</td></tr>';
        return;
    }
    const statusLabel = { available: 'Διαθέσιμος/η', on_leave: 'Άδεια', half_day: 'Μισή Μέρα' };
    const statusClass = { available: 'active', on_leave: 'on-leave', half_day: 'inactive' };
    tbody.innerHTML = availability.map(a => `
        <tr>
            <td style="font-weight:500;">${a.diagnostician_name}</td>
            <td class="date-cell">${formatDate(a.date)}</td>
            <td><span class="status-badge ${statusClass[a.status] || 'inactive'}">${statusLabel[a.status] || a.status}</span></td>
            <td style="color:var(--text-tertiary);">${a.notes || '—'}</td>
        </tr>
    `).join('');
}

function renderSkills() {
    const tbody = document.getElementById('skills-tbody');
    if (!skills.length) {
        tbody.innerHTML = '<tr><td colspan="4" style="color:var(--text-tertiary);text-align:center;padding:20px;">Δεν υπάρχουν δεδομένα δεξιοτήτων</td></tr>';
        return;
    }
    const bodyPartLabel = { abdomen: 'Κοιλία', chest: 'Θώρακας', neuro: 'Εγκέφαλος', msk: 'Μυοσκελετικό', spine: 'Σπονδ. Στήλη', pelvis: 'Πύελος' };
    tbody.innerHTML = skills.map(s => {
        const pct = Math.round(s.proficiency_level * 100);
        return `
            <tr>
                <td style="font-weight:500;">${s.diagnostician_name}</td>
                <td>${bodyPartLabel[s.body_part] || s.body_part}</td>
                <td><span class="modality-badge ${s.modality.toLowerCase()}">${s.modality}</span></td>
                <td>
                    <div class="proficiency-bar-wrap">
                        <div class="proficiency-bar"><div class="proficiency-bar-fill" style="width:${pct}%"></div></div>
                        <span style="font-size:var(--font-size-xs);color:var(--text-secondary);">${pct}%</span>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function renderPartnerships() {
    const tbody = document.getElementById('part-tbody');
    if (!partnerships.length) {
        tbody.innerHTML = '<tr><td colspan="4" style="color:var(--text-tertiary);text-align:center;padding:20px;">Δεν υπάρχουν συνεργασίες</td></tr>';
        return;
    }
    tbody.innerHTML = partnerships.map(p => `
        <tr>
            <td style="font-weight:500;">${p.issuing_doctor_name} <span style="color:var(--text-tertiary);font-size:11px;">(${p.issuing_doctor_id})</span></td>
            <td style="color:var(--accent-primary);font-weight:600;">${p.preferred_diagnostician_name}</td>
            <td>
                <div style="display:flex;gap:2px;">${'★'.repeat(p.priority)}${'☆'.repeat(5-p.priority)}</div>
            </td>
            <td>
                <button class="btn btn-secondary btn-sm" style="color:var(--accent-danger);" onclick="deletePartnership(${p.id})">Διαγραφή</button>
            </td>
        </tr>
    `).join('');
}

function renderDoctors() {
    const tbody = document.getElementById('doc-tbody');
    tbody.innerHTML = doctors.map(d => `
        <tr>
            <td style="color:var(--text-tertiary);font-size:var(--font-size-xs);">${d.id}</td>
            <td style="font-weight:500;">${d.name}</td>
            <td style="color:var(--text-secondary);">${d.specialty || '—'}</td>
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

    if (!diagId || !dateVal) { showToast('Επιλέξτε ακτινοδιαγνώστη και ημερομηνία', 'warning'); return; }

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
        const result = await apiCall('/admin/diagnosticians', 'POST', { name, active, can_ct, can_mri, daily_quota: quota });
        if (result) diagnosticians.push(result);
        else diagnosticians.push({ id: Date.now(), name, active, can_ct, can_mri, daily_quota: quota });
    } catch {
        diagnosticians.push({ id: Date.now(), name, active, can_ct, can_mri, daily_quota: quota });
    }

    renderDiagnosticians();
    populateDiagnosticianSelects();
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
    showToast(`${newActive ? '✅ Ενεργοποίηση' : '⚠️ Απενεργοποίηση'}: ${d.name}`, newActive ? 'success' : 'warning');
}

async function setAvailability() {
    const selEl = document.getElementById('avail-diag');
    const diagId = parseInt(selEl.value);
    const diagName = selEl.options[selEl.selectedIndex]?.dataset?.name || '';
    const dateVal = document.getElementById('avail-date').value;
    const status = document.getElementById('avail-status').value;
    const notes = document.getElementById('avail-notes').value.trim();

    if (!diagId || !dateVal) { showToast('Επιλέξτε ακτινοδιαγνώστη και ημερομηνία', 'warning'); return; }

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

    renderAvailability();
    showToast(`✅ Διαθεσιμότητα ενημερώθηκε: ${diagName}`, 'success');
}

async function setSkill() {
    const selEl = document.getElementById('skill-diag');
    const diagId = parseInt(selEl.value);
    const diagName = selEl.options[selEl.selectedIndex]?.dataset?.name || '';
    const body_part = document.getElementById('skill-body').value;
    const modality = document.getElementById('skill-modality').value;
    const proficiency_level = parseInt(document.getElementById('skill-proficiency').value) / 100;

    if (!diagId) { showToast('Επιλέξτε ακτινοδιαγνώστη', 'warning'); return; }

    const record = { diagnostician_id: diagId, diagnostician_name: diagName, body_part, modality, proficiency_level };

    try {
        const result = await apiCall('/admin/skills', 'POST', record);
        skills = skills.filter(s => !(s.diagnostician_id === diagId && s.body_part === body_part && s.modality === modality));
        if (result) skills.push(result);
        else skills.push({ id: Date.now(), ...record });
    } catch {
        skills = skills.filter(s => !(s.diagnostician_id === diagId && s.body_part === body_part && s.modality === modality));
        skills.push({ id: Date.now(), ...record });
    }

    renderSkills();
    showToast(`✅ Δεξιότητα ενημερώθηκε: ${diagName} — ${body_part} (${modality})`, 'success');
}

async function addPartnership() {
    const doctorId = document.getElementById('part-doctor-id').value.trim();
    const doctorName = document.getElementById('part-doctor-name').value.trim();
    const diagSelEl = document.getElementById('part-diag');
    const diagId = parseInt(diagSelEl.value);
    const diagName = diagSelEl.options[diagSelEl.selectedIndex]?.dataset?.name || '';
    const priority = parseInt(document.getElementById('part-priority').value);

    if (!doctorId || !doctorName || !diagId) {
        showToast('Συμπληρώστε όλα τα στοιχεία', 'warning');
        return;
    }

    const record = {
        issuing_doctor_id: doctorId,
        issuing_doctor_name: doctorName,
        preferred_diagnostician_id: diagId,
        preferred_diagnostician_name: diagName,
        priority,
    };

    try {
        const result = await apiCall('/admin/partnerships', 'POST', record);
        partnerships.push(result || { id: Date.now(), ...record });
    } catch {
        partnerships.push({ id: Date.now(), ...record });
    }

    renderPartnerships();
    document.getElementById('part-doctor-id').value = '';
    document.getElementById('part-doctor-name').value = '';
    showToast(`✅ Συνεργασία προστέθηκε: ${doctorName} → ${diagName}`, 'success');
}

async function deletePartnership(id) {
    try {
        await apiCall(`/admin/partnerships/${id}`, 'DELETE');
    } catch { /* mock mode */ }
    partnerships = partnerships.filter(p => p.id !== id);
    renderPartnerships();
    showToast('Η συνεργασία διαγράφηκε', 'info');
}

async function addDoctor() {
    const name = document.getElementById('new-doc-name').value.trim();
    const specialty = document.getElementById('new-doc-specialty').value.trim();

    if (!name) { showToast('Εισάγετε ονοματεπώνυμο', 'warning'); return; }

    try {
        const result = await apiCall('/admin/doctors', 'POST', { name, specialty });
        doctors.push(result || { id: `DR-${Date.now()}`, name, specialty });
    } catch {
        doctors.push({ id: `DR-${Date.now()}`, name, specialty });
    }

    renderDoctors();
    document.getElementById('new-doc-name').value = '';
    document.getElementById('new-doc-specialty').value = '';
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
        { id: 1, issuing_doctor_id: 'DR-101', issuing_doctor_name: 'Παπαδόπουλος Ν.', preferred_diagnostician_id: 3, preferred_diagnostician_name: 'Παπαδόπουλος Γ.', priority: 5 },
        { id: 2, issuing_doctor_id: 'DR-205', issuing_doctor_name: 'Ιωάννου Ε.', preferred_diagnostician_id: 2, preferred_diagnostician_name: 'Κωνσταντίνου Β.', priority: 4 },
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
        { id: 1, diagnostician_id: 1, diagnostician_name: 'Νάτσικα Α.', body_part: 'abdomen', modality: 'MRI', proficiency_level: 0.9 },
        { id: 2, diagnostician_id: 1, diagnostician_name: 'Νάτσικα Α.', body_part: 'chest', modality: 'CT', proficiency_level: 0.7 },
        { id: 3, diagnostician_id: 2, diagnostician_name: 'Κωνσταντίνου Β.', body_part: 'chest', modality: 'CT', proficiency_level: 0.95 },
        { id: 4, diagnostician_id: 3, diagnostician_name: 'Παπαδόπουλος Γ.', body_part: 'neuro', modality: 'MRI', proficiency_level: 0.95 },
    ];
}

function getMockAvailability() {
    const today = new Date().toISOString().split('T')[0];
    return [
        { id: 1, diagnostician_id: 6, diagnostician_name: 'Αντωνίου Ζ.', date: today, status: 'on_leave', notes: 'Άδεια' },
    ];
}
