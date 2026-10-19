// 學習紀錄報告的畫面：學生的「我的學習紀錄」頁（learning.js）和管理後台看單一學生時（admin_learning.js）共用。
// 資料來自後端 learning_analysis.build_report()。單元、觀念、題目是 AI 標記的文字，一律用 textContent 放進畫面。
// 圖表都只有一組資料：只用一個顏色（--chart-1）、不放圖例；滑鼠移上去或用 Tab 選到會顯示數字，
// 每張圖也都有「看數字」的表格，不用滑鼠也看得到全部的值。
window.LearningReport = (() => {
    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    // 資料庫存的是 UTC 時間（YYYY-MM-DD HH:MM:SS），轉成瀏覽器所在時區顯示
    function formatTime(value) {
        if (!value) return '—';
        const date = new Date(value.replace(' ', 'T') + 'Z');
        if (Number.isNaN(date.getTime())) return value;
        return date.toLocaleString('zh-TW', {
            month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
        });
    }

    function percent(value) {
        return value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`;
    }

    function minutesText(minutes) {
        if (minutes < 60) return `${minutes} 分鐘`;
        const hours = Math.floor(minutes / 60);
        const rest = minutes % 60;
        return rest ? `${hours} 小時 ${rest} 分` : `${hours} 小時`;
    }

    function section(title, subtitle) {
        const wrap = el('section', 'report-section');
        wrap.appendChild(el('h2', 'report-heading', title));
        if (subtitle) wrap.appendChild(el('p', 'section-sub', subtitle));
        return wrap;
    }

    function statTile(label, value, sub) {
        const tile = el('div', 'stat-tile');
        tile.append(el('div', 'stat-label', label), el('div', 'stat-value', value));
        if (sub) tile.appendChild(el('div', 'stat-sub', sub));
        return tile;
    }

    function statGrid(tiles) {
        const grid = el('div', 'stat-grid');
        grid.append(...tiles);
        return grid;
    }

    function emptyNote(text) {
        return el('p', 'report-empty', text);
    }

    // ---------- 提示框：滑鼠移到長條上、或用 Tab 選到時，顯示那一條的數字 ----------
    let tooltip = null;

    function showTooltip(target, lines) {
        if (!tooltip) {
            tooltip = el('div', 'chart-tooltip');
            document.body.appendChild(tooltip);
        }
        // 數字在上、說明在下：看圖的人已經知道是哪一條，想知道的是數字
        tooltip.replaceChildren(...lines.map((line, i) => el('div', i === 0 ? 'tooltip-value' : 'tooltip-label', line)));
        tooltip.hidden = false;
        const rect = target.getBoundingClientRect();
        const tip = tooltip.getBoundingClientRect();
        const left = Math.max(8, Math.min(rect.left + rect.width / 2 - tip.width / 2, window.innerWidth - tip.width - 8));
        const top = rect.top - tip.height - 8 < 8 ? rect.bottom + 8 : rect.top - tip.height - 8;
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
    }

    function hideTooltip() {
        if (tooltip) tooltip.hidden = true;
    }

    function withTooltip(node, lines) {
        node.tabIndex = 0;
        node.setAttribute('aria-label', lines.join('，'));
        node.addEventListener('pointerenter', () => showTooltip(node, lines));
        node.addEventListener('pointerleave', hideTooltip);
        node.addEventListener('focus', () => showTooltip(node, lines));
        node.addEventListener('blur', hideTooltip);
    }

    // 刻度取整數：1、2、5、10、20、50…裡面第一個不小於最大值的
    function niceMax(max) {
        if (max <= 1) return 1;
        const power = 10 ** Math.floor(Math.log10(max));
        return [1, 2, 5, 10].map((m) => m * power).find((v) => v >= max);
    }

    // ---------- 直條圖：近 8 週每週提問次數 ----------
    function columnChart(weeks) {
        const max = niceMax(Math.max(...weeks.map((w) => w.questions)));
        const ticks = max % 2 === 0 ? [0, max / 2, max] : [0, max];
        const chart = el('div', 'col-chart');
        const axis = el('div', 'col-axis');
        const plot = el('div', 'col-plot');
        ticks.forEach((t) => {
            const bottom = `${(t / max) * 100}%`;
            const tick = el('span', 'col-tick', String(t));
            tick.style.bottom = bottom;
            axis.appendChild(tick);
            if (t > 0) {
                const line = el('div', 'col-grid');
                line.style.bottom = bottom;
                plot.appendChild(line);
            }
        });
        const labels = el('div', 'col-labels');
        weeks.forEach((week, i) => {
            const isThisWeek = i === weeks.length - 1;
            const column = el('div', 'col');
            // 只標這週的數字，其他週看刻度、提示框或表格
            if (isThisWeek && week.questions > 0) column.appendChild(el('span', 'col-value', String(week.questions)));
            const bar = el('div', 'col-bar');
            bar.style.height = `${(week.questions / max) * 100}%`;
            column.appendChild(bar);
            withTooltip(column, [
                `提問 ${week.questions} 次`,
                `${week.label} 那一週${isThisWeek ? '（這週）' : ''}・約 ${minutesText(week.minutes)}`,
            ]);
            plot.appendChild(column);
            labels.appendChild(el('span', 'col-label', isThisWeek ? '這週' : week.label));
        });
        chart.append(axis, plot, el('span'), labels);
        return chart;
    }

    // ---------- 橫條：每一條的數字標在尾端 ----------
    function barList(items) {
        const max = Math.max(...items.map((item) => item.value), 1);
        const list = el('div', 'bar-list');
        items.forEach((item) => {
            const row = el('div', 'bar-row');
            const track = el('div', 'bar-track');
            const fill = el('div', 'bar-fill');
            fill.style.width = `${(item.value / max) * 80}%`; // 最長的留兩成空間放數字
            track.append(fill, el('span', 'bar-value', item.text || String(item.value)));
            withTooltip(track, [item.text || String(item.value), item.label]);
            row.append(el('span', 'bar-label', item.label), track);
            list.appendChild(row);
        });
        return list;
    }

    // 答對率的小量尺：填滿的部分是答對率，底色是同色系淺一階
    function meter(value) {
        const wrap = el('span', 'meter-wrap');
        const track = el('span', 'meter');
        const fill = el('span', 'meter-fill');
        fill.style.width = `${Math.round((value || 0) * 100)}%`;
        track.appendChild(fill);
        wrap.append(track, el('span', 'meter-text', percent(value)));
        return wrap;
    }

    // numericColumns：哪幾欄是數字（靠右對齊）；不給就是第一欄以外全部
    function table(headers, rows, numericColumns = null) {
        const isNumeric = (i) => (numericColumns ? numericColumns.includes(i) : i > 0);
        const wrap = el('div', 'report-table-wrap');
        const tbl = el('table', 'report-table');
        const headRow = el('tr');
        headers.forEach((h, i) => headRow.appendChild(el('th', isNumeric(i) ? 'num' : '', h)));
        const thead = el('thead');
        thead.appendChild(headRow);
        const tbody = el('tbody');
        rows.forEach((cells) => {
            const row = el('tr');
            cells.forEach((cell, i) => {
                const td = el('td', isNumeric(i) ? 'num' : '');
                if (cell instanceof Node) td.appendChild(cell);
                else td.textContent = cell;
                row.appendChild(td);
            });
            tbody.appendChild(row);
        });
        tbl.append(thead, tbody);
        wrap.appendChild(tbl);
        return wrap;
    }

    // 圖表旁邊的「看數字」：收起來的表格，不用滑鼠也看得到每一個值
    function tableTwin(headers, rows) {
        const details = el('details', 'table-twin');
        details.append(el('summary', null, '看數字'), table(headers, rows));
        return details;
    }

    function unitName(unit, title) {
        const wrap = el('span', 'unit-name');
        if (unit) wrap.appendChild(el('span', 'unit-code', unit));
        wrap.appendChild(el('span', null, title || '（沒有對應的單元）'));
        return wrap;
    }

    // AI 學習建議的文字：「- 」開頭的行變成條列，其他是段落（** 粗體記號拿掉）
    function formatAdvice(text) {
        const nodes = [];
        let list = null;
        (text || '').replace(/\*\*/g, '').split('\n').forEach((raw) => {
            const line = raw.trim();
            const bullet = line.match(/^[-*•]\s+(.*)$/);
            if (!line) {
                list = null;
            } else if (bullet) {
                if (!list) {
                    list = el('ul');
                    nodes.push(list);
                }
                list.appendChild(el('li', null, bullet[1]));
            } else {
                list = null;
                nodes.push(el('p', null, line));
            }
        });
        return nodes;
    }

    // ---------- 各區塊 ----------
    function usageSection(usage) {
        const sec = section('使用情形', '學習時間是估計的：每次對話從第一句算到最後一句，再加 3 分鐘看老師的回覆。');
        sec.appendChild(statGrid([
            statTile('學習天數', `${usage.active_days} 天`, `最後上線 ${formatTime(usage.last_active)}`),
            statTile('提問次數', `${usage.questions} 次`, `近 7 天 ${usage.questions_7d} 次`),
            statTile('估計學習時間', minutesText(usage.minutes), `近 7 天 ${minutesText(usage.minutes_7d)}`),
        ]));
        const card = el('div', 'report-card');
        card.append(
            el('h3', 'card-title', '近 8 週每週提問次數'),
            columnChart(usage.weeks),
            tableTwin(['那一週（從週一算）', '提問次數', '估計學習時間'],
                usage.weeks.map((w) => [w.label, `${w.questions} 次`, minutesText(w.minutes)])),
        );
        sec.appendChild(card);
        return sec;
    }

    function practiceSection(practice) {
        const sec = section('練習表現', '「作答」是回答老師的提問、或自己算出答案；「解出」是自己得到那一題正確的最終答案。');
        sec.appendChild(statGrid([
            statTile('答對率', percent(practice.accuracy),
                `作答 ${practice.attempts} 次：答對 ${practice.correct}、部分正確 ${practice.partial}、答錯 ${practice.wrong}`),
            statTile('解出的題目', `${practice.solved} / ${practice.problems} 題`,
                practice.avg_turns_to_solve ? `平均來回 ${practice.avg_turns_to_solve} 次才解出` : '還沒有完整解出的題目'),
            statTile('說自己卡住', `${practice.stuck} 次`, '說「不會」「不知道」「要提示」的次數'),
        ]));
        return sec;
    }

    function weakUnitsSection(weakUnits) {
        const sec = section('需要加強的單元', '答錯、卡住越多的排越前面。');
        if (!weakUnits.length) {
            sec.appendChild(emptyNote('目前沒有特別需要加強的單元，繼續保持！'));
            return sec;
        }
        const list = el('div', 'weak-list');
        weakUnits.forEach((unit) => {
            const card = el('div', 'weak-card');
            card.append(unitName(unit.unit, unit.title), el('p', 'weak-reasons', unit.reasons));
            list.appendChild(card);
        });
        sec.appendChild(list);
        return sec;
    }

    function weakConceptsSection(concepts, conversationLink) {
        const sec = section('常卡住的觀念', '答錯或卡住時，錯在哪個觀念。');
        if (!concepts.length) {
            sec.appendChild(emptyNote('還沒有答錯或卡住的紀錄。'));
            return sec;
        }
        const list = el('ul', 'concept-list');
        concepts.forEach((c) => {
            const item = el('li', 'concept-item');
            const main = el('div', 'concept-main');
            main.append(el('strong', null, c.concept), el('span', 'concept-unit', `${c.unit || ''} ${c.title || ''}`.trim()));
            const side = el('div', 'concept-side');
            side.appendChild(el('span', 'concept-count', `${c.count} 次`));
            if (conversationLink && c.conversation_id) {
                const link = el('a', 'btn-link', '回到當時的對話');
                link.href = conversationLink(c.conversation_id);
                side.appendChild(link);
            }
            item.append(main, side);
            list.appendChild(item);
        });
        sec.appendChild(list);
        return sec;
    }

    function mistakesSection(errorTypes, mistakes, conversationLink) {
        const sec = section('答錯的情形');
        if (!mistakes.length) {
            sec.appendChild(emptyNote('還沒有答錯的紀錄。'));
            return sec;
        }
        const card = el('div', 'report-card');
        card.append(
            el('h3', 'card-title', '錯誤類型'),
            barList(errorTypes.map((t) => ({ label: t.type, value: t.count, text: `${t.count} 次` }))),
        );
        sec.appendChild(card);

        const list = el('ul', 'concept-list');
        mistakes.forEach((m) => {
            const item = el('li', 'concept-item');
            const main = el('div', 'concept-main');
            main.append(
                el('strong', null, m.problem || m.concept || '（沒有記到題目）'),
                el('span', 'concept-unit', [formatTime(m.at), m.unit, m.error_type ? `${m.result}・${m.error_type}` : m.result]
                    .filter(Boolean).join('　')),
            );
            item.appendChild(main);
            if (conversationLink && m.conversation_id) {
                const link = el('a', 'btn-link', '回到當時的對話');
                link.href = conversationLink(m.conversation_id);
                item.appendChild(link);
            }
            list.appendChild(item);
        });
        sec.append(el('h3', 'card-title list-title', '最近答錯的題目'), list);
        return sec;
    }

    function unitsSection(units) {
        const sec = section('各單元紀錄', '問的次數多的排前面。');
        if (!units.length) {
            sec.appendChild(emptyNote('還沒有對應到課本單元的紀錄。'));
            return sec;
        }
        const wrap = table(
            ['單元', '問了幾次', '作答', '答錯', '卡住', '答對率'],
            units.map((u) => [unitName(u.unit, u.title), `${u.turns}`, `${u.attempts}`, `${u.wrong + u.partial}`,
                `${u.stuck}`, meter(u.accuracy)]),
        );
        wrap.classList.add('units-table');
        sec.appendChild(wrap);
        return sec;
    }

    function adviceSection(advice, requestAdvice, hint) {
        const sec = section('AI 學習建議', hint);
        const card = el('div', 'report-card advice-card');
        const body = el('div', 'advice-text');
        const meta = el('p', 'advice-meta');
        const msg = el('p', 'auth-msg');
        const button = el('button', 'btn-primary advice-btn');
        button.type = 'button';

        function show(current) {
            body.replaceChildren(...formatAdvice(current ? current.text : ''));
            meta.textContent = current ? `產生於 ${formatTime(current.created_at)}` : '還沒有產生過學習建議。';
            button.textContent = current ? '重新產生' : '產生學習建議';
        }
        show(advice);

        button.addEventListener('click', async () => {
            const label = button.textContent;
            button.disabled = true;
            button.textContent = '產生中…';
            msg.textContent = '';
            try {
                show(await requestAdvice());
            } catch (err) {
                msg.textContent = err.message || '產生失敗，請再試一次';
                button.textContent = label;
            } finally {
                button.disabled = false;
            }
        });
        card.append(body, meta, msg, button);
        sec.appendChild(card);
        return sec;
    }

    /**
     * 把報告畫進 container。options：
     *   conversationLink(id) → 連結網址：有給才顯示「回到當時的對話」（只有學生自己看得到自己的對話）
     *   requestAdvice() → Promise<{text, created_at}>：有給才顯示 AI 學習建議的區塊
     *   emptyText：完全沒有紀錄時顯示的文字
     */
    function render(container, report, options = {}) {
        const { conversationLink = null, requestAdvice = null, emptyText = '還沒有學習紀錄。',
                adviceHint = '依照上面的紀錄，請 AI 老師整理接下來可以怎麼加強。按一次就產生一次。' } = options;
        hideTooltip();
        container.replaceChildren(el('p', 'report-note',
            '這些紀錄是 AI 根據和老師的對話自動整理的，不一定完全準確，看看趨勢就好。'));
        if (!report.usage.questions && !report.event_count) {
            container.appendChild(el('div', 'empty-state', emptyText));
            return;
        }
        container.append(
            usageSection(report.usage),
            practiceSection(report.practice),
            weakUnitsSection(report.weak_units),
            weakConceptsSection(report.weak_concepts, conversationLink),
            mistakesSection(report.error_types, report.recent_mistakes, conversationLink),
            unitsSection(report.units),
        );
        if (requestAdvice) container.appendChild(adviceSection(report.advice, requestAdvice, adviceHint));
    }

    return { render, formatTime, percent, minutesText, el, meter, barList, statTile, statGrid, table, unitName, section };
})();
