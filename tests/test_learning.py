# -*- coding: utf-8 -*-
"""
tests/test_learning.py
功能簡介：學習歷程的測試——單元清單、AI 標記的整理、學習紀錄報告與全班總覽的計算、
          學習紀錄與管理後台的 API、背景標記、刪除時跟著清掉。Gemini 一律換成假的，不需要金鑰或網路。
執行方式：python -m unittest tests.test_learning -v
"""

import os
import sys
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

# 將 project 根目錄加入 sys.path 以便 import src 與 tests
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import curriculum
from src.api import main
from src.services import conversation_store, learning_analysis, learning_store
from src.services.learning_analysis import TurnTag
from tests.api_test_base import ApiTestCase, USERNAME

REAL_RECORD_LEARNING = main._record_learning  # ApiTestCase 預設把背景標記關掉，要測它時換回來
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)  # 台灣時間 9/27（週日）20:00


def tag(**fields):
    base = dict(unit="", concept="", activity="其他", result="", error_type="", problem="",
                same_problem=False, solved=False)
    return TurnTag(**{**base, **fields})


def event(unit="", concept="", activity="作答", result="", error_type="", problem_id="", problem="",
          solved=False, created_at="2026-09-27 10:00:00", conversation_id="c1", username=USERNAME):
    return dict(unit=unit, concept=concept, activity=activity, result=result, error_type=error_type,
                problem_id=problem_id, problem=problem, solved=solved, created_at=created_at,
                conversation_id=conversation_id, username=username)


class TestCurriculum(unittest.TestCase):

    def test_unit_codes_written_in_different_ways_are_recognised(self):
        for text in ("8上 3-2", "8上3-2", "8 上 3–2", "八上 3-2", "8上 3-2 利用十字交乘法因式分解", "利用十字交乘法因式分解"):
            with self.subTest(text=text):
                self.assertEqual(curriculum.normalize_unit(text), "8上 3-2")

    def test_chapters_with_a_single_section(self):
        self.assertEqual(curriculum.normalize_unit("7上 4 線對稱與三視圖"), "7上 4")

    def test_units_not_in_the_list_are_dropped(self):
        for text in ("", "10上 1-1", "微積分", "8上 9-9"):
            with self.subTest(text=text):
                self.assertEqual(curriculum.normalize_unit(text), "")

    def test_every_textbook_has_units(self):
        books = {unit_id.split()[0] for unit_id, _ in curriculum.UNITS}
        self.assertEqual(books, set(curriculum.SOURCE_BOOKS.values()))


class TestNormalizeTag(unittest.TestCase):

    def test_values_outside_the_allowed_choices_are_cleaned_up(self):
        result = learning_analysis.normalize_tag(
            tag(unit="8上3-2", activity="寫作業", result="正確", error_type="粗心"), None)
        self.assertEqual((result["unit"], result["activity"], result["result"], result["error_type"]),
                         ("8上 3-2", "其他", "", ""))

    def test_error_type_only_for_wrong_answers(self):
        right = learning_analysis.normalize_tag(tag(activity="作答", result="正確", error_type="計算錯誤"), None)
        wrong = learning_analysis.normalize_tag(tag(activity="作答", result="錯誤", error_type="亂猜"), None)
        self.assertEqual(right["error_type"], "")
        self.assertEqual(wrong["error_type"], "其他")

    def test_same_problem_keeps_the_problem_id(self):
        first = learning_analysis.normalize_tag(tag(activity="題目求助", problem="解 x²-5x+6=0"), None)
        second = learning_analysis.normalize_tag(tag(activity="作答", same_problem=True, solved=True), first)
        third = learning_analysis.normalize_tag(tag(activity="題目求助", problem="解 x²+x-6=0"), second)

        self.assertTrue(first["problem_id"])
        self.assertEqual(second["problem_id"], first["problem_id"])
        self.assertEqual(second["problem"], "解 x²-5x+6=0")  # 同一題沒寫題目就沿用
        self.assertTrue(second["solved"])
        self.assertNotEqual(third["problem_id"], first["problem_id"])

    def test_not_solving_anything_means_no_problem_and_not_solved(self):
        result = learning_analysis.normalize_tag(tag(activity="觀念提問", concept="畢氏定理", solved=True), None)
        self.assertEqual((result["problem_id"], result["solved"]), ("", False))

    def test_tag_turn_prompt_has_the_units_previous_problem_and_known_concepts(self):
        prompts = []

        def fake(contents, gen_config):
            prompts.append(contents)
            self.assertLessEqual(gen_config.http_options.timeout, 60_000)  # 背景標記不能一直卡著
            return SimpleNamespace(parsed=tag(unit="8上 4-1", activity="作答", result="正確"))

        previous = {"problem": "解 x²-5x+6=0", "problem_id": "p1"}
        result = learning_analysis.tag_turn(fake, "x=2 或 x=3", "答對了！", "那 x 是多少呢？", previous,
                                            ["移項要變號"])
        self.assertEqual(result["unit"], "8上 4-1")
        for expected in ("8上 3-2 利用十字交乘法因式分解", "上一輪的題目：解 x²-5x+6=0", "移項要變號",
                         "那 x 是多少呢？", "x=2 或 x=3", "答對了！"):
            self.assertIn(expected, prompts[0])

    def test_known_concepts_are_unique_and_newest_first(self):
        events = [event(concept="畢氏定理"), event(concept=""), event(concept="移項要變號"), event(concept="畢氏定理")]
        self.assertEqual(learning_analysis.known_concepts(events), ["畢氏定理", "移項要變號"])


class TestBuildReport(unittest.TestCase):

    def test_usage_counts_days_in_taiwan_time_and_estimates_minutes(self):
        times = [
            "2026-09-26 15:30:00", "2026-09-26 15:40:00",  # 台灣 9/26 23:30、23:40：同一次，10 分鐘
            "2026-09-26 16:30:00",                         # 台灣 9/27 00:30：隔了 50 分鐘，另一次、另一天
            "2026-09-10 01:00:00",                         # 兩週多以前
        ]
        usage = learning_analysis.build_report([], sorted(times), NOW)["usage"]

        self.assertEqual(usage["active_days"], 3)
        self.assertEqual((usage["questions"], usage["questions_7d"]), (4, 3))
        # 每次最後多算 3 分鐘看回覆：(10+3) + 3 + 3
        self.assertEqual((usage["minutes"], usage["minutes_7d"]), (19, 16))
        self.assertEqual(usage["last_active"], "2026-09-26 16:30:00")
        self.assertEqual(len(usage["weeks"]), 8)
        self.assertEqual(usage["weeks"][-1]["label"], "9/21")  # 這週從週一 9/21 開始
        self.assertEqual(usage["weeks"][-1]["questions"], 3)

    def test_no_activity_at_all(self):
        report = learning_analysis.build_report([], [], NOW)
        self.assertEqual((report["usage"]["questions"], report["usage"]["last_active"]), (0, None))
        self.assertIsNone(report["practice"]["accuracy"])
        self.assertEqual((report["units"], report["weak_units"]), ([], []))

    def test_practice_and_turns_to_solve(self):
        events = [
            event("8上 4-1", activity="題目求助", problem_id="p1"),
            event("8上 4-1", result="部分正確", error_type="計算錯誤", problem_id="p1", concept="移項要變號"),
            event("8上 4-1", result="正確", problem_id="p1", solved=True),
            event("8上 4-1", activity="卡住", problem_id="p2", concept="十字交乘法"),
            event("8上 2-3", activity="觀念提問", concept="畢氏定理"),
        ]
        practice = learning_analysis.build_report(events, [], NOW)["practice"]
        self.assertEqual((practice["attempts"], practice["correct"], practice["partial"], practice["stuck"]), (2, 1, 1, 1))
        self.assertEqual(practice["accuracy"], 0.5)
        self.assertEqual((practice["problems"], practice["solved"], practice["avg_turns_to_solve"]), (2, 1, 3.0))

    def test_weak_units_are_the_ones_with_the_most_mistakes(self):
        events = (
            [event("8上 3-2", result="錯誤", error_type="計算錯誤")] * 2
            + [event("8上 3-2", result="正確")]
            + [event("7上 3-2", activity="卡住"), event("7上 3-2", result="部分正確", error_type="觀念錯誤")]
            + [event("8上 2-3", result="正確")] * 5   # 問最多次、但都答對：不算要加強
        )
        report = learning_analysis.build_report(events, [], NOW)

        self.assertEqual(report["units"][0]["unit"], "8上 2-3")  # 各單元依問的次數排
        self.assertEqual([u["unit"] for u in report["weak_units"]], ["8上 3-2", "7上 3-2"])
        self.assertEqual(report["weak_units"][0]["reasons"], "答錯 2 次、答對率 33%")
        self.assertEqual(report["weak_units"][1]["reasons"], "部分正確 1 次、卡住 1 次、答對率 0%")
        self.assertEqual(report["error_types"], [{"type": "計算錯誤", "count": 2}, {"type": "觀念錯誤", "count": 1}])

    def test_weak_concepts_group_mistakes_and_link_to_the_latest_conversation(self):
        events = [
            event("8上 3-2", "十字交乘法的正負號", result="錯誤", created_at="2026-09-20 10:00:00", conversation_id="old"),
            event("7上 3-2", "移項要變號", activity="卡住", created_at="2026-09-25 10:00:00", conversation_id="c2"),
            event("8上 3-2", "十字交乘法的正負號", result="部分正確", created_at="2026-09-26 10:00:00", conversation_id="new"),
            event("8上 2-3", "畢氏定理", result="正確"),  # 答對的不算
        ]
        concepts = learning_analysis.build_report(events, [], NOW)["weak_concepts"]
        self.assertEqual([(c["concept"], c["count"]) for c in concepts], [("十字交乘法的正負號", 2), ("移項要變號", 1)])
        self.assertEqual(concepts[0]["conversation_id"], "new")
        self.assertEqual(concepts[0]["title"], "利用十字交乘法因式分解")

    def test_recent_mistakes_are_newest_first(self):
        events = [event("8上 3-2", result="錯誤", problem=f"第 {i} 題") for i in range(7)]
        mistakes = learning_analysis.build_report(events, [], NOW)["recent_mistakes"]
        self.assertEqual([m["problem"] for m in mistakes], ["第 6 題", "第 5 題", "第 4 題", "第 3 題", "第 2 題"])


class TestBuildOverview(unittest.TestCase):

    def test_class_overview(self):
        events = [
            event("8上 3-2", result="錯誤", username="小華"),
            event("8上 3-2", activity="卡住", username="小明"),
            event("8上 3-2", result="正確", username="小美"),
            event("8上 2-3", result="正確", username="小華"),
        ]
        times = [("小華", "2026-09-27 09:00:00"), ("小明", "2026-09-10 09:00:00"), ("小美", "2026-09-26 09:00:00")]
        overview = learning_analysis.build_overview(["小華", "小明", "小美", "新來的"], events, times, NOW)

        self.assertEqual(overview["totals"]["students"], 4)
        self.assertEqual(overview["totals"]["active_7d"], 2)
        self.assertEqual(overview["totals"]["accuracy"], round(2 / 3, 2))
        top = overview["units"][0]
        self.assertEqual((top["unit"], top["students"], top["struggling"]), ("8上 3-2", 3, 2))
        self.assertEqual([s["username"] for s in overview["students"]], ["小華", "小美", "小明", "新來的"])
        self.assertEqual(overview["students"][0]["weak_unit"]["unit"], "8上 3-2")
        self.assertEqual([s["username"] for s in overview["inactive"]], ["小明", "新來的"])


class TestLearningApi(ApiTestCase):

    def setUp(self):
        super().setUp()
        self.register_and_login()
        self.conversation_id = conversation_store.create_conversation(USERNAME)

    def add_turn(self, tag_fields, conversation_id=None, username=USERNAME):
        """存一輪問答和它的學習標記，回傳學生那則訊息的 id。"""
        conversation_id = conversation_id or self.conversation_id
        message_id = conversation_store.append_message(conversation_id, "user", "學生的問題")
        conversation_store.append_message(conversation_id, "model", "老師的回覆")
        learning_store.add_event(username, conversation_id, message_id,
                                 learning_analysis.normalize_tag(tag(**tag_fields), None))
        return message_id

    def add_mistakes(self, n=3):
        for _ in range(n):
            self.add_turn(dict(unit="8上 3-2", concept="十字交乘法的正負號", activity="作答", result="錯誤",
                               error_type="計算錯誤"))

    def admin_login(self):
        self.client.post("/api/admin/login", json={"username": "admin", "password": "admin"})

    def test_learning_page_is_served(self):
        res = self.client.get("/learning")
        self.assertEqual(res.status_code, 200)
        self.assertIn("學習紀錄", res.text)

    def test_report_requires_login(self):
        self.client.post("/api/logout")
        self.assertEqual(self.client.get("/api/learning/report").status_code, 401)
        self.assertEqual(self.client.post("/api/learning/advice").status_code, 401)

    def test_report_only_has_my_own_data(self):
        self.add_mistakes(2)
        self.register("小明", "another-pw")
        other_conversation = conversation_store.create_conversation("小明")
        self.add_turn(dict(unit="9下 2-2", activity="作答", result="錯誤"), other_conversation, "小明")

        report = self.client.get("/api/learning/report").json()
        self.assertEqual(report["username"], USERNAME)
        self.assertEqual([u["unit"] for u in report["units"]], ["8上 3-2"])
        self.assertEqual(report["usage"]["questions"], 2)
        self.assertIsNone(report["advice"])

    def test_advice_needs_enough_data_and_does_not_call_gemini_otherwise(self):
        self.add_mistakes(1)
        with mock.patch.object(main, "_call_gemini") as call:
            res = self.client.post("/api/learning/advice")
        self.assertEqual(res.status_code, 400)
        call.assert_not_called()

    def test_advice_is_generated_saved_and_shown_in_the_report(self):
        self.add_mistakes(3)
        prompts = []

        def fake_call(contents, gen_config=None, optional=False, budget_s=None):
            prompts.append(contents)
            self.assertTrue(optional)  # 有時限，學生不會一直等
            return SimpleNamespace(text="你最近常在 $8上 3-2$ 弄錯正負號，加油！"), "model"

        with mock.patch.object(main, "_call_gemini", side_effect=fake_call), \
             mock.patch.object(main, "_ensure_client"):
            res = self.client.post("/api/learning/advice")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["advice"]["text"], "你最近常在 8上 3-2 弄錯正負號，加油！")  # LaTeX 也整理掉
        self.assertIn("十字交乘法的正負號", prompts[0])
        self.assertEqual(self.client.get("/api/learning/report").json()["advice"]["text"],
                         "你最近常在 8上 3-2 弄錯正負號，加油！")

    def test_advice_failure_is_reported_nicely(self):
        self.add_mistakes(3)
        with mock.patch.object(main, "_call_gemini", side_effect=Exception("503 UNAVAILABLE")), \
             mock.patch.object(main, "_ensure_client"):
            res = self.client.post("/api/learning/advice")
        self.assertEqual(res.status_code, 503)
        self.assertIsNone(learning_store.get_advice(USERNAME))

    def test_admin_endpoints_require_admin(self):
        for res in (self.client.get("/api/admin/learning/overview"),
                    self.client.get("/api/admin/learning/report", params={"username": USERNAME}),
                    self.client.post("/api/admin/learning/advice", json={"username": USERNAME})):
            self.assertEqual(res.status_code, 401)

    def test_admin_overview_and_student_report(self):
        self.add_mistakes(2)
        self.admin_login()

        overview = self.client.get("/api/admin/learning/overview").json()
        self.assertEqual([s["username"] for s in overview["students"]], [USERNAME])
        self.assertEqual(overview["units"][0]["unit"], "8上 3-2")
        self.assertEqual(overview["reflection"]["total"], 0)

        report = self.client.get("/api/admin/learning/report", params={"username": USERNAME}).json()
        self.assertEqual(report["weak_units"][0]["unit"], "8上 3-2")
        self.assertEqual(self.client.get("/api/admin/learning/report", params={"username": "沒有這個人"}).status_code, 404)

    def test_admin_can_generate_advice_for_a_student(self):
        self.add_mistakes(3)
        self.admin_login()
        with mock.patch.object(main, "_call_gemini", return_value=(SimpleNamespace(text="多練習十字交乘"), "model")), \
             mock.patch.object(main, "_ensure_client"):
            res = self.client.post("/api/admin/learning/advice", json={"username": USERNAME})
        self.assertEqual(res.json()["advice"]["text"], "多練習十字交乘")
        self.assertEqual(learning_store.get_advice(USERNAME)["text"], "多練習十字交乘")


class TestBackgroundTagging(ApiTestCase):

    def setUp(self):
        super().setUp()
        self.register_and_login()
        patcher = mock.patch.object(main, "_record_learning", REAL_RECORD_LEARNING)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_client(self, *tags):
        tags, prompts = list(tags), []

        def generate_content(model, contents, config=None):
            prompts.append(contents)
            result = tags.pop(0)
            if isinstance(result, Exception):
                raise result
            return SimpleNamespace(parsed=result)

        return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)), prompts

    def chat(self, message, reply, conversation_id=None, client=None):
        fake_chat = SimpleNamespace(get_history=lambda: [], send_message=lambda parts: SimpleNamespace(text=reply))
        with mock.patch.object(main, "get_or_create_chat", return_value=fake_chat), \
             mock.patch.object(main, "prefetch_context", return_value=None), \
             mock.patch.object(main, "global_client", client):
            return self.client.post("/api/chat", json={"message": message, "conversation_id": conversation_id,
                                                       "request_id": "turn-1"}).json()

    def test_each_turn_is_tagged_after_the_reply(self):
        client, prompts = self.fake_client(
            tag(unit="8上 4-1", activity="題目求助", problem="解 x²-5x+6=0", concept="因式分解法"),
            tag(unit="8上 4-1", activity="作答", result="部分正確", error_type="計算錯誤", same_problem=True,
                concept="移項要變號"),
        )
        conversation_id = self.chat("x²-5x+6=0 怎麼解", "相乘 6、相加 -5 的兩個數是？", client=client)["conversation_id"]
        self.chat("x=2 或 x=-3", "再檢查一下正負號喔", conversation_id, client)

        first, second = learning_store.events_for_user(USERNAME)
        self.assertEqual((first["unit"], first["activity"]), ("8上 4-1", "題目求助"))
        self.assertEqual((second["result"], second["error_type"]), ("部分正確", "計算錯誤"))
        self.assertEqual(second["problem_id"], first["problem_id"])  # 還在解同一題
        self.assertIn("相乘 6、相加 -5 的兩個數是？", prompts[1])       # 看得到老師上一輪問了什麼
        self.assertIn("因式分解法", prompts[1])                          # 之前標過的觀念，沿用同一種寫法

    def test_tagging_failure_does_not_affect_the_student(self):
        client, _ = self.fake_client(Exception("400 INVALID_ARGUMENT"))
        data = self.chat("什麼是質數", "你覺得 7 是不是質數？", client=client)
        self.assertEqual(data["reply"], "你覺得 7 是不是質數？")
        self.assertEqual(learning_store.events_for_user(USERNAME), [])

    def test_tag_that_finishes_after_the_turn_was_stopped_is_not_saved(self):
        conversation_id = conversation_store.create_conversation(USERNAME)
        message_id = conversation_store.append_message(conversation_id, "user", "什麼是質數")
        conversation_store.delete_messages(conversation_id, [message_id])  # 學生按了停止

        client, _ = self.fake_client(tag(unit="7上 2-1", activity="觀念提問"))
        with mock.patch.object(main, "global_client", client):
            main._record_learning(USERNAME, conversation_id, message_id, "什麼是質數", "你覺得呢？", "")
        self.assertEqual(learning_store.events_for_user(USERNAME), [])


class TestDeletingRemovesLearningRecords(ApiTestCase):

    def setUp(self):
        super().setUp()
        self.register_and_login()

    def add_records(self):
        conversation_id = conversation_store.create_conversation(USERNAME)
        user_id = conversation_store.append_message(conversation_id, "user", "問題")
        reply_id = conversation_store.append_message(conversation_id, "model", "回覆")
        learning_store.add_event(USERNAME, conversation_id, user_id, {"unit": "8上 2-3", "activity": "作答"})
        learning_store.add_review(USERNAME, conversation_id, user_id, reply_id, learning_store.REVIEW_REVISED,
                                  [{"kind": "數學錯誤", "detail": "算錯"}], "原稿")
        learning_store.save_advice(USERNAME, "多練習")
        return conversation_id

    def test_deleting_a_conversation(self):
        conversation_id = self.add_records()
        self.client.delete(f"/api/conversations/{conversation_id}")
        self.assertEqual(learning_store.events_for_user(USERNAME), [])
        self.assertEqual(learning_store.review_stats()["total"], 0)

    def test_deleting_the_account(self):
        self.add_records()
        self.client.post("/api/account/delete", json={"password": "pw-1234"})
        self.assertEqual(learning_store.events_for_user(USERNAME), [])
        self.assertEqual(learning_store.review_stats()["total"], 0)
        self.assertIsNone(learning_store.get_advice(USERNAME))


if __name__ == "__main__":
    unittest.main()
