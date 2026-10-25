import os
import re
import struct
import sys
import tempfile
import threading
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.genai import types

from src.api import main
from src.services import conversation_store
from tests.api_test_base import GENERATED_DIR, ApiTestCase

MADE_UP_REPLY = (
    "為了讓你看得更清楚，老師幫你畫了一個直角三角形，標示了它的三個邊（兩股與斜邊）：\n\n"
    "![直角三角形與畢氏定理示意圖](/generated/pythagorean_theorem.png)\n\n"
    "你可以觀察一下圖片裡的直角三角形。"
)


class FakeImagesMixin:

    def make_image(self):
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        image = GENERATED_DIR / f"{uuid.uuid4().hex}.png"
        image.write_bytes(b"not really a png")
        self.addCleanup(image.unlink, missing_ok=True)
        return f"/generated/{image.name}"

    def fake_draw(self, prompt):
        return f"![{prompt}]({self.make_image()})"


class TestRenderMatplotlibCode(unittest.TestCase):

    def render(self, code):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.png")
            main._render_matplotlib_code(code, path)
            return os.path.getsize(path)

    def test_helper_function_sees_top_level_variables(self):
        self.assertGreater(self.render(
            "fig, ax = plt.subplots()\n"
            "def label(p, text):\n"
            "    ax.text(p[0], p[1], text)\n"
            "for i, p in enumerate(sorted([(4, 0), (0, 0), (0, 3)])):\n"
            "    label(p, chr(65 + i))\n"
        ), 0)

    def test_lambda_sees_top_level_variables(self):
        self.assertGreater(self.render(
            "a, b = 1, -2\n"
            "f = lambda x: a * x**2 + b\n"
            "xs = np.linspace(-3, 3, 50)\n"
            "plt.plot(xs, f(xs))\n"
        ), 0)

    def test_import_and_open_are_still_blocked(self):
        for code in ("import os", "open('x.txt', 'w')"):
            with self.subTest(code=code), self.assertRaises((ImportError, NameError)):
                self.render(code)

    def layout_problems(self, code, prompt=""):
        with tempfile.TemporaryDirectory() as tmp:
            return main._render_matplotlib_code(code, os.path.join(tmp, "out.png"), prompt)

    def test_normal_drawing_has_no_layout_problems(self):
        self.assertEqual(self.layout_problems(
            "fig, ax = plt.subplots()\n"
            "ax.add_patch(plt.Polygon([[0, 0], [4, 0], [0, 3]], fill=False))\n"
            "ax.text(2, -0.4, 'b')\n"
            "ax.text(-0.4, 1.5, 'a')\n"
            "ax.set_xlim(-1, 5)\nax.set_ylim(-1, 4)\nax.set_aspect('equal')\n"
        ), [])

    def test_blank_drawing_is_reported(self):
        self.assertIn("空白", self.layout_problems("fig, ax = plt.subplots()")[0])

    def test_shape_cut_off_by_the_axes_is_reported(self):
        problems = self.layout_problems(
            "fig, ax = plt.subplots()\n"
            "ax.add_patch(plt.Rectangle((0, 0), 5, 5))\n"
            "ax.set_xlim(0, 2)\nax.set_ylim(0, 2)\n"
        )
        self.assertTrue(any("超出座標軸" in p for p in problems), problems)

    def test_overlapping_labels_are_reported(self):
        problems = self.layout_problems(
            "fig, ax = plt.subplots()\n"
            "ax.plot([0, 1], [0, 1])\n"
            "ax.text(0.5, 0.5, '面積 a²')\n"
            "ax.text(0.5, 0.5, '面積 b²')\n"
        )
        self.assertTrue(any("重疊" in p for p in problems), problems)

    def test_stretched_geometry_is_reported(self):
        problems = self.layout_problems(
            "fig, ax = plt.subplots()\n"
            "ax.add_patch(plt.Polygon([[0, 0], [4, 0], [0, 3]], fill=False))\n"
            "ax.set_xlim(-1, 5)\nax.set_ylim(-1, 4)\n"
        )
        self.assertTrue(any("set_aspect('equal')" in p for p in problems), problems)

    def test_charts_and_function_graphs_are_not_reported_as_stretched(self):
        for code in (
            "plt.bar(['一', '二', '三'], [5, 7, 3])",
            "plt.hist([1, 2, 2, 3, 3, 3], bins=3)",
            "plt.pie([1, 2, 3], labels=['甲', '乙', '丙'])",
            "xs = np.linspace(-3, 3, 50)\nplt.plot(xs, xs**2)\nplt.gca().arrow(0, 0, 1, 2, head_width=0.1)",
        ):
            with self.subTest(code=code):
                self.assertEqual(self.layout_problems(code), [])

    TRIANGLE_WITH_LABELS = (
        "fig, ax = plt.subplots()\n"
        "ax.add_patch(plt.Polygon([[0, 0], [4, 0], [0, 3]], fill=False))\n"
        "ax.text(-0.3, -0.3, '$A$')\nax.text(4.1, -0.3, 'B(4, 0)')\n{extra}"
        "ax.set_xlim(-1, 5)\nax.set_ylim(-1, 4)\nax.set_aspect('equal')\n"
    )

    def test_point_names_missing_from_the_picture_are_reported(self):
        problems = self.layout_problems(self.TRIANGLE_WITH_LABELS.format(extra=""), "直角三角形ABC，∠C 為直角")
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("點 C 沒有標", problems[0])

    def test_point_names_that_are_labeled_are_not_reported(self):
        code = self.TRIANGLE_WITH_LABELS.format(extra="ax.text(-0.3, 3.1, 'C')\n")
        for prompt in ("直角三角形ABC，∠C 為直角", "△ABC，點 A 在原點，線段 AB 長 4"):
            with self.subTest(prompt=prompt):
                self.assertEqual(self.layout_problems(code, prompt), [])

    def test_symbols_missing_from_the_chinese_font_still_render(self):
        self.assertEqual(self.layout_problems(
            "fig, ax = plt.subplots()\n"
            "ax.text(0.1, 0.8, 'SAS 全等：⇒ △ABC ≅ △DEF')\n"
            "ax.text(0.1, 0.5, '相似：△ABC ∼ △DEF')\n"
            "ax.text(0.1, 0.2, '⇔ ✓ 90°')\n"
        ), [])

    def test_characters_no_font_can_draw_are_reported(self):
        for text_call in ("ax.text(0.1, 0.5, '✅ 全等')",
                          "ax.text(0.1, 0.5, '△ABC ≅ △DEF', fontfamily='DejaVu Sans')\n"
                          "ax.text(0.1, 0.2, '✅', fontfamily='DejaVu Sans')"):
            with self.subTest(code=text_call):
                problems = self.layout_problems("fig, ax = plt.subplots()\n" + text_call)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("「✅」(U+2705)", problems[0])
                self.assertIn("方框", problems[0])

    def test_only_letters_named_as_points_are_required(self):
        self.assertEqual(self.layout_problems(
            self.TRIANGLE_WITH_LABELS.format(extra=""), "用 SAS 全等說明，AB=3，x 軸上的直角三角形"
        ), [])


SMALL_PLOT = "fig, ax = plt.subplots(figsize=(2, 2))\nax.plot([0, 1], [0, 1])"
LARGE_PLOT = "fig, ax = plt.subplots(figsize=(5, 5))\nax.plot([0, 1], [0, 1])"
BLANK_PLOT = "fig, ax = plt.subplots()"
LOOKS_FINE = main._ImageReview(ok=True, problems=[])
SQUARE_INSIDE = main._ImageReview(ok=False, problems=["c² 的正方形畫進三角形裡面了，要畫在斜邊外側"])
BUSY = Exception("503 UNAVAILABLE. This model is currently experiencing high demand.")
PRIMARY, BACKUP = "primary-model", "backup-model"


def png_width(path):
    with open(path, "rb") as f:
        return struct.unpack(">I", f.read(24)[16:20])[0]


class FakeGemini:

    def __init__(self, codes=(), reviews=(), review_delays=None):
        self.codes, self.reviews = list(codes), list(reviews)
        self.code_prompts, self.code_configs, self.review_configs = [], [], []
        self.code_models, self.review_models = [], []
        self.review_delays, self.release = dict(review_delays or {}), threading.Event()

    @property
    def review_calls(self):
        return len(self.review_configs)

    def generate_content(self, model, contents, config=None):
        if config is not None and config.response_schema is not None:
            self.review_configs.append(config)
            self.review_models.append(model)
            if model in self.review_delays and self.release.wait(self.review_delays[model]):
                raise TimeoutError("卡住的呼叫被放開了")
            review = self.reviews.pop(0)
            if isinstance(review, Exception):
                raise review
            return SimpleNamespace(parsed=review, text=review.model_dump_json())
        self.code_prompts.append(contents)
        self.code_configs.append(config)
        self.code_models.append(model)
        code = self.codes.pop(0)
        if isinstance(code, Exception):
            raise code
        return SimpleNamespace(text=code)


class TestDrawingSelfCheck(unittest.TestCase):

    def setUp(self):
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        existing = set(os.listdir(GENERATED_DIR))
        self.new_files = lambda: sorted(set(os.listdir(GENERATED_DIR)) - existing)
        self.addCleanup(lambda: [os.remove(GENERATED_DIR / name) for name in self.new_files()])

    def draw(self, fake, max_fixes=1):
        self.addCleanup(fake.release.set)
        with mock.patch.object(main, "global_client", SimpleNamespace(models=fake)), \
             mock.patch.object(main, "MODEL_CANDIDATES", [PRIMARY, BACKUP]), \
             mock.patch.object(main.config, "DRAW_MAX_FIXES", max_fixes):
            result = main.generate_math_image("直角三角形，三邊外側各畫一個正方形")
        match = re.fullmatch(r"!\[[^\]]*\]\(/generated/([a-f0-9]+\.png)\)", result)
        return result, (GENERATED_DIR / match.group(1)) if match else None

    def width_of(self, code):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.png")
            main._render_matplotlib_code(code, path)
            return png_width(path)

    def test_good_drawing_is_reviewed_once_and_kept(self):
        fake = FakeGemini(codes=[SMALL_PLOT], reviews=[LOOKS_FINE])
        _, image = self.draw(fake)
        self.assertEqual(png_width(image), self.width_of(SMALL_PLOT))
        self.assertEqual((len(fake.code_prompts), fake.review_calls), (1, 1))

    def test_drawing_the_reviewer_rejects_is_redrawn_with_its_problems(self):
        fake = FakeGemini(codes=[SMALL_PLOT, LARGE_PLOT], reviews=[SQUARE_INSIDE])
        _, image = self.draw(fake)
        self.assertEqual(png_width(image), self.width_of(LARGE_PLOT))
        self.assertEqual(self.new_files(), [image.name])
        fix_prompt = fake.code_prompts[1]
        self.assertIn(SQUARE_INSIDE.problems[0], fix_prompt)
        self.assertIn(SMALL_PLOT, fix_prompt)

    def test_redraw_that_comes_out_worse_keeps_the_original(self):
        fake = FakeGemini(codes=[SMALL_PLOT, BLANK_PLOT], reviews=[SQUARE_INSIDE])
        _, image = self.draw(fake)
        self.assertEqual(png_width(image), self.width_of(SMALL_PLOT))
        self.assertEqual(self.new_files(), [image.name])

    def test_code_that_crashes_is_rewritten_with_the_error_message(self):
        fake = FakeGemini(codes=["ax = plt.gca()\nax.plot(undefined_points)", SMALL_PLOT])
        _, image = self.draw(fake)
        self.assertTrue(image.exists())
        self.assertIn("NameError", fake.code_prompts[1])

    def test_blank_drawing_is_redrawn_without_asking_the_reviewer(self):
        fake = FakeGemini(codes=[BLANK_PLOT, SMALL_PLOT])
        _, image = self.draw(fake)
        self.assertEqual(png_width(image), self.width_of(SMALL_PLOT))
        self.assertIn("空白", fake.code_prompts[1])
        self.assertEqual(fake.review_calls, 0)

    def test_gives_up_with_the_error_when_every_attempt_crashes(self):
        fake = FakeGemini(codes=["boom()", "boom()"])
        result, image = self.draw(fake)
        self.assertIsNone(image)
        self.assertTrue(result.startswith("[圖片生成失敗：程式碼執行失敗：NameError"), result)
        self.assertEqual(self.new_files(), [])

    def test_review_failure_does_not_block_the_drawing(self):
        fake = FakeGemini(codes=[SMALL_PLOT], reviews=[ValueError("回覆不是 JSON")])
        _, image = self.draw(fake)
        self.assertTrue(image.exists())
        self.assertEqual(len(fake.code_prompts), 1)

    def test_checks_can_be_turned_off(self):
        fake = FakeGemini(codes=[SMALL_PLOT])
        _, image = self.draw(fake, max_fixes=0)
        self.assertTrue(image.exists())
        self.assertEqual(fake.review_calls, 0)

    def test_busy_primary_model_check_is_done_by_the_backup_model(self):
        fake = FakeGemini(codes=[SMALL_PLOT, LARGE_PLOT], reviews=[BUSY, SQUARE_INSIDE])
        with mock.patch.object(main.time, "sleep"):
            _, image = self.draw(fake)
        self.assertEqual(fake.review_models, [PRIMARY, BACKUP])
        self.assertEqual(png_width(image), self.width_of(LARGE_PLOT))

    def test_busy_check_keeps_trying_until_the_time_limit_then_keeps_the_picture(self):
        fake = FakeGemini(codes=[SMALL_PLOT], reviews=[BUSY] * 50)
        clock = [0.0]

        def fake_sleep(seconds):
            clock[0] += seconds

        with mock.patch.object(main.time, "monotonic", lambda: clock[0]), \
             mock.patch.object(main.time, "sleep", side_effect=fake_sleep):
            _, image = self.draw(fake)
        self.assertTrue(image.exists())
        self.assertEqual(len(fake.code_prompts), 1)
        self.assertGreater(fake.review_calls, 4)
        self.assertEqual(fake.review_models[:4], [PRIMARY, BACKUP, PRIMARY, BACKUP])
        self.assertLessEqual(clock[0], main._OPTIONAL_CALL_BUDGET_S)
        self.assertTrue(all(c.http_options.timeout >= 10_000 for c in fake.review_configs))

    def fast_budget(self):
        return mock.patch.multiple(main, _OPTIONAL_CALL_BUDGET_S=0.6, _OPTIONAL_HEDGE_AFTER_S=0.05,
                                   _OPTIONAL_MIN_CALL_S=0.1)

    def test_stuck_primary_model_check_gets_a_backup_answer(self):
        fake = FakeGemini(codes=[SMALL_PLOT, LARGE_PLOT], reviews=[SQUARE_INSIDE], review_delays={PRIMARY: None})
        start = time.monotonic()
        with self.fast_budget():
            _, image = self.draw(fake)
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(fake.review_models, [PRIMARY, BACKUP])
        self.assertEqual(png_width(image), self.width_of(LARGE_PLOT))

    def test_slow_primary_model_answer_is_preferred_over_the_backup(self):
        fake = FakeGemini(codes=[SMALL_PLOT, LARGE_PLOT], reviews=[LOOKS_FINE, SQUARE_INSIDE],
                          review_delays={PRIMARY: 0.2})
        with self.fast_budget():
            _, image = self.draw(fake)
        self.assertEqual(fake.review_models, [PRIMARY, BACKUP])
        self.assertEqual(png_width(image), self.width_of(LARGE_PLOT))

    def test_busy_redraw_is_done_by_the_backup_model(self):
        fake = FakeGemini(codes=[SMALL_PLOT, BUSY, LARGE_PLOT], reviews=[SQUARE_INSIDE])
        with mock.patch.object(main.time, "sleep"):
            _, image = self.draw(fake)
        self.assertEqual(fake.code_models, [PRIMARY, PRIMARY, BACKUP])
        self.assertEqual(png_width(image), self.width_of(LARGE_PLOT))

    def test_redraw_has_a_time_limit_only_when_there_is_already_a_picture(self):
        normal_call = main._CALL_TIMEOUT_S * 1000
        with_picture = FakeGemini(codes=[SMALL_PLOT, LARGE_PLOT], reviews=[SQUARE_INSIDE])
        self.draw(with_picture)
        self.assertEqual(with_picture.code_configs[0].http_options.timeout, normal_call)
        self.assertLessEqual(with_picture.code_configs[1].http_options.timeout,
                             (main._OPTIONAL_CALL_BUDGET_S + 5) * 1000)

        without_picture = FakeGemini(codes=["boom()", SMALL_PLOT])
        self.draw(without_picture)
        self.assertEqual(without_picture.code_configs[1].http_options.timeout, normal_call)


class TestFixReplyImages(FakeImagesMixin, unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.object(main, "generate_math_image", side_effect=self.fake_draw)
        self.draw = patcher.start()
        self.addCleanup(patcher.stop)

    def test_real_image_is_kept(self):
        reply = f"看看這張圖：\n\n![三角形]({self.make_image()})\n\n你發現了什麼？"
        self.assertEqual(main._fix_reply_images(reply, [], "畫一個三角形"), reply)
        self.draw.assert_not_called()

    def test_made_up_url_is_redrawn_from_its_alt_text(self):
        fixed = main._fix_reply_images(MADE_UP_REPLY, [], "什麼是畢氏定理？可以舉個例子嗎？")

        self.assertNotIn("pythagorean_theorem.png", fixed)
        url = re.search(r"!\[直角三角形與畢氏定理示意圖\]\(([^)]+)\)", fixed).group(1)
        self.assertTrue(main._is_generated_image(url))
        self.assertTrue(fixed.startswith("為了讓你看得更清楚"))
        self.assertTrue(fixed.endswith("你可以觀察一下圖片裡的直角三角形。"))
        prompt = self.draw.call_args.args[0]
        self.assertIn("直角三角形與畢氏定理示意圖", prompt)
        self.assertIn("標示了它的三個邊", prompt)
        self.assertIn("什麼是畢氏定理", prompt)

    def test_miscopied_url_is_replaced_by_the_image_drawn_this_turn(self):
        drawn = self.make_image()
        reply = f"畫好了：\n![直角三角形]({drawn[:-6]}.png)"
        fixed = main._fix_reply_images(reply, [drawn], "畫一個直角三角形")
        self.assertEqual(fixed, f"畫好了：\n![直角三角形]({drawn})")
        self.draw.assert_not_called()

    def test_made_up_url_is_removed_when_redraw_fails(self):
        self.draw.side_effect = None
        self.draw.return_value = "[圖片生成失敗：name 'ax' is not defined]"
        fixed = main._fix_reply_images(MADE_UP_REPLY, [], "什麼是畢氏定理？")
        self.assertNotIn("![", fixed)
        self.assertIn("你可以觀察一下圖片裡的直角三角形。", fixed)

    def test_drawn_image_left_out_of_the_reply_is_added(self):
        drawn = self.make_image()
        fixed = main._fix_reply_images("直角三角形的兩股是 3 和 4。", [drawn], "畫一個直角三角形")
        self.assertEqual(fixed, f"![數學示意圖]({drawn})\n\n直角三角形的兩股是 3 和 4。")
        self.draw.assert_not_called()

    def test_only_images_drawn_this_turn_count(self):
        old, new = self.make_image(), self.make_image()

        def tool_turn(name, result):
            return types.Content(role="user", parts=[
                types.Part.from_function_response(name=name, response={"result": result})
            ])

        history = [
            types.Content(role="user", parts=[types.Part(text="上一輪的問題")]),
            tool_turn("generate_math_image", f"![舊圖]({old})"),
            types.Content(role="user", parts=[types.Part(text="這一輪的問題")]),
            tool_turn("search_math_materials", "[出處：8_1.pdf 第 3 頁] 畢氏定理…"),
            tool_turn("generate_math_image", "[圖片生成失敗：name 'ax' is not defined]"),
            tool_turn("generate_math_image", f"![新圖]({new})"),
            types.Content(role="model", parts=[types.Part(text="看看這張圖")]),
        ]
        chat = SimpleNamespace(get_history=lambda: history)
        self.assertEqual(main._images_drawn_this_turn(chat, pre_len=2), [new])


class TestChatEndpointImages(FakeImagesMixin, ApiTestCase):

    def chat(self, message, model_reply):
        fake_chat = SimpleNamespace(
            get_history=lambda: [],
            send_message=lambda parts: SimpleNamespace(text=model_reply),
        )
        with mock.patch.object(main, "get_or_create_chat", return_value=fake_chat), \
             mock.patch.object(main, "prefetch_context", return_value=None), \
             mock.patch.object(main, "generate_math_image", side_effect=self.fake_draw) as draw:
            res = self.client.post("/api/chat", json={"message": message})
        self.assertEqual(res.status_code, 200)
        return res.json(), draw

    def test_made_up_image_url_never_reaches_the_student(self):
        self.register_and_login()
        data, draw = self.chat("什麼是畢氏定理？可以舉個例子嗎？", MADE_UP_REPLY)

        self.assertNotIn("pythagorean_theorem.png", data["reply"])
        url = re.search(r"!\[直角三角形與畢氏定理示意圖\]\(([^)]+)\)", data["reply"]).group(1)
        self.assertTrue(main._is_generated_image(url))
        draw.assert_called_once()
        saved = conversation_store.load_messages_for_display(data["conversation_id"])
        self.assertEqual(saved[-1]["text"], data["reply"])

    def test_drawing_request_with_made_up_url_is_drawn_only_once(self):
        self.register_and_login()
        data, draw = self.chat("幫我畫一個直角三角形", MADE_UP_REPLY)

        draw.assert_called_once()
        self.assertEqual(len(main._IMAGE_MARKDOWN_RE.findall(data["reply"])), 1)


if __name__ == "__main__":
    unittest.main()
