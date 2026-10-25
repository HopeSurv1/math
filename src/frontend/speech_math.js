const SpeechMath = (() => {
    'use strict';

    const SUPERSCRIPT = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
        '-': '⁻', '+': '⁺',
        a: 'ᵃ', b: 'ᵇ', c: 'ᶜ', d: 'ᵈ', e: 'ᵉ', f: 'ᶠ', g: 'ᵍ', h: 'ʰ', i: 'ⁱ', j: 'ʲ', k: 'ᵏ', l: 'ˡ',
        m: 'ᵐ', n: 'ⁿ', o: 'ᵒ', p: 'ᵖ', r: 'ʳ', s: 'ˢ', t: 'ᵗ', u: 'ᵘ', v: 'ᵛ', w: 'ʷ', x: 'ˣ', y: 'ʸ', z: 'ᶻ',
    };

    function superscript(str) {
        let out = '';
        for (const ch of str.toLowerCase()) {
            if (!SUPERSCRIPT[ch]) return null;
            out += SUPERSCRIPT[ch];
        }
        return out;
    }

    const CN_DIGIT = { '零': 0, '〇': 0, '一': 1, '二': 2, '兩': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9 };
    const CN_UNIT = { '十': 10, '百': 100, '千': 1000 };
    const CN_NUM = '[零〇一二兩三四五六七八九十百千萬]+';

    function parseCnInt(s) {
        if (s === '零' || s === '〇') return 0;
        let total = 0, section = 0, digit = null, lastUnit = Infinity;
        for (let i = 0; i < s.length; i++) {
            const ch = s[i];
            if (ch === '零' || ch === '〇') {
                if (i === 0 || digit !== null) return null;
            } else if (ch in CN_DIGIT) {
                if (digit !== null) return null;
                digit = CN_DIGIT[ch];
            } else if (ch === '萬') {
                if (digit === null && section === 0) return null;
                total = (section + (digit || 0)) * 10000;
                section = 0; digit = null; lastUnit = 10000;
            } else {
                const unit = CN_UNIT[ch];
                if (unit >= lastUnit) return null;
                if (digit === null) {
                    if (ch !== '十' || section !== 0) return null;
                    digit = 1;
                }
                section += digit * unit;
                digit = null; lastUnit = unit;
            }
        }
        return total + section + (digit || 0);
    }

    function parseCnNumber(s) {
        const [intPart, fracPart] = s.split('點');
        const int = parseCnInt(intPart);
        if (int === null || fracPart === '') return null;
        if (fracPart === undefined) return String(int);
        let frac = '';
        for (const ch of fracPart) {
            if (!(ch in CN_DIGIT) || ch === '兩') return null;
            frac += CN_DIGIT[ch];
        }
        return `${int}.${frac}`;
    }

    const isHan = (ch) => /[㐀-鿿]/.test(ch || '');
    const inSet = (set, ch) => !!ch && set.includes(ch);

    function matchRule(rules, match) {
        for (const [re, props] of rules) {
            const m = match(re);
            if (m) return [m, typeof props === 'function' ? props(m) : props];
        }
        return null;
    }

    const NUM_BAD_PREV = '第之每任某另其唯統同單專逐均劃週周期拜初不';

    const NUM_OK_NEXT = '的是嗎呢吧啊呀啦了和跟與或再然會要就還怎算結答為可能該得等度公喔哦耶欸嘛加減乘除開平立拍派根比大小對約時左右括圓';

    const YI_WORD_NEXT = '共起樣下定般直些';

    const PI_WORDS = '拍派';

    const PI_OK_PREV = '零〇一二兩三四五六七八九十百千萬加減乘以於號上去掉';
    const PI_OK_NEXT = '的是嗎呢吧啊呀啦了和跟與或再會要就還怎算等加減乘除開平立根約';

    const ANGLE_BAD_PREV = '直銳鈍對內外頂補餘平周心夾位錯同圓鄰三四五六七八多';

    const ZH_TRIANGLE = /三角形 ?([A-Za-z]) ?([A-Za-z]) ?([A-Za-z])(?![A-Za-z])/y;

    const ZH_ANGLE = /([角腳]) ?(?:([A-Za-z](?: ?[A-Za-z]){0,2})(?![A-Za-z])|(\d+|[一二三四五六七八九])(?![\d零〇一二三四五六七八九十百千萬]| ?度))/y;

    const ZH_POWER = new RegExp(`(的)?(?:(平方)|(立方)|(負)?(${CN_NUM}|\\d+|[A-Za-z])次方)`, 'y');

    const POWER_BLOCKED_BEFORE = /^(?:公|米|英|根|差|數|式|體|程)/;
    const ZH_NUMBER = new RegExp(`${CN_NUM}(?:點[零〇一二三四五六七八九]+)?`, 'y');

    const SYMBOL_WORDS = [
        [/\+/y, { kind: 'bin', sym: '+' }],
        [/[-−]/y, { kind: 'bin', sym: '-', canNeg: true }],
        [/×/y, { kind: 'bin', sym: '×' }],
        [/÷/y, { kind: 'bin', sym: '÷' }],
        [/=/y, { kind: 'bin', sym: '=' }],
        [/\(/y, { kind: 'lparen' }],
        [/\)/y, { kind: 'rparen' }],
    ];
    const ZH_WORDS = [
        [/開根號/y, { kind: 'rsqrt' }],
        [/根號/y, { kind: 'sqrt' }],
        [/左小?括[號弧]/y, { kind: 'lparen' }],
        [/右小?括[號弧]/y, { kind: 'rparen' }],
        [/小?括[號弧]/y, { kind: 'paren' }],
        [/加上|加/y, { kind: 'bin', sym: '+' }],
        [/減去|減掉|減/y, { kind: 'bin', sym: '-' }],
        [/乘以|乘上|乘/y, { kind: 'bin', sym: '×' }],
        [/除以/y, { kind: 'bin', sym: '÷' }],
        [/等於/y, { kind: 'bin', sym: '=' }],
        [/負/y, { kind: 'neg' }],
        [/西塔|希塔|θ/y, { kind: 'const', sym: 'θ' }],
        [/π/y, { kind: 'const', sym: 'π' }],
        [/圓周率/y, { kind: 'const', sym: 'π', soft: true }],
        ...SYMBOL_WORDS,
    ];

    function tokenizeChinese(input) {

        const s = input.replace(/[０-９Ａ-Ｚａ-ｚ＋－＝]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0));
        const tokens = [];
        let i = 0;
        const push = (raw, props) => { tokens.push({ raw, ...props }); i += raw.length; };
        const match = (re) => { re.lastIndex = i; return re.exec(s); };

        while (i < s.length) {
            const prev = s[i - 1] || '';
            let m;
            if ((m = match(ZH_TRIANGLE))) {
                push(m[0], { kind: 'shape', sym: '△' + (m[1] + m[2] + m[3]).toUpperCase() });
                continue;
            }
            if (!inSet(ANGLE_BAD_PREV, prev) && (m = match(ZH_ANGLE)) && (m[1] === '角' || m[2])) {
                const label = m[2] ? m[2].replace(/ /g, '').toUpperCase()
                    : /\d/.test(m[3]) ? m[3] : String(CN_DIGIT[m[3]]);
                push(m[0], { kind: 'shape', sym: '∠' + label });
                continue;
            }
            if ((m = match(ZH_POWER))) {
                push(m[0], zhPower(m, s.slice(i + m[0].length)));
                continue;
            }
            const rule = matchRule(ZH_WORDS, match);
            if (rule) {
                push(rule[0][0], rule[1]);
                continue;
            }
            if (inSet(PI_WORDS, s[i])) {
                const next = s[i + 1] || '';
                const ok = (!isHan(prev) || inSet(PI_OK_PREV, prev)) && (!isHan(next) || inSet(PI_OK_NEXT, next));
                push(s[i], ok ? { kind: 'const', sym: 'π', soft: true } : { kind: 'text' });
                continue;
            }
            if ((m = match(/\d+(?:\.\d+)?/y))) {
                push(m[0], { kind: 'num' });
                continue;
            }
            if ((m = match(ZH_NUMBER))) {
                let raw = m[0];
                let next = s[i + raw.length] || '';
                const yiWord = raw.length > 1 && raw.endsWith('一') && !raw.includes('點') && inSet(YI_WORD_NEXT, next);
                if (yiWord) raw = raw.slice(0, -1);
                const value = parseCnNumber(raw);
                const ok = value !== null && !inSet(NUM_BAD_PREV, prev)
                    && (yiWord || !isHan(next) || inSet(NUM_OK_NEXT, next));
                push(raw, ok ? { kind: 'num', value } : { kind: 'text' });
                continue;
            }
            if ((m = match(/[A-Za-z]+/y))) {
                push(m[0], letterToken(m[0]));
                continue;
            }
            if ((m = match(/\s+/y))) {
                push(m[0], { kind: 'space' });
                continue;
            }
            push(s[i], { kind: 'text' });
        }
        return tokens;
    }

    function zhPower(m, rest) {
        let exp = m[2] ? '2' : m[3] ? '3' : null;
        if (m[5]) {
            const n = /^(?:\d+|[A-Za-z])$/.test(m[5]) ? m[5] : parseCnInt(m[5]);
            exp = n === null ? null : (m[4] ? '-' : '') + n;
        }
        const sym = exp === null ? null : superscript(exp);
        return { kind: 'pow', sym, blocked: !sym || POWER_BLOCKED_BEFORE.test(rest) };
    }

    function letterToken(word) {
        const lower = word.toLowerCase();
        if (lower === 'pi') return { kind: 'const', sym: 'π' };
        if (lower === 'theta') return { kind: 'const', sym: 'θ' };
        return word.length <= 3 ? { kind: 'var' } : { kind: 'text' };
    }

    const EN_UNITS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
        'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen'];
    const EN_TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'];
    const EN_ORDINALS = ['zeroth', 'first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth'];

    const EN_NUMBER = `(?:${EN_TENS.slice(2).join('|')})(?:[-\\s](?:${EN_UNITS.slice(1, 10).join('|')}))?|${[...EN_UNITS].reverse().join('|')}`;

    function parseEnNumber(words) {
        const [first, second] = words.toLowerCase().split(/[-\s]+/);
        if (EN_UNITS.includes(first)) return EN_UNITS.indexOf(first);
        return EN_TENS.indexOf(first) * 10 + (second ? EN_UNITS.indexOf(second) : 0);
    }

    function enPower(negative, exp) {
        const lower = exp.toLowerCase();
        let value;
        if (EN_ORDINALS.includes(lower)) value = String(EN_ORDINALS.indexOf(lower));
        else if (/^\d/.test(lower)) value = lower.match(/^\d+/)[0];
        else if (/^[a-z](?:-?th)?$/.test(lower)) value = lower[0];
        else value = String(parseEnNumber(lower));
        const sym = superscript((negative ? '-' : '') + value);
        return { kind: 'pow', sym, blocked: !sym };
    }

    const EN_RULES = [
        [/[Tt]riangle\s+([A-Z])\s?([A-Z])\s?([A-Z])\b/y, (m) => ({ kind: 'shape', sym: '△' + m[1] + m[2] + m[3] })],
        [/[Aa]ngle\s+([A-Z](?:\s?[A-Z]){0,2}|\d+)\b/y, (m) => ({ kind: 'shape', sym: '∠' + m[1].replace(/\s/g, '') })],
        [new RegExp(`(?:raised\\s+)?to\\s+the\\s+power\\s+of\\s+(?:(negative|minus)\\s+)?(\\d+|${EN_NUMBER}|[a-z])\\b`, 'iy'),
            (m) => enPower(m[1], m[2])],
        [new RegExp(`(?:raised\\s+)?to\\s+the\\s+(?:(negative|minus)\\s+)?(${EN_ORDINALS.join('|')}|\\d+(?:st|nd|rd|th)?|[a-z](?:-?th)?)(?:\\s+power)?\\b`, 'iy'),
            (m) => enPower(m[1], m[2])],
        [/squared\b/iy, () => ({ kind: 'pow', sym: '²' })],
        [/cubed\b/iy, () => ({ kind: 'pow', sym: '³' })],
        [/(?:the\s+)?(?:square\s+)?root(?:\s+of)?\b/iy, () => ({ kind: 'sqrt' })],
        [/plus\b/iy, () => ({ kind: 'bin', sym: '+' })],
        [/minus\b/iy, () => ({ kind: 'bin', sym: '-', canNeg: true })],
        [/(?:times|multiplied\s+by)\b/iy, () => ({ kind: 'bin', sym: '×' })],
        [/divided\s+by\b/iy, () => ({ kind: 'bin', sym: '÷' })],
        [/(?:(?:is\s+)?equal\s+to|equals)\b/iy, () => ({ kind: 'bin', sym: '=' })],
        [/negative\b/iy, () => ({ kind: 'neg' })],
        [/(?:open|left)\s+(?:parenthesis|paren|bracket)\b/iy, () => ({ kind: 'lparen' })],
        [/(?:close|right)\s+(?:parenthesis|paren|bracket)\b/iy, () => ({ kind: 'rparen' })],
        [/pi\b/iy, () => ({ kind: 'const', sym: 'π' })],
        [/theta\b/iy, () => ({ kind: 'const', sym: 'θ' })],
        [new RegExp(`(?:${EN_NUMBER})\\b`, 'iy'), (m) => ({ kind: 'num', value: String(parseEnNumber(m[0])) })],
    ];

    function tokenizeEnglish(s) {
        const tokens = [];
        let i = 0;
        const push = (raw, props) => { tokens.push({ raw, ...props }); i += raw.length; };
        const match = (re) => { re.lastIndex = i; return re.exec(s); };

        while (i < s.length) {
            let m;
            const wordStart = !/[A-Za-z0-9]/.test(s[i - 1] || '');
            const rule = (wordStart && matchRule(EN_RULES, match)) || matchRule(SYMBOL_WORDS, match);
            if (rule) push(rule[0][0], rule[1]);
            else if ((m = match(/\d+(?:\.\d+)?/y))) push(m[0], { kind: 'num' });
            else if ((m = match(/[A-Za-z]+/y))) push(m[0], { kind: m[0].length === 1 ? 'var' : 'text' });
            else if ((m = match(/\s+/y))) push(m[0], { kind: 'space' });
            else push(s[i], { kind: 'text' });
        }

        tokens.forEach((t, k) => {
            if (t.kind !== 'var' || !/^[aAI]$/.test(t.raw)) return;
            const next = tokens[neighborIndex(tokens, k, 1)];
            if (next && !['pow', 'bin', 'rparen'].includes(next.kind) && /^[A-Za-z]/.test(next.raw)) t.kind = 'text';
        });
        return tokens;
    }

    const ATOMS = ['num', 'var', 'const', 'shape'];

    function neighborIndex(tokens, i, dir) {
        for (let k = i + dir; k >= 0 && k < tokens.length; k += dir) {
            if (tokens[k].kind !== 'space') return k;
        }
        return -1;
    }
    const neighbor = (tokens, i, dir) => tokens[neighborIndex(tokens, i, dir)] || null;

    const endsOperand = (t) => !!t && (ATOMS.includes(t.kind) || (!!t.active && ['pow', 'rsqrt', 'rparen'].includes(t.kind)));

    const startsOperand = (t) => !!t && (ATOMS.includes(t.kind) || (!!t.active && ['sqrt', 'neg', 'lparen'].includes(t.kind)));

    const mayEndOperand = (t) => !!t && (ATOMS.includes(t.kind) || ['pow', 'rsqrt', 'rparen'].includes(t.kind));
    const isPlainAtom = (t) => !!t && (t.kind === 'num' || t.kind === 'var');

    const isQuestion = (t) => !!t && t.kind === 'text' && /^(?:多少|幾|什麼|啥|what\b|[?？])/i.test(t.raw);

    function mergeText(tokens) {
        const out = [];
        for (const t of tokens) {
            const last = out[out.length - 1];
            if (t.kind === 'text' && last && last.kind === 'text') last.raw += t.raw;
            else out.push(t);
        }
        return out;
    }

    function pairBareParens(tokens) {
        let depth = 0;
        tokens.forEach((t, i) => {
            if (t.kind === 'lparen') depth++;
            else if (t.kind === 'rparen') depth = Math.max(0, depth - 1);
            else if (t.kind === 'paren') {
                const next = neighbor(tokens, i, 1);
                if (depth > 0 && mayEndOperand(neighbor(tokens, i, -1))) { t.kind = 'rparen'; depth--; }
                else if (next && (ATOMS.includes(next.kind) || ['sqrt', 'neg', 'lparen', 'paren'].includes(next.kind))) { t.kind = 'lparen'; depth++; }
                else t.kind = 'text';
            }
        });
    }

    function resolve(tokens) {
        pairBareParens(tokens);
        let changed = true;
        while (changed) {
            changed = false;
            tokens.forEach((t, i) => {
                if (t.active) return;
                const L = neighbor(tokens, i, -1);
                const R = neighbor(tokens, i, 1);
                let uses = null;
                switch (t.kind) {
                    case 'bin':
                        if (endsOperand(L) && (startsOperand(R) || (t.sym === '=' && isQuestion(R)))) uses = [L, R];
                        else if (t.canNeg && !mayEndOperand(L) && startsOperand(R)) { t.kind = 'neg'; uses = [R]; }
                        break;
                    case 'pow':
                        if (!t.blocked && endsOperand(L)) uses = [L];
                        break;
                    case 'rsqrt': case 'rparen':
                        if (endsOperand(L)) uses = [L];
                        break;
                    case 'sqrt': case 'neg': case 'lparen':
                        if (startsOperand(R)) uses = [R];
                        break;
                    case 'const':

                        if (t.soft && (isPlainAtom(L) || isPlainAtom(R))) uses = [];
                        break;
                }
                if (uses) {
                    t.active = true;
                    uses.forEach((u) => { if (u && u.kind === 'const') u.active = true; });
                    changed = true;
                }
            });
        }
        closeOpenParens(tokens);
    }

    const isMathToken = (t) => t.active || (ATOMS.includes(t.kind) && !(t.kind === 'const' && t.soft));

    function closeOpenParens(tokens) {
        const inserts = [];
        let open = 0, last = -1;
        const flush = () => { if (open > 0 && last >= 0) inserts.push([last + 1, open]); open = 0; };
        tokens.forEach((t, i) => {
            if (t.kind === 'space') return;
            if (!isMathToken(t) || (t.kind === 'bin' && t.sym === '=')) flush();
            if (!isMathToken(t)) { last = -1; return; }
            if (t.kind === 'lparen') open++;
            else if (t.kind === 'rparen' && open > 0) open--;
            last = i;
        });
        flush();
        inserts.reverse().forEach(([at, n]) => {
            for (let k = 0; k < n; k++) tokens.splice(at, 0, { kind: 'rparen', raw: '', active: true });
        });
    }

    function markNumbers(tokens) {
        const TAKES_LEFT = ['bin', 'pow', 'rsqrt', 'rparen', 'sqrt'];
        const TAKES_RIGHT = ['bin', 'sqrt', 'neg', 'lparen'];
        const markRun = (i, dir) => {
            for (let k = neighborIndex(tokens, i, dir); k >= 0 && k < tokens.length && ATOMS.includes(tokens[k].kind); k += dir) {
                tokens[k].inMath = true;
            }
        };
        tokens.forEach((t, i) => {
            const symbol = t.kind === 'const' && (!t.soft || t.active);
            if ((t.active && TAKES_LEFT.includes(t.kind)) || symbol) markRun(i, -1);
            if ((t.active && TAKES_RIGHT.includes(t.kind)) || symbol) markRun(i, 1);
        });
    }

    function operandStart(tokens, end) {
        const t = tokens[end];
        if (t.kind === 'rparen' && t.active) {
            let depth = 0;
            for (let k = end; k >= 0; k--) {
                if (tokens[k].kind === 'rparen' && tokens[k].active) depth++;
                else if (tokens[k].kind === 'lparen' && tokens[k].active && --depth === 0) return k;
            }
            return end;
        }
        if (t.kind === 'pow' && t.active) return operandStart(tokens, neighborIndex(tokens, end, -1));
        let start = end;
        while (start > 0 && ATOMS.includes(tokens[start - 1].kind)) start--;
        return start;
    }

    function negatedEnd(tokens, k) {
        if (k >= 0 && tokens[k].kind === 'sqrt' && tokens[k].active) k = neighborIndex(tokens, k, 1);
        if (k < 0 || !ATOMS.includes(tokens[k].kind)) return -1;
        while (k + 1 < tokens.length && ATOMS.includes(tokens[k + 1].kind)) k++;
        return k;
    }

    function dropSpace(tokens, i) {
        const p = neighbor(tokens, i, -1);
        const n = neighbor(tokens, i, 1);
        if (n && n.active && ['pow', 'rsqrt', 'rparen'].includes(n.kind)) return true;
        if (p && p.active && ['sqrt', 'neg', 'lparen'].includes(p.kind)) return true;

        const atom = (t) => !!t && ['num', 'var', 'const'].includes(t.kind);
        const symbol = (t) => !!t && t.kind === 'const' && (!t.soft || t.active);
        return atom(p) && atom(n) && (symbol(p) || symbol(n));
    }

    function render(tokens) {
        const before = new Map();
        const after = new Map();
        const closeAfter = (k) => after.set(k, (after.get(k) || 0) + 1);

        tokens.forEach((t, i) => {
            if (t.kind !== 'rsqrt' || !t.active) return;
            const end = neighborIndex(tokens, i, -1);
            const start = operandStart(tokens, end);
            const grouped = start === end || tokens[start].kind === 'lparen';
            before.set(start, (before.get(start) || '') + (grouped ? '√' : '√('));
            if (!grouped) closeAfter(end);
        });

        const piece = (t, i) => {
            if (t.kind === 'space') return dropSpace(tokens, i) ? '' : t.raw;
            if (t.kind === 'num') return t.inMath && t.value !== undefined ? t.value : t.raw;
            if (t.kind === 'const') return t.soft && !t.active ? t.raw : t.sym;
            if (t.kind === 'shape') return t.sym;
            if (!t.active) return t.raw;
            switch (t.kind) {
                case 'bin': case 'pow': return t.sym;
                case 'sqrt': return '√';
                case 'rsqrt': return '';
                case 'lparen': return '(';
                case 'rparen': return ')';
                case 'neg': {

                    const end = negatedEnd(tokens, neighborIndex(tokens, i, 1));
                    const prevOp = neighbor(tokens, i, -1);
                    const nextOp = end >= 0 ? neighbor(tokens, end, 1) : null;
                    const wrap = end >= 0 && ((nextOp && nextOp.kind === 'pow' && nextOp.active)
                        || (prevOp && prevOp.kind === 'bin' && prevOp.active && prevOp.sym !== '='));
                    if (!wrap) return '-';
                    closeAfter(end);
                    return '(-';
                }
            }
            return t.raw;
        };

        let out = '';
        tokens.forEach((t, i) => {
            out += (before.get(i) || '') + piece(t, i) + ')'.repeat(after.get(i) || 0);
        });
        return out;
    }

    const isEnglish = (lang) => /^en/i.test(lang || '');

    function analyze(text, lang) {
        const tokens = mergeText(isEnglish(lang) ? tokenizeEnglish(text) : tokenizeChinese(text));
        resolve(tokens);
        markNumbers(tokens);
        return tokens;
    }

    function convert(text, lang) {
        return text ? render(analyze(text, lang)) : text;
    }

    function score(text, lang) {
        if (!text) return 0;
        return analyze(text, lang).filter((t) => t.kind === 'shape'
            || (t.kind === 'const' ? !t.soft || t.active : !!t.active)).length;
    }

    function joinSpeech(a, b, english) {
        if (!a || !b) return a + b;
        if (english) return /\s$/.test(a) || /^\s/.test(b) ? a + b : `${a} ${b}`;
        return a + (isHan(a.slice(-1)) || isHan(b.trimStart()[0]) ? b.trimStart() : b);
    }

    function pick(candidates, lang) {
        const english = isEnglish(lang);
        let text = '';
        for (const alternatives of candidates) {
            let best = '', bestScore = -1;
            for (const alt of alternatives) {
                const s = score(joinSpeech(text, alt, english), lang);
                if (s > bestScore) { best = alt; bestScore = s; }
            }
            text = joinSpeech(text, best, english);
        }
        return text;
    }

    return { convert, pick };
})();
