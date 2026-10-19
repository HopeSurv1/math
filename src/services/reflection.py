# -*- coding: utf-8 -*-
"""
src/services/reflection.py
功能簡介：反思機制——老師的回覆送出前先自我檢查，有問題就改寫，學生只會看到改好的版本。
  1. 檢查：把「最近的對話、學生這次說的話、這一輪查到的課本內容、回覆草稿」交給 Gemini，
     檢查有沒有：直接給答案、數學錯誤、跟課本不一致、答非所問。
  2. 改寫：有問題就把檢查意見交回給老師（同一套教學紀律），請它只修正有問題的地方。
  3. 改寫過的不再檢查第二次；檢查或改寫沒做成（忙線、逾時）就送出原稿，不讓學生一直等。
圖片：回覆裡的 ![說明](/generated/xxx.png) 先換成 [圖1]、[圖2] 再交給 Gemini，改寫完再換回來。
      Gemini 抄網址很容易抄錯（見 main.py 的 _fix_reply_images），這樣它根本碰不到網址；
      改寫時漏掉的圖補在最前面，它自己編出來的圖片語法直接拿掉。
主要函數：
  - reflect(call_gemini, draft, ...): 檢查＋必要時改寫，回傳 Reflection（學生看到的回覆、結果、問題、原稿、花了幾秒）。
    call_gemini(contents, gen_config, budget_s, step) 由 main.py 傳進來（有時限、會換備援模型），測試時換成假的；
    step 是 STEP_REVIEW 或 STEP_REWRITE，main.py 依此決定先問哪個模型（檢查用便宜的，省主要模型的額度）。
相依模組：pydantic、google.genai.types、src.services.learning_store（檢查結果的代號）
"""

import re
import time
from dataclasses import dataclass, field
from typing import Callable, List

from google.genai import types
from pydantic import BaseModel

from src.services import learning_store
from src.utils.logger import logger

PROBLEM_KINDS = ("直接給答案", "數學錯誤", "跟課本不一致", "答非所問")

# 呼叫 call_gemini 時告訴它這是哪一步
STEP_REVIEW = "review"
STEP_REWRITE = "rewrite"

# 時限：檢查最多等這麼久；檢查＋改寫加起來最多這麼久；剩不到 _MIN_REWRITE_S 就不改寫了，直接送原稿
REVIEW_BUDGET_S = 25
TOTAL_BUDGET_S = 40
_MIN_REWRITE_S = 10

# 最近的對話只附最後幾則、每則只取前面一段，課本內容也有上限，免得每次檢查都送一大堆字
_RECENT_MESSAGES = 6
_MESSAGE_CHARS = 600
_REFERENCE_CHARS = 4000

REVIEW_INSTRUCTION = """你是國中數學家教回覆的檢查員。下面有一段師生對話，最後是老師準備傳給學生的「回覆草稿」。
這位老師用蘇格拉底提問法教學：一步一步反問、引導學生自己想出答案，不直接給出最終答案；內容要依據課本；每次都要針對學生這次說的話回應。

請檢查回覆草稿有沒有下面四種問題：
1. 直接給答案：學生正在解一道題，草稿卻直接說出這題的最終答案，或把完整的解題過程一次寫完，學生不用想就能照抄。
   以下都「不算」直接給答案：學生自己算出答案後老師確認對錯；學生問的是定義、公式、性質這類觀念（直接解釋觀念沒關係）；
   學生試了好幾次還是卡住，老師示範其中一個步驟；老師舉一個跟學生的題目不同的例子說明。
2. 數學錯誤：計算、公式、定義或推理有錯；或把學生對的答案說成錯的、錯的說成對的（學生的答案只對一部分，老師卻說「完全正確」也算）。
   只挑你確定是錯的，並寫出正確的內容。
3. 跟課本不一致：跟「課本參考資料」的講法衝突，或用了國中沒教、學生看不懂的方法（例如微積分、三角函數的公式）。
   沒有課本參考資料時，只檢查有沒有超出國中範圍。
4. 答非所問：沒有回應學生這次說的內容（例如學生換了新題目，老師還在講上一題）。

注意：
- [圖1]、[圖2] 這類標記是圖片，不用檢查。
- 語氣、排版、emoji、長短這些小地方不用挑。
- 只挑真的會讓學生學錯、或違反引導原則的問題；大致沒問題就回 ok = true、problems 留空。
- problems 的每一項：kind 只能填「直接給答案」「數學錯誤」「跟課本不一致」「答非所問」其中一個；
  detail 用繁體中文一兩句話說清楚哪裡有問題、應該怎麼改。"""

REWRITE_INSTRUCTION = """你剛剛寫好要回給學生的「回覆草稿」，自我檢查時發現了下面的問題。請依照檢查意見修改，寫出真正要傳給學生的回覆。
規則：
1. 只修正有問題的地方；其他內容、語氣、長短盡量跟草稿一樣。
2. 還是要用蘇格拉底提問法一步一步引導，不直接給出最終答案。
3. 草稿裡的 [圖1]、[圖2] 是圖片，要原封不動保留在原本的位置。
4. 只回傳修改後的回覆本身，不要加「以下是修改後的回覆」這類說明，也不要提到檢查或修改的過程。

檢查發現的問題：
{problems}"""


class ReviewProblem(BaseModel):
    kind: str
    detail: str


class ReplyReview(BaseModel):
    ok: bool
    problems: list[ReviewProblem]


@dataclass
class Reflection:
    reply: str                      # 學生實際看到的回覆
    status: str                     # learning_store.REVIEW_*
    problems: List[dict] = field(default_factory=list)  # [{"kind", "detail"}]
    draft: str = ""                 # 發現問題時留下原稿
    seconds: float = 0.0


# 回覆裡的 Markdown 圖片語法（跟 main.py 的 _IMAGE_MARKDOWN_RE 一樣）
_IMAGE_MARKDOWN_RE = re.compile(r"!\[([^\]\n]*)\]\(([^)\s]*)\)")
_PLACEHOLDER_RE = re.compile(r"\[圖(\d+)\]")


def hide_images(text: str):
    """把圖片語法換成 [圖1]、[圖2]…，回傳 (換好的文字, 依序的圖片語法清單)。"""
    images = []

    def placeholder(match):
        images.append(match.group(0))
        return f"[圖{len(images)}]"

    return _IMAGE_MARKDOWN_RE.sub(placeholder, text or ""), images


def restore_images(text: str, images: List[str]) -> str:
    """把 [圖N] 換回原本的圖片語法；Gemini 自己寫的圖片語法拿掉，漏掉的圖補在最前面。"""
    text = _IMAGE_MARKDOWN_RE.sub("", text)
    used = set()

    def image(match):
        index = int(match.group(1)) - 1
        if 0 <= index < len(images):
            used.add(index)
            return images[index]
        return ""

    text = _PLACEHOLDER_RE.sub(image, text).strip()
    missing = [img for i, img in enumerate(images) if i not in used]
    return "\n\n".join(missing + [text]) if missing else text


def _shorten(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…（以下省略）"


def build_context(student_message: str, recent_messages: List[dict], references: str) -> str:
    """檢查和改寫共用的背景資料：最近的對話、學生這次說的話、這一輪查到的課本內容。"""
    lines = ["【最近的對話】"]
    recent = recent_messages[-_RECENT_MESSAGES:]
    for m in recent:
        speaker = "學生" if m.get("role") == "user" else "老師"
        lines.append(f"{speaker}：{_shorten(_IMAGE_MARKDOWN_RE.sub('[圖]', m.get('text') or ''), _MESSAGE_CHARS)}")
    if not recent:
        lines.append("（這是對話的第一句）")
    lines += ["", "【學生這次說的話】", student_message or "", "", "【這一輪查到的課本參考資料】",
              _shorten(references, _REFERENCE_CHARS) if references else "（這一輪沒有查課本）"]
    return "\n".join(lines)


def _normalize_kind(kind: str) -> str:
    kind = (kind or "").strip()
    for known in PROBLEM_KINDS:
        if kind and (known in kind or kind in known):
            return known
    return "其他"


def _parse_review(result) -> List[dict]:
    parsed = getattr(result, "parsed", None)
    review = parsed if isinstance(parsed, ReplyReview) else ReplyReview.model_validate_json(result.text)
    problems = [{"kind": _normalize_kind(p.kind), "detail": p.detail.strip()}
                for p in review.problems if p.detail.strip()]
    return [] if review.ok else problems


def reflect(call_gemini: Callable, draft: str, student_message: str, recent_messages: List[dict],
            references: str, tutor_instruction: str) -> Reflection:
    """
    檢查回覆草稿，有問題就改寫。回傳 Reflection：reply 是學生該看到的回覆。
    call_gemini(contents, gen_config, budget_s, step) 回傳 Gemini 的結果；忙線、逾時就拋出錯誤，這裡接住、送原稿。
    """
    start = time.monotonic()
    elapsed = lambda: time.monotonic() - start
    hidden_draft, images = hide_images(draft)
    context = build_context(student_message, recent_messages, references)

    try:
        result = call_gemini(
            f"{REVIEW_INSTRUCTION}\n\n{context}\n\n【老師的回覆草稿】\n{hidden_draft}",
            types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=ReplyReview, temperature=0,
            ),
            REVIEW_BUDGET_S,
            STEP_REVIEW,
        )
        problems = _parse_review(result)
    except Exception as e:
        logger.warning(f"老師回覆的自我檢查沒做成，直接送出原稿：{e}")
        return Reflection(draft, learning_store.REVIEW_SKIPPED, seconds=elapsed())

    if not problems:
        return Reflection(draft, learning_store.REVIEW_OK, seconds=elapsed())

    logger.warning(f"老師回覆的自我檢查發現問題，請老師改寫：{problems}")
    budget = TOTAL_BUDGET_S - elapsed()
    if budget < _MIN_REWRITE_S:
        logger.warning("自我檢查花太久，來不及改寫，直接送出原稿。")
        return Reflection(draft, learning_store.REVIEW_FLAGGED, problems, draft, elapsed())
    try:
        result = call_gemini(
            f"{context}\n\n【你的回覆草稿】\n{hidden_draft}\n\n"
            + REWRITE_INSTRUCTION.format(problems="\n".join(f"- {p['kind']}：{p['detail']}" for p in problems)),
            types.GenerateContentConfig(system_instruction=tutor_instruction, temperature=0.5),
            budget,
            STEP_REWRITE,
        )
        rewritten = (result.text or "").strip()
        if not rewritten:
            raise ValueError("改寫結果是空的")
    except Exception as e:
        logger.warning(f"改寫老師回覆失敗，直接送出原稿：{e}")
        return Reflection(draft, learning_store.REVIEW_FLAGGED, problems, draft, elapsed())
    return Reflection(restore_images(rewritten, images), learning_store.REVIEW_REVISED, problems, draft, elapsed())
