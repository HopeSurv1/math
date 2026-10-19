// 管理後台的「學習分析」與「老師自我檢查」分頁（分頁切換在 admin.js）。
// 學生的學習紀錄用 learning_report.js 畫，跟學生自己看到的是同一份；管理員看不到對話內容，
// 所以不顯示「回到當時的對話」。帳號、AI 標記的文字、老師的回覆一律用 textContent 放進畫面。
window.AdminLearning = (() => {
    const R = LearningReport;
    let onUnauthorized = () => {};
    let els = null;

    const STATUS_LABELS = { revised: '已改寫', flagged: '有問題，沒改成' };

    class Unauthorized extends Error {}

    async function getJson(url, options) {
        const res = await fetch(url, options);
        if (res.status === 401) {
            onUnauthorized();
            throw new Unauthorized();
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || '讀取失敗，請再試一次');
        return data;
    }

    function showError(container, err) {
        if (err instanceof Unauthorized) return;
        console.error(err);
        container.replaceChildren(R.el('p', 'report-empty', err.message || '讀取失敗，請按「重新整理」再試一次'));
    }

    // ---------- 全班總覽 ----------
    function unitsSection(units) {
        const sec = R.section('最常卡住的單元', '答錯、卡住越多的排越前面；「需要加強」是在這個單元答錯或卡住比較多的學生人數。');
        const weak = units.filter((u) => u.weakness > 0);
        if (!weak.length) {
            sec.appendChild(R.el('p', 'report-empty', '目前沒有學生在哪個單元特別卡住。'));
            return sec;
        }
        const wrap = R.table(
            ['單元', '練習過', '需要加強', '答錯', '卡住', '答對率'],
            weak.map((u) => [R.unitName(u.unit, u.title), `${u.students} 人`, `${u.struggling} 人`,
                `${u.wrong + u.partial}`, `${u.stuck}`, R.meter(u.accuracy)]),
        );
        wrap.classList.add('class-units-table');
        sec.appendChild(wrap);
        return sec;
    }

    function studentsSection(students) {
        const sec = R.section('學生一覽', '點一下看這個學生的學習紀錄。');
        if (!students.length) {
            sec.appendChild(R.el('p', 'report-empty', '目前還沒有任何註冊帳號。'));
            return sec;
        }
        const wrap = R.table(
            ['帳號', '最後活動', '近 7 天提問', '答對率', '最需要加強'],
            students.map((s) => [s.username, R.formatTime(s.last_active), `${s.questions_7d} 次`, R.percent(s.accuracy),
                s.weak_unit ? R.unitName(s.weak_unit.unit, s.weak_unit.title) : '—']),
            [2, 3],
        );
        wrap.classList.add('students-table');
        wrap.querySelectorAll('tbody tr').forEach((row, i) => {
            row.classList.add('clickable-row');
            row.tabIndex = 0;
            const open = () => showStudent(students[i].username);
            row.addEventListener('click', open);
            row.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') open();
            });
        });
        sec.appendChild(wrap);
        return sec;
    }

    function inactiveSection(inactive) {
        const sec = R.section('很久沒上線', '超過 7 天沒有問問題的學生（包含註冊後還沒用過的）。');
        if (!inactive.length) {
            sec.appendChild(R.el('p', 'report-empty', '大家最近 7 天都有來！'));
            return sec;
        }
        const list = R.el('div', 'chip-list');
        inactive.forEach((s) => {
            const chip = R.el('button', 'user-chip-btn');
            chip.type = 'button';
            chip.append(R.el('span', 'chip-name', s.username),
                R.el('span', 'chip-meta', s.last_active ? `最後 ${R.formatTime(s.last_active)}` : '還沒用過'));
            chip.addEventListener('click', () => showStudent(s.username));
            list.appendChild(chip);
        });
        sec.appendChild(list);
        return sec;
    }

    function renderOverview(data) {
        const t = data.totals;
        els.overviewContent.replaceChildren(
            R.el('p', 'report-note', '學習紀錄是 AI 根據對話自動整理的，不一定完全準確，適合看趨勢。'),
            R.statGrid([
                R.statTile('學生人數', `${t.students} 人`),
                R.statTile('近 7 天有來', `${t.active_7d} 人`, `近 7 天共提問 ${t.questions_7d} 次`),
                R.statTile('全班答對率', R.percent(t.accuracy), `作答 ${t.attempts} 次`),
            ]),
            unitsSection(data.units),
            studentsSection(data.students),
            inactiveSection(data.inactive),
        );
    }

    async function showOverview() {
        els.studentView.hidden = true;
        els.overviewView.hidden = false;
        try {
            renderOverview(await getJson('/api/admin/learning/overview'));
        } catch (err) {
            showError(els.overviewContent, err);
        }
    }

    // ---------- 單一學生 ----------
    async function showStudent(username) {
        els.overviewView.hidden = true;
        els.studentView.hidden = false;
        els.studentTitle.textContent = `${username} 的學習紀錄`;
        els.studentReport.replaceChildren(R.el('p', 'report-empty', '載入中…'));
        try {
            const report = await getJson(`/api/admin/learning/report?username=${encodeURIComponent(username)}`);
            R.render(els.studentReport, report, {
                emptyText: '這個學生還沒有任何學習紀錄。',
                adviceHint: '請 AI 依這個學生的紀錄寫學習建議；學生自己的學習紀錄頁也會看到這一份。',
                requestAdvice: async () => {
                    const data = await getJson('/api/admin/learning/advice', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username }),
                    });
                    return data.advice;
                },
            });
        } catch (err) {
            showError(els.studentReport, err);
        }
        document.querySelector('.admin-page').scrollTop = 0;
    }

    // ---------- 老師自我檢查 ----------
    // 回覆裡的圖片語法換成〔圖片〕，比較好讀
    function readable(text) {
        return (text || '').replace(/!\[[^\]\n]*\]\([^)\s]*\)/g, '〔圖片〕').trim();
    }

    function reviewItem(review) {
        const item = R.el('details', 'review-item');
        const summary = R.el('summary', 'review-summary');
        summary.append(
            R.el('span', `review-status ${review.status}`, STATUS_LABELS[review.status] || review.status),
            R.el('span', 'review-kinds', [...new Set(review.problems.map((p) => p.kind))].join('、')),
            R.el('span', 'review-meta', `${review.username}・${R.formatTime(review.created_at)}`),
        );
        const body = R.el('div', 'review-body');
        const block = (label, content) => {
            const wrap = R.el('div', 'review-block');
            wrap.appendChild(R.el('h4', null, label));
            wrap.appendChild(content instanceof Node ? content : R.el('p', 'review-text', content));
            return wrap;
        };
        const problems = R.el('ul', 'review-problems');
        review.problems.forEach((p) => problems.appendChild(R.el('li', null, `${p.kind}：${p.detail}`)));
        body.append(
            block('學生的問題', readable(review.question) || '（這則訊息已經不在了）'),
            block('檢查發現的問題', problems),
            block('原稿', readable(review.draft)),
            block(review.status === 'revised' ? '改寫後（學生看到的）' : '學生看到的（改寫沒成功，是原稿）',
                readable(review.final) || '（這則訊息已經不在了）'),
        );
        item.append(summary, body);
        return item;
    }

    function renderReviews(stats, reviews) {
        const nodes = [R.statGrid([
            R.statTile('檢查次數', `${stats.total} 次`, stats.avg_seconds !== null ? `平均每次多花 ${stats.avg_seconds} 秒` : null),
            R.statTile('通過', `${stats.ok} 次`, '沒有問題，原稿直接送出'),
            R.statTile('發現問題、已改寫', `${stats.revised} 次`, '學生看到的是改寫後的版本'),
            R.statTile('發現問題、沒改成', `${stats.flagged} 次`, '改寫時忙線或逾時，送出原稿'),
            R.statTile('沒檢查成', `${stats.skipped} 次`, '檢查時忙線或逾時，送出原稿'),
        ])];
        if (!stats.total) {
            nodes.push(R.el('p', 'report-empty section-gap', '還沒有檢查紀錄。（.env 設了 REPLY_REVIEW=0 時不會檢查。）'));
        }
        if (stats.by_kind.length) {
            const sec = R.section('發現的問題類型');
            const card = R.el('div', 'report-card');
            card.appendChild(R.barList(stats.by_kind.map((k) => ({ label: k.kind, value: k.count, text: `${k.count} 次` }))));
            sec.appendChild(card);
            nodes.push(sec);
        }
        const sec = R.section('最近發現問題的回覆', '點開看學生的問題、原稿、改寫後的版本。');
        if (reviews.length) {
            const list = R.el('div', 'review-list');
            reviews.forEach((review) => list.appendChild(reviewItem(review)));
            sec.appendChild(list);
        } else {
            sec.appendChild(R.el('p', 'report-empty', '還沒有發現問題的回覆。'));
        }
        nodes.push(sec);
        els.reviewsContent.replaceChildren(...nodes);
    }

    async function showReviews() {
        try {
            const [overview, reviews] = await Promise.all([
                getJson('/api/admin/learning/overview'),
                getJson('/api/admin/reviews'),
            ]);
            renderReviews(overview.reflection, reviews.reviews);
        } catch (err) {
            showError(els.reviewsContent, err);
        }
    }

    function init(options) {
        onUnauthorized = options.onUnauthorized;
        els = {
            overviewView: document.getElementById('overviewView'),
            overviewContent: document.getElementById('overviewContent'),
            studentView: document.getElementById('studentView'),
            studentTitle: document.getElementById('studentTitle'),
            studentReport: document.getElementById('studentReport'),
            reviewsContent: document.getElementById('reviewsContent'),
        };
        document.getElementById('refreshOverviewBtn').addEventListener('click', showOverview);
        document.getElementById('backToOverviewBtn').addEventListener('click', showOverview);
        document.getElementById('refreshReviewsBtn').addEventListener('click', showReviews);
    }

    return { init, showOverview, showStudent, showReviews };
})();
