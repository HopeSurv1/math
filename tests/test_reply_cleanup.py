import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api import main
from src.services import conversation_store
from src.utils.reply_cleanup import clean_reply_text
from tests.api_test_base import USERNAME, ApiTestCase

CLEANED = [
    ("並且標示了兩股 $a$、$b$ 以及斜邊 $c$：", "並且標示了兩股 a、b 以及斜邊 c："),
    ("公式是 $a^2 + b^2 = c^2$。", "公式是 a² + b² = c²。"),
    ("$a^{2}+b^{2}=c^{2}$", "a²+b²=c²"),
    ("$10^{-3}$", "10⁻³"),
    ("$x^{n+1}$", "xⁿ⁺¹"),
    ("$a_1 + a_2$", "a₁ + a₂"),
    ("$\\frac{1}{3}$", "1/3"),
    ("$\\frac{x+1}{2}$", "(x+1)/2"),
    ("$\\frac{x^{2}}{2}$", "x²/2"),
    ("$\\frac{\\sqrt{2}}{2}$", "√2/2"),
    ("$\\sqrt{2}$", "√2"),
    ("$\\sqrt{x^2+1}$", "√(x²+1)"),
    ("$\\sqrt[3]{8}$", "∛8"),
    ("$3 \\times 4 \\div 2$", "3 × 4 ÷ 2"),
    ("$x \\le 3$", "x ≤ 3"),
    ("$\\angle ABC = 90^\\circ$", "∠ABC = 90°"),
    ("$\\triangle ABC \\cong \\triangle DEF$", "△ABC ≅ △DEF"),
    ("$2\\pi r$", "2πr"),
    ("$\\pi = 3.14$", "π = 3.14"),
    ("$\\text{面積} = a^2$", "面積 = a²"),
    ("\\(x = 5\\)", "x = 5"),
    ("$$a^2+b^2=c^2$$", "a²+b²=c²"),
    ("$\\overline{AB}^2 + \\overline{AC}^2 = \\overline{BC}^2$",
     "A̅B̅² + A̅C̅² = B̅C̅²"),
    ("線段 $\\overline{AB}$ 的長度是 5", "線段 A̅B̅ 的長度是 5"),
    ("\\overline{AB} \\perp \\overline{CD}", "A̅B̅ ⊥ C̅D̅"),
    ("$\\vec{v}$ 和 $\\hat{x}$", "v 和 x"),
    ("寫成 \\frac{1}{3} 就好", "寫成 1/3 就好"),
    ("所以 x^2 = 9", "所以 x² = 9"),
    ("10^-3 公尺", "10⁻³ 公尺"),
    ("3 \\times 4 = 12", "3 × 4 = 12"),
    ("角度是 60^\\circ", "角度是 60°"),
    ("(股1的平方) + (股2の平方) = (斜邊的平方)", "(股1的平方) + (股2的平方) = (斜邊的平方)"),
    ("三角形の內角和是 180 度", "三角形的內角和是 180 度"),
]

UNCHANGED = [
    "蘋果一斤 $30，香蕉一斤 $20",
    "NT$30 和 NT$50",
    "It costs $5 and $10.",
    "好喔^^ 加油 ^_^",
    "看看這張圖：![直角三角形](/generated/0232feb6b28c4cb6a70defe69d234683.png)",
    "a² + b² = c²，√2 約等於 1.414",
    "線段 A̅B̅ 的長度是 5",
    "**粗體** 和 `程式碼`",
    "snake_case_name",
    "これは三角形の面積です。",
    "",
]


class TestCleanReplyText(unittest.TestCase):

    def test_cleans_latex_and_stray_japanese(self):
        for raw, expected in CLEANED:
            with self.subTest(raw=raw):
                self.assertEqual(clean_reply_text(raw), expected)

    def test_leaves_normal_text_alone(self):
        for text in UNCHANGED:
            with self.subTest(text=text):
                self.assertEqual(clean_reply_text(text), text)


class TestChatUsesCleanup(ApiTestCase):

    def test_new_reply_is_cleaned_before_it_is_shown_and_saved(self):
        self.register_and_login()
        raw = "標示了兩股 $a$、$b$，公式是 (股1的平方) + (股2の平方) = (斜邊的平方)"
        fake_chat = SimpleNamespace(
            get_history=lambda: [],
            send_message=lambda parts: SimpleNamespace(text=raw),
        )
        with mock.patch.object(main, "get_or_create_chat", return_value=fake_chat), \
             mock.patch.object(main, "prefetch_context", return_value=None):
            res = self.client.post("/api/chat", json={"message": "什麼是畢氏定理"})

        expected = "標示了兩股 a、b，公式是 (股1的平方) + (股2的平方) = (斜邊的平方)"
        self.assertEqual(res.json()["reply"], expected)
        saved = conversation_store.load_messages_for_display(res.json()["conversation_id"])
        self.assertEqual(saved[-1]["text"], expected)

    def test_old_replies_are_cleaned_when_the_conversation_is_opened(self):
        self.register_and_login()
        conversation_id = conversation_store.create_conversation(USERNAME)
        conversation_store.append_message(conversation_id, "user", "花 $30 買了 $x^2$ 個")
        conversation_store.append_message(conversation_id, "model", "所以 $a^2 + b^2 = c^2$")

        messages = self.client.get(f"/api/conversations/{conversation_id}/messages").json()["messages"]

        self.assertEqual(messages[0]["text"], "花 $30 買了 $x^2$ 個")
        self.assertEqual(messages[1]["text"], "所以 a² + b² = c²")


if __name__ == "__main__":
    unittest.main()
