import html
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "reflection_eval"))

import make_sheet
import run_experiment
import score
from common import NO_REVIEW, WITH_REVIEW
from src.api import main
from src.config import config
from src.services import conversation_store, learning_store
from tests.api_test_base import ApiTestCase
from tests.test_reflection import BUSY, DRAFT, GIVES_ANSWER, LOOKS_FINE, REWRITTEN, FakeGemini
from tests.test_reply_images import FakeImagesMixin

BROWSER = next((b for b in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                            r"C:\Program Files\Google\Chrome\Application\chrome.exe") if os.path.exists(b)), None)

SCENARIO = {"id": "T01", "type": "直接要答案", "hint": "x＝2 或 x＝3", "history": [],
            "message": "x²-5x+6=0 的答案是多少？"}


class TestRunScenario(FakeImagesMixin, ApiTestCase):

    def setUp(self):
        super().setUp()
        self.register_and_login(run_experiment.USERNAME, run_experiment.PASSWORD)
        patcher = mock.patch.object(config, "REPLY_REVIEW", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.results = Path(tmp.name)
        (self.results / "images").mkdir()

    def run_with(self, fake, draft=DRAFT, scenario=SCENARIO, send_error=None):
        def send_message(parts):
            if send_error:
                raise send_error
            return SimpleNamespace(text=draft)

        fake_chat = SimpleNamespace(get_history=lambda: [], send_message=send_message)

        def call(contents, gen_config=None, optional=False, budget_s=None, models=None):
            return fake(contents, gen_config, budget_s), "model"

        with mock.patch.object(main, "get_or_create_chat", return_value=fake_chat), \
             mock.patch.object(main, "prefetch_context", return_value=None), \
             mock.patch.object(main, "_call_gemini", side_effect=call):
            return run_experiment.run_scenario(self.client, scenario, self.results)

    def test_rewritten_reply_keeps_both_the_draft_and_the_final_reply(self):
        image_url = self.make_image()
        image_name = image_url.rsplit("/", 1)[1]
        record = self.run_with(FakeGemini(reviews=[GIVES_ANSWER], rewrites=[f"[圖1]\n{REWRITTEN}"]),
                               draft=f"![圖]({image_url})\n{DRAFT}")

        self.assertEqual(record["status"], learning_store.REVIEW_REVISED)
        self.assertIn(DRAFT, record["draft"])
        self.assertIn(REWRITTEN, record["final"])
        self.assertNotIn(DRAFT, record["final"])
        self.assertEqual(record["problems"][0]["kind"], "直接給答案")
        self.assertGreaterEqual(record["total_seconds"], record["review_seconds"])
        self.assertTrue((self.results / "images" / image_name).exists())
        self.assertFalse((run_experiment.GENERATED_DIR / image_name).exists())
        self.assertIn(f"images/{image_name}", record["draft"])
        self.assertIn(f"images/{image_name}", record["final"])

    def test_reply_that_passes_has_the_same_draft_and_final_reply(self):
        record = self.run_with(FakeGemini(reviews=[LOOKS_FINE]))
        self.assertEqual(record["status"], learning_store.REVIEW_OK)
        self.assertEqual(record["draft"], DRAFT)
        self.assertEqual(record["final"], DRAFT)

    def test_earlier_conversation_is_written_before_the_question(self):
        scenario = dict(SCENARIO, history=[["user", "x²-5x+6=0 要怎麼解？"],
                                           ["model", "哪兩個數相乘是 6、相加是 -5 呢？"]],
                        message="-2 和 -3")
        fake = FakeGemini(reviews=[LOOKS_FINE])
        self.run_with(fake, scenario=scenario)

        [conversation] = conversation_store.list_conversations(run_experiment.USERNAME)
        texts = [m["text"] for m in conversation_store.load_messages_for_display(conversation["id"])]
        self.assertEqual(texts[:3], ["x²-5x+6=0 要怎麼解？", "哪兩個數相乘是 6、相加是 -5 呢？", "-2 和 -3"])
        self.assertIn("哪兩個數相乘是 6", str(fake.review_prompts[0]))

    def test_turn_without_a_review_is_not_recorded(self):
        with self.assertRaises(run_experiment.ScenarioFailed):
            self.run_with(FakeGemini(reviews=[BUSY]))

    def test_turn_where_the_teacher_failed_is_not_recorded(self):
        with self.assertRaises(run_experiment.ScenarioFailed):
            self.run_with(FakeGemini(), send_error=ValueError("壞掉了"))


def _record(qid, kind, draft, final, total, review):
    return {"id": qid, "type": kind, "status": "ok" if draft == final else "revised", "problems": [],
            "draft": draft, "final": final, "total_seconds": total, "review_seconds": review}


SCENARIOS = [{"id": q, "type": t, "hint": "提示", "history": h, "message": f"{q} 的問題"} for q, t, h in [
    ("X1", "觀念題（對照組）", []),
    ("X2", "直接要答案", []),
    ("X3", "學生答錯", [["user", "怎麼解？"], ["model", "你覺得呢？"]]),
    ("X4", "學生答錯", []),
]]
RAW = {
    "X1": _record("X1", "觀念題（對照組）", "質數是…", "質數是…", 10, 2),
    "X2": _record("X2", "直接要答案", "答案是 4", "你覺得要先做什麼？", 20, 4),
    "X3": _record("X3", "學生答錯", "還差一點喔", "再想想看", 30, 6),
    "X4": _record("X4", "學生答錯", "答錯了喔", "完全正確！", 40, 8),
}
JUDGED = {("X2", NO_REVIEW): "直接給答案", ("X4", WITH_REVIEW): "數學錯誤"}


class TestSheetAndScore(unittest.TestCase):

    def fill(self, rows, key, extra=None):
        filled = []
        for row in rows:
            row = dict(zip(make_sheet.COLUMNS, row))
            qid = row["題號"]
            for side in ("A", "B"):
                version = NO_REVIEW if key[qid] == "same" else key[qid][side]
                problem = JUDGED.get((qid, version))
                if problem and not (key[qid] == "same" and side == "B"):
                    row[f"{side}{problem}"] = "1"
            row.update((extra or {}).get(qid, {}))
            filled.append(row)
        return filled

    def test_default_sheet_puts_the_draft_in_a_and_the_final_reply_in_b(self):
        rows, key = make_sheet.build_sheet(SCENARIOS, RAW)
        by_id = {row[0]: dict(zip(make_sheet.COLUMNS, row)) for row in rows}
        self.assertEqual(key["X1"], "same")
        self.assertEqual(by_id["X1"]["回覆B"], make_sheet.SAME)
        for qid in ("X2", "X3", "X4"):
            self.assertEqual(key[qid], {"A": NO_REVIEW, "B": WITH_REVIEW})
            self.assertEqual((by_id[qid]["回覆A"], by_id[qid]["回覆B"]), (RAW[qid]["draft"], RAW[qid]["final"]))
        result = score.score(self.fill(rows, key), key, RAW)
        self.assertEqual(result["counts"][NO_REVIEW]["直接給答案"], 1)
        self.assertEqual(result["counts"][WITH_REVIEW]["數學錯誤"], 1)

    def test_sheet_hides_which_reply_went_through_the_review(self):
        rows, key = make_sheet.build_sheet(SCENARIOS, RAW, blind=True)
        by_id = {row[0]: dict(zip(make_sheet.COLUMNS, row)) for row in rows}
        self.assertEqual(key["X1"], "same")
        self.assertEqual(by_id["X1"]["回覆B"], make_sheet.SAME)
        for qid in ("X2", "X3", "X4"):
            versions = {key[qid]["A"]: by_id[qid]["回覆A"], key[qid]["B"]: by_id[qid]["回覆B"]}
            self.assertEqual(versions, {NO_REVIEW: RAW[qid]["draft"], WITH_REVIEW: RAW[qid]["final"]})
        self.assertEqual(by_id["X3"]["先前對話"], "學生：怎麼解？\n老師：你覺得呢？")
        self.assertEqual(make_sheet.build_sheet(SCENARIOS, RAW, blind=True)[1], key)
        self.assertTrue(any(key[q] != {"A": NO_REVIEW, "B": WITH_REVIEW} for q in ("X2", "X3", "X4")))

    def test_score_counts_the_five_numbers(self):
        rows, key = make_sheet.build_sheet(SCENARIOS, RAW, blind=True)
        result = score.score(self.fill(rows, key), key, RAW)

        self.assertEqual(result["n"], 4)
        self.assertEqual(result["counts"][NO_REVIEW], {"直接給答案": 1, "數學錯誤": 0, "與課本不一致": 0})
        self.assertEqual(result["counts"][WITH_REVIEW], {"直接給答案": 0, "數學錯誤": 1, "與課本不一致": 0})
        self.assertEqual(result["fixed"], ["X2"])
        self.assertEqual(result["needless"], ["X3", "X4"])
        self.assertEqual(result["made_worse"], ["X4"])
        self.assertEqual(result["seconds"], {NO_REVIEW: 20.0, WITH_REVIEW: 25.0})
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["reviewer"], {"real": ["X2"], "caught": ["X2"], "missed": [],
                                              "rewritten": ["X2", "X3", "X4"]})
        self.assertIn("改寫的準確率：1／3（33%）", score.report(result))
        self.assertIn("抓到率：1／1（100%）", score.report(result))
        table = score.report(result)
        self.assertIn("| 無反思 | 1／4 | 0 | 0 | — | 20.0 秒 |", table)
        self.assertIn("| 有反思 | 0／4 | 1 | 0 | 2 | 25.0 秒 |", table)

    def test_unreadable_marks_are_reported(self):
        rows, key = make_sheet.build_sheet(SCENARIOS, RAW)
        result = score.score(self.fill(rows, key, extra={"X1": {"A與課本不一致": "大概有"}}), key, RAW)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("X1", result["warnings"][0])

    def test_sheet_round_trips_and_is_not_overwritten(self):
        rows, key = make_sheet.build_sheet(SCENARIOS, RAW)
        with tempfile.TemporaryDirectory() as tmp:
            sheet_path, _ = make_sheet.write_sheet(rows, key, results_dir=tmp)
            read_back = score.read_sheet(sheet_path)
            self.assertEqual([r["題號"] for r in read_back], ["X1", "X2", "X3", "X4"])
            self.assertEqual(read_back[2]["先前對話"], "學生：怎麼解？\n老師：你覺得呢？")
            with self.assertRaises(SystemExit):
                make_sheet.write_sheet(rows, key, results_dir=tmp)

    def test_sheet_saved_by_excel_as_big5_can_be_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sheet.csv")
            with open(path, "w", encoding="cp950", newline="") as f:
                f.write("題號,A直接給答案\nX2,1\n")
            self.assertEqual(score.read_sheet(path), [{"題號": "X2", "A直接給答案": "1"}])

    def test_judge_page_has_no_answer_key_and_survives_script_tags_in_replies(self):
        raw = dict(RAW, X2=dict(RAW["X2"], draft="答案是 4</script><b>"))
        rows, _ = make_sheet.build_sheet(SCENARIOS, raw)
        page = make_sheet.build_page(rows)
        self.assertNotIn(NO_REVIEW, page)
        self.assertNotIn(WITH_REVIEW, page)
        self.assertEqual(page.count("</script>"), 1)

    @unittest.skipUnless(BROWSER, "找不到 Edge / Chrome，略過網頁測試")
    def test_ticks_in_the_judge_page_export_a_csv_that_score_reads(self):
        rows, key = make_sheet.build_sheet(SCENARIOS, RAW)
        ticks = []
        for (qid, version), kind in JUDGED.items():
            side = "A" if key[qid] == "same" else next(s for s in "AB" if key[qid][s] == version)
            ticks.append(f'mark("{qid}").{side}[{list(make_sheet.KINDS).index(kind)}] = true;')
        script = ("<script>" + "".join(ticks) + 'mark("X1").done = true;'
                  'mark("X3").note = "備註，含 \\"引號\\"";'
                  'const pre = document.createElement("pre"); pre.id = "csv"; pre.textContent = buildCsv();'
                  "document.body.appendChild(pre);</script></body>")
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "judge.html"
            page.write_text(make_sheet.build_page(rows).replace("</body>", script), encoding="utf-8")
            dom = subprocess.run([BROWSER, "--headless=new", "--disable-gpu", "--dump-dom", page.as_uri()],
                                 capture_output=True, timeout=90).stdout.decode("utf-8")
            csv_text = html.unescape(re.search(r'<pre id="csv">(.*?)</pre>', dom, re.S).group(1))
            exported = Path(tmp) / "exported.csv"
            exported.write_text(csv_text, encoding="utf-8-sig")
            read_back = score.read_sheet(exported)

        self.assertEqual([r["題號"] for r in read_back], ["X1", "X2", "X3", "X4"])
        self.assertEqual(read_back[2]["備註"], '備註，含 "引號"')
        result = score.score(read_back, key, RAW)
        self.assertEqual(result["counts"][NO_REVIEW], {"直接給答案": 1, "數學錯誤": 0, "與課本不一致": 0})
        self.assertEqual(result["counts"][WITH_REVIEW], {"直接給答案": 0, "數學錯誤": 1, "與課本不一致": 0})
        self.assertEqual(result["warnings"], [])

    def test_scenarios_file_is_well_formed(self):
        scenarios = run_experiment.load_scenarios()
        self.assertEqual(len(scenarios), 100)
        self.assertEqual(len({s["id"] for s in scenarios}), 100)
        for s in scenarios:
            self.assertTrue(s["message"] and s["hint"] and s["type"])
            for role, text in s["history"]:
                self.assertIn(role, ("user", "model"))
            if s["type"] in ("學生答錯", "只答對一部分"):
                self.assertTrue(s["history"], f"{s['id']} 要先有老師的引導問題，學生的答案才接得起來")


if __name__ == "__main__":
    unittest.main()
