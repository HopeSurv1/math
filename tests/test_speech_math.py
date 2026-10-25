import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "src" / "frontend"

ASCII_JSON = r"""JSON.stringify(__VALUE__)
    .replace(/[\u007f-\uffff]/g, (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'))"""

CONVERTER_PAGE = r"""<!DOCTYPE html><meta charset="utf-8">
<script src="__SCRIPT__"></script>
<pre id="testOut"></pre>
<script>
const results = __CASES__.map(([method, ...args]) => {
    try { return SpeechMath[method](...args); } catch (e) { return 'ERROR: ' + e; }
});
document.getElementById('testOut').textContent = __ASCII_JSON__;
</script>""".replace("__ASCII_JSON__", ASCII_JSON.replace("__VALUE__", "results"))

ZH_CONVERTED = [
    ("二的平方", "2²"),
    ("二的三次方", "2³"),
    ("2的3次方", "2³"),
    ("x的平方加y的平方等於z的平方", "x²+y²=z²"),
    ("X的平方", "X²"),
    ("請問二的平方是多少", "請問2²是多少"),
    ("三的平方加四的平方等於多少", "3²+4²=多少"),
    ("負三的平方是多少", "(-3)²是多少"),
    ("十的負三次方", "10⁻³"),
    ("二的十次方", "2¹⁰"),
    ("a的m次方乘以a的n次方", "aᵐ×aⁿ"),
    ("五的立方", "5³"),
    ("x平方加2x加1", "x²+2x+1"),
    ("三點五的平方", "3.5²"),
    ("根號二", "√2"),
    ("根號十六等於多少", "√16=多少"),
    ("二根號三", "2√3"),
    ("根號二乘以根號八", "√2×√8"),
    ("十六開根號", "√16"),
    ("三加五等於八", "3+5=8"),
    ("三加五一共是多少", "3+5一共是多少"),
    ("十減七", "10-7"),
    ("六乘以七", "6×7"),
    ("十二除以四", "12÷4"),
    ("五減負三", "5-(-3)"),
    ("負二乘以負三", "-2×(-3)"),
    ("一百零五減五", "105-5"),
    ("兩百加三百", "200+300"),
    ("x的平方減四等於零", "x²-4=0"),
    ("2x加3等於7", "2x+3=7"),
    ("2拍r", "2πr"),
    ("拍r平方", "πr²"),
    ("二拍乘以五", "2π×5"),
    ("2派r", "2πr"),
    ("圓周率乘以二", "π×2"),
    ("theta等於三十度", "θ=30度"),
    ("角ABC等於九十度", "∠ABC=90度"),
    ("角1等於角2", "∠1=∠2"),
    ("三角形ABC全等於三角形DEF", "△ABC全等於△DEF"),
    ("二乘以左括號三加四右括號", "2×(3+4)"),
    ("括號三加四括號乘以二", "(3+4)×2"),
    ("二乘以括號三加四", "2×(3+4)"),
    ("-3的平方", "(-3)²"),
    ("3+五的平方", "3+5²"),
    ("x=負三", "x=-3"),
]

ZH_UNCHANGED = [
    "什麼是平方",
    "平方是什麼意思",
    "次方是什麼",
    "平方根是什麼",
    "十六的平方根是多少",
    "x的平方根",
    "五平方公尺",
    "三立方公分",
    "一個數的平方",
    "斜邊的平方等於兩股的平方和",
    "一元二次方程式",
    "二次函數",
    "平方差公式",
    "完全平方式",
    "三分之二的平方",
    "加法和減法",
    "乘法怎麼算",
    "什麼是根號",
    "三角形的內角和是幾度",
    "直角三角形",
    "這個角是幾度",
    "圓周率是什麼",
    "我們去拍照",
    "這首歌的節拍",
    "派對",
    "等於是什麼意思",
    "我們一起加油",
    "第一加第二",
    "一半加一半",
    "增加三倍",
    "考試考了九十分",
    "你好-再見",
]

EN_CONVERTED = [
    ("x squared plus y squared equals z squared", "x² + y² = z²"),
    ("a squared plus b squared equals c squared", "a² + b² = c²"),
    ("two squared", "2²"),
    ("2 cubed", "2³"),
    ("2 to the power of 3", "2³"),
    ("two to the power of three", "2³"),
    ("2 to the third power", "2³"),
    ("x to the nth power", "xⁿ"),
    ("10 to the power of negative three", "10⁻³"),
    ("What is 2 squared?", "What is 2²?"),
    ("the square root of 16", "√16"),
    ("root 2", "√2"),
    ("3 plus 5 equals 8", "3 + 5 = 8"),
    ("10 minus 7", "10 - 7"),
    ("6 times 7", "6 × 7"),
    ("12 divided by 4", "12 ÷ 4"),
    ("negative 3 squared", "(-3)²"),
    ("5 minus negative 3", "5 - (-3)"),
    ("x equals minus 3", "x = -3"),
    ("-3 squared", "(-3)²"),
    ("2 pi r", "2πr"),
    ("angle ABC equals 90 degrees", "∠ABC = 90 degrees"),
    ("triangle ABC", "△ABC"),
    ("2 times open parenthesis 3 plus 4 close parenthesis", "2 × (3 + 4)"),
]

EN_UNCHANGED = [
    "what does squared mean",
    "what is a square root",
    "the square root of a negative number",
    "a number squared",
    "plus and minus signs",
    "go to the second page",
    "a triangle has three angles",
    "I love math",
    "a well-known fact",
]

PICKED = [
    ("zh-TW", [["二的評分", "二的平方"]], "二的平方"),
    ("zh-TW", [["什麼是平方", "什麼是評分"]], "什麼是平方"),
    ("zh-TW", [["x的平方加"], ["外的平方", "y的平方"]], "x的平方加y的平方"),
    ("zh-TW", [["根號二"], []], "根號二"),
    ("en-US", [["x squared plus"], ["why squared", "y squared"]], "x squared plus y squared"),
]


def find_browser():
    candidates = [
        os.environ.get("CHROME_PATH"),
        shutil.which("chrome"), shutil.which("google-chrome"), shutil.which("chromium"),
        shutil.which("chromium-browser"), shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    return next((p for p in candidates if p and os.path.isfile(p)), None)


def run_page(browser, page):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        page_path = Path(tmp) / "speech_test.html"
        page_path.write_text(page, encoding="utf-8")
        proc = subprocess.run(
            [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={Path(tmp) / 'profile'}", "--virtual-time-budget=10000",
             "--dump-dom", page_path.as_uri()],
            capture_output=True, timeout=120,
        )
    dom = proc.stdout.decode("utf-8", errors="replace")
    match = re.search(r'<pre id="testOut">(.*?)</pre>', dom, re.S)
    if not match or not match.group(1):
        raise AssertionError("瀏覽器沒有跑出結果（JavaScript 可能有語法錯誤）：\n" + dom[-2000:])
    return json.loads(html.unescape(match.group(1)))


class TestSpeechMath(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        browser = find_browser()
        if browser is None:
            raise unittest.SkipTest("找不到 Chrome / Edge，略過語音數學符號轉換的測試")
        cases = [["convert", text, "zh-TW"] for text, _ in ZH_CONVERTED]
        cases += [["convert", text, "zh-TW"] for text in ZH_UNCHANGED]
        cases += [["convert", text, "en-US"] for text, _ in EN_CONVERTED]
        cases += [["convert", text, "en-US"] for text in EN_UNCHANGED]
        cases += [["pick", candidates, lang] for lang, candidates, _ in PICKED]
        page = CONVERTER_PAGE.replace("__SCRIPT__", (FRONTEND / "speech_math.js").as_uri()).replace(
            "__CASES__", json.dumps(cases).replace("</", "<\\/")
        )
        outputs = run_page(browser, page)
        cls.results = {json.dumps(case): out for case, out in zip(cases, outputs)}

    def result(self, *case):
        return self.results[json.dumps(list(case))]

    def check_convert(self, lang, cases):
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.result("convert", text, lang), expected)

    def test_chinese_math_is_converted(self):
        self.check_convert("zh-TW", ZH_CONVERTED)

    def test_chinese_concepts_stay_unchanged(self):
        self.check_convert("zh-TW", [(text, text) for text in ZH_UNCHANGED])

    def test_english_math_is_converted(self):
        self.check_convert("en-US", EN_CONVERTED)

    def test_english_concepts_stay_unchanged(self):
        self.check_convert("en-US", [(text, text) for text in EN_UNCHANGED])

    def test_pick_prefers_the_candidate_that_reads_as_math(self):
        for lang, candidates, expected in PICKED:
            with self.subTest(candidates=candidates):
                self.assertEqual(self.result("pick", candidates, lang), expected)


FAKE_RECOGNITION = r"""<script>
class FakeRecognition {
    constructor() { window.__rec = this; this.calls = []; this.running = false; }
    start() { this.calls.push('start'); this.running = true; if (this.onstart) this.onstart(); }
    stop() { this.finish('stop'); }
    abort() { this.finish('abort'); }
    finish(how) {
        this.calls.push(how);
        if (!this.running) return;
        this.running = false;
        setTimeout(() => this.onend && this.onend(), 0);
    }
}
window.SpeechRecognition = FakeRecognition;
</script>"""

VOICE_SCENARIO = r"""<pre id="testOut"></pre>
<script>
window.addEventListener('load', () => {
    const out = {};
    const input = document.getElementById('userInput');
    const mic = document.getElementById('voiceInputBtn');
    // segments：[[候選1, 候選2…], 是否為最終結果]
    const say = (...segments) => window.__rec.onresult({
        resultIndex: 0,
        results: segments.map(([alternatives, isFinal]) =>
            Object.assign(alternatives.map((transcript) => ({ transcript, confidence: 0.9 })), { isFinal })),
    });

    mic.click();
    const rec = window.__rec;
    out.continuous = rec.continuous;
    out.maxAlternatives = rec.maxAlternatives;
    say([['二的評分', '二的平方'], true]);
    out.picked = input.value;
    say([['x的平方加'], true], [['y的平方'], false]);
    out.joined = input.value;

    setTimeout(() => {
        out.autoStopped = rec.calls.includes('stop');
        rec.calls.length = 0;
        input.value = '';
        mic.click();
        say([['三加五'], false]);
        document.getElementById('sendBtn').click();
        out.sendAborts = rec.calls.includes('abort');
        document.getElementById('testOut').textContent = __ASCII_JSON__;
    }, 3000);
});
</script>""".replace("__ASCII_JSON__", ASCII_JSON.replace("__VALUE__", "out"))


class TestVoiceInputPage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        browser = find_browser()
        if browser is None:
            raise unittest.SkipTest("找不到 Chrome / Edge，略過語音輸入頁面的測試")
        page = (FRONTEND / "index.html").read_text(encoding="utf-8")
        page, n_math = re.subn(
            r'<script src="speech_math\.js\?v=\d+"></script>',
            lambda m: FAKE_RECOGNITION + f'<script src="{(FRONTEND / "speech_math.js").as_uri()}"></script>',
            page,
        )
        page, n_app = re.subn(
            r'<script src="app\.js\?v=\d+"></script>',
            lambda m: f'<script src="{(FRONTEND / "app.js").as_uri()}"></script>' + VOICE_SCENARIO,
            page,
        )
        assert n_math == 1 and n_app == 1, "index.html 裡找不到 speech_math.js / app.js 的 <script>"
        cls.out = run_page(browser, page)

    def test_listens_through_pauses_and_asks_for_alternatives(self):
        self.assertTrue(self.out["continuous"])
        self.assertGreater(self.out["maxAlternatives"], 1)

    def test_picks_the_math_candidate_and_converts_it(self):
        self.assertEqual(self.out["picked"], "2²")

    def test_joins_segments_split_by_a_pause(self):
        self.assertEqual(self.out["joined"], "x²+y²")

    def test_stops_by_itself_after_a_pause(self):
        self.assertTrue(self.out["autoStopped"])

    def test_sending_discards_results_still_on_the_way(self):
        self.assertTrue(self.out["sendAborts"])


if __name__ == "__main__":
    unittest.main()
