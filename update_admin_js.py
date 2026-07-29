import codecs
code = '''

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
        if (u.role !== 'super_admin' && u.role !== 'it_support') {
            actions += `<button class="btn btn-secondary btn-sm" onclick="deleteAdminUser(${u.id})">Διαγραφή</button>`;
        }
        if (u.role === 'super_admin' || u.role === 'admin') {
            actions += ` <button class="btn btn-secondary btn-sm" onclick="resetAdminUser(${u.id})">Επαναφορά (admin/admin1234)</button>`;
        }
            
        tr.innerHTML = `
            <td>${u.username}</td>
            <td><span class="admin-badge">${u.role}</span></td>
            <td>${u.is_active ? '<span style="color:var(--success-color);">Ενεργός</span>' : '<span style="color:var(--error-color);">Ανενεργός</span>'}</td>
            <td>${actions}</td>
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
'''
with codecs.open('frontend/js/admin.js', 'a', encoding='utf-8') as f:
    f.write(code)
print('Appended JS')
