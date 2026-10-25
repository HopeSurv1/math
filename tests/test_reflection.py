import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api import main
from src.config import config
from src.services import conversation_store, learning_store, reflection
from src.services.reflection import ReplyReview, ReviewProblem
from tests.api_test_base import ApiTestCase, USERNAME
from tests.test_reply_images import FakeImagesMixin

LOOKS_FINE = ReplyReview(ok=True, problems=[])
GIVES_ANSWER = ReplyReview(ok=False, problems=[ReviewProblem(kind="直接給答案", detail="直接說出 x=2 或 x=3，應該改成引導學生自己找。")])
WRONG_SUM = ReplyReview(ok=False, problems=[ReviewProblem(kind="數學錯誤", detail="9+16 應該是 25，不是 24。")])
BUSY = Exception("503 UNAVAILABLE. This model is currently experiencing high demand.")

DRAFT = "x²-5x+6=0 可以分解成 (x-2)(x-3)=0，所以 x=2 或 x=3。"
REWRITTEN = "我們先找兩個數：相乘是 6、相加是 -5，你覺得是哪兩個數呢？"


class FakeGemini:

    def __init__(self, reviews=(), rewrites=()):
        self.reviews, self.rewrites = list(reviews), list(rewrites)
        self.review_prompts, self.rewrite_prompts, self.rewrite_configs, self.budgets = [], [], [], []
        self.steps = []

    def __call__(self, contents, gen_config, budget_s, step=None):
        self.budgets.append(budget_s)
        self.steps.append(step)
        if gen_config.response_schema is not None:
            self.review_prompts.append(contents)
            result = self.reviews.pop(0)
            if isinstance(result, Exception):
                raise result
            return SimpleNamespace(parsed=result, text=result.model_dump_json())
        self.rewrite_prompts.append(contents)
        self.rewrite_configs.append(gen_config)
        result = self.rewrites.pop(0)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(text=result)


def reflect(fake, draft=DRAFT, message="我不會解 x²-5x+6=0", recent=(), references=""):
    return reflection.reflect(fake, draft, message, list(recent), references, "老師的教學紀律")


class TestReflect(unittest.TestCase):

    def test_reply_that_passes_is_sent_as_is(self):
        fake = FakeGemini(reviews=[LOOKS_FINE])
        result = reflect(fake)
        self.assertEqual((result.reply, result.status, result.draft), (DRAFT, learning_store.REVIEW_OK, ""))
        self.assertEqual(fake.rewrite_prompts, [])

    def test_reply_with_problems_is_rewritten_with_the_review_notes(self):
        fake = FakeGemini(reviews=[GIVES_ANSWER], rewrites=[f"  {REWRITTEN}\n"])
        result = reflect(fake)

        self.assertEqual(result.reply, REWRITTEN)
        self.assertEqual(result.status, learning_store.REVIEW_REVISED)
        self.assertEqual(result.draft, DRAFT)
        self.assertEqual(result.problems, [{"kind": "直接給答案", "detail": GIVES_ANSWER.problems[0].detail}])
        prompt = fake.rewrite_prompts[0]
        self.assertIn(DRAFT, prompt)
        self.assertIn(GIVES_ANSWER.problems[0].detail, prompt)
        self.assertEqual(fake.rewrite_configs[0].system_instruction, "老師的教學紀律")

    def test_rewritten_reply_is_not_checked_again(self):
        fake = FakeGemini(reviews=[WRONG_SUM], rewrites=[REWRITTEN])
        reflect(fake)
        self.assertEqual(len(fake.review_prompts), 1)

    def test_ok_with_leftover_notes_counts_as_passing(self):
        fake = FakeGemini(reviews=[ReplyReview(ok=True, problems=[ReviewProblem(kind="數學錯誤", detail="語氣可以再活潑一點")])])
        self.assertEqual(reflect(fake).status, learning_store.REVIEW_OK)

    def test_unknown_problem_kind_is_recorded_as_other(self):
        fake = FakeGemini(reviews=[ReplyReview(ok=False, problems=[ReviewProblem(kind="排版", detail="太長了")])],
                          rewrites=[REWRITTEN])
        self.assertEqual(reflect(fake).problems[0]["kind"], "其他")

    def test_review_that_fails_sends_the_draft(self):
        fake = FakeGemini(reviews=[BUSY])
        result = reflect(fake)
        self.assertEqual((result.reply, result.status), (DRAFT, learning_store.REVIEW_SKIPPED))

    def test_rewrite_that_fails_sends_the_draft_but_keeps_the_problems(self):
        for failure in (BUSY, "   "):
            with self.subTest(failure=failure):
                result = reflect(FakeGemini(reviews=[GIVES_ANSWER], rewrites=[failure]))
                self.assertEqual((result.reply, result.status), (DRAFT, learning_store.REVIEW_FLAGGED))
                self.assertEqual(len(result.problems), 1)

    def test_no_rewrite_when_the_review_used_up_the_time(self):
        clock = iter([0.0, reflection.TOTAL_BUDGET_S - 5, reflection.TOTAL_BUDGET_S - 5, reflection.TOTAL_BUDGET_S])
        fake = FakeGemini(reviews=[GIVES_ANSWER])
        with mock.patch.object(reflection.time, "monotonic", lambda: next(clock)):
            result = reflect(fake)
        self.assertEqual(result.status, learning_store.REVIEW_FLAGGED)
        self.assertEqual(fake.rewrite_prompts, [])

    def test_rewrite_only_gets_the_time_that_is_left(self):
        fake = FakeGemini(reviews=[GIVES_ANSWER], rewrites=[REWRITTEN])
        reflect(fake)
        self.assertEqual(fake.budgets[0], reflection.REVIEW_BUDGET_S)
        self.assertLessEqual(fake.budgets[1], reflection.TOTAL_BUDGET_S)

    def test_each_call_says_which_step_it_is(self):
        fake = FakeGemini(reviews=[GIVES_ANSWER], rewrites=[REWRITTEN])
        reflect(fake)
        self.assertEqual(fake.steps, [reflection.STEP_REVIEW, reflection.STEP_REWRITE])

    def test_review_sees_recent_messages_the_question_and_the_textbook(self):
        fake = FakeGemini(reviews=[LOOKS_FINE])
        recent = [{"role": "user", "text": "什麼是一元二次方程式"},
                  {"role": "model", "text": "![圖](/generated/abc.png)\n就是最高次方是 2 的方程式"}]
        reflect(fake, recent=recent, references="[出處：8_1.pdf 第 150 頁]\n因式分解法")
        prompt = fake.review_prompts[0]
        for expected in ("學生：什麼是一元二次方程式", "老師：[圖]\n就是最高次方是 2", "我不會解 x²-5x+6=0",
                         "因式分解法", DRAFT):
            self.assertIn(expected, prompt)
        self.assertNotIn("/generated/abc.png", prompt)

        reflect(fake := FakeGemini(reviews=[LOOKS_FINE]))
        self.assertIn("這一輪沒有查課本", fake.review_prompts[0])


class TestImagesDuringRewrite(unittest.TestCase):

    IMAGE = "![直角三角形](/generated/0123abcd.png)"
    DRAFT_WITH_IMAGE = f"看看這張圖：\n\n{IMAGE}\n\n斜邊是 5。"

    def rewrite(self, rewritten):
        fake = FakeGemini(reviews=[GIVES_ANSWER], rewrites=[rewritten])
        result = reflect(fake, draft=self.DRAFT_WITH_IMAGE)
        return result.reply, fake

    def test_reviewer_and_rewriter_see_a_placeholder_instead_of_the_url(self):
        _, fake = self.rewrite("看看這張圖：\n\n[圖1]\n\n斜邊是多少呢？")
        for prompt in fake.review_prompts + fake.rewrite_prompts:
            self.assertIn("[圖1]", prompt)
            self.assertNotIn("/generated/0123abcd.png", prompt)

    def test_placeholder_is_turned_back_into_the_image(self):
        reply, _ = self.rewrite("看看這張圖：\n\n[圖1]\n\n斜邊是多少呢？")
        self.assertEqual(reply, f"看看這張圖：\n\n{self.IMAGE}\n\n斜邊是多少呢？")

    def test_image_left_out_of_the_rewrite_is_put_back_at_the_top(self):
        reply, _ = self.rewrite("斜邊是多少呢？")
        self.assertEqual(reply, f"{self.IMAGE}\n\n斜邊是多少呢？")

    def test_image_syntax_the_rewriter_made_up_is_removed(self):
        reply, _ = self.rewrite("[圖1]\n![新圖](/generated/made_up.png)\n斜邊是多少呢？")
        self.assertNotIn("made_up.png", reply)
        self.assertIn(self.IMAGE, reply)


class TestChatReflection(FakeImagesMixin, ApiTestCase):

    def setUp(self):
        super().setUp()
        self.register_and_login()
        patcher = mock.patch.object(config, "REPLY_REVIEW", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        for registry in (main._finished_turns, main._cancelled_requests):
            patcher = mock.patch.dict(registry, clear=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def chat(self, fake, message="我不會解 x²-5x+6=0", draft=DRAFT, conversation_id=None,
             prefetched=None, request_id="turn-1"):
        fake_chat = SimpleNamespace(get_history=lambda: [], send_message=lambda parts: SimpleNamespace(text=draft))
        self.models_asked = []

        def call(contents, gen_config=None, optional=False, budget_s=None, models=None):
            self.models_asked.append(models)
            return fake(contents, gen_config, budget_s), "model"

        with mock.patch.object(main, "get_or_create_chat", return_value=fake_chat), \
             mock.patch.object(main, "prefetch_context", return_value=prefetched), \
             mock.patch.object(main, "_call_gemini", side_effect=call):
            res = self.client.post("/api/chat", json={"message": message, "conversation_id": conversation_id,
                                                      "request_id": request_id})
        self.assertEqual(res.status_code, 200)
        return res.json()

    def test_student_gets_and_history_keeps_the_rewritten_reply(self):
        data = self.chat(FakeGemini(reviews=[GIVES_ANSWER], rewrites=[REWRITTEN]))

        self.assertEqual(data["reply"], REWRITTEN)
        saved = conversation_store.load_messages_for_display(data["conversation_id"])
        self.assertEqual(saved[-1]["text"], REWRITTEN)

        stats = learning_store.review_stats()
        self.assertEqual((stats["total"], stats["revised"]), (1, 1))
        self.assertEqual(stats["by_kind"], [{"kind": "直接給答案", "count": 1}])
        [record] = learning_store.recent_reviews()
        self.assertEqual((record["question"], record["draft"], record["final"]),
                         ("我不會解 x²-5x+6=0", DRAFT, REWRITTEN))

    def test_review_asks_the_cheaper_model_first_and_rewrite_the_main_model(self):
        self.chat(FakeGemini(reviews=[GIVES_ANSWER], rewrites=[REWRITTEN]))
        review_models, rewrite_models = self.models_asked
        self.assertEqual(review_models[0], config.REVIEW_MODEL)
        self.assertEqual(set(review_models), {config.REVIEW_MODEL, *main.MODEL_CANDIDATES})
        self.assertIsNone(rewrite_models)

    def test_teacher_forgets_the_draft_after_a_rewrite(self):
        conversation_id, _ = self.add_conversation_with_image()
        main.chat_sessions[conversation_id] = ("還記得原稿的聊天物件", "model")
        self.chat(FakeGemini(reviews=[GIVES_ANSWER], rewrites=[REWRITTEN]), conversation_id=conversation_id)
        self.assertNotIn(conversation_id, main.chat_sessions)

    def test_reply_that_passes_is_unchanged_and_recorded(self):
        data = self.chat(FakeGemini(reviews=[LOOKS_FINE]))
        self.assertEqual(data["reply"], DRAFT)
        self.assertEqual(learning_store.review_stats()["ok"], 1)
        self.assertEqual(learning_store.recent_reviews(), [])

    def test_review_gets_the_textbook_and_earlier_messages(self):
        conversation_id, _ = self.add_conversation_with_image()
        fake = FakeGemini(reviews=[LOOKS_FINE])
        self.chat(fake, conversation_id=conversation_id, prefetched="[出處：8_1.pdf 第 160 頁]\n因式分解法")
        prompt = fake.review_prompts[0]
        self.assertIn("因式分解法", prompt)
        self.assertIn("學生：幫我畫一個三角形", prompt)

    def test_images_in_the_reply_survive_the_rewrite(self):
        url = self.make_image()
        fake = FakeGemini(reviews=[GIVES_ANSWER], rewrites=["[圖1]\n你覺得斜邊是多少？"])
        data = self.chat(fake, message="畫一個 3、4、5 的直角三角形", draft=f"![三角形]({url})\n斜邊是 5。")
        self.assertEqual(data["reply"], f"![三角形]({url})\n你覺得斜邊是多少？")

    def test_stopping_the_turn_removes_its_review(self):
        self.chat(FakeGemini(reviews=[GIVES_ANSWER], rewrites=[REWRITTEN]))
        self.client.post("/api/chat/cancel", json={"request_id": "turn-1"})
        self.assertEqual(learning_store.review_stats()["total"], 0)

    def test_can_be_turned_off(self):
        with mock.patch.object(config, "REPLY_REVIEW", False):
            fake = FakeGemini()
            data = self.chat(fake)
        self.assertEqual(data["reply"], DRAFT)
        self.assertEqual(fake.review_prompts, [])
        self.assertEqual(learning_store.review_stats()["total"], 0)

    def test_admin_sees_the_review_records(self):
        self.chat(FakeGemini(reviews=[GIVES_ANSWER], rewrites=[REWRITTEN]))
        self.assertEqual(self.client.get("/api/admin/reviews").status_code, 401)
        self.client.post("/api/admin/login", json={"username": "admin", "password": "admin"})

        [record] = self.client.get("/api/admin/reviews").json()["reviews"]
        self.assertEqual((record["username"], record["status"], record["final"]), (USERNAME, "revised", REWRITTEN))
        overview = self.client.get("/api/admin/learning/overview").json()
        self.assertEqual(overview["reflection"]["revised"], 1)


if __name__ == "__main__":
    unittest.main()
