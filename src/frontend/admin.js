document.addEventListener('DOMContentLoaded', () => {
    const loginScreen = document.getElementById('adminLoginScreen');
    const dashboard = document.getElementById('adminDashboard');
    const loginForm = document.getElementById('adminLoginForm');
    const loginMsg = document.getElementById('adminLoginMsg');
    const logoutBtn = document.getElementById('adminLogoutBtn');
    const refreshBtn = document.getElementById('refreshBtn');
    const searchInput = document.getElementById('userSearch');
    const userCount = document.getElementById('userCount');
    const tableBody = document.getElementById('userTableBody');
    const emptyState = document.getElementById('userEmpty');
    const notice = document.getElementById('adminNotice');

    const userDialog = document.getElementById('userDialog');
    const resetForm = document.getElementById('resetPasswordForm');
    const newPasswordInput = document.getElementById('newPassword');
    const resetMsg = document.getElementById('resetMsg');
    const resetBtn = document.getElementById('resetPasswordBtn');
    const closeUserDialogBtn = document.getElementById('closeUserDialogBtn');
    const openDeleteUserBtn = document.getElementById('openDeleteUserBtn');

    const deleteDialog = document.getElementById('deleteUserDialog');
    const deleteForm = document.getElementById('deleteUserForm');
    const deleteConfirmInput = document.getElementById('deleteUserConfirm');
    const deleteMsg = document.getElementById('deleteUserMsg');
    const confirmDeleteBtn = document.getElementById('confirmDeleteUserBtn');
    const cancelDeleteBtn = document.getElementById('cancelDeleteUserBtn');

    let users = [];
    let selectedUser = null;
    let noticeTimer = null;

    function showLogin(message = '') {
        dashboard.hidden = true;
        loginScreen.hidden = false;
        loginMsg.textContent = message;
        notice.hidden = true;
        if (userDialog.open) userDialog.close();
        if (deleteDialog.open) deleteDialog.close();
    }

    AdminLearning.init({ onUnauthorized: () => showLogin('登入已逾時，請重新登入') });

    const tabs = document.querySelectorAll('.admin-tab');

    function showTab(panelId, { load = true } = {}) {
        tabs.forEach((tab) => {
            const active = tab.dataset.panel === panelId;
            tab.classList.toggle('active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
            document.getElementById(tab.dataset.panel).hidden = !active;
        });
        if (!load) return;
        if (panelId === 'learningPanel') AdminLearning.showOverview();
        if (panelId === 'reviewsPanel') AdminLearning.showReviews();
    }

    tabs.forEach((tab) => tab.addEventListener('click', () => showTab(tab.dataset.panel)));

    document.getElementById('openLearningBtn').addEventListener('click', () => {
        if (!selectedUser) return;
        userDialog.close();
        showTab('learningPanel', { load: false });
        AdminLearning.showStudent(selectedUser.username);
    });

    function showNotice(text) {
        notice.textContent = text;
        notice.hidden = false;
        clearTimeout(noticeTimer);
        noticeTimer = setTimeout(() => { notice.hidden = true; }, 8000);
    }

    function showDashboard() {
        loginScreen.hidden = true;
        dashboard.hidden = false;
        showTab('usersPanel');
        loadUsers();
    }

    function formatTime(value) {
        if (!value) return '—';
        const date = new Date(value.replace(' ', 'T') + 'Z');
        if (Number.isNaN(date.getTime())) return value;
        return date.toLocaleString('zh-TW', {
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit', hour12: false,
        });
    }

    async function loadUsers() {
        userCount.textContent = '載入中…';
        try {
            const res = await fetch('/api/admin/users');
            if (res.status === 401) {
                showLogin('登入已逾時，請重新登入');
                return;
            }
            const data = await res.json();
            users = data.users || [];
            renderUsers();
        } catch (err) {
            console.error('載入帳號列表失敗:', err);
            userCount.textContent = '載入失敗，請按「重新整理」再試一次';
        }
    }

    function renderUsers() {
        const keyword = searchInput.value.trim().toLowerCase();
        const shown = keyword ? users.filter((u) => u.username.toLowerCase().includes(keyword)) : users;

        userCount.textContent = keyword
            ? `共 ${users.length} 個帳號，符合搜尋的有 ${shown.length} 個`
            : `共 ${users.length} 個帳號`;

        tableBody.replaceChildren();
        shown.forEach((user) => {
            const row = document.createElement('tr');

            const nameCell = document.createElement('td');
            const nameWrap = document.createElement('span');
            nameWrap.className = 'user-cell';
            const avatar = document.createElement('span');
            avatar.className = 'user-avatar';
            avatar.textContent = user.username.charAt(0);
            const name = document.createElement('span');
            name.className = 'user-name';
            name.textContent = user.username;
            nameWrap.append(avatar, name);
            nameCell.appendChild(nameWrap);

            const createdCell = document.createElement('td');
            createdCell.textContent = formatTime(user.created_at);

            const countCell = document.createElement('td');
            countCell.className = 'num';
            countCell.textContent = user.conversation_count;

            const activeCell = document.createElement('td');
            activeCell.textContent = formatTime(user.last_active);

            const actionCell = document.createElement('td');
            actionCell.className = 'action';
            const detailBtn = document.createElement('button');
            detailBtn.type = 'button';
            detailBtn.className = 'btn-link';
            detailBtn.textContent = '詳細資訊';
            actionCell.appendChild(detailBtn);

            row.append(nameCell, createdCell, countCell, activeCell, actionCell);
            row.addEventListener('click', () => openUserDialog(user));
            tableBody.appendChild(row);
        });

        emptyState.hidden = shown.length > 0;
        emptyState.textContent = users.length === 0 ? '目前還沒有任何註冊帳號' : '沒有符合搜尋的帳號';
    }

    function openUserDialog(user) {
        selectedUser = user;
        document.getElementById('detailUsername').textContent = user.username;
        document.getElementById('detailCreated').textContent = formatTime(user.created_at);
        document.getElementById('detailCounts').textContent =
            `${user.conversation_count} 條對話串，共 ${user.message_count} 則訊息`;
        document.getElementById('detailActive').textContent = formatTime(user.last_active);
        resetForm.reset();
        resetMsg.textContent = '';
        resetMsg.classList.remove('success');
        userDialog.showModal();
    }

    closeUserDialogBtn.addEventListener('click', () => userDialog.close());

    [userDialog, deleteDialog].forEach((dialog) => {
        dialog.addEventListener('click', (e) => {
            if (e.target === dialog) dialog.close();
        });
    });

    function openDeleteDialog(user) {
        deleteForm.reset();
        deleteMsg.textContent = '';
        document.getElementById('deleteUserAvatar').textContent = user.username.charAt(0);
        document.getElementById('deleteUserName').textContent = user.username;
        document.getElementById('deleteUserConfirmName').textContent = user.username;
        document.getElementById('deleteUserSummary').textContent =
            `這個帳號的 ${user.conversation_count} 條對話串、${user.message_count} 則訊息，` +
            '以及老師畫的圖都會一起永久刪除，所有裝置也都會被登出。';
        confirmDeleteBtn.disabled = true;
        deleteDialog.showModal();
        deleteConfirmInput.focus();
    }

    function typedNameMatches() {
        return selectedUser !== null && deleteConfirmInput.value.trim() === selectedUser.username;
    }

    openDeleteUserBtn.addEventListener('click', () => {
        if (!selectedUser) return;
        userDialog.close();
        openDeleteDialog(selectedUser);
    });

    cancelDeleteBtn.addEventListener('click', () => deleteDialog.close());

    deleteConfirmInput.addEventListener('input', () => {
        confirmDeleteBtn.disabled = !typedNameMatches();
    });

    deleteForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!typedNameMatches()) return;
        const username = selectedUser.username;
        deleteMsg.textContent = '';
        confirmDeleteBtn.disabled = true;
        try {
            const res = await fetch('/api/admin/delete-user', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username }),
            });
            if (res.status === 401) {
                showLogin('登入已逾時，請重新登入');
                return;
            }
            const data = await res.json().catch(() => ({}));
            if (res.ok || res.status === 404) {

                deleteDialog.close();
                selectedUser = null;
                showNotice(res.ok ? `已刪除帳號「${username}」，連同對話紀錄和圖片。` : data.error || '找不到這個帳號');
                loadUsers();
            } else {
                deleteMsg.textContent = data.error || '刪除失敗，請再試一次';
                confirmDeleteBtn.disabled = false;
            }
        } catch (err) {
            console.error('刪除帳號失敗:', err);
            deleteMsg.textContent = '網路好像怪怪的，請再試一次';
            confirmDeleteBtn.disabled = false;
        }
    });

    resetForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!selectedUser) return;
        resetMsg.textContent = '';
        resetMsg.classList.remove('success');
        resetBtn.disabled = true;
        try {
            const res = await fetch('/api/admin/reset-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: selectedUser.username, new_password: newPasswordInput.value }),
            });
            if (res.status === 401) {
                showLogin('登入已逾時，請重新登入');
                return;
            }
            const data = await res.json().catch(() => ({}));
            if (res.ok) {
                resetMsg.classList.add('success');
                resetMsg.textContent = `已重設。請把新密碼告訴「${selectedUser.username}」，他所有的裝置都已被登出。`;
                resetForm.reset();
            } else {
                resetMsg.textContent = data.error || '重設失敗，請再試一次';
            }
        } catch (err) {
            console.error('重設密碼失敗:', err);
            resetMsg.textContent = '網路好像怪怪的，請再試一次';
        } finally {
            resetBtn.disabled = false;
        }
    });

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        loginMsg.textContent = '';
        try {
            const res = await fetch('/api/admin/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: document.getElementById('adminUsername').value.trim(),
                    password: document.getElementById('adminPassword').value,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (res.ok) {
                loginForm.reset();
                showDashboard();
            } else {
                loginMsg.textContent = data.error || '登入失敗，請再試一次';
            }
        } catch (err) {
            console.error('管理員登入失敗:', err);
            loginMsg.textContent = '網路好像怪怪的，請再試一次';
        }
    });

    logoutBtn.addEventListener('click', async () => {
        try {
            await fetch('/api/admin/logout', { method: 'POST' });
        } catch (err) {
            console.error('管理員登出失敗:', err);
        }
        showLogin();
    });

    refreshBtn.addEventListener('click', loadUsers);
    searchInput.addEventListener('input', renderUsers);

    (async () => {
        try {
            const res = await fetch('/api/admin/me');
            const data = await res.json();
            if (data.admin) {
                showDashboard();
            } else {
                showLogin();
            }
        } catch (err) {
            console.error('確認管理員登入狀態失敗:', err);
            showLogin();
        }
    })();
});
