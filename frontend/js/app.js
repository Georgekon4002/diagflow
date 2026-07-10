/**
 * DiagFlow — Secretariat Review Dashboard
 *
 * Handles:
 * - Loading pending exams from the API
 * - Generating and displaying assignment suggestions
 * - Confirm/override workflow
 * - Toast notifications
 * - Παμακάριστος on-call display
 */

// ── Configuration ──
const API_BASE = '/api';

// ── State ──
let pendingExams = [];
let currentSuggestion = null;
let currentExamId = null;
let diagnosticians = [];
let assignedToday = 0;
let overriddenToday = 0;


// ══════════════════════════════════════════════
//  Initialization
// ══════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', async () => {
    await Promise.all([
        loadPendingExams(),
        loadDiagnosticians(),
        loadOncall(),
    ]);
    updateStats();
});


// ══════════════════════════════════════════════
//  API Calls
// ══════════════════════════════════════════════

async function apiCall(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) options.body = JSON.stringify(body);

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, options);
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        return await response.json();
    } catch (err) {
        if (err.message.includes('Failed to fetch')) {
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
    const tbody = document.getElementById('exams-tbody');
    const emptyState = document.getElementById('empty-state');

    try {
        const data = await apiCall('/exams/pending');

        if (data) {
            pendingExams = data;
        } else {
            // Mock data for offline development
            pendingExams = getMockExams();
        }

        if (pendingExams.length === 0) {
            tbody.innerHTML = '';
            emptyState.style.display = 'flex';
            return;
        }

        emptyState.style.display = 'none';
        renderExamsTable(pendingExams);
        updateStats();

    } catch (err) {
        showToast(`Σφάλμα φόρτωσης: ${err.message}`, 'error');
        pendingExams = getMockExams();
        renderExamsTable(pendingExams);
    }
}

async function loadDiagnosticians() {
    try {
        const data = await apiCall('/diagnosticians');
        if (data) {
            diagnosticians = data;
        } else {
            diagnosticians = getMockDiagnosticians();
        }
    } catch {
        diagnosticians = getMockDiagnosticians();
    }
}

async function loadOncall() {
    try {
        const data = await apiCall('/pamakristos/oncall');
        if (data) {
            document.getElementById('oncall-name').textContent = data.diagnostician_name;
        } else {
            document.getElementById('oncall-name').textContent = 'Παπαδόπουλος Γ.';
        }
    } catch {
        document.getElementById('oncall-name').textContent = '—';
    }
}


// ══════════════════════════════════════════════
//  Render Table
// ══════════════════════════════════════════════

function renderExamsTable(exams) {
    const tbody = document.getElementById('exams-tbody');

    tbody.innerHTML = exams.map(exam => {
        const hasComment = exam.comments && exam.comments.trim().length > 0;
        const hasSuggestion = exam.suggestion != null;

        return `
            <tr id="row-${exam.exam_id}">
                <td>
                    <span style="font-weight: 600; color: var(--text-primary);">${exam.exam_id}</span>
                </td>
                <td>${exam.patient_name}</td>
                <td>
                    <span class="modality-badge ${exam.modality.toLowerCase()}">${exam.modality}</span>
                </td>
                <td><span class="body-part-tag">${translateBodyPart(exam.body_part)}</span></td>
                <td>${exam.lab_name}</td>
                <td>${exam.issuing_doctor_name}</td>
                <td class="comment-cell ${hasComment ? 'has-comment' : ''}" title="${exam.comments || '—'}">
                    ${hasComment ? exam.comments : '—'}
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
//  Suggestion Flow
// ══════════════════════════════════════════════

async function getSuggestion(examId) {
    const btn = event.target.closest('.btn');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="loading-spinner"></span>';
    btn.disabled = true;

    try {
        let suggestion = await apiCall('/assignments/suggest', 'POST', { exam_id: examId });

        if (!suggestion) {
            // Mock suggestion for offline development
            suggestion = getMockSuggestion(examId);
        }

        // Store the suggestion on the exam
        const exam = pendingExams.find(e => e.exam_id === examId);
        if (exam) {
            exam.suggestion = suggestion;
        }

        // Re-render and open modal
        renderExamsTable(pendingExams);
        openSuggestionModal(examId, suggestion);

    } catch (err) {
        showToast(`Σφάλμα: ${err.message}`, 'error');
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

function viewSuggestion(examId) {
    const exam = pendingExams.find(e => e.exam_id === examId);
    if (exam && exam.suggestion) {
        openSuggestionModal(examId, exam.suggestion);
    }
}


// ══════════════════════════════════════════════
//  Modal
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
        ${exam.comments ? `<br><strong>Σχόλια:</strong> <span style="color: var(--accent-warning);">${exam.comments}</span>` : ''}
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
                    <div class="score-bar-fill" style="width: ${barWidth}%"></div>
                </div>
            </div>
        `;
    }).join('');

    // Alternatives
    const altList = document.getElementById('alternatives-list');
    if (suggestion.alternatives && suggestion.alternatives.length > 0) {
        document.getElementById('alternatives-section').style.display = 'block';
        altList.innerHTML = suggestion.alternatives.map((alt, i) => `
            <div class="alternative-item" onclick="selectAlternative(${alt.id}, '${alt.name}')">
                <span class="alt-rank">#${i + 2}</span>
                <span class="alt-name">${alt.name}</span>
                <span class="alt-score">${Math.round(alt.score * 100)}%</span>
            </div>
        `).join('');
    } else {
        document.getElementById('alternatives-section').style.display = 'none';
    }

    // Override dropdown
    const overrideSelect = document.getElementById('override-select');
    overrideSelect.innerHTML = '<option value="">— Επιλέξτε εναλλακτικό —</option>';
    diagnosticians.forEach(d => {
        if (d.id !== suggestion.suggested_diagnostician_id && d.available) {
            overrideSelect.innerHTML += `<option value="${d.id}">${d.name} (${d.daily_quota - d.current_day_count}/${d.daily_quota} slots)</option>`;
        }
    });

    // Show modal
    document.getElementById('suggestion-modal').style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    document.getElementById('suggestion-modal').style.display = 'none';
    document.body.style.overflow = '';
    currentExamId = null;
    currentSuggestion = null;
}

function selectAlternative(id, name) {
    const select = document.getElementById('override-select');
    select.value = id.toString();
    // Scroll to override section
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

        assignedToday++;
        showToast(
            `✅ Ανατέθηκε στον/στην ${currentSuggestion.suggested_diagnostician_name}`,
            'success'
        );

        // Remove from pending list
        pendingExams = pendingExams.filter(e => e.exam_id !== currentExamId);
        renderExamsTable(pendingExams);
        updateStats();
        closeModal();

    } catch (err) {
        // In mock mode, still simulate success
        assignedToday++;
        showToast(
            `✅ Ανατέθηκε στον/στην ${currentSuggestion.suggested_diagnostician_name}`,
            'success'
        );
        pendingExams = pendingExams.filter(e => e.exam_id !== currentExamId);
        renderExamsTable(pendingExams);
        updateStats();
        closeModal();
    }
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
    const overrideName = select.options[select.selectedIndex].text.split(' (')[0];

    const btn = document.getElementById('btn-override');
    btn.innerHTML = '<span class="loading-spinner"></span>';
    btn.disabled = true;

    try {
        await apiCall('/assignments/override', 'POST', {
            exam_id: currentExamId,
            original_diagnostician_id: currentSuggestion.suggested_diagnostician_id,
            override_diagnostician_id: overrideId,
            reason: reason,
        });
    } catch {
        // Continue in mock mode
    }

    assignedToday++;
    overriddenToday++;
    showToast(
        `⚠️ Αλλαγή → ${overrideName} (αντί ${currentSuggestion.suggested_diagnostician_name})`,
        'warning'
    );

    pendingExams = pendingExams.filter(e => e.exam_id !== currentExamId);
    renderExamsTable(pendingExams);
    updateStats();
    closeModal();
}


// ══════════════════════════════════════════════
//  Stats
// ══════════════════════════════════════════════

function updateStats() {
    document.getElementById('stat-pending').textContent = pendingExams.length;
    document.getElementById('stat-assigned').textContent = assignedToday;
    document.getElementById('stat-overridden').textContent = overriddenToday;

    if (assignedToday > 0) {
        const accuracy = Math.round(((assignedToday - overriddenToday) / assignedToday) * 100);
        document.getElementById('stat-accuracy').textContent = `${accuracy}%`;
    }
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

function translateBodyPart(part) {
    const map = {
        'abdomen': 'Κοιλία',
        'chest': 'Θώρακας',
        'neuro': 'Εγκέφαλος',
        'msk': 'Μυοσκελετικό',
        'spine': 'Σπονδυλική Στήλη',
        'pelvis': 'Πύελος',
    };
    return map[part?.toLowerCase()] || part || '—';
}

function translateRule(rule) {
    const map = {
        'capacity': 'Χωρητικότητα',
        'skills': 'Εξειδίκευση',
        'partnership': 'Συνεργασία',
        'patient_history': 'Ιστορικό',
        'comment_exclusion': 'Σχόλια',
        'subcategory_load': 'Φόρτος',
    };
    return map[rule] || rule;
}


// ══════════════════════════════════════════════
//  Mock Data (for offline development)
// ══════════════════════════════════════════════

function getMockExams() {
    return [
        {
            exam_id: 'EX-2026-001',
            patient_id: 'PT-5432',
            patient_name: 'Γεώργιος Κ.',
            modality: 'MRI',
            body_part: 'abdomen',
            lab_id: 'LAB-KIF',
            lab_name: 'Κηφισιά',
            issuing_doctor_id: 'DR-101',
            issuing_doctor_name: 'Παπαδόπουλος Ν.',
            request_date: '2026-07-10',
            status: 'pending',
            comments: '',
            suggestion: null,
        },
        {
            exam_id: 'EX-2026-002',
            patient_id: 'PT-8821',
            patient_name: 'Μαρία Α.',
            modality: 'CT',
            body_part: 'chest',
            lab_id: 'LAB-MAR',
            lab_name: 'Μαρούσι',
            issuing_doctor_id: 'DR-205',
            issuing_doctor_name: 'Ιωάννου Ε.',
            request_date: '2026-07-10',
            status: 'pending',
            comments: 'Επείγον',
            suggestion: null,
        },
        {
            exam_id: 'EX-2026-003',
            patient_id: 'PT-1190',
            patient_name: 'Δημήτρης Λ.',
            modality: 'MRI',
            body_part: 'neuro',
            lab_id: 'LAB-KIF',
            lab_name: 'Κηφισιά',
            issuing_doctor_id: 'DR-101',
            issuing_doctor_name: 'Παπαδόπουλος Ν.',
            request_date: '2026-07-10',
            status: 'pending',
            comments: 'ΟΧΙ ΝΑΤΣΙΚΑ, ασθενής ζήτησε συγκεκριμένο ιατρό',
            suggestion: null,
        },
        {
            exam_id: 'EX-2026-004',
            patient_id: 'PT-3301',
            patient_name: 'Ελένη Π.',
            modality: 'CT',
            body_part: 'abdomen',
            lab_id: 'LAB-PAM',
            lab_name: 'Παμμακάριστος',
            issuing_doctor_id: 'DR-PAM-01',
            issuing_doctor_name: 'Παμμακάριστος (Εφημερία)',
            request_date: '2026-07-10',
            status: 'pending',
            comments: 'ΕΦΗΜΕΡΙΑ ΠΑΜΜΑΚΑΡΙΣΤΟΥ',
            suggestion: null,
        },
        {
            exam_id: 'EX-2026-005',
            patient_id: 'PT-6677',
            patient_name: 'Αντώνης Σ.',
            modality: 'MRI',
            body_part: 'msk',
            lab_id: 'LAB-GLY',
            lab_name: 'Γλυφάδα',
            issuing_doctor_id: 'DR-310',
            issuing_doctor_name: 'Βασιλείου Κ.',
            request_date: '2026-07-10',
            status: 'pending',
            comments: '',
            suggestion: null,
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

    // Simulate different suggestions based on exam
    const suggestions = {
        'EX-2026-001': {
            exam_id: examId,
            patient_id: 'PT-5432',
            exam_summary: `MRI Κοιλία — Dr. Παπαδόπουλος Ν. — Lab Κηφισιά`,
            suggested_diagnostician_id: 1,
            suggested_diagnostician_name: 'Νάτσικα Α.',
            confidence_score: 0.847,
            score_breakdown: [
                { rule: 'capacity', display_name: 'Χωρητικότητα', raw_score: 0.667, weight: 0.30, weighted_score: 0.200, explanation: 'Υπόλοιπο: 10/15 εξετάσεις' },
                { rule: 'skills', display_name: 'Εξειδίκευση', raw_score: 0.9, weight: 0.25, weighted_score: 0.225, explanation: 'Εξειδίκευση στο \'abdomen\' (MRI): 90%' },
                { rule: 'partnership', display_name: 'Συνεργασία Ιατρού', raw_score: 0.0, weight: 0.25, weighted_score: 0.0, explanation: 'Δεν υπάρχει συνεργασία με τον ιατρό' },
                { rule: 'patient_history', display_name: 'Ιστορικό Ασθενή', raw_score: 0.9, weight: 0.15, weighted_score: 0.135, explanation: 'Η Νάτσικα Α. έχει αξιολογήσει 3 παρόμοιες εξετάσεις αυτού του ασθενή' },
                { rule: 'subcategory_load', display_name: 'Ποινή Υποκατηγορίας', raw_score: 0.6, weight: 0.05, weighted_score: -0.030, explanation: 'Φόρτος κατηγορίας \'abdomen\': 3/5 (ήπιο όριο)' },
            ],
            alternatives: [
                { id: 3, name: 'Παπαδόπουλος Γ.', score: 0.612 },
                { id: 5, name: 'Δημητρίου Ε.', score: 0.498 },
                { id: 2, name: 'Κωνσταντίνου Β.', score: 0.321 },
            ],
            rules_fired: ['capacity', 'skills', 'patient_history'],
            solver_status: 'GREEDY',
            is_direct_assignment: false,
            direct_assignment_reason: '',
            pipeline_timestamp: new Date().toISOString(),
        },
        'EX-2026-002': {
            exam_id: examId,
            patient_id: 'PT-8821',
            exam_summary: `CT Θώρακας — Dr. Ιωάννου Ε. — Lab Μαρούσι`,
            suggested_diagnostician_id: 2,
            suggested_diagnostician_name: 'Κωνσταντίνου Β.',
            confidence_score: 0.921,
            score_breakdown: [
                { rule: 'capacity', display_name: 'Χωρητικότητα', raw_score: 0.75, weight: 0.30, weighted_score: 0.225, explanation: 'Υπόλοιπο: 9/12 εξετάσεις' },
                { rule: 'skills', display_name: 'Εξειδίκευση', raw_score: 0.95, weight: 0.25, weighted_score: 0.238, explanation: 'Εξειδίκευση στο \'chest\' (CT): 95%' },
                { rule: 'partnership', display_name: 'Συνεργασία Ιατρού', raw_score: 0.0, weight: 0.25, weighted_score: 0.0, explanation: 'Δεν υπάρχει συνεργασία' },
                { rule: 'patient_history', display_name: 'Ιστορικό Ασθενή', raw_score: 0.0, weight: 0.15, weighted_score: 0.0, explanation: 'Δεν υπάρχει ιστορικό' },
                { rule: 'subcategory_load', display_name: 'Ποινή Υποκατηγορίας', raw_score: 0.5, weight: 0.05, weighted_score: -0.025, explanation: 'Φόρτος κατηγορίας \'chest\': 2/4 (ήπιο όριο)' },
            ],
            alternatives: [
                { id: 4, name: 'Λιάκος Δ.', score: 0.689 },
                { id: 1, name: 'Νάτσικα Α.', score: 0.423 },
            ],
            rules_fired: ['capacity', 'skills'],
            solver_status: 'GREEDY',
            is_direct_assignment: false,
            direct_assignment_reason: '',
            pipeline_timestamp: new Date().toISOString(),
        },
        'EX-2026-003': {
            exam_id: examId,
            patient_id: 'PT-1190',
            exam_summary: `MRI Εγκέφαλος — Dr. Παπαδόπουλος Ν. — Lab Κηφισιά`,
            suggested_diagnostician_id: 3,
            suggested_diagnostician_name: 'Παπαδόπουλος Γ.',
            confidence_score: 0.783,
            score_breakdown: [
                { rule: 'capacity', display_name: 'Χωρητικότητα', raw_score: 0.556, weight: 0.30, weighted_score: 0.167, explanation: 'Υπόλοιπο: 10/18 εξετάσεις' },
                { rule: 'skills', display_name: 'Εξειδίκευση', raw_score: 0.95, weight: 0.25, weighted_score: 0.238, explanation: 'Εξειδίκευση στο \'neuro\' (MRI): 95%' },
                { rule: 'partnership', display_name: 'Συνεργασία Ιατρού', raw_score: 0.6, weight: 0.25, weighted_score: 0.150, explanation: 'Προτίμηση ιατρού Παπαδόπουλος Ν. → Παπαδόπουλος Γ.' },
                { rule: 'patient_history', display_name: 'Ιστορικό Ασθενή', raw_score: 0.6, weight: 0.15, weighted_score: 0.090, explanation: 'Ο Παπαδόπουλος Γ. έχει αξιολογήσει 2 παρόμοιες εξετάσεις' },
                { rule: 'subcategory_load', display_name: 'Ποινή Υποκατηγορίας', raw_score: 0.714, weight: 0.05, weighted_score: -0.036, explanation: 'Φόρτος κατηγορίας \'neuro\': 5/7 (ήπιο όριο)' },
            ],
            alternatives: [
                { id: 5, name: 'Δημητρίου Ε.', score: 0.412 },
                { id: 2, name: 'Κωνσταντίνου Β.', score: 0.287 },
            ],
            rules_fired: ['capacity', 'skills', 'partnership', 'patient_history'],
            solver_status: 'GREEDY',
            is_direct_assignment: false,
            direct_assignment_reason: '',
            pipeline_timestamp: new Date().toISOString(),
        },
    };

    // Default suggestion for any exam not in the map
    return suggestions[examId] || {
        exam_id: examId,
        patient_id: exam?.patient_id || '',
        exam_summary: `${exam?.modality || ''} ${translateBodyPart(exam?.body_part)} — ${exam?.lab_name || ''}`,
        suggested_diagnostician_id: 3,
        suggested_diagnostician_name: 'Παπαδόπουλος Γ.',
        confidence_score: 0.72,
        score_breakdown: [
            { rule: 'capacity', display_name: 'Χωρητικότητα', raw_score: 0.556, weight: 0.30, weighted_score: 0.167, explanation: 'Υπόλοιπο: 10/18 εξετάσεις' },
            { rule: 'skills', display_name: 'Εξειδίκευση', raw_score: 0.7, weight: 0.25, weighted_score: 0.175, explanation: 'Εξειδίκευση: 70%' },
            { rule: 'partnership', display_name: 'Συνεργασία Ιατρού', raw_score: 0.0, weight: 0.25, weighted_score: 0.0, explanation: 'Δεν υπάρχει συνεργασία' },
            { rule: 'patient_history', display_name: 'Ιστορικό Ασθενή', raw_score: 0.0, weight: 0.15, weighted_score: 0.0, explanation: 'Δεν υπάρχει ιστορικό' },
            { rule: 'subcategory_load', display_name: 'Ποινή Υποκατηγορίας', raw_score: 0.0, weight: 0.05, weighted_score: 0.0, explanation: 'Χωρίς φόρτο' },
        ],
        alternatives: [
            { id: 1, name: 'Νάτσικα Α.', score: 0.65 },
            { id: 5, name: 'Δημητρίου Ε.', score: 0.58 },
        ],
        rules_fired: ['capacity', 'skills'],
        solver_status: 'GREEDY',
        is_direct_assignment: false,
        direct_assignment_reason: '',
        pipeline_timestamp: new Date().toISOString(),
    };
}
