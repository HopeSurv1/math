import os
import base64
import builtins as _builtins_module
import math
import re
import time
import uuid
import warnings
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Optional
import httpx
from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from google import genai
from google.genai import types
from src.config import config
from src.rag_tools import search_math_materials, prefetch_context
from src.services import auth_store, conversation_store, learning_analysis, learning_store, reflection
from src.utils.logger import logger
from src.utils.reply_cleanup import clean_reply_text

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

matplotlib.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Noto Sans TC", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False
matplotlib.rcParams["font.family"] = ["sans-serif", "DejaVu Sans"]

app = FastAPI()

class ChatRequest(BaseModel):
    message: str
    image_data: Optional[str] = None
    mime_type: Optional[str] = None
    conversation_id: Optional[str] = None
    request_id: Optional[str] = None

class CancelChatRequest(BaseModel):
    request_id: str

class AuthRequest(BaseModel):
    username: str
    password: str

class RenameConversationRequest(BaseModel):
    title: str

class DeleteAccountRequest(BaseModel):
    password: str

class ResetPasswordRequest(BaseModel):
    username: str
    new_password: str

class DeleteUserRequest(BaseModel):
    username: str

class StudentRequest(BaseModel):
    username: str

class ChatResponse(BaseModel):
    reply: str
    used_tool: bool = False
    conversation_id: str = ""

chat_sessions = {}
SESSION_COOKIE_NAME = "session_id"
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 180
ADMIN_COOKIE_NAME = "admin_session_id"
ADMIN_COOKIE_MAX_AGE = 60 * 60 * auth_store.ADMIN_SESSION_HOURS

if config.ADMIN_PASSWORD == "admin":
    logger.warning("管理員密碼仍是預設的 admin；公開部署前請在 .env 設定 ADMIN_PASSWORD。")

GENERATED_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "generated")

_ALLOWED_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len",
    "list", "max", "min", "range", "round", "set", "str", "sum", "tuple",
    "zip", "isinstance", "True", "False", "None", "print",
    "sorted", "reversed", "map", "filter", "pow", "chr", "ord",
)
_SAFE_BUILTINS = {
    name: getattr(_builtins_module, name)
    for name in _ALLOWED_BUILTIN_NAMES
    if hasattr(_builtins_module, name)
}

_MATPLOTLIB_CODE_INSTRUCTION = """你是一個把數學描述轉換成 matplotlib 繪圖程式碼的工具。
根據使用者的描述，寫出一段可以直接執行的 Python 程式碼，畫出對應的數學圖形。

規則（務必遵守）：
1. 不要寫任何 import 陳述式。以下變數已經準備好可以直接用：
   - plt（matplotlib.pyplot）
   - np（numpy）
   - math（Python 內建 math 模組）
2. 圖形要清楚正確：重要的點/邊/角要用 plt.text() 或 ax.annotate() 標示文字，
   可以用繁體中文標籤（例如「斜邊」「股」）。需要格線就加 plt.grid(True)。
3. 不要呼叫 plt.show()、不要呼叫 plt.savefig()（系統會自動處理存檔）、不要做任何檔案讀寫、
   網路請求，或使用 input()。
4. 只回傳程式碼本身，不要任何說明文字，也不要用 ``` 包起來。

畫幾何圖形時（很容易畫錯，務必照做）：
5. 先用 np.array 算出每個頂點的座標（例如 A = np.array([0, 0])），線段、多邊形、標示位置全部用這些
   座標算出來，不要憑感覺猜位置。長度、角度要跟描述的數字一致。
6. 一定要加 ax.set_aspect('equal')，不然正方形會變長方形、直角看起來不直。
7. 在多邊形的邊「外側」畫圖形時（例如畢氏定理在直角三角形的三邊各畫一個正方形），方向要算出來：
   把邊的向量轉 90 度得到垂直方向，並確認它指向「遠離多邊形重心」的那一側；畫好的正方形不能跟三角形重疊。
8. 座標軸範圍要把所有圖形和文字都包進去、四周只留一點空白：不要讓圖形被切掉，也不要留一大片空白。
   純幾何圖可以用 ax.axis('off') 隱藏座標軸。
9. 標示文字放在對應的點、邊或區域旁邊，文字彼此不要重疊。
"""

_MATPLOTLIB_FIX_INSTRUCTION = """你上一次寫的程式碼有下面這些問題，請修正後重新寫一份完整的程式碼（規則跟上面一樣，只回傳程式碼）：
{problems}

上一次的程式碼：
{code}"""

_IMAGE_REVIEW_INSTRUCTION = """你是國中數學圖形的檢查員。這張圖是照下面的「圖形描述」用程式畫出來的，請仔細看圖檢查：
1. 圖形對不對：形狀、位置關係、長度比例、角度是否符合描述和數學事實
   （例如在三角形的邊上畫正方形，正方形要在三角形外側、不能跟三角形重疊）。
2. 標示對不對：點、邊、角的名稱和數字是否標在正確的位置、有沒有漏標，文字有沒有互相重疊到看不清楚。
3. 有沒有圖形被切掉，或擠在角落、留下一大片空白。
只挑會讓學生看錯或看不懂的問題，顏色、字型這種小地方不用挑；圖大致正確就回 ok = true。
problems 用繁體中文，每個問題一句話，說清楚哪裡錯、應該怎麼改。"""

class _ImageReview(BaseModel):
    ok: bool
    problems: list[str]

def _sticks_out(extent, box) -> bool:
    dx, dy = box.width * 0.02, box.height * 0.02
    return (extent.x0 < box.x0 - dx or extent.x1 > box.x1 + dx
            or extent.y0 < box.y0 - dy or extent.y1 > box.y1 + dy)

def _overlap_ratio(a, b) -> float:
    w = min(a.x1, b.x1) - max(a.x0, b.x0)
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    smaller = min(a.width * a.height, b.width * b.height)
    return w * h / smaller if w > 0 and h > 0 and smaller > 0 else 0.0

_GEOMETRY_PATCH_TYPES = (mpatches.Polygon, mpatches.Rectangle, mpatches.Ellipse, mpatches.RegularPolygon, mpatches.Wedge)

def _has_geometry_shapes(ax) -> bool:
    chart_bars = {id(p) for container in ax.containers for p in container}
    return any(isinstance(p, _GEOMETRY_PATCH_TYPES) and not isinstance(p, mpatches.FancyArrow)
               and id(p) not in chart_bars for p in ax.patches)

def _is_stretched(ax) -> bool:
    if ax.name != "rectilinear" or ax.get_xscale() != "linear" or ax.get_yscale() != "linear":
        return False
    (x0, y0), (x1, y1) = ax.transData.transform([(0, 0), (1, 1)])
    return y1 != y0 and abs(abs(x1 - x0) / abs(y1 - y0) - 1) > 0.05

_POINT_NAMES_IN_PROMPT = re.compile(
    r"(?:△|∠|三角形|四邊形|五邊形|六邊形|多邊形|梯形|菱形|正方形|長方形|矩形|扇形|圓心|圓|弧|頂點|點|線段|直線|射線|邊|角)"
    r"\s*([A-Z]+)(?![A-Za-z])"
)

def _missing_point_names(fig, prompt: str) -> list:
    names = sorted({letter for word in _POINT_NAMES_IN_PROMPT.findall(prompt) for letter in word})
    shown = " ".join(t.get_text() for t in fig.findobj(plt.Text))
    return [name for name in names if name not in shown]

_MISSING_GLYPH_WARNING = re.compile(r"Glyph (\d+)\b.*\bmissing from")

def _unrenderable_characters(caught_warnings) -> list:
    chars = []
    for w in caught_warnings:
        match = _MISSING_GLYPH_WARNING.search(str(w.message))
        if match and chr(int(match.group(1))) not in chars:
            chars.append(chr(int(match.group(1))))
    return chars

def _layout_problems(fig, prompt: str = "") -> list:
    axes = fig.get_axes()
    if not fig.texts and not any(ax.lines or ax.patches or ax.collections or ax.texts or ax.images for ax in axes):
        return ["圖是空白的，什麼都沒有畫出來"]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    problems = []
    unrenderable = _unrenderable_characters(caught)
    if unrenderable:
        shown = "、".join(f"「{ch}」(U+{ord(ch):04X})" for ch in unrenderable[:5])
        problems.append(f"文字裡的 {shown} 字型顯示不出來，圖上會變成方框；請拿掉，或改用文字說明、$...$ 數學式")
    missing = _missing_point_names(fig, prompt)
    if missing:
        problems.append(f"描述裡的點 {'、'.join(missing)} 沒有標在圖上，請用 ax.text 在對應的位置標出來")
    for ax in axes:
        if _has_geometry_shapes(ax) and _is_stretched(ax):
            problems.append("幾何圖形的 x、y 軸比例不一樣，正方形會變長方形、直角看起來不直，"
                            "請加上 ax.set_aspect('equal')")
        clipped = [p for p in ax.patches
                   if p.get_visible() and p.get_clip_on() and _sticks_out(p.get_window_extent(renderer), ax.bbox)]
        if clipped:
            problems.append(f"有 {len(clipped)} 個圖形超出座標軸範圍、被切掉一部分，請把座標軸範圍調大到包住所有圖形")
        texts = [t for t in ax.texts if t.get_visible() and t.get_text().strip()]
        extents = [t.get_window_extent(renderer) for t in texts]
        overlapping = [f"「{texts[i].get_text()}」和「{texts[j].get_text()}」"
                       for i in range(len(texts)) for j in range(i + 1, len(texts))
                       if _overlap_ratio(extents[i], extents[j]) > 0.3]
        if overlapping:
            problems.append(f"文字標示互相重疊：{'、'.join(overlapping[:3])}，請把它們分開")
    return problems

def _render_matplotlib_code(code: str, filepath: str, prompt: str = "") -> list:
    plt.close("all")
    try:
        safe_globals = {"__builtins__": _SAFE_BUILTINS, "plt": plt, "np": np, "math": math}
        exec(compile(code, "<gemini_matplotlib_code>", "exec"), safe_globals)
        try:
            problems = _layout_problems(plt.gcf(), prompt)
        except Exception as e:
            logger.warning(f"繪圖版面檢查失敗，略過：{e}")
            problems = []
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        return problems
    finally:
        plt.close("all")

MODEL_CANDIDATES = []
for _m in (config.CHAT_MODEL, config.FALLBACK_CHAT_MODEL):
    if _m and _m not in MODEL_CANDIDATES:
        MODEL_CANDIDATES.append(_m)

_RETRYABLE_ERROR_MARKERS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded")

def _is_retryable_error(e: Exception) -> bool:
    s = str(e)
    return any(marker in s for marker in _RETRYABLE_ERROR_MARKERS)

_CALL_TIMEOUT_S = 90

def _is_timeout_error(e: Exception) -> bool:
    return isinstance(e, (httpx.TimeoutException, TimeoutError)) or "timed out" in str(e).lower()

def _with_timeout(gen_config: Optional[types.GenerateContentConfig]) -> types.GenerateContentConfig:
    gen_config = gen_config or types.GenerateContentConfig()
    if gen_config.http_options and gen_config.http_options.timeout:
        return gen_config
    return gen_config.model_copy(update={"http_options": types.HttpOptions(timeout=_CALL_TIMEOUT_S * 1000)})

def _with_retry_and_fallback(models, call_fn, max_attempts: int = 3):
    last_error = None
    for model in models:
        for attempt in range(1, max_attempts + 1):
            try:
                return call_fn(model), model
            except Exception as e:
                last_error = e
                if _is_timeout_error(e):
                    logger.warning(f"呼叫模型 {model} 等太久沒有回應（逾時），直接改用下一個模型：{e}")
                    break
                if not _is_retryable_error(e):
                    raise
                logger.warning(f"呼叫模型 {model} 第 {attempt} 次失敗（暫時性錯誤，將重試）：{e}")
                if attempt < max_attempts:
                    time.sleep(2 ** (attempt - 1))
        else:
            logger.warning(f"模型 {model} 重試 {max_attempts} 次後仍失敗，改用下一個備援模型。")
    raise last_error

_OPTIONAL_CALL_BUDGET_S = 30
_OPTIONAL_HEDGE_AFTER_S = 15
_OPTIONAL_MIN_CALL_S = 5
_GEMINI_MIN_TIMEOUT_S = 10

def _call_gemini_within_budget(contents, gen_config: Optional[types.GenerateContentConfig] = None,
                               budget_s: Optional[float] = None, models: Optional[list] = None):
    budget_s = budget_s or _OPTIONAL_CALL_BUDGET_S
    models = models or MODEL_CANDIDATES
    deadline = time.monotonic() + budget_s
    primary = models[0]
    pool = ThreadPoolExecutor(max_workers=2)
    waiting = {}
    backup = None
    asked = failures = 0
    last_error: Exception = TimeoutError(f"{budget_s:g} 秒內沒有模型回應")

    def time_left():
        return deadline - time.monotonic()

    def ask_next_model():
        nonlocal asked
        for _ in models:
            model = models[asked % len(models)]
            asked += 1
            if model not in waiting.values():
                break
        timeout_s = max(time_left() + 5, _GEMINI_MIN_TIMEOUT_S)
        call_config = (gen_config or types.GenerateContentConfig()).model_copy(
            update={"http_options": types.HttpOptions(timeout=int(timeout_s * 1000))}
        )
        future = pool.submit(global_client.models.generate_content, model=model, contents=contents, config=call_config)
        waiting[future] = model

    try:
        ask_next_model()
        while waiting and time_left() > 0:
            done, _ = wait(waiting, timeout=min(time_left(), _OPTIONAL_HEDGE_AFTER_S), return_when=FIRST_COMPLETED)
            if not done:
                if backup is None and len(waiting) < 2 and time_left() > _OPTIONAL_MIN_CALL_S:
                    logger.warning(f"模型 {'、'.join(waiting.values())} 遲遲沒有回應，同時改問下一個模型。")
                    ask_next_model()
                continue
            failed = False
            for future in done:
                model = waiting.pop(future)
                try:
                    result = future.result()
                except Exception as e:
                    if not _is_retryable_error(e):
                        raise
                    logger.warning(f"呼叫模型 {model} 失敗（暫時性錯誤，時限內換模型再問）：{e}")
                    last_error, failures, failed = e, failures + 1, True
                    continue
                if model == primary or primary not in waiting.values():
                    return result, model
                backup = (result, model)
            if backup is not None and primary not in waiting.values():
                return backup
            if failed:
                pause = min(2 ** (failures - 1), 4)
                if time_left() > pause + _OPTIONAL_MIN_CALL_S:
                    time.sleep(pause)
                    ask_next_model()
    finally:
        pool.shutdown(wait=False)
    if backup is not None:
        return backup
    raise last_error

def _call_gemini(contents, gen_config: Optional[types.GenerateContentConfig] = None, optional: bool = False,
                 budget_s: Optional[float] = None, models: Optional[list] = None):
    if optional:
        return _call_gemini_within_budget(contents, gen_config, budget_s, models)
    call_config = _with_timeout(gen_config)
    return _with_retry_and_fallback(
        models or MODEL_CANDIDATES,
        lambda model: global_client.models.generate_content(model=model, contents=contents, config=call_config),
    )

def _write_plot_code(prompt: str, previous_code: str = "", problems: Optional[list] = None,
                     optional: bool = False) -> str:
    contents = f"{_MATPLOTLIB_CODE_INSTRUCTION}\n\n使用者描述：{prompt}"
    if problems:
        contents += "\n\n" + _MATPLOTLIB_FIX_INSTRUCTION.format(
            problems="\n".join(f"- {p}" for p in problems), code=previous_code
        )
    result, used_model = _call_gemini(contents, optional=optional)
    if used_model != config.CHAT_MODEL:
        logger.info(f"畫圖工具改用備援模型 {used_model} 產生繪圖程式碼。")
    code = (result.text or "").strip()
    code = re.sub(r"^```[a-zA-Z]*\n?", "", code)
    return re.sub(r"```$", "", code).strip()

def _try_render(code: str, filepath: str, prompt: str):
    try:
        return True, _render_matplotlib_code(code, filepath, prompt)
    except Exception as e:
        return False, [f"程式碼執行失敗：{type(e).__name__}: {e}"]

def _review_image(filepath: str, prompt: str) -> list:
    try:
        with open(filepath, "rb") as f:
            image = types.Part.from_bytes(data=f.read(), mime_type="image/png")
        result, used_model = _call_gemini(
            [image, f"{_IMAGE_REVIEW_INSTRUCTION}\n\n圖形描述：{prompt}"],
            types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=_ImageReview, temperature=0,
            ),
            optional=True,
        )
        if used_model != config.CHAT_MODEL:
            logger.info(f"看圖檢查改用備援模型 {used_model}。")
        parsed = getattr(result, "parsed", None)
        review = parsed if isinstance(parsed, _ImageReview) else _ImageReview.model_validate_json(result.text)
    except Exception as e:
        logger.warning(f"圖片自動檢查失敗，略過檢查：{e}")
        return []
    problems = [p.strip() for p in review.problems if p.strip()]
    return problems if not review.ok else []

def generate_math_image(prompt: str) -> str:
    global global_client
    if global_client is None:
        global_client = genai.Client(api_key=config.GEMINI_API_KEY)

    try:
        logger.info(f"開始生成 matplotlib 繪圖程式碼，描述: {prompt}")
        code = _write_plot_code(prompt)
        if not code:
            return "[圖片生成失敗：模型沒有回傳繪圖程式碼]"

        os.makedirs(GENERATED_DIR, exist_ok=True)

        filename = f"{uuid.uuid4().hex}.png"
        filepath = os.path.join(GENERATED_DIR, filename)
        drawn, problems = _try_render(code, filepath, prompt)

        for _ in range(config.DRAW_MAX_FIXES):
            if drawn and not problems:
                problems = _review_image(filepath, prompt)
                if not problems:
                    break
            logger.warning(f"繪圖有問題，附上問題請 Gemini 重寫：{problems}")
            try:
                new_code = _write_plot_code(prompt, code, problems, optional=drawn)
            except Exception as e:
                logger.warning(f"重寫繪圖程式碼失敗，沿用原本的結果：{e}")
                break
            candidate = os.path.join(GENERATED_DIR, f"{uuid.uuid4().hex}.png")
            new_drawn, new_problems = _try_render(new_code, candidate, prompt)
            if new_drawn and (not drawn or not new_problems):
                os.replace(candidate, filepath)
                code, drawn, problems = new_code, True, new_problems
            elif not drawn:
                code, problems = new_code, new_problems
            else:
                _remove_generated_images([os.path.basename(candidate)])
                break

        if not drawn:
            return f"[圖片生成失敗：{problems[0]}]"

        alt = re.sub(r"[\[\]\s]+", " ", prompt).strip()[:40] or "數學示意圖"
        return f"![{alt}](/generated/{filename})"
    except Exception as e:
        logger.error(f"圖片生成發生錯誤: {e}")
        return f"[圖片生成失敗：{str(e)}]"
global_client = None

def _ensure_client():
    global global_client
    if global_client is None:
        global_client = genai.Client(api_key=config.GEMINI_API_KEY)
    return global_client

_TUTOR_PERSONA = "你是一位專業、有耐心且「啟發式」的國中數學老師。"
_TUTOR_TOOL_RULES = """*重要規則*：如果學生問到定義、觀念、公式或特定定理，你「務必」優先呼叫 search_math_materials 工具查閱知識庫確認課本有沒有教過——即使你覺得這可能超出國中範圍，也要先查證，不要單憑自己判斷就跳過檢索。
*重要規則*：即使學生問的是計算題或應用題，只要解題會用到課本教過的方法或性質（例如：根式化簡、因式分解、質因數分解、乘法公式、畢氏定理、一元一次方程式解法等），你也「務必」先呼叫 search_math_materials 查閱該方法的課本說明，再依課本的步驟引導學生。
*重要規則*：只要學生的訊息裡出現「畫」、「繪製」或英文的 "draw", "plot", "graph", "sketch", "diagram", "figure" 等字眼，或是學生需要視覺化的輔助（例如幾何圖形、解題示意圖）才能講清楚，你「務必」呼叫 generate_math_image 工具生成對應的圖片，不可以自己判斷「用文字說明就夠了」而跳過畫圖，也不可以用文字描述或文字步驟取代真正產生一張圖片。呼叫工具產生圖片之後，仍然可以在圖片下面搭配文字說明或反問引導學生，畫圖跟蘇格拉底引導並不衝突、兩者都要做。如果你收到學生上傳圖片，請分析圖片內容來回答問題。
*重要規則*：只要你呼叫 generate_math_image 並取得回傳結果，「務必」把它回傳的完整 Markdown 圖片語法（以 `![` 開頭的那一段）原封不動、逐字複製到你最終回覆的內容中，絕對不要只用文字描述圖片、或省略這段語法——否則學生的畫面上會看不到圖。"""
_TUTOR_TEACHING_RULES = """【教學與回答紀律】：
1. 引導解題才是你的初衷！**絕對不要**直接丟出最終答案。請使用蘇格拉底提問法，一步一步反問學生，引導他們自己思考出答案。
2. 你的回答必須依據工具回傳的參考資料，且只挑其中真正切題的部分來說明——不要提到參考資料裡不相關的方法或名詞、講了又立刻否定，那會讓學生更困惑。如果查無資料，請回答「這部分我們先用常理想想看」（英文時為 "Let's think through this step by step..."），不要過度瞎掰沒教過的進階公式。
3. **透明度規則**：只要你有呼叫 search_math_materials 工具並獲得資料，請務必在回答中讓學生知道你的說明是依據國中數學課本的內容（例如「國中課本是這樣定義的…」）。但每個學生用的課本、講義版本都不一樣（不同出版社、不同學校），所以**不要**說出頁碼、章節編號或例題編號（例如「第 91 頁」「3-2 節」「例題 2」），也不要說「我們的課本」「我們的講義」——學生手上的書跟你查的不一定是同一本，說了反而對不上。
4. 語氣要活潑、親切、多給予鼓勵（可以使用 emoji）。
5. **語言一致性規則（重要）**：務必配合學生發問所使用的語言進行回答與引導。若學生使用英文發問，請全程使用流暢親切且易懂的英文（English）進行教學與提問；若學生使用繁體中文發問，請使用繁體中文回答，而且只能用中文字，不要夾雜日文假名（例如把「的」寫成「の」）或簡體字。
6. 遇到數學公式與數字時，請直接使用一般人類容易閱讀的文字或符號呈現，**絕對不要使用**帶有 `$` 符號的 LaTeX 語法（例如：寫成「1/3」，不要寫成「\\frac{1}{3}」；變數直接寫 a、b、c，不要寫成「$a$」；次方用上標字寫成 a²+b²=c²，根號寫成 √2）。
7. **不要卡在舊話題**：每一輪都要先看清楚學生「這一則」訊息實際問的是什麼。如果學生換了新的、不相關的主題，就直接針對新主題回答，不要因為你上一輪問的反問題還沒被回答，就無視新訊息、繼續講舊的內容。只有在學生這次的訊息明顯是在嘗試回答你上一輪的問題時，才接續舊話題。"""
TUTOR_INSTRUCTION = f"{_TUTOR_PERSONA}\n{_TUTOR_TOOL_RULES}\n\n{_TUTOR_TEACHING_RULES}"
_REWRITE_INSTRUCTION = f"{_TUTOR_PERSONA}\n\n{_TUTOR_TEACHING_RULES}"

def get_or_create_chat(conversation_id: str, model: str = None):
    global global_client
    model = model or config.CHAT_MODEL
    if global_client is None:
        global_client = genai.Client(api_key=config.GEMINI_API_KEY)

    cached = chat_sessions.get(conversation_id)
    if cached is None or cached[1] != model:
        history = conversation_store.load_history(conversation_id)
        if history:
            logger.info(f"對話串 {conversation_id[:8]}... 讀回 {len(history)} 則歷史訊息")

        chat = global_client.chats.create(
            model=model,
            history=history,
            config=types.GenerateContentConfig(
                system_instruction=TUTOR_INSTRUCTION,
                tools=[search_math_materials, generate_math_image],
                temperature=0.7,
                http_options=types.HttpOptions(timeout=_CALL_TIMEOUT_S * 1000),
            )
        )
        chat_sessions[conversation_id] = (chat, model)

    return chat_sessions[conversation_id][0]

def _called_search_tool(chat, pre_len: int) -> bool:
    history = chat.get_history() or []
    for turn in history[pre_len:]:
        for part in (turn.parts or []):
            fc = getattr(part, "function_call", None)
            if fc is not None and getattr(fc, "name", None) == "search_math_materials":
                return True
    return False

_IMAGE_MARKDOWN_RE = re.compile(r"!\[([^\]\n]*)\]\(([^)\s]*)\)")
_GENERATED_URL_RE = re.compile(r"/generated/([a-f0-9]+\.(?:png|jpg))")

def _is_generated_image(url: str) -> bool:
    match = _GENERATED_URL_RE.fullmatch(url)
    return bool(match) and os.path.isfile(os.path.join(GENERATED_DIR, match.group(1)))

def _drawn_image_url(tool_result: str) -> Optional[str]:
    match = _GENERATED_URL_RE.search(tool_result or "")
    return match.group(0) if match and _is_generated_image(match.group(0)) else None

def _images_drawn_this_turn(chat, pre_len: int) -> list:
    urls = []
    for turn in (chat.get_history() or [])[pre_len:]:
        for part in (turn.parts or []):
            fr = getattr(part, "function_response", None)
            if fr is None or getattr(fr, "name", None) != "generate_math_image":
                continue
            url = _drawn_image_url(str((fr.response or {}).get("result", "")))
            if url:
                urls.append(url)
    return urls

def _fix_reply_images(reply: str, drawn_urls: list, student_message: str) -> str:
    unused = [url for url in drawn_urls if url not in reply]

    def fix(match):
        alt, url = match.group(1), match.group(2)
        if _is_generated_image(url):
            return match.group(0)
        if unused:
            logger.warning(f"回覆裡的圖片網址 {url} 抄錯了，換成這輪畫圖工具真正畫的圖。")
            return f"![{alt}]({unused.pop(0)})"
        logger.warning(f"回覆裡的圖片網址 {url} 不是畫圖工具產生的，照圖片說明補畫一張。")
        intro = match.string[:match.start()].rstrip().rsplit("\n", 1)[-1]
        new_url = _drawn_image_url(
            generate_math_image(f"{alt}\n圖片前面的說明：{intro}\n學生的問題：{student_message}")
        )
        return f"![{alt}]({new_url})" if new_url else ""

    reply = _IMAGE_MARKDOWN_RE.sub(fix, reply)
    if unused:
        logger.warning("畫圖工具有畫出圖，但回覆裡漏掉了，補在回覆最前面。")
        reply = "\n\n".join([f"![數學示意圖]({url})" for url in unused] + [reply])
    return reply

def _references_this_turn(chat, pre_len: int) -> str:
    texts = []
    for turn in (chat.get_history() or [])[pre_len:]:
        for part in (turn.parts or []):
            fr = getattr(part, "function_response", None)
            if fr is not None and getattr(fr, "name", None) == "search_math_materials":
                texts.append(str((fr.response or {}).get("result", "")))
    return "\n---\n".join(t for t in texts if t)

_REVIEW_MODELS = list(dict.fromkeys(m for m in (config.REVIEW_MODEL, *MODEL_CANDIDATES) if m))

def _reflect_on_reply(draft: str, student_message: str, recent_messages: list, references: str):
    _ensure_client()
    return reflection.reflect(
        lambda contents, gen_config, budget_s, step: _call_gemini(
            contents, gen_config, optional=True, budget_s=budget_s,
            models=_REVIEW_MODELS if step == reflection.STEP_REVIEW else None,
        )[0],
        draft, student_message, recent_messages, references, _REWRITE_INSTRUCTION,
    )

_LEARNING_MODELS = list(dict.fromkeys(m for m in (config.LEARNING_MODEL, config.CHAT_MODEL) if m))

def _record_learning(username: str, conversation_id: str, message_id: int, student_message: str,
                     reply: str, previous_reply: str) -> None:
    try:
        client = _ensure_client()
        tag = learning_analysis.tag_turn(
            lambda contents, gen_config: _with_retry_and_fallback(
                _LEARNING_MODELS,
                lambda model: client.models.generate_content(model=model, contents=contents, config=gen_config),
            )[0],
            student_message, reply, previous_reply, learning_store.last_event(conversation_id),
            learning_analysis.known_concepts(learning_store.events_for_user(username)),
        )
        if not learning_store.add_event(username, conversation_id, message_id, tag):
            logger.info("這一輪已經被學生撤銷，學習標記不存。")
    except Exception as e:
        logger.warning(f"學習標記失敗，這一輪不列入學習紀錄：{e}")

@app.post("/api/register")
async def register_endpoint(auth: AuthRequest):
    if auth_store.is_reserved_username(auth.username):
        return JSONResponse(status_code=400, content={"error": "這個帳號名稱是保留字，請換一個"})
    if auth_store.is_reserved_password(auth.password):
        return JSONResponse(status_code=400, content={"error": "不能使用「admin」當作密碼，請換一個"})
    if auth_store.register_user(auth.username, auth.password):
        logger.info(f"新帳號註冊成功: {auth.username}")
        return {"message": "註冊成功，請登入"}
    return JSONResponse(status_code=409, content={"error": "帳號已存在，或帳號密碼不可空白"})

@app.post("/api/login")
async def login_endpoint(auth: AuthRequest, response: Response):
    if auth_store.is_reserved_username(auth.username) or not auth_store.verify_user(auth.username, auth.password):
        return JSONResponse(status_code=401, content={"error": "帳號或密碼錯誤"})
    token = auth_store.create_session(auth.username)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    logger.info(f"使用者登入: {auth.username}")
    return {"message": "登入成功", "username": auth.username}

@app.post("/api/logout")
async def logout_endpoint(http_request: Request, response: Response):
    auth_store.delete_session(http_request.cookies.get(SESSION_COOKIE_NAME))
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"message": "已登出"}

@app.get("/api/me")
async def me_endpoint(http_request: Request):
    username = auth_store.resolve_session(http_request.cookies.get(SESSION_COOKIE_NAME))
    return {"username": username}

def _current_username(http_request: Request) -> Optional[str]:
    return auth_store.resolve_session(http_request.cookies.get(SESSION_COOKIE_NAME))

def _collect_image_filenames(conversation_id: str) -> set:
    filenames = set()
    for m in conversation_store.load_messages_for_display(conversation_id):
        filenames.update(_GENERATED_URL_RE.findall(m.get("text") or ""))
    return filenames

def _remove_generated_images(filenames) -> None:
    for filename in filenames:
        try:
            os.remove(os.path.join(GENERATED_DIR, filename))
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"刪除對話串附帶圖片失敗（{filename}）: {e}")

def _delete_account_and_data(username: str) -> None:
    image_filenames = set()
    for conv in conversation_store.list_conversations(username):
        image_filenames |= _collect_image_filenames(conv["id"])
        chat_sessions.pop(conv["id"], None)

    learning_store.delete_for_user(username)
    conversation_store.delete_all_conversations(username)
    auth_store.delete_user(username)
    _remove_generated_images(image_filenames)

@app.post("/api/account/delete")
async def delete_account_endpoint(
    request: DeleteAccountRequest, http_request: Request, response: Response
):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    if not auth_store.verify_user(username, request.password):
        return JSONResponse(status_code=403, content={"error": "密碼錯誤"})

    _delete_account_and_data(username)
    response.delete_cookie(SESSION_COOKIE_NAME)
    logger.info(f"帳號已刪除: {username}")
    return {"message": "帳號已刪除"}

@app.post("/api/conversations")
async def create_conversation_endpoint(http_request: Request):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    conversation_id = conversation_store.create_conversation(username)
    return {"id": conversation_id, "title": "新的對話"}

@app.get("/api/conversations")
async def list_conversations_endpoint(http_request: Request):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    return {"conversations": conversation_store.list_conversations(username)}

@app.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages_endpoint(conversation_id: str, http_request: Request):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    if conversation_store.get_conversation_owner(conversation_id) != username:
        return JSONResponse(status_code=404, content={"error": "找不到這條對話"})
    messages = conversation_store.load_messages_for_display(conversation_id)
    for m in messages:
        if m["role"] == "model":
            m["text"] = clean_reply_text(m["text"])
    return {"messages": messages}

@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation_endpoint(conversation_id: str, http_request: Request):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    if conversation_store.get_conversation_owner(conversation_id) != username:
        return JSONResponse(status_code=404, content={"error": "找不到這條對話"})

    image_filenames = _collect_image_filenames(conversation_id)
    learning_store.delete_for_conversation(conversation_id)
    conversation_store.delete_conversation(conversation_id)
    chat_sessions.pop(conversation_id, None)
    _remove_generated_images(image_filenames)
    return {"message": "已刪除"}

@app.patch("/api/conversations/{conversation_id}")
async def rename_conversation_endpoint(
    conversation_id: str, request: RenameConversationRequest, http_request: Request
):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    if conversation_store.get_conversation_owner(conversation_id) != username:
        return JSONResponse(status_code=404, content={"error": "找不到這條對話"})
    if not request.title.strip():
        return JSONResponse(status_code=400, content={"error": "名稱不能是空的"})

    conversation_store.rename_conversation(conversation_id, request.title)
    return {"message": "已更新"}


_ADVICE_BUDGET_S = 45

def _learning_report(username: str) -> dict:
    report = learning_analysis.build_report(
        learning_store.events_for_user(username),
        [t for _, t in conversation_store.student_message_times(username)],
    )
    report["username"] = username
    report["advice"] = learning_store.get_advice(username)
    return report

def _generate_advice(username: str):
    report = _learning_report(username)
    if not learning_analysis.has_enough_data(report):
        return JSONResponse(status_code=400, content={"error": "紀錄還太少，多和老師練習幾題，再來看學習建議吧！"})
    try:
        _ensure_client()
        advice = learning_analysis.write_advice(
            lambda contents: _call_gemini(contents, optional=True, budget_s=_ADVICE_BUDGET_S)[0], report
        )
    except Exception as e:
        logger.error(f"產生學習建議失敗: {e}")
        return JSONResponse(status_code=503, content={"error": "老師現在有點忙，等一下再試一次"})
    return {"advice": learning_store.save_advice(username, clean_reply_text(advice))}

@app.get("/api/learning/report")
async def learning_report_endpoint(http_request: Request):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    return _learning_report(username)

@app.post("/api/learning/advice")
async def learning_advice_endpoint(http_request: Request):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    return _generate_advice(username)


def _is_admin(http_request: Request) -> bool:
    return auth_store.resolve_admin_session(http_request.cookies.get(ADMIN_COOKIE_NAME))

@app.post("/api/admin/login")
async def admin_login_endpoint(auth: AuthRequest, response: Response):
    if not auth_store.verify_admin(auth.username, auth.password):
        logger.warning("管理員登入失敗")
        return JSONResponse(status_code=401, content={"error": "管理員帳號或密碼錯誤"})
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=auth_store.create_admin_session(),
        max_age=ADMIN_COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
    )
    logger.info("管理員登入")
    return {"message": "登入成功"}

@app.post("/api/admin/logout")
async def admin_logout_endpoint(http_request: Request, response: Response):
    auth_store.delete_admin_session(http_request.cookies.get(ADMIN_COOKIE_NAME))
    response.delete_cookie(ADMIN_COOKIE_NAME)
    return {"message": "已登出"}

@app.get("/api/admin/me")
async def admin_me_endpoint(http_request: Request):
    return {"admin": _is_admin(http_request)}

@app.get("/api/admin/users")
async def admin_list_users_endpoint(http_request: Request):
    if not _is_admin(http_request):
        return JSONResponse(status_code=401, content={"error": "請先以管理員身分登入"})
    stats = conversation_store.stats_by_user()
    empty = {"conversation_count": 0, "message_count": 0, "last_active": None}
    users = [{**u, **stats.get(u["username"], empty)} for u in auth_store.list_users()]
    return {"users": users}

@app.post("/api/admin/reset-password")
async def admin_reset_password_endpoint(request: ResetPasswordRequest, http_request: Request):
    if not _is_admin(http_request):
        return JSONResponse(status_code=401, content={"error": "請先以管理員身分登入"})
    if not request.new_password:
        return JSONResponse(status_code=400, content={"error": "新密碼不可空白"})
    if auth_store.is_reserved_password(request.new_password):
        return JSONResponse(status_code=400, content={"error": "不能使用「admin」當作密碼"})
    if not auth_store.set_password(request.username, request.new_password):
        return JSONResponse(status_code=404, content={"error": "找不到這個帳號"})
    logger.info(f"管理員重設了帳號密碼: {request.username}")
    return {"message": "密碼已重設"}

@app.post("/api/admin/delete-user")
async def admin_delete_user_endpoint(request: DeleteUserRequest, http_request: Request):
    if not _is_admin(http_request):
        return JSONResponse(status_code=401, content={"error": "請先以管理員身分登入"})
    if not auth_store.user_exists(request.username):
        return JSONResponse(status_code=404, content={"error": "找不到這個帳號，可能已經被刪除了"})
    _delete_account_and_data(request.username)
    logger.info(f"管理員刪除了帳號: {request.username}")
    return {"message": "帳號已刪除"}

@app.get("/api/admin/learning/overview")
async def admin_learning_overview_endpoint(http_request: Request):
    if not _is_admin(http_request):
        return JSONResponse(status_code=401, content={"error": "請先以管理員身分登入"})
    overview = learning_analysis.build_overview(
        [u["username"] for u in auth_store.list_users()],
        learning_store.all_events(),
        conversation_store.student_message_times(),
    )
    overview["reflection"] = learning_store.review_stats()
    return overview

@app.get("/api/admin/learning/report")
async def admin_learning_report_endpoint(username: str, http_request: Request):
    if not _is_admin(http_request):
        return JSONResponse(status_code=401, content={"error": "請先以管理員身分登入"})
    if not auth_store.user_exists(username):
        return JSONResponse(status_code=404, content={"error": "找不到這個帳號"})
    return _learning_report(username)

@app.post("/api/admin/learning/advice")
async def admin_learning_advice_endpoint(request: StudentRequest, http_request: Request):
    if not _is_admin(http_request):
        return JSONResponse(status_code=401, content={"error": "請先以管理員身分登入"})
    if not auth_store.user_exists(request.username):
        return JSONResponse(status_code=404, content={"error": "找不到這個帳號"})
    return _generate_advice(request.username)

@app.get("/api/admin/reviews")
async def admin_reviews_endpoint(http_request: Request):
    if not _is_admin(http_request):
        return JSONResponse(status_code=401, content={"error": "請先以管理員身分登入"})
    return {"reviews": learning_store.recent_reviews()}

_finished_turns = {}
_cancelled_requests = {}
_MAX_REMEMBERED_TURNS = 200

def _remember(registry: dict, key: str, value) -> None:
    registry[key] = value
    while len(registry) > _MAX_REMEMBERED_TURNS:
        registry.pop(next(iter(registry)))

def _discard_turn(turn: dict) -> None:
    conversation_id = turn["conversation_id"]
    if turn["created_conversation"]:
        learning_store.delete_for_conversation(conversation_id)
        conversation_store.delete_conversation(conversation_id)
    else:
        learning_store.delete_for_messages(turn["message_ids"])
        conversation_store.delete_messages(conversation_id, turn["message_ids"])
    chat_sessions.pop(conversation_id, None)
    _remove_generated_images(turn["images"] - _collect_image_filenames(conversation_id))

@app.post("/api/chat/cancel")
async def cancel_chat_endpoint(request: CancelChatRequest, http_request: Request):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    turn = _finished_turns.get(request.request_id)
    if turn is None:
        _remember(_cancelled_requests, request.request_id, username)
        return {"message": "已停止"}
    if turn["username"] != username:
        return JSONResponse(status_code=404, content={"error": "找不到這一輪對話"})
    del _finished_turns[request.request_id]
    _discard_turn(turn)
    logger.info("學生按了停止，撤銷剛剛存進去的這一輪問答。")
    return {"message": "已停止"}

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, http_request: Request, background_tasks: BackgroundTasks):
    logger.info(f"收到來自前端的問題: {request.message}")
    try:
        username = auth_store.resolve_session(http_request.cookies.get(SESSION_COOKIE_NAME))
        if not username:
            return JSONResponse(status_code=401, content={"error": "請先登入"})

        conversation_id = request.conversation_id
        created_conversation = False
        if conversation_id:
            if conversation_store.get_conversation_owner(conversation_id) != username:
                return JSONResponse(status_code=404, content={"error": "找不到這條對話"})
        else:
            conversation_id = conversation_store.create_conversation(username)
            created_conversation = True
            logger.info(f"沒有帶 conversation_id，自動開一條新對話串：{conversation_id[:8]}...")

        drawing_keywords = ["畫", "繪製", "draw", "plot", "graph", "sketch", "diagram", "figure"]
        msg_lower = request.message.lower()
        looks_like_drawing_request = any(kw in msg_lower for kw in drawing_keywords)
        prefetched = None if looks_like_drawing_request else prefetch_context(request.message)

        message_parts = []
        if prefetched:
            message_parts.append(
                "[系統自動檢索到以下可能相關的課本內容，這是自動比對出來的，不一定符合學生"
                "「這次」的真正意圖。只有在內容確實直接對應學生這次的問題時才使用，並讓學生知道"
                "這是依據國中課本的內容（不要說頁碼、章節或例題編號，也不要說「我們的課本／講義」，"
                "學生手上的課本版本不一定跟這份一樣）；如果學生其實是在要求你做某件事（例如畫圖），或者這份資料主題對不上，"
                "就完全忽略它、不要提到它，直接處理學生原本的請求]\n" + prefetched
            )
        message_parts.append(
            "【學生這次實際問的內容如下，請務必針對這句話本身回答；如果這句話明顯跟"
            "你上一輪問過的問題不同主題，就直接切換過去處理這次的新內容，不要忽略它、"
            "也不要繼續糾結在你自己上一輪還沒被回答的反問上。如果這句話看起來就是在"
            "回答你上一輪的提問，才正常接續下去】\n" + request.message
        )
        if request.image_data and request.mime_type:
            try:
                image_bytes = base64.b64decode(request.image_data)
                message_parts.append(
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=request.mime_type
                    )
                )
                logger.info("收到附帶圖片的訊息")
            except Exception as e:
                logger.error(f"解析圖片失敗: {e}")
                
        def _send_with_model(model):
            chat = get_or_create_chat(conversation_id, model)
            pre_history = chat.get_history()
            pre_len = len(pre_history) if pre_history else 0
            resp = chat.send_message(message_parts)
            return chat, pre_len, resp

        (chat, pre_len, response), used_model = _with_retry_and_fallback(MODEL_CANDIDATES, _send_with_model)
        if used_model != config.CHAT_MODEL:
            logger.info(f"這一輪聊天改用備援模型 {used_model} 回覆。")
        reply = response.text

        if reply:
            reply = clean_reply_text(reply)
            reply = _fix_reply_images(reply, _images_drawn_this_turn(chat, pre_len), request.message)

        if looks_like_drawing_request and not _IMAGE_MARKDOWN_RE.search(reply or ""):
            logger.warning("學生要求畫圖，但這輪回覆沒有圖片，後端直接補畫一張。")
            fallback_image = generate_math_image(f"請畫出以下描述對應的數學圖形：{request.message}")
            if fallback_image.startswith("!["):
                reply = f"{fallback_image}\n\n{reply or ''}".strip()

        used_tool = bool(prefetched) or _called_search_tool(chat, pre_len)

        recent_messages = conversation_store.load_messages_for_display(conversation_id)
        reflected = None
        if reply and config.REPLY_REVIEW:
            references = "\n---\n".join(t for t in (prefetched, _references_this_turn(chat, pre_len)) if t)
            reflected = _reflect_on_reply(reply, request.message, recent_messages, references)
            if reflected.status == learning_store.REVIEW_REVISED:
                reply = clean_reply_text(reflected.reply)
                chat_sessions.pop(conversation_id, None)

        turn = {"username": username, "conversation_id": conversation_id, "created_conversation": created_conversation,
                "images": set(_GENERATED_URL_RE.findall(reply or "")), "message_ids": []}
        if request.request_id and _cancelled_requests.pop(request.request_id, None) == username:
            _discard_turn(turn)
            logger.info("學生按了停止，這一輪問答不存。")
            return JSONResponse(status_code=409, content={"error": "這一輪已經停止了"})

        user_message_id = conversation_store.append_message(conversation_id, "user", request.message)
        reply_message_id = conversation_store.append_message(conversation_id, "model", reply)
        turn["message_ids"] = [i for i in (user_message_id, reply_message_id) if i is not None]
        if request.request_id:
            _remember(_finished_turns, request.request_id, turn)

        if reflected is not None:
            learning_store.add_review(username, conversation_id, user_message_id, reply_message_id,
                                      reflected.status, reflected.problems, reflected.draft, reflected.seconds)
        if user_message_id is not None and reply:
            previous_reply = next((m["text"] for m in reversed(recent_messages) if m["role"] == "model"), "")
            background_tasks.add_task(_record_learning, username, conversation_id, user_message_id,
                                      request.message, reply, previous_reply)

        return ChatResponse(reply=reply, used_tool=used_tool, conversation_id=conversation_id)
    except Exception as e:
        logger.error(f"模型回應失敗: {e}")
        return ChatResponse(reply=f"[系統錯誤] 老師好像有點累了，請稍後再試。({str(e)})")

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(frontend_dir, "index.html"))

@app.get("/admin")
async def serve_admin():
    return FileResponse(os.path.join(frontend_dir, "admin.html"))

@app.get("/learning")
async def serve_learning():
    return FileResponse(os.path.join(frontend_dir, "learning.html"))

app.mount("/", StaticFiles(directory=frontend_dir), name="frontend")
