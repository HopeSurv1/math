document.addEventListener('DOMContentLoaded', () => {
    const chatHistory = document.getElementById('chatHistory');
    const userInput = document.getElementById('userInput');
    const sendBtn = document.getElementById('sendBtn');

    // 圖片上傳相關元素
    const imageUpload = document.getElementById('imageUpload');
    const imagePreviewContainer = document.getElementById('imagePreviewContainer');
    const imagePreview = document.getElementById('imagePreview');
    const removeImageBtn = document.getElementById('removeImageBtn');

    // 數學鍵盤元素
    const toggleKeyboardBtn = document.getElementById('toggleKeyboardBtn');
    const mathKeyboard = document.getElementById('mathKeyboard');
    const mathKeys = document.querySelectorAll('.math-key');

    // 語音輸入元素
    const voiceInputBtn = document.getElementById('voiceInputBtn');
    let isListening = false;
    let recognition = null;
    let speechBaseText = '';

    let currentImageBase64 = null;
    let currentImageMimeType = null;

    // ===== 登入／註冊相關元素 =====
    const authScreen = document.getElementById('authScreen');
    const appContainer = document.getElementById('appContainer');
    const authTabs = document.querySelectorAll('.auth-tab');
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const loginMsg = document.getElementById('loginMsg');
    const registerMsg = document.getElementById('registerMsg');
    const currentUsernameEl = document.getElementById('currentUsername');
    const logoutBtn = document.getElementById('logoutBtn');

    // ===== 對話紀錄相關元素與狀態 =====
    const newChatBtn = document.getElementById('newChatBtn');
    const historyList = document.getElementById('historyList');
    let currentConversationId = null; // null 代表「還沒送出過第一句話的新對話」
    let currentUsername = '';
    // 從學習紀錄頁的「回到當時的對話」連過來時，網址是 /?c=<對話 id>：進聊天室時先打開那一條
    let conversationFromUrl = new URLSearchParams(window.location.search).get('c');

    // ===== 送出與停止（見 handleSend / stopReply）=====
    // 一次只能有一則訊息在等老師回覆；等待中傳送鈕會變成「停止」鈕。
    let pendingReply = null;   // 正在等回覆的這一輪；null 代表沒有在等
    let pendingCancel = null;  // 還沒做完的「撤銷」請求：下一則訊息要等它做完再送，老師才不會看到被撤銷的那一輪
    let viewVersion = 0;       // 換對話、開新對話、登出時 +1；回覆回來時畫面已經換了，就不能畫進去

    // ===== 側欄（桌機可收合成圖示、手機是滑出抽屜）=====
    const sidebarToggleBtn = document.getElementById('sidebarToggleBtn');
    const mobileMenuBtn = document.getElementById('mobileMenuBtn');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');
    const userAvatar = document.getElementById('userAvatar');
    const mobileQuery = window.matchMedia('(max-width: 768px)');

    // localStorage 可能被瀏覽器封鎖（無痕模式等），讀寫都包 try/catch，失敗就當沒存過
    function readPref(key, fallback) {
        try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
    }
    function writePref(key, value) {
        try { localStorage.setItem(key, value); } catch { /* 存不了就算了 */ }
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
        // 登出（或登入失效）時還在等的回覆就不等了；這不是「停止」，後端照樣會把它存進原本的對話串
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
        // 進聊天室時，順便把對話紀錄清單load出來；如果有舊對話，自動接回最近那條，
        // 這樣重新整理網頁也看得到之前聊過的內容，不會每次都變成一片空白。
        currentConversationId = null;
        renderMessages([]);
        loadConversationList(true);
    }

    // 空白對話時顯示的歡迎畫面：漸層問候語 + 幾個點了就直接送出的範例問題
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
                if (pendingReply) return; // 老師還在回覆別的問題，不要蓋掉輸入框裡打到一半的字
                userInput.value = s.text;
                lastValue = userInput.value;
                handleSend();
            });
            grid.appendChild(card);
        });

        welcome.append(title, subtitle, grid);
        chatHistory.appendChild(welcome);
    }

    // 把一批訊息（從資料庫讀出來的舊紀錄）畫回聊天視窗，取代目前畫面上的內容
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

    // 重新載入「對話紀錄」清單；selectMostRecentIfNone 為 true 時，如果目前沒有選定
    // 任何對話串、但清單不是空的，會自動選最近更新的那一條接回去
    async function loadConversationList(selectMostRecentIfNone) {
        try {
            const res = await fetch('/api/conversations');
            if (!res.ok) return;
            const data = await res.json();
            const conversations = data.conversations || [];
            if (selectMostRecentIfNone && !currentConversationId && conversations.length > 0) {
                // 網址指定的對話還在就打開它（已經被刪掉就照舊打開最近的），用過就從網址拿掉
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

            // 把標題換成可編輯的輸入框，讓使用者改名；Enter 或失去焦點時送出，Esc 取消
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
                        finished = true; // 取消編輯，不儲存
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
                e.stopPropagation(); // 不要連帶觸發外層的「切換到這條對話」
                startEditingTitle();
            });
            item.appendChild(editBtn);

            const delBtn = document.createElement('button');
            delBtn.className = 'history-item-delete';
            delBtn.type = 'button';
            delBtn.title = '刪除這則對話';
            delBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>';
            delBtn.addEventListener('click', async (e) => {
                e.stopPropagation(); // 不要連帶觸發外層的「切換到這條對話」
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

    // 切換到某一條舊對話：把它的內容讀回來畫在畫面上
    async function selectConversation(conversationId) {
        currentConversationId = conversationId;
        const view = ++viewVersion;
        closeMobileSidebar();
        try {
            const res = await fetch(`/api/conversations/${conversationId}/messages`);
            if (res.ok) {
                const data = await res.json();
                if (view !== viewVersion) return; // 讀的時候又換到別的對話了，這份內容已經過時
                renderMessages(data.messages || []);
                reattachPendingReply(conversationId);
            }
        } catch (err) {
            console.error('讀取對話內容失敗:', err);
        }
        loadConversationList(false); // 重畫一次清單，讓「目前選中」的樣式更新
    }

    // 換回正在等回覆的那條對話時，把還在等的問題和「老師正在想」接回畫面上，回覆回來就畫在這裡
    function reattachPendingReply(conversationId) {
        if (!pendingReply || pendingReply.conversationId !== conversationId) return;
        appendMessage('student', pendingReply.text, false, false, pendingReply.imageUrl);
        pendingReply.studentMsg = chatHistory.lastElementChild;
        showTypingIndicator();
        pendingReply.view = viewVersion;
    }

    // 開新對話：畫面清空回到歡迎訊息，實際的對話串會在送出第一句話時才由後端建立
    // （避免按了「開新對話」卻什麼都沒問，就先在清單裡留下一筆空對話）
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

    // 切換「登入 / 註冊」分頁
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

    // 送出登入表單
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        loginMsg.textContent = '';
        loginMsg.classList.remove('success'); // 刪除帳號後會留下綠色的成功訊息，這裡改回一般錯誤樣式
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

    // 送出註冊表單
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

    // 登出
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

    // ===== 帳號設定：刪除帳號 =====
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

    // 點對話框外面的暗色背景也能關閉（padding 放在內層 form，所以只有點到背景時 target 才是 dialog）
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
                loginForm.reset(); // 登入表單裡可能還留著剛剛那個帳號的帳密
                showAuthScreen();
                loginMsg.classList.add('success');
                loginMsg.textContent = '帳號已刪除，謝謝你的使用！';
            } else if (res.status === 401) {
                // 登入已經失效，帳號沒有被刪，回登入畫面
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

    // 一開始先確認有沒有登入過（cookie 還在的話不用重新輸入帳密）
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

    // 行內格式：圖片、粗體、行內程式碼（輸入已經先跳脫過 HTML）
    function formatInline(line) {
        return line
            // 圖片只接受站內路徑或 data:image，避免插入外部網址
            .replace(/!\[([^\]]*)\]\(((?:\/|data:image\/)[^)\s]+)\)/g, '<img src="$2" alt="$1" />')
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            // 線段（邊長）：A̅B̅（每個字母後面接「組合上橫線」）→ 整段 AB 上面一條連續的線。
            // 直接顯示組合字元在有些字型（例如微軟正黑體）會歪掉，改用 CSS 畫線才穩
            .replace(/(?:[A-Za-z]̅)+/g, run => `<span class="seg">${run.replace(/̅/g, '')}</span>`);
    }

    // 簡易 Markdown：段落、# 標題、- / * / 1. 清單、粗體、行內程式碼、圖片。
    // 一律先跳脫 HTML，所以像「x < 3」這種數學式不會被瀏覽器當成標籤吃掉。
    function formatText(text) {
        if (!text) return '';
        const lines = escapeHtml(text).split('\n');
        const html = [];
        let listType = null;   // 'ul' | 'ol' | null
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

    // 新增訊息到對話框
    function appendMessage(sender, text, isHtml = false, usedTool = false, imageUrl = null) {
        // 第一則訊息出現時，拿掉歡迎畫面
        const welcome = chatHistory.querySelector('.welcome');
        if (welcome) welcome.remove();

        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${sender}`;

        const avatar = document.createElement('div');
        // 老師用 π 標誌當頭像；學生的頭像由 CSS 隱藏
        avatar.className = sender === 'teacher' ? 'avatar logo-mark' : 'avatar';
        avatar.textContent = sender === 'teacher' ? 'π' : '';

        const bubble = document.createElement('div');
        bubble.className = 'bubble';

        // 如果有使用工具查閱講義，加上 Badge
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

        // 捲動到最下面
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    // 顯示打字中動畫
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

    // 移除打字中動畫
    function removeTypingIndicator() {
        const indicator = document.getElementById('typingIndicator');
        if (indicator) {
            indicator.remove();
        }
    }

    // 每一輪的編號，按「停止」時用它請後端撤銷這一輪。
    // 不用 crypto.randomUUID：它只有 https 或 localhost 才能用，用區網 IP 開網頁時會壞掉
    function newRequestId() {
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    }

    // 處理送出
    async function handleSend() {
        // 老師還沒回完就不能再送。Enter、傳送鈕、歡迎畫面的範例問題都會走到這裡，一律在這裡擋
        if (pendingReply) return;
        if (isListening) {
            stopListening(true);
        }

        const typed = userInput.value.trim();
        // 如果沒文字也沒圖片就不送出
        if (!typed && !currentImageBase64) return;

        const turn = {
            controller: new AbortController(),  // 按「停止」時用來中斷這個請求
            requestId: newRequestId(),
            conversationId: currentConversationId, // 第一句話會是 null，後端會自動開一條新對話串
            view: viewVersion,
            text: typed || '請看這張圖片',        // 如果有圖片但沒文字，預設給個文字
            typed,                                 // 按「停止」時放回輸入框的是學生自己打的字
            imageBase64: currentImageBase64,
            mimeType: currentImageMimeType,
            imageUrl: currentImageBase64 ? `data:${currentImageMimeType};base64,${currentImageBase64}` : null,
        };
        pendingReply = turn;
        setWaiting(true);

        // UI 狀態更新
        userInput.value = '';
        lastValue = '';
        clearImagePreview();
        appendMessage('student', turn.text, false, false, turn.imageUrl);
        turn.studentMsg = chatHistory.lastElementChild;
        showTypingIndicator();

        try {
            // 上一輪剛按了停止：等後端撤銷完再送，老師才不會看到被撤銷的那一輪
            if (pendingCancel) await pendingCancel;
            if (turn.controller.signal.aborted) return;

            // 呼叫後端 API
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
                // 登入過期或被登出了，退回登入畫面，剛剛打的話不會被送出
                removeTypingIndicator();
                showAuthScreen();
                return;
            }

            const data = await response.json();

            if (turn.view !== viewVersion) {
                // 等的時候換到別的對話了：回覆已經存進它自己的對話串，不能畫在現在的畫面上
                if (data.conversation_id && data.conversation_id === currentConversationId) {
                    selectConversation(currentConversationId); // 剛好又切回這條：重新讀一次
                } else {
                    loadConversationList(false);
                }
                return;
            }
            removeTypingIndicator();
            appendMessage('teacher', data.reply, false, data.used_tool);

            // 記住這句話最後存進了哪一條對話串（第一句話送出後，後端才會分配新的 id），
            // 並重新整理左側清單，讓標題／排序即時反映最新狀態。
            if (data.conversation_id) {
                currentConversationId = data.conversation_id;
            }
            loadConversationList(false);
        } catch (error) {
            if (turn.controller.signal.aborted) return; // 按了停止（或登出了），畫面已經處理好
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

    // 按「停止」：不等這一輪的回覆了。問題從畫面上收回、放回輸入框，改一改可以直接再送。
    // 後端可能已經（或等一下就會）把這一輪存起來，請它撤銷，老師才不會記得這個收回的問題。
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
            keepalive: true, // 按完停止馬上關掉網頁，也照樣送得出去
        })
            .catch((err) => console.error('停止這一輪失敗:', err))
            .finally(() => {
                if (pendingCancel === cancel) pendingCancel = null;
                loadConversationList(false); // 這一輪如果開了新對話串，撤銷後清單裡也要消失
            });
        pendingCancel = cancel;

        if (turn.view !== viewVersion) return; // 已經換到別的對話了，畫面上沒有這一輪
        removeTypingIndicator();
        turn.studentMsg.remove();
        if (!chatHistory.querySelector('.message')) renderMessages([]); // 收回的是新對話唯一的一句：回到歡迎畫面
        // 等的時候已經打了新的字（或附了新的圖）就不蓋掉
        if (!userInput.value.trim() && !currentImageBase64) {
            userInput.value = turn.typed;
            lastValue = userInput.value;
            if (turn.imageBase64) setAttachedImage(turn.imageBase64, turn.mimeType);
        }
        updateSendState();
        userInput.focus();
    }

    // 等待中：傳送鈕換成「停止」鈕
    function setWaiting(waiting) {
        sendBtn.classList.toggle('stop', waiting);
        sendBtn.title = waiting ? '停止回覆' : '傳送';
        sendBtn.setAttribute('aria-label', sendBtn.title);
    }

    // 輸入框有字或有附圖時，傳送鈕才亮起來
    function updateSendState() {
        sendBtn.classList.toggle('ready', !!userInput.value.trim() || !!currentImageBase64);
    }

    // 附上一張圖片：選好檔案時、按「停止」把圖放回輸入框時都用這個
    function setAttachedImage(base64, mimeType) {
        currentImageBase64 = base64;
        currentImageMimeType = mimeType;
        imagePreview.src = `data:${mimeType};base64,${base64}`;
        imagePreviewContainer.style.display = 'inline-block';
        updateSendState();
    }

    // 清除圖片預覽
    function clearImagePreview() {
        currentImageBase64 = null;
        currentImageMimeType = null;
        imageUpload.value = '';
        imagePreview.src = '';
        imagePreviewContainer.style.display = 'none';
        updateSendState();
    }

    // 處理圖片上傳選擇
    imageUpload.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = (e) => {
                // dataUrl 格式為 data:image/jpeg;base64,...，逗號後面才是圖片內容
                setAttachedImage(e.target.result.split(',')[1], file.type);
            };
            reader.readAsDataURL(file);
        }
    });

    removeImageBtn.addEventListener('click', clearImagePreview);

    // 上標對應表與狀態
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

    // 監聽點擊與 Enter 鍵。等待回覆時按鈕是「停止」鈕；Enter 則由 handleSend 擋下，不會重複送出
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

        // 找出共同前綴
        let start = 0;
        while (start < lastValue.length && start < curValue.length && lastValue[start] === curValue[start]) {
            start++;
        }

        // 找出共同後綴
        let endLast = lastValue.length - 1;
        let endCur = curValue.length - 1;
        while (endLast >= start && endCur >= start && lastValue[endLast] === curValue[endCur]) {
            endLast--;
            endCur--;
        }

        // 本次插入的新文字
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

    // 處理數學鍵盤開關
    toggleKeyboardBtn.addEventListener('mousedown', (e) => {
        e.preventDefault(); // 防止按鈕搶走 input 的 focus
        const isHidden = window.getComputedStyle(mathKeyboard).display === 'none';
        mathKeyboard.style.display = isHidden ? 'grid' : 'none';
        toggleKeyboardBtn.classList.toggle('active', isHidden);
        userInput.focus();
    });

    // 處理數學鍵盤按鈕點擊
    mathKeys.forEach(key => {
        key.addEventListener('mousedown', (e) => {
            e.preventDefault(); // 防止按鈕搶走 input 的 focus
            const symbol = key.getAttribute('data-symbol');
            if (!symbol) return; // 跳過沒有 data-symbol 的按鈕 (例如 powerModeBtn)

            const startPos = userInput.selectionStart || userInput.value.length;
            const endPos = userInput.selectionEnd || userInput.value.length;

            // 插入符號
            userInput.value = userInput.value.substring(0, startPos) + symbol + userInput.value.substring(endPos, userInput.value.length);

            // 恢復游標位置並 focus
            userInput.selectionStart = startPos + symbol.length;
            userInput.selectionEnd = startPos + symbol.length;
            userInput.focus();
            lastValue = userInput.value;
            updateSendState();
        });
    });

    // 語音輸入 (Web Speech API) 邏輯
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

    // 語音辨識每一段都有好幾個候選結果，挑最像算式的接起來（例如在「二的評分」和「二的平方」之間選後者），
    // 再把數學講法換成數學鍵盤上的符號（「二的平方」→ 2²）。見 speech_math.js。
    // 出錯就用各段排第一的候選、不轉換，不影響語音輸入本身。
    function speechToMath(candidates) {
        try {
            return SpeechMath.convert(SpeechMath.pick(candidates, currentSpeechLang), currentSpeechLang);
        } catch (e) {
            console.warn('數學符號轉換失敗：', e);
            return candidates.map((alternatives) => alternatives[0] || '').join('');
        }
    }

    // 連續聆聽什麼時候自動結束：按下麥克風後一直沒開口 8 秒，或講完後停頓 2.5 秒沒有新的字
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
        // 電腦上用連續聆聽：講算式常常會停下來想，單句模式一停頓就結束、只收到半句。
        // 停頓超過 SPEECH_PAUSE_TIMEOUT_MS 才自動結束。手機瀏覽器的連續模式常會重複前面的字，維持單句模式。
        recognition.continuous = !/Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
        recognition.interimResults = true; // 即時輸出中間結果
        recognition.maxAlternatives = 5; // 每段多拿幾個候選結果，挑最像算式的（見 speechToMath）
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
            // 連續聆聽時，每停頓一次就多一段結果：每次都從第一段重組，跨段的算式（「x的平方」停一下「加y的平方」）才接得起來
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
                // 語音辨識實際聽到什麼（各段的候選）：有講法沒轉成功時，從瀏覽器的主控台可以看到原文
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

    // discardPending：送出訊息時改用 abort()，丟掉還沒回來的辨識結果，免得送出後輸入框又被填回去
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

    // 初始化：先確認登入狀態，再決定顯示登入畫面還是聊天室
    checkAuthOnLoad();
});
