document.addEventListener('DOMContentLoaded', () => {
    const chatHistory = document.getElementById('chatHistory');
    const userInput = document.getElementById('userInput');
    const sendBtn = document.getElementById('sendBtn');

    const imageUpload = document.getElementById('imageUpload');
    const imagePreviewContainer = document.getElementById('imagePreviewContainer');
    const imagePreview = document.getElementById('imagePreview');
    const removeImageBtn = document.getElementById('removeImageBtn');

    const toggleKeyboardBtn = document.getElementById('toggleKeyboardBtn');
    const mathKeyboard = document.getElementById('mathKeyboard');
    const mathKeys = document.querySelectorAll('.math-key');

    const voiceInputBtn = document.getElementById('voiceInputBtn');
    let isListening = false;
    let recognition = null;
    let speechBaseText = '';

    let currentImageBase64 = null;
    let currentImageMimeType = null;

    const authScreen = document.getElementById('authScreen');
    const appContainer = document.getElementById('appContainer');
    const authTabs = document.querySelectorAll('.auth-tab');
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const loginMsg = document.getElementById('loginMsg');
    const registerMsg = document.getElementById('registerMsg');
    const currentUsernameEl = document.getElementById('currentUsername');
    const logoutBtn = document.getElementById('logoutBtn');

    const newChatBtn = document.getElementById('newChatBtn');
    const historyList = document.getElementById('historyList');
    let currentConversationId = null;
    let currentUsername = '';

    let conversationFromUrl = new URLSearchParams(window.location.search).get('c');

    let pendingReply = null;
    let pendingCancel = null;
    let viewVersion = 0;

    const sidebarToggleBtn = document.getElementById('sidebarToggleBtn');
    const mobileMenuBtn = document.getElementById('mobileMenuBtn');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');
    const userAvatar = document.getElementById('userAvatar');
    const mobileQuery = window.matchMedia('(max-width: 768px)');

    function readPref(key, fallback) {
        try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
    }
    function writePref(key, value) {
        try { localStorage.setItem(key, value); } catch { }
    }

    if (readPref('sidebar_collapsed', '0') === '1') {
        appContainer.classList.add('sidebar-collapsed');
    }

    function closeMobileSidebar() {
        appContainer.classList.remove('sidebar-open');
    }

    sidebarToggleBtn.addEventListener('click', () => {
        if (mobileQuery.matches) {
            closeMobileSidebar();
            return;
        }
        const collapsed = appContainer.classList.toggle('sidebar-collapsed');
        writePref('sidebar_collapsed', collapsed ? '1' : '0');
    });
    mobileMenuBtn.addEventListener('click', () => appContainer.classList.add('sidebar-open'));
    sidebarBackdrop.addEventListener('click', closeMobileSidebar);

    function showAuthScreen() {
        appContainer.hidden = true;
        authScreen.hidden = false;
        currentConversationId = null;
        viewVersion++;

        if (pendingReply) {
            pendingReply.controller.abort();
            pendingReply = null;
            setWaiting(false);
        }
    }

    function showChatScreen(username) {
        authScreen.hidden = true;
        appContainer.hidden = false;
        currentUsername = username || '';
        if (currentUsernameEl) {
            currentUsernameEl.textContent = currentUsername;
        }
        if (userAvatar) {
            userAvatar.textContent = currentUsername ? currentUsername.charAt(0) : '?';
        }
        userInput.focus();

        currentConversationId = null;
        renderMessages([]);
        loadConversationList(true);
    }

    const SUGGESTIONS = [
        { text: '什麼是畢氏定理？可以舉個例子嗎？', icon: 'a²' },
        { text: '幫我畫一個邊長 3、4、5 的直角三角形', icon: '△' },
        { text: '質因數分解要怎麼做？', icon: '×' },
        { text: '我不會解 2x + 3 = 11，可以一步一步帶我想嗎？', icon: 'x=' },
    ];

    function renderWelcome() {
        const welcome = document.createElement('div');
        welcome.className = 'welcome';

        const title = document.createElement('h1');
        title.className = 'welcome-title';
        const hello = document.createElement('span');
        hello.className = 'gradient-text';
        hello.textContent = currentUsername ? `嗨，${currentUsername}` : '嗨，你好';
        title.appendChild(hello);

        const subtitle = document.createElement('p');
        subtitle.className = 'welcome-subtitle';
        subtitle.textContent = '今天想一起解什麼數學題？';

        const grid = document.createElement('div');
        grid.className = 'suggestions';
        SUGGESTIONS.forEach((s) => {
            const card = document.createElement('button');
            card.type = 'button';
            card.className = 'suggestion-card';
            const text = document.createElement('span');
            text.textContent = s.text;
            const icon = document.createElement('span');
            icon.className = 'suggestion-icon';
            icon.textContent = s.icon;
            card.append(text, icon);
            card.addEventListener('click', () => {
                if (pendingReply) return;
                userInput.value = s.text;
                lastValue = userInput.value;
                handleSend();
            });
            grid.appendChild(card);
        });

        welcome.append(title, subtitle, grid);
        chatHistory.appendChild(welcome);
    }

    function renderMessages(messages) {
        chatHistory.innerHTML = '';
        if (!messages || messages.length === 0) {
            renderWelcome();
            return;
        }
        messages.forEach((m) => {
            appendMessage(m.role === 'user' ? 'student' : 'teacher', m.text);
        });
    }

    async function loadConversationList(selectMostRecentIfNone) {
        try {
            const res = await fetch('/api/conversations');
            if (!res.ok) return;
            const data = await res.json();
            const conversations = data.conversations || [];
            if (selectMostRecentIfNone && !currentConversationId && conversations.length > 0) {

                const fromUrl = conversations.find((c) => c.id === conversationFromUrl);
                if (conversationFromUrl) {
                    conversationFromUrl = null;
                    window.history.replaceState(null, '', '/');
                }
                await selectConversation((fromUrl || conversations[0]).id);
                return;
            }
            renderHistoryList(conversations);
        } catch (err) {
            console.error('載入對話清單失敗:', err);
        }
    }

    function renderHistoryList(conversations) {
        if (!historyList) return;
        historyList.innerHTML = '';
        if (conversations.length === 0) {
            const empty = document.createElement('p');
            empty.className = 'history-empty';
            empty.textContent = '還沒有對話紀錄';
            historyList.appendChild(empty);
            return;
        }
        conversations.forEach((conv) => {
            const item = document.createElement('div');
            item.className = 'history-item' + (conv.id === currentConversationId ? ' active' : '');

            const title = document.createElement('span');
            title.className = 'history-item-title';
            title.textContent = conv.title || '新的對話';
            item.appendChild(title);

            const startEditingTitle = () => {
                const input = document.createElement('input');
                input.type = 'text';
                input.className = 'history-item-title-input';
                input.value = conv.title || '新的對話';
                item.replaceChild(input, title);
                input.focus();
                input.select();

                let finished = false;
                const finishEditing = async (shouldSave) => {
                    if (finished) return;
                    finished = true;
                    const newTitle = input.value.trim();
                    if (shouldSave && newTitle && newTitle !== conv.title) {
                        try {
                            await fetch(`/api/conversations/${conv.id}`, {
                                method: 'PATCH',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ title: newTitle }),
                            });
                        } catch (err) {
                            console.error('更新對話名稱失敗:', err);
                        }
                    }
                    loadConversationList(false);
                };
                input.addEventListener('blur', () => finishEditing(true));
                input.addEventListener('keydown', (e) => {
                    e.stopPropagation();
                    if (e.key === 'Enter') {
                        input.blur();
                    } else if (e.key === 'Escape') {
                        finished = true;
                        loadConversationList(false);
                    }
                });
                input.addEventListener('click', (e) => e.stopPropagation());
            };

            const editBtn = document.createElement('button');
            editBtn.className = 'history-item-edit';
            editBtn.type = 'button';
            editBtn.title = '編輯對話名稱';
            editBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
            editBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                startEditingTitle();
            });
            item.appendChild(editBtn);

            const delBtn = document.createElement('button');
            delBtn.className = 'history-item-delete';
            delBtn.type = 'button';
            delBtn.title = '刪除這則對話';
            delBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>';
            delBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                if (!confirm(`確定要刪除「${conv.title}」這則對話嗎？刪除後無法復原。`)) return;
                try {
                    await fetch(`/api/conversations/${conv.id}`, { method: 'DELETE' });
                } catch (err) {
                    console.error('刪除對話失敗:', err);
                }
                if (currentConversationId === conv.id) {
                    startNewChat();
                } else {
                    loadConversationList(false);
                }
            });
            item.appendChild(delBtn);

            item.addEventListener('click', () => selectConversation(conv.id));
            historyList.appendChild(item);
        });
    }

    async function selectConversation(conversationId) {
        currentConversationId = conversationId;
        const view = ++viewVersion;
        closeMobileSidebar();
        try {
            const res = await fetch(`/api/conversations/${conversationId}/messages`);
            if (res.ok) {
                const data = await res.json();
                if (view !== viewVersion) return;
                renderMessages(data.messages || []);
                reattachPendingReply(conversationId);
            }
        } catch (err) {
            console.error('讀取對話內容失敗:', err);
        }
        loadConversationList(false);
    }

    function reattachPendingReply(conversationId) {
        if (!pendingReply || pendingReply.conversationId !== conversationId) return;
        appendMessage('student', pendingReply.text, false, false, pendingReply.imageUrl);
        pendingReply.studentMsg = chatHistory.lastElementChild;
        showTypingIndicator();
        pendingReply.view = viewVersion;
    }

    function startNewChat() {
        currentConversationId = null;
        viewVersion++;
        closeMobileSidebar();
        renderMessages([]);
        loadConversationList(false);
    }

    if (newChatBtn) {
        newChatBtn.addEventListener('click', () => startNewChat());
    }

    authTabs.forEach((tab) => {
        tab.addEventListener('click', () => {
            authTabs.forEach((t) => t.classList.remove('active'));
            tab.classList.add('active');
            const isLogin = tab.dataset.tab === 'login';
            loginForm.hidden = !isLogin;
            registerForm.hidden = isLogin;
            loginMsg.textContent = '';
            registerMsg.textContent = '';
        });
    });

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        loginMsg.textContent = '';
        loginMsg.classList.remove('success');
        const username = document.getElementById('loginUsername').value.trim();
        const password = document.getElementById('loginPassword').value;
        try {
            const res = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            const data = await res.json();
            if (res.ok) {
                showChatScreen(data.username);
            } else {
                loginMsg.textContent = data.error || '登入失敗，請再試一次';
            }
        } catch (err) {
            console.error('Login error:', err);
            loginMsg.textContent = '網路好像怪怪的，請再試一次';
        }
    });

    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        registerMsg.textContent = '';
        const username = document.getElementById('registerUsername').value.trim();
        const password = document.getElementById('registerPassword').value;
        try {
            const res = await fetch('/api/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            const data = await res.json();
            if (res.ok) {
                registerMsg.classList.add('success');
                registerMsg.textContent = '註冊成功！請切換到「登入」分頁登入';
                registerForm.reset();
            } else {
                registerMsg.classList.remove('success');
                registerMsg.textContent = data.error || '註冊失敗，請再試一次';
            }
        } catch (err) {
            console.error('Register error:', err);
            registerMsg.textContent = '網路好像怪怪的，請再試一次';
        }
    });

    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            try {
                await fetch('/api/logout', { method: 'POST' });
            } catch (err) {
                console.error('Logout error:', err);
            }
            showAuthScreen();
        });
    }

    const accountBtn = document.getElementById('accountBtn');
    const accountDialog = document.getElementById('accountDialog');
    const accountDialogName = document.getElementById('accountDialogName');
    const accountDialogAvatar = document.getElementById('accountDialogAvatar');
    const deleteAccountForm = document.getElementById('deleteAccountForm');
    const deleteAccountPassword = document.getElementById('deleteAccountPassword');
    const deleteAccountMsg = document.getElementById('deleteAccountMsg');
    const confirmDeleteAccountBtn = document.getElementById('confirmDeleteAccountBtn');
    const closeAccountDialogBtn = document.getElementById('closeAccountDialogBtn');

    accountBtn.addEventListener('click', () => {
        closeMobileSidebar();
        accountDialogName.textContent = currentUsername;
        accountDialogAvatar.textContent = currentUsername ? currentUsername.charAt(0) : '?';
        deleteAccountForm.reset();
        deleteAccountMsg.textContent = '';
        accountDialog.showModal();
    });

    closeAccountDialogBtn.addEventListener('click', () => accountDialog.close());

    accountDialog.addEventListener('click', (e) => {
        if (e.target === accountDialog) accountDialog.close();
    });

    deleteAccountForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        deleteAccountMsg.textContent = '';
        confirmDeleteAccountBtn.disabled = true;
        try {
            const res = await fetch('/api/account/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password: deleteAccountPassword.value }),
            });
            if (res.ok) {
                accountDialog.close();
                loginForm.reset();
                showAuthScreen();
                loginMsg.classList.add('success');
                loginMsg.textContent = '帳號已刪除，謝謝你的使用！';
            } else if (res.status === 401) {

                accountDialog.close();
                showAuthScreen();
            } else {
                const data = await res.json().catch(() => ({}));
                deleteAccountMsg.textContent = data.error || '刪除失敗，請再試一次';
                deleteAccountPassword.select();
            }
        } catch (err) {
            console.error('Delete account error:', err);
            deleteAccountMsg.textContent = '網路好像怪怪的，請再試一次';
        } finally {
            confirmDeleteAccountBtn.disabled = false;
        }
    });

    async function checkAuthOnLoad() {
        try {
            const res = await fetch('/api/me');
            const data = await res.json();
            if (data.username) {
                showChatScreen(data.username);
            } else {
                showAuthScreen();
            }
        } catch (err) {
            console.error('Auth check error:', err);
            showAuthScreen();
        }
    }

    function escapeHtml(str) {
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function formatInline(line) {
        return line

            .replace(/!\[([^\]]*)\]\(((?:\/|data:image\/)[^)\s]+)\)/g, '<img src="$2" alt="$1" />')
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')

            .replace(/(?:[A-Za-z]̅)+/g, run => `<span class="seg">${run.replace(/̅/g, '')}</span>`);
    }

    function formatText(text) {
        if (!text) return '';
        const lines = escapeHtml(text).split('\n');
        const html = [];
        let listType = null;
        let paragraph = [];

        const flushParagraph = () => {
            if (paragraph.length) {
                html.push(`<p>${paragraph.map(formatInline).join('<br>')}</p>`);
                paragraph = [];
            }
        };
        const closeList = () => {
            if (listType) {
                html.push(`</${listType}>`);
                listType = null;
            }
        };

        lines.forEach((raw) => {
            const line = raw.trimEnd();
            const heading = line.match(/^#{1,4}\s+(.*)$/);
            const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
            const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);

            if (!line.trim()) {
                flushParagraph();
                closeList();
            } else if (heading) {
                flushParagraph();
                closeList();
                html.push(`<h3>${formatInline(heading[1])}</h3>`);
            } else if (bullet || numbered) {
                flushParagraph();
                const type = bullet ? 'ul' : 'ol';
                if (listType !== type) {
                    closeList();
                    html.push(`<${type}>`);
                    listType = type;
                }
                html.push(`<li>${formatInline((bullet || numbered)[1])}</li>`);
            } else {
                closeList();
                paragraph.push(line);
            }
        });
        flushParagraph();
        closeList();
        return html.join('');
    }

    function appendMessage(sender, text, isHtml = false, usedTool = false, imageUrl = null) {

        const welcome = chatHistory.querySelector('.welcome');
        if (welcome) welcome.remove();

        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${sender}`;

        const avatar = document.createElement('div');

        avatar.className = sender === 'teacher' ? 'avatar logo-mark' : 'avatar';
        avatar.textContent = sender === 'teacher' ? 'π' : '';

        const bubble = document.createElement('div');
        bubble.className = 'bubble';

        let badgeHtml = '';
        if (usedTool && sender === 'teacher') {
            badgeHtml = '<div class="ref-badge">📚 已查閱講義</div>';
        }

        let imageHtml = '';
        if (imageUrl) {
            imageHtml = `<img src="${imageUrl}" alt="上傳的圖片" /><br>`;
        }

        let contentHtml = isHtml ? text : formatText(text);
        bubble.innerHTML = badgeHtml + imageHtml + contentHtml;

        msgDiv.appendChild(avatar);
        msgDiv.appendChild(bubble);
        chatHistory.appendChild(msgDiv);

        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function showTypingIndicator() {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message teacher typing-msg';
        msgDiv.id = 'typingIndicator';

        const avatar = document.createElement('div');
        avatar.className = 'avatar logo-mark';
        avatar.textContent = 'π';

        const bubble = document.createElement('div');
        bubble.className = 'bubble';
        bubble.innerHTML = `
            <div class="typing-indicator">
                <div class="dot"></div>
                <div class="dot"></div>
                <div class="dot"></div>
                <span class="typing-label">老師正在想怎麼引導你…</span>
            </div>
        `;

        msgDiv.appendChild(avatar);
        msgDiv.appendChild(bubble);
        chatHistory.appendChild(msgDiv);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function removeTypingIndicator() {
        const indicator = document.getElementById('typingIndicator');
        if (indicator) {
            indicator.remove();
        }
    }

    function newRequestId() {
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    }

    async function handleSend() {

        if (pendingReply) return;
        if (isListening) {
            stopListening(true);
        }

        const typed = userInput.value.trim();

        if (!typed && !currentImageBase64) return;

        const turn = {
            controller: new AbortController(),
            requestId: newRequestId(),
            conversationId: currentConversationId,
            view: viewVersion,
            text: typed || '請看這張圖片',
            typed,
            imageBase64: currentImageBase64,
            mimeType: currentImageMimeType,
            imageUrl: currentImageBase64 ? `data:${currentImageMimeType};base64,${currentImageBase64}` : null,
        };
        pendingReply = turn;
        setWaiting(true);

        userInput.value = '';
        lastValue = '';
        clearImagePreview();
        appendMessage('student', turn.text, false, false, turn.imageUrl);
        turn.studentMsg = chatHistory.lastElementChild;
        showTypingIndicator();

        try {

            if (pendingCancel) await pendingCancel;
            if (turn.controller.signal.aborted) return;

            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    message: turn.text,
                    image_data: turn.imageBase64,
                    mime_type: turn.mimeType,
                    conversation_id: turn.conversationId,
                    request_id: turn.requestId,
                }),
                signal: turn.controller.signal,
            });

            if (response.status === 401) {

                removeTypingIndicator();
                showAuthScreen();
                return;
            }

            const data = await response.json();

            if (turn.view !== viewVersion) {

                if (data.conversation_id && data.conversation_id === currentConversationId) {
                    selectConversation(currentConversationId);
                } else {
                    loadConversationList(false);
                }
                return;
            }
            removeTypingIndicator();
            appendMessage('teacher', data.reply, false, data.used_tool);

            if (data.conversation_id) {
                currentConversationId = data.conversation_id;
            }
            loadConversationList(false);
        } catch (error) {
            if (turn.controller.signal.aborted) return;
            console.error('API Error:', error);
            if (turn.view === viewVersion) {
                removeTypingIndicator();
                appendMessage('teacher', '抱歉！網路好像怪怪的，可以再問一次嗎？😵');
            }
        } finally {
            if (pendingReply === turn) {
                pendingReply = null;
                setWaiting(false);
                if (turn.view === viewVersion) userInput.focus();
            }
        }
    }

    function stopReply() {
        const turn = pendingReply;
        if (!turn) return;
        pendingReply = null;
        turn.controller.abort();
        setWaiting(false);

        const cancel = fetch('/api/chat/cancel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ request_id: turn.requestId }),
            keepalive: true,
        })
            .catch((err) => console.error('停止這一輪失敗:', err))
            .finally(() => {
                if (pendingCancel === cancel) pendingCancel = null;
                loadConversationList(false);
            });
        pendingCancel = cancel;

        if (turn.view !== viewVersion) return;
        removeTypingIndicator();
        turn.studentMsg.remove();
        if (!chatHistory.querySelector('.message')) renderMessages([]);

        if (!userInput.value.trim() && !currentImageBase64) {
            userInput.value = turn.typed;
            lastValue = userInput.value;
            if (turn.imageBase64) setAttachedImage(turn.imageBase64, turn.mimeType);
        }
        updateSendState();
        userInput.focus();
    }

    function setWaiting(waiting) {
        sendBtn.classList.toggle('stop', waiting);
        sendBtn.title = waiting ? '停止回覆' : '傳送';
        sendBtn.setAttribute('aria-label', sendBtn.title);
    }

    function updateSendState() {
        sendBtn.classList.toggle('ready', !!userInput.value.trim() || !!currentImageBase64);
    }

    function setAttachedImage(base64, mimeType) {
        currentImageBase64 = base64;
        currentImageMimeType = mimeType;
        imagePreview.src = `data:${mimeType};base64,${base64}`;
        imagePreviewContainer.style.display = 'inline-block';
        updateSendState();
    }

    function clearImagePreview() {
        currentImageBase64 = null;
        currentImageMimeType = null;
        imageUpload.value = '';
        imagePreview.src = '';
        imagePreviewContainer.style.display = 'none';
        updateSendState();
    }

    imageUpload.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = (e) => {

                setAttachedImage(e.target.result.split(',')[1], file.type);
            };
            reader.readAsDataURL(file);
        }
    });

    removeImageBtn.addEventListener('click', clearImagePreview);

    const superscriptMap = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
        '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
        '-': '⁻', '+': '⁺',
        '０': '⁰', '１': '¹', '２': '²', '３': '³', '４': '⁴',
        '５': '⁵', '６': '⁶', '７': '⁷', '８': '⁸', '９': '⁹',
        '－': '⁻', '＋': '⁺'
    };
    let isPowerMode = false;
    let lastValue = userInput.value;
    let isComposing = false;
    const powerModeBtn = document.getElementById('powerModeBtn');

    if (powerModeBtn) {
        powerModeBtn.addEventListener('mousedown', (e) => {
            e.preventDefault();
            isPowerMode = !isPowerMode;
            if (isPowerMode) {
                powerModeBtn.classList.add('active');
            } else {
                powerModeBtn.classList.remove('active');
            }
            userInput.focus();
        });
    }

    sendBtn.addEventListener('click', () => (pendingReply ? stopReply() : handleSend()));
    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.isComposing) {
            handleSend();
            e.preventDefault();
        }
    });

    function toSuperscript(str) {
        let res = '';
        for (let i = 0; i < str.length; i++) {
            const char = str[i];
            res += superscriptMap[char] || char;
        }
        return res;
    }

    function handlePowerModeConversion() {
        const curValue = userInput.value;
        if (!isPowerMode) {
            lastValue = curValue;
            return;
        }

        if (curValue === lastValue) {
            return;
        }

        let start = 0;
        while (start < lastValue.length && start < curValue.length && lastValue[start] === curValue[start]) {
            start++;
        }

        let endLast = lastValue.length - 1;
        let endCur = curValue.length - 1;
        while (endLast >= start && endCur >= start && lastValue[endLast] === curValue[endCur]) {
            endLast--;
            endCur--;
        }

        const insertedText = curValue.substring(start, endCur + 1);

        let hasSuperscriptTarget = false;
        for (let i = 0; i < insertedText.length; i++) {
            if (superscriptMap[insertedText[i]]) {
                hasSuperscriptTarget = true;
                break;
            }
        }

        if (hasSuperscriptTarget) {
            const convertedInserted = toSuperscript(insertedText);
            const prefix = curValue.substring(0, start);
            const suffix = curValue.substring(endCur + 1);
            const newValue = prefix + convertedInserted + suffix;

            const newCursorPos = start + convertedInserted.length;
            userInput.value = newValue;
            userInput.selectionStart = newCursorPos;
            userInput.selectionEnd = newCursorPos;
            lastValue = newValue;
        } else {
            lastValue = curValue;
        }
    }

    userInput.addEventListener('compositionstart', () => {
        isComposing = true;
    });

    userInput.addEventListener('compositionend', () => {
        isComposing = false;
        handlePowerModeConversion();
    });

    userInput.addEventListener('input', (e) => {
        updateSendState();
        if (isComposing || e.isComposing) {
            return;
        }
        handlePowerModeConversion();
    });

    toggleKeyboardBtn.addEventListener('mousedown', (e) => {
        e.preventDefault();
        const isHidden = window.getComputedStyle(mathKeyboard).display === 'none';
        mathKeyboard.style.display = isHidden ? 'grid' : 'none';
        toggleKeyboardBtn.classList.toggle('active', isHidden);
        userInput.focus();
    });

    mathKeys.forEach(key => {
        key.addEventListener('mousedown', (e) => {
            e.preventDefault();
            const symbol = key.getAttribute('data-symbol');
            if (!symbol) return;

            const startPos = userInput.selectionStart || userInput.value.length;
            const endPos = userInput.selectionEnd || userInput.value.length;

            userInput.value = userInput.value.substring(0, startPos) + symbol + userInput.value.substring(endPos, userInput.value.length);

            userInput.selectionStart = startPos + symbol.length;
            userInput.selectionEnd = startPos + symbol.length;
            userInput.focus();
            lastValue = userInput.value;
            updateSendState();
        });
    });

    const voiceLangBtn = document.getElementById('voiceLangBtn');
    let currentSpeechLang = localStorage.getItem('speech_lang') || 'zh-TW';

    function updateVoiceLangUI() {
        if (voiceLangBtn) {
            if (currentSpeechLang === 'en-US') {
                voiceLangBtn.textContent = 'EN';
                voiceLangBtn.title = "目前語音語言：英文 (點擊切換為中文)";
                voiceLangBtn.classList.add('en-mode');
            } else {
                voiceLangBtn.textContent = '中';
                voiceLangBtn.title = "目前語音語言：繁體中文 (點擊切換為英文)";
                voiceLangBtn.classList.remove('en-mode');
            }
        }
    }
    updateVoiceLangUI();

    function speechToMath(candidates) {
        try {
            return SpeechMath.convert(SpeechMath.pick(candidates, currentSpeechLang), currentSpeechLang);
        } catch (e) {
            console.warn('數學符號轉換失敗：', e);
            return candidates.map((alternatives) => alternatives[0] || '').join('');
        }
    }

    const SPEECH_START_TIMEOUT_MS = 8000;
    const SPEECH_PAUSE_TIMEOUT_MS = 2500;
    let speechStopTimer = null;

    function scheduleSpeechStop(ms) {
        clearTimeout(speechStopTimer);
        speechStopTimer = setTimeout(() => {
            if (isListening) stopListening();
        }, ms);
    }

    if (voiceLangBtn) {
        voiceLangBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            currentSpeechLang = currentSpeechLang === 'zh-TW' ? 'en-US' : 'zh-TW';
            localStorage.setItem('speech_lang', currentSpeechLang);
            updateVoiceLangUI();
            if (isListening) {
                stopListening();
            }
        });
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        recognition = new SpeechRecognition();

        recognition.continuous = !/Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
        recognition.interimResults = true;
        recognition.maxAlternatives = 5;
        recognition.lang = currentSpeechLang;

        recognition.onstart = () => {
            isListening = true;
            if (voiceInputBtn) {
                voiceInputBtn.classList.add('recording');
                voiceInputBtn.title = "點擊停止錄音";
            }
            userInput.placeholder = currentSpeechLang === 'en-US'
                ? "Listening (English)... Speak now 🎙️"
                : "正在聆聽 (中文)... 請說話 🎙️";
            speechBaseText = userInput.value;
            scheduleSpeechStop(SPEECH_START_TIMEOUT_MS);
        };

        recognition.onresult = (event) => {

            const candidates = Array.from(event.results, (result) => Array.from(result, (alt) => alt.transcript));
            const currentTranscript = speechToMath(candidates);
            if (speechBaseText) {
                userInput.value = speechBaseText + (speechBaseText.endsWith(' ') ? '' : ' ') + currentTranscript;
            } else {
                userInput.value = currentTranscript;
            }
            lastValue = userInput.value;
            updateSendState();
            if (event.results[event.results.length - 1].isFinal) {

                console.info('[語音輸入] 辨識候選：', candidates, '→', currentTranscript);
            }
            scheduleSpeechStop(SPEECH_PAUSE_TIMEOUT_MS);
        };

        recognition.onerror = (event) => {
            console.warn('Speech recognition error:', event.error);
            if (event.error === 'not-allowed') {
                alert('請允許麥克風權限以使用語音輸入功能！🎤');
            } else if (event.error !== 'no-speech' && event.error !== 'aborted') {
                console.error('語音辨識發生錯誤：', event.error);
            }
            stopListening();
        };

        recognition.onend = () => {
            stopListening();
        };
    }

    function startListening() {
        if (!recognition) {
            alert('您的瀏覽器不支援語音辨識功能，建議使用 Google Chrome 或 Microsoft Edge 瀏覽器！');
            return;
        }
        try {
            recognition.lang = currentSpeechLang;
            recognition.start();
        } catch (e) {
            console.error('啟動語音辨識失敗:', e);
            stopListening();
        }
    }

    function stopListening(discardPending = false) {
        isListening = false;
        clearTimeout(speechStopTimer);
        if (voiceInputBtn) {
            voiceInputBtn.classList.remove('recording');
            voiceInputBtn.title = "語音輸入";
        }
        if (userInput) {
            userInput.placeholder = "問問數學小老師";
        }
        try {
            if (recognition) {
                if (discardPending) recognition.abort();
                else recognition.stop();
            }
        } catch (e) {}
    }

    if (voiceInputBtn) {
        voiceInputBtn.addEventListener('click', (e) => {
            e.preventDefault();
            if (isListening) {
                stopListening();
            } else {
                startListening();
            }
        });
    }

    checkAuthOnLoad();
});
