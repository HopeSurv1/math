# -*- coding: utf-8 -*-
"""
src/api/main.py
這是我們整個專案的「大腦對外窗口」（也就是後端 API 伺服器）。
它負責接收網頁端傳來的使用者訊息，然後去找 Gemini 老師幫忙回答，最後把回答傳回給網頁。

重點功能：
  - GET / : 當你在瀏覽器輸入網址時，它會把聊天室的畫面 (index.html) 傳送給你。
  - POST /api/register、/api/login、/api/logout、GET /api/me : 帳號註冊、登入、登出，
    以及讓前端確認「現在是不是已登入、登入的是誰」（見 auth_store.py）。
  - POST /api/account/delete : 刪除帳號（要再輸入一次密碼），連同所有對話紀錄、圖片與登入 session。
    註冊與一般登入都不接受「admin」這個保留字。
  - GET /admin、/api/admin/* : 管理後台。管理員帳密來自 .env（預設 admin / admin），
    用獨立的 cookie 登入；可以查看所有帳號（帳號、註冊時間、對話數）、幫使用者重設密碼，
    以及刪除帳號（連同對話紀錄、圖片與登入 session，跟使用者自己刪除帳號一樣徹底）。
  - POST /api/conversations、GET /api/conversations、
    GET /api/conversations/{id}/messages、DELETE /api/conversations/{id}、
    PATCH /api/conversations/{id} :
    對話紀錄清單——開新對話、列出、查看某條的內容、刪除、改名（見 conversation_store.py）。
  - POST /api/chat : 當你在聊天室送出問題，問題會傳到這裡，然後它會請 Gemini 老師幫忙解答。
    一定要先登入才能問問題，身分是靠登入時發的 cookie 認的；每句話都屬於某一條「對話串」
    （conversation_id），同一個帳號可以同時有很多條互不干擾的對話串。
    回覆送出前會先經過「反思機制」自我檢查（見 reflection.py），送出後在背景標記學習歷程（見 learning_analysis.py）。
  - GET /learning、GET /api/learning/report、POST /api/learning/advice : 學生的「我的學習紀錄」頁與 AI 學習建議。
  - GET /api/admin/learning/overview、/api/admin/learning/report、POST /api/admin/learning/advice、
    GET /api/admin/reviews : 管理後台的學習分析（全班、單一學生）與老師自我檢查紀錄。

主要小幫手 (函數)：
  - get_or_create_chat : 負責幫每一條「對話串」開一個聊天室，確保不同對話串的紀錄不會混在一起。
    重新建立聊天室時會從資料庫讀回那條對話串的歷史紀錄，所以就算伺服器重啟，對話也不會憑空
    消失（見 conversation_store.py）。
  - generate_math_image : 畫圖工具。請 Gemini 寫 matplotlib 程式碼，再在限制過的環境裡執行存成圖片。
  - _with_retry_and_fallback : Gemini 忙線（503）或額度超過（429）時自動重試，
    重試用盡就改用 config.FALLBACK_CHAT_MODEL 備援模型。對話與畫圖都會經過它。
  - _call_gemini_within_budget : 加分項專用（畫圖的看圖檢查與重畫、老師回覆的自我檢查與改寫），
    在時限內主要、備援模型輪流問，盡量問到答案。
  - _reflect_on_reply : 反思機制，回覆送出前自我檢查、有問題就改寫。
  - _record_learning : 在背景標記這一輪的學習狀況，存進 learning_store。
"""

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
matplotlib.use("Agg")  # 伺服器沒有畫面，用純繪圖後端，不開視窗
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

# 讓 matplotlib 畫得出中文標籤（三角形、斜邊…），並修正中文字型下負號顯示錯誤的問題
matplotlib.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Noto Sans TC", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False
# 備用字型：中文字型裡沒有的符號（≅ 全等、∼ 相似、⇒、⇔、✓…）改用 matplotlib 內建、每台電腦都有的
# DejaVu Sans 補上，不然會畫成方框。一定要寫在 font.family：這份清單的每一項各是一套字型，缺字時依序往後找；
# 上面的 font.sans-serif 清單只會挑出「第一套找得到的」字型，寫在那裡不會有備用效果。
matplotlib.rcParams["font.family"] = ["sans-serif", "DejaVu Sans"]

app = FastAPI()

# 告訴系統，前端網頁傳來的「問題」應該長什麼樣子（一定要包含 message 字串）
# conversation_id 是「這句話要接在哪一條對話串底下」；前端第一次送訊息可以不帶，
# 後端會自動幫忙開一條新的，並在回覆裡告訴前端新開的 id 是什麼。
class ChatRequest(BaseModel):
    message: str
    image_data: Optional[str] = None
    mime_type: Optional[str] = None
    conversation_id: Optional[str] = None
    request_id: Optional[str] = None  # 前端每次送出產生的亂數；學生按「停止」時靠它撤銷這一輪

# 學生按「停止」時，前端送來要撤銷的是哪一輪
class CancelChatRequest(BaseModel):
    request_id: str

# 註冊／登入共用的格式：一組帳號密碼
class AuthRequest(BaseModel):
    username: str
    password: str

# 對話串改名時，前端會送這個格式過來
class RenameConversationRequest(BaseModel):
    title: str

# 刪除帳號時要再輸入一次密碼確認
class DeleteAccountRequest(BaseModel):
    password: str

# 管理員幫某個帳號重設密碼。帳號放在 body 而不是網址裡，帳號名稱含有「/」也不會出問題
class ResetPasswordRequest(BaseModel):
    username: str
    new_password: str

# 管理員刪除某個帳號（帳號一樣放在 body 裡）
class DeleteUserRequest(BaseModel):
    username: str

# 管理員幫某個學生產生學習建議
class StudentRequest(BaseModel):
    username: str

# 告訴系統，我們要回傳給前端網頁的「答案」會長什麼樣子
class ChatResponse(BaseModel):
    reply: str          # 老師的回覆內容
    used_tool: bool = False # 老師有沒有去翻講義（用來在網頁上顯示提示）
    conversation_id: str = ""  # 這句話最後存進了哪一條對話串（前端要記住，下一句才接得上）

# 這裡是「這次執行期間」的聊天室快取，用「對話串 id」當 key（不是帳號）——
# 一個帳號底下可能同時開好幾條對話串，每一條都要有自己獨立的 Gemini 聊天物件，
# 不然歷史紀錄會全部混在一起。真正長久保存的地方是 conversation_store.py 寫進去的
# SQLite，這個 dict 重啟就會清空，但清空後 get_or_create_chat() 會自動從資料庫把
# 對應那條對話串的歷史紀錄讀回來。
chat_sessions = {}
# 這個 cookie 存的是「登入後拿到的 session token」（見 auth_store.py），
# 不是帳號本身——瀏覽器只知道一串不能反推出密碼的亂數，真正的帳號要查資料庫才知道。
SESSION_COOKIE_NAME = "session_id"
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 180  # 180 天
# 管理員用另一個 cookie，和學生的登入狀態完全分開；有效時間也短很多
ADMIN_COOKIE_NAME = "admin_session_id"
ADMIN_COOKIE_MAX_AGE = 60 * 60 * auth_store.ADMIN_SESSION_HOURS

if config.ADMIN_PASSWORD == "admin":
    logger.warning("管理員密碼仍是預設的 admin；公開部署前請在 .env 設定 ADMIN_PASSWORD。")

# 畫圖工具把圖片存在這裡，前端用 /generated/<檔名> 讀取（最下面把整個 frontend 資料夾掛成靜態檔案）
GENERATED_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "generated")

# 給 exec() 用的「白名單」內建函式：只給畫圖真正需要的東西，
# 刻意不給 __import__、open、eval、exec、input 這些——這樣 AI 產生的程式碼
# 就沒辦法匯入其他模組、讀寫檔案、或再執行別的程式碼，降低任意程式碼執行的風險。
# 注意：這不是滴水不漏的沙盒（Python 本身很難做到 100% 隔離），只是合理的把關。
_ALLOWED_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len",
    "list", "max", "min", "range", "round", "set", "str", "sum", "tuple",
    "zip", "isinstance", "True", "False", "None", "print",
    # 繪圖程式碼也常用到、又碰不到檔案或模組的：排序、map/filter、次方、用 chr(65 + i) 標出 A, B, C…
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

# 自動檢查發現問題時，附在原本的指示後面，請 Gemini 修正上一版程式碼
_MATPLOTLIB_FIX_INSTRUCTION = """你上一次寫的程式碼有下面這些問題，請修正後重新寫一份完整的程式碼（規則跟上面一樣，只回傳程式碼）：
{problems}

上一次的程式碼：
{code}"""

# 畫好的圖交給 Gemini 看圖檢查時的指示
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
    """圖形的範圍是不是超出座標軸範圍（容許 2% 的誤差，貼著邊的點不算）。"""
    dx, dy = box.width * 0.02, box.height * 0.02
    return (extent.x0 < box.x0 - dx or extent.x1 > box.x1 + dx
            or extent.y0 < box.y0 - dy or extent.y1 > box.y1 + dy)

def _overlap_ratio(a, b) -> float:
    """兩個文字框重疊的面積，占比較小那個框的比例。"""
    w = min(a.x1, b.x1) - max(a.x0, b.x0)
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    smaller = min(a.width * a.height, b.width * b.height)
    return w * h / smaller if w > 0 and h > 0 and smaller > 0 else 0.0

# 幾何圖形（多邊形、長方形、圓、弧、扇形），x、y 比例不一樣就會變形。
# 長條圖、直方圖的長條（放在 ax.containers 裡）和 ax.arrow 畫的箭頭（FancyArrow）不算。
_GEOMETRY_PATCH_TYPES = (mpatches.Polygon, mpatches.Rectangle, mpatches.Ellipse, mpatches.RegularPolygon, mpatches.Wedge)

def _has_geometry_shapes(ax) -> bool:
    chart_bars = {id(p) for container in ax.containers for p in container}
    return any(isinstance(p, _GEOMETRY_PATCH_TYPES) and not isinstance(p, mpatches.FancyArrow)
               and id(p) not in chart_bars for p in ax.patches)

def _is_stretched(ax) -> bool:
    """x、y 一單位畫出來的長度差超過 5%（沒設 ax.set_aspect('equal') 時常見，預設的畫布差了 12%）。"""
    if ax.name != "rectilinear" or ax.get_xscale() != "linear" or ax.get_yscale() != "linear":
        return False
    (x0, y0), (x1, y1) = ax.transData.transform([(0, 0), (1, 1)])
    return y1 != y0 and abs(abs(x1 - x0) / abs(y1 - y0) - 1) > 0.05

# 描述裡用「三角形ABC」「點P」「∠B」「線段AB」這類說法提到的點，圖上一定要標出名稱。
# 只認這些說法後面緊跟著的大寫字母，像「SAS 全等」「AB=3」這種沒有前導詞的不算，避免誤判。
_POINT_NAMES_IN_PROMPT = re.compile(
    r"(?:△|∠|三角形|四邊形|五邊形|六邊形|多邊形|梯形|菱形|正方形|長方形|矩形|扇形|圓心|圓|弧|頂點|點|線段|直線|射線|邊|角)"
    r"\s*([A-Z]+)(?![A-Za-z])"
)

def _missing_point_names(fig, prompt: str) -> list:
    """描述裡提到、但圖上任何文字都沒出現的點名稱（例如描述說三角形ABC，圖上卻沒有 C）。"""
    names = sorted({letter for word in _POINT_NAMES_IN_PROMPT.findall(prompt) for letter in word})
    shown = " ".join(t.get_text() for t in fig.findobj(plt.Text))
    return [name for name in names if name not in shown]

# matplotlib 畫到「所有字型都沒有的字」時會發出這種警告，圖上那個字會變成方框（缺字、豆腐字）：
#   Glyph 9989 (\N{WHITE HEAVY CHECK MARK}) missing from font(s) Microsoft JhengHei, DejaVu Sans.
# （舊版 matplotlib 的寫法是 Glyph 9989 missing from current font.）
# 直接看畫圖當下的警告，連程式碼自己指定字型（fontfamily=...）的文字也查得到。
_MISSING_GLYPH_WARNING = re.compile(r"Glyph (\d+)\b.*\bmissing from")

def _unrenderable_characters(caught_warnings) -> list:
    """從畫圖時的警告找出字型顯示不出來、畫成方框的字（照出現順序、不重複）。"""
    chars = []
    for w in caught_warnings:
        match = _MISSING_GLYPH_WARNING.search(str(w.message))
        if match and chr(int(match.group(1))) not in chars:
            chars.append(chr(int(match.group(1))))
    return chars

def _layout_problems(fig, prompt: str = "") -> list:
    """
    不用問模型、程式自己就查得出來的問題：圖是空白的、圖形超出座標軸被切掉、文字標示互相重疊、
    幾何圖形被拉長變形（沒設 equal）、描述裡的點名稱沒標在圖上、有字型顯示不出來的字（會變方框）。
    """
    axes = fig.get_axes()
    if not fig.texts and not any(ax.lines or ax.patches or ax.collections or ax.texts or ax.images for ax in axes):
        return ["圖是空白的，什麼都沒有畫出來"]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")  # 同一個字每次畫都要記到，不能只警告第一次
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
    """
    在限制過的環境裡執行 AI 產生的 matplotlib 程式碼，畫完後存成圖片，
    回傳程式查得出來的版面問題（見 _layout_problems；prompt 是圖形描述，用來查點名稱有沒有標；空的代表沒問題）。
    只提供 plt / np / math 三個變數，builtins 也只給白名單裡的名字，
    程式碼裡如果有 import、open() 之類的操作會直接失敗（NameError），這時不會存出圖片。
    """
    plt.close("all")  # 保險起見，先清空前一次可能留下的畫布
    try:
        safe_globals = {"__builtins__": _SAFE_BUILTINS, "plt": plt, "np": np, "math": math}
        # globals 和 locals 一定要用同一個 dict：分開的話，程式碼最外層定義的變數（例如 fig, ax）
        # 會放進 locals，但程式碼裡的 def / lambda 只查得到 globals，一用到就 NameError、整張圖畫不出來。
        exec(compile(code, "<gemini_matplotlib_code>", "exec"), safe_globals)
        try:
            problems = _layout_problems(plt.gcf(), prompt)
        except Exception as e:  # 檢查本身出錯不該害圖存不出來
            logger.warning(f"繪圖版面檢查失敗，略過：{e}")
            problems = []
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        return problems
    finally:
        plt.close("all")

# 主要模型 + 備援模型的清單（依序嘗試），並去除重複（如果兩個設定成同一個模型，只留一個）。
MODEL_CANDIDATES = []
for _m in (config.CHAT_MODEL, config.FALLBACK_CHAT_MODEL):
    if _m and _m not in MODEL_CANDIDATES:
        MODEL_CANDIDATES.append(_m)

# Gemini 忙線／額度超過時常見的錯誤字樣。命中這些字樣才算「暫時性錯誤」，值得重試或換備援模型；
# 其他錯誤（例如金鑰錯誤、模型名稱打錯的 404）重試也沒用，應該直接讓錯誤往外拋出。
_RETRYABLE_ERROR_MARKERS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded")

def _is_retryable_error(e: Exception) -> bool:
    s = str(e)
    return any(marker in s for marker in _RETRYABLE_ERROR_MARKERS)

# 一般呼叫（老師回答、第一次寫繪圖程式碼）每次最多等這麼久。以前沒有上限，實測模型偶爾卡 4 分鐘以上，
# 學生的畫面一直轉圈；伺服器同一時間只處理一個請求，其他學生也跟著卡住。平常回答約 5～30 秒。
# 查課本、畫圖這些工具在兩次呼叫之間執行，不算在這個時間裡。
_CALL_TIMEOUT_S = 90

def _is_timeout_error(e: Exception) -> bool:
    """等太久沒回應（httpx 的 TimeoutException，或錯誤訊息寫 timed out）。"""
    return isinstance(e, (httpx.TimeoutException, TimeoutError)) or "timed out" in str(e).lower()

def _with_timeout(gen_config: Optional[types.GenerateContentConfig]) -> types.GenerateContentConfig:
    """幫這次呼叫加上 _CALL_TIMEOUT_S 秒的等待上限（已經有設的就不動）。"""
    gen_config = gen_config or types.GenerateContentConfig()
    if gen_config.http_options and gen_config.http_options.timeout:
        return gen_config
    return gen_config.model_copy(update={"http_options": types.HttpOptions(timeout=_CALL_TIMEOUT_S * 1000)})

def _with_retry_and_fallback(models, call_fn, max_attempts: int = 3):
    """
    依序嘗試 models 清單裡的每個模型呼叫 call_fn(model)：
      - 遇到「暫時性」錯誤（503 忙線中 / 429 額度超過）會在同一個模型內重試，
        重試間隔採指數退避（1 秒、2 秒、4 秒），重試用盡才換下一個備援模型。
      - 等太久沒回應（逾時）：這個模型正卡著，在它身上重試只會再卡一次，直接換下一個模型。
      - 遇到其他種類的錯誤（例如模型名稱打錯的 404、金鑰錯誤）不重試，直接往外拋出，
        不然學生會一直等到所有重試跟備援都跑完才看到錯誤訊息。
    回傳 (call_fn 的回傳值, 實際成功時用的模型名稱)；全部都失敗則拋出最後一次的錯誤。
    """
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
                    time.sleep(2 ** (attempt - 1))  # 1s, 2s, 4s
        else:
            logger.warning(f"模型 {model} 重試 {max_attempts} 次後仍失敗，改用下一個備援模型。")
    raise last_error

# 看圖檢查、以及「已經有圖時的重畫」都是加分項：學生最多只為它們多等這麼久，等不到就沿用原本的圖。
# 模型大塞車時一次 503 可能要一分多鐘才回來，照一般的重試＋備援，學生會為了檢查多等好幾分鐘。
_OPTIONAL_CALL_BUDGET_S = 30
# 問了這麼久還沒回應，就同時問下一個模型當後備
# （實測：主要模型寫繪圖程式碼約 20 秒；備援模型看圖檢查約 2 秒、寫程式碼約 5 秒）
_OPTIONAL_HEDGE_AFTER_S = 15
# 離時限剩不到這麼久，就不再開新的呼叫（反正來不及答完）
_OPTIONAL_MIN_CALL_S = 5
# Gemini 不接受少於 10 秒的等待上限（會回 400 INVALID_ARGUMENT）
_GEMINI_MIN_TIMEOUT_S = 10

def _call_gemini_within_budget(contents, gen_config: Optional[types.GenerateContentConfig] = None,
                               budget_s: Optional[float] = None, models: Optional[list] = None):
    """
    加分項專用的呼叫：總共最多等 budget_s 秒（預設 _OPTIONAL_CALL_BUDGET_S），在這段時間內盡量問到答案，
    回傳 (結果, 實際用的模型)。models 是依序要問的模型（預設 MODEL_CANDIDATES，第一個當「主要模型」）。
      - 從主要模型問起；回 503／429 這類暫時性錯誤，就稍等一下（1、2、4 秒）換下一個模型再問，主要、備援輪流。
      - 問了 _OPTIONAL_HEDGE_AFTER_S 秒還沒回應也不乾等：同時問下一個模型當後備。
      - 主要模型的答案優先：後備先答出來就先收著，主要模型失敗或時間到才用它（備援模型看圖、寫程式都比較弱）。
      - 時間到還沒有答案，就拋出最後一次的錯誤；其他種類的錯誤（例如模型名稱打錯）直接拋出。
    時限由這裡的迴圈把關，時間一到就不等了；每次呼叫本身的等待上限比時限多 5 秒，
    確保是這裡先喊停，而且那些沒等完的呼叫最多再過 5 秒也會自己結束，不會一直在背景拖著。
    """
    budget_s = budget_s or _OPTIONAL_CALL_BUDGET_S
    models = models or MODEL_CANDIDATES
    deadline = time.monotonic() + budget_s
    primary = models[0]
    pool = ThreadPoolExecutor(max_workers=2)
    waiting = {}   # 還在等回應的呼叫 → 問的是哪個模型
    backup = None  # 主要模型還沒回來時，其他模型先給的答案 (結果, 模型)
    asked = failures = 0
    last_error: Exception = TimeoutError(f"{budget_s:g} 秒內沒有模型回應")

    def time_left():
        return deadline - time.monotonic()

    def ask_next_model():
        """主要、備援輪流問，正在等回應的模型先跳過。"""
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
                # 問了很久還沒回應：同時問下一個模型當後備（已經有後備答案就不用了）
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
                backup = (result, model)  # 主要模型還在想：答案先收著
            if backup is not None and primary not in waiting.values():
                return backup
            if failed:
                # 稍等一下再問下一個模型；剩下的時間不夠問完一次就不問了
                pause = min(2 ** (failures - 1), 4)
                if time_left() > pause + _OPTIONAL_MIN_CALL_S:
                    time.sleep(pause)
                    ask_next_model()
    finally:
        pool.shutdown(wait=False)  # 沒等完的呼叫留在背景自己結束，不在這裡等
    if backup is not None:
        return backup
    raise last_error

def _call_gemini(contents, gen_config: Optional[types.GenerateContentConfig] = None, optional: bool = False,
                 budget_s: Optional[float] = None, models: Optional[list] = None):
    """
    呼叫 Gemini 產生內容，回傳 (結果, 實際用的模型)。models 是依序要問的模型，預設 MODEL_CANDIDATES。
    一般呼叫會重試並換備援模型（_with_retry_and_fallback），每次最多等 _CALL_TIMEOUT_S 秒；
    optional=True 是加分項，有總時限（_call_gemini_within_budget，budget_s 秒，預設 30 秒）。
    """
    if optional:
        return _call_gemini_within_budget(contents, gen_config, budget_s, models)
    call_config = _with_timeout(gen_config)
    return _with_retry_and_fallback(
        models or MODEL_CANDIDATES,
        lambda model: global_client.models.generate_content(model=model, contents=contents, config=call_config),
    )

def _write_plot_code(prompt: str, previous_code: str = "", problems: Optional[list] = None,
                     optional: bool = False) -> str:
    """請 Gemini 寫 matplotlib 繪圖程式碼；有 problems 時附上上一版程式碼和問題，請它修正後重寫。"""
    contents = f"{_MATPLOTLIB_CODE_INSTRUCTION}\n\n使用者描述：{prompt}"
    if problems:
        contents += "\n\n" + _MATPLOTLIB_FIX_INSTRUCTION.format(
            problems="\n".join(f"- {p}" for p in problems), code=previous_code
        )
    result, used_model = _call_gemini(contents, optional=optional)
    if used_model != config.CHAT_MODEL:
        logger.info(f"畫圖工具改用備援模型 {used_model} 產生繪圖程式碼。")
    code = (result.text or "").strip()
    # 保險起見還是清一下 Markdown 圍籬，避免模型沒完全照規則、還是包了 ```python ... ```
    code = re.sub(r"^```[a-zA-Z]*\n?", "", code)
    return re.sub(r"```$", "", code).strip()

def _try_render(code: str, filepath: str, prompt: str):
    """執行繪圖程式碼，回傳 (有沒有存出圖片, 問題清單)；程式跑不動時，錯誤訊息就是問題。"""
    try:
        return True, _render_matplotlib_code(code, filepath, prompt)
    except Exception as e:
        return False, [f"程式碼執行失敗：{type(e).__name__}: {e}"]

def _review_image(filepath: str, prompt: str) -> list:
    """把畫好的圖交給 Gemini 看圖檢查，回傳它發現的問題；檢查本身出錯就當作沒問題，不擋住這張圖。"""
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
    """
    這是一個用來「畫圖」的工具。當學生需要視覺化的幾何圖形或示意圖來幫助理解時，呼叫此工具。
    做法：先請 Gemini 把文字描述轉成一段 matplotlib 繪圖程式碼，再由後端在限制過的環境裡
    執行這段程式碼畫出圖片（而不是呼叫圖片生成模型），畫出來的圖形數字、座標都是精確的。
    :param prompt: 給畫圖工具的詳細文字描述，例如 "一個直角三角形，標示邊長 3, 4, 5"
    :return: 產生圖片的 Markdown 語法，例如 `![幾何圖形](/generated/123.png)`
    """
    global global_client
    if global_client is None:
        global_client = genai.Client(api_key=config.GEMINI_API_KEY)

    try:
        logger.info(f"開始生成 matplotlib 繪圖程式碼，描述: {prompt}")
        code = _write_plot_code(prompt)
        if not code:
            return "[圖片生成失敗：模型沒有回傳繪圖程式碼]"

        # 建立 generated 目錄 (如果不存在)
        os.makedirs(GENERATED_DIR, exist_ok=True)

        # 產生唯一的檔名
        filename = f"{uuid.uuid4().hex}.png"
        filepath = os.path.join(GENERATED_DIR, filename)
        drawn, problems = _try_render(code, filepath, prompt)

        # 自動檢查：程式跑不動、圖是空白的／被切掉／文字重疊／變形／漏標點名稱／缺字，或 Gemini 看圖發現畫錯
        # （例如畢氏定理的正方形畫進三角形裡），就把問題連同上一版程式碼交回去重寫，
        # 最多重畫 config.DRAW_MAX_FIXES 次。重畫出來的圖更好才換上去，檔名不變。
        for _ in range(config.DRAW_MAX_FIXES):
            if drawn and not problems:
                problems = _review_image(filepath, prompt)
                if not problems:
                    break
            logger.warning(f"繪圖有問題，附上問題請 Gemini 重寫：{problems}")
            try:
                # 已經有一張圖時，重畫只是加分項（optional）；還沒有圖時就一定要重試到底
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
                code, problems = new_code, new_problems  # 還是畫不出來：帶著新的錯誤訊息再試
            else:
                _remove_generated_images([os.path.basename(candidate)])
                break

        if not drawn:
            return f"[圖片生成失敗：{problems[0]}]"

        # 圖片說明直接拿描述來用，但要拿掉 [ ] 和換行（前端會認不出這段圖片語法）；
        # 也縮短一點——Gemini 要把整段語法抄進回覆，越短越不容易抄錯
        alt = re.sub(r"[\[\]\s]+", " ", prompt).strip()[:40] or "數學示意圖"
        return f"![{alt}](/generated/{filename})"
    except Exception as e:
        logger.error(f"圖片生成發生錯誤: {e}")
        return f"[圖片生成失敗：{str(e)}]"
# 這裡是預先準備好的 Gemini 叫號機 (Client)，先存起來，免得每次都要重新準備
global_client = None

def _ensure_client():
    """還沒建立 Gemini 叫號機就用金鑰建一個（背景標記、學習建議這些不經過聊天室的呼叫用）。"""
    global global_client
    if global_client is None:
        global_client = genai.Client(api_key=config.GEMINI_API_KEY)
    return global_client

# 這是給 Gemini 老師的「教戰守則」，告訴他該怎麼當個好老師。分成三段：
# 聊天時三段都用；反思機制改寫回覆時沒有工具可用，只給身分和教學紀律（見 reflection.py）。
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
    """
    這是一個用來「幫某一條對話串建立或找回專屬聊天室」的函數。
    如果是新開的對話串，就幫它開一個新的 Gemini 聊天物件；如果之前聊過（不論是這次執行期間
    聊過、還是伺服器重啟前聊過、存在資料庫裡），就把歷史紀錄讀回來接著聊。

    :param model: 這條聊天室要用哪個模型。快取是用 (conversation_id, model) 一起比對的——
        如果主要模型忙線、chat_endpoint 改用備援模型重試，這裡會用備援模型重新建立一個聊天物件
        （歷史紀錄一樣會從資料庫讀回來，所以不會漏掉先前聊過的內容）。
    """
    global global_client
    model = model or config.CHAT_MODEL
    # 如果還沒有準備好 Gemini 叫號機，就立刻用金鑰建立一個
    if global_client is None:
        global_client = genai.Client(api_key=config.GEMINI_API_KEY)

    cached = chat_sessions.get(conversation_id)
    # 如果這條對話串在這次執行期間還沒建立過聊天物件，或者快取裡是用別的模型建的
    # （例如上一輪因為主要模型忙線、換成備援模型建立），就重新建立一個
    if cached is None or cached[1] != model:
        # 從資料庫讀回這條對話串過去聊過的內容（新開的對話串就是空的）。
        # 就算伺服器剛剛重啟、記憶體裡的 chat_sessions 被清空，只要對話串 id 沒變，
        # 這裡就能把歷史對話接回來，老師不會失憶。
        history = conversation_store.load_history(conversation_id)
        if history:
            logger.info(f"對話串 {conversation_id[:8]}... 讀回 {len(history)} 則歷史訊息")

        # 正式幫他開一個聊天視窗，並且把教戰守則跟「翻講義工具、畫圖工具」都交給老師。
        # 畫圖的決定權交還給 Gemini 自己判斷（維持 AI Agent 的自主性）；
        # chat_endpoint 裡仍保留一個安全網——Gemini 這輪真的沒畫，後端才會事後補一張，
        # 但不會取代或干涉 Gemini 自己的判斷過程。
        chat = global_client.chats.create(
            model=model,
            history=history,
            config=types.GenerateContentConfig(
                system_instruction=TUTOR_INSTRUCTION,
                tools=[search_math_materials, generate_math_image],
                temperature=0.7, # 稍微給老師一點自由發揮的空間，讓語氣比較活潑
                # 每次呼叫最多等 _CALL_TIMEOUT_S 秒；卡住就換備援模型（見 _with_retry_and_fallback）
                http_options=types.HttpOptions(timeout=_CALL_TIMEOUT_S * 1000),
            )
        )
        # 把開好的聊天視窗、以及它是用哪個模型建的，一起存進這次執行期間的快取
        chat_sessions[conversation_id] = (chat, model)

    # 把屬於這條對話串的聊天視窗交出去
    return chat_sessions[conversation_id][0]

def _called_search_tool(chat, pre_len: int) -> bool:
    """
    精確判斷「這一輪對話裡，老師是否真的呼叫了 search_math_materials」。
    不能只看對話歷史多了幾句去猜——呼叫 generate_math_image（純畫圖，沒查課本）
    造成的歷史成長量，跟呼叫 search_math_materials 是一樣的，用長度猜會把「只有畫圖」
    誤判成「有查講義」。這裡直接檢查新增回合裡有沒有名字對得上的 function_call。
    """
    history = chat.get_history() or []
    for turn in history[pre_len:]:
        for part in (turn.parts or []):
            fc = getattr(part, "function_call", None)
            if fc is not None and getattr(fc, "name", None) == "search_math_materials":
                return True
    return False

# 回覆裡的 Markdown 圖片語法：![圖片說明](網址)
_IMAGE_MARKDOWN_RE = re.compile(r"!\[([^\]\n]*)\]\(([^)\s]*)\)")
# 畫圖工具存下來的圖片網址（檔名是 uuid 的十六進位字串）
_GENERATED_URL_RE = re.compile(r"/generated/([a-f0-9]+\.(?:png|jpg))")

def _is_generated_image(url: str) -> bool:
    """這個網址是不是指到畫圖工具真的存下來、而且現在還在的圖片檔。"""
    match = _GENERATED_URL_RE.fullmatch(url)
    return bool(match) and os.path.isfile(os.path.join(GENERATED_DIR, match.group(1)))

def _drawn_image_url(tool_result: str) -> Optional[str]:
    """從 generate_math_image 的回傳值找出圖片網址；畫失敗（回傳的是錯誤訊息）就回傳 None。"""
    match = _GENERATED_URL_RE.search(tool_result or "")
    return match.group(0) if match and _is_generated_image(match.group(0)) else None

def _images_drawn_this_turn(chat, pre_len: int) -> list:
    """
    這一輪 generate_math_image 真正畫出來的圖片網址。跟 _called_search_tool 一樣檢查新增回合，
    只是看的是工具的回傳值（function_response），不是呼叫本身——工具畫失敗時回傳的是錯誤訊息，不算。
    """
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
    """
    確保回覆裡的每張圖都真的存在。Gemini 有時沒呼叫畫圖工具（或工具畫失敗了），卻自己編出
    一段圖片語法，例如 ![示意圖](/generated/pythagorean_theorem.png)，學生就只看到一張破圖：
      - 網址指到真的檔案：保留。
      - 網址是編的，但這輪工具確實畫了圖（Gemini 抄錯網址）：換成工具畫的那張。
      - 網址是編的，這輪也沒畫出圖：照 Gemini 寫的圖片說明當場補畫一張；補畫失敗就拿掉這段語法。
    工具畫好了、Gemini 卻完全沒放進回覆的圖，補在回覆最前面。
    """
    unused = [url for url in drawn_urls if url not in reply]

    def fix(match):
        alt, url = match.group(1), match.group(2)
        if _is_generated_image(url):
            return match.group(0)
        if unused:
            logger.warning(f"回覆裡的圖片網址 {url} 抄錯了，換成這輪畫圖工具真正畫的圖。")
            return f"![{alt}]({unused.pop(0)})"
        logger.warning(f"回覆裡的圖片網址 {url} 不是畫圖工具產生的，照圖片說明補畫一張。")
        intro = match.string[:match.start()].rstrip().rsplit("\n", 1)[-1]  # 圖片前面那句，通常在介紹這張圖
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
    """這一輪老師呼叫 search_math_materials 查到的課本內容（反思機制拿來對照回覆有沒有跟課本不一致）。"""
    texts = []
    for turn in (chat.get_history() or [])[pre_len:]:
        for part in (turn.parts or []):
            fr = getattr(part, "function_response", None)
            if fr is not None and getattr(fr, "name", None) == "search_math_materials":
                texts.append(str((fr.response or {}).get("result", "")))
    return "\n---\n".join(t for t in texts if t)

# 自我檢查先問 config.REVIEW_MODEL（預設是備援模型，省下主要模型的免費額度），忙線再換主要模型
_REVIEW_MODELS = list(dict.fromkeys(m for m in (config.REVIEW_MODEL, *MODEL_CANDIDATES) if m))

def _reflect_on_reply(draft: str, student_message: str, recent_messages: list, references: str):
    """
    反思機制：回覆送出前先自我檢查，有問題就改寫（見 reflection.py）。
    檢查和改寫都是加分項：有時限、忙線就換模型，做不成就送原稿。
    檢查用 _REVIEW_MODELS；改寫是學生直接看到的回覆，照常從主要模型問起。
    """
    _ensure_client()
    return reflection.reflect(
        lambda contents, gen_config, budget_s, step: _call_gemini(
            contents, gen_config, optional=True, budget_s=budget_s,
            models=_REVIEW_MODELS if step == reflection.STEP_REVIEW else None,
        )[0],
        draft, student_message, recent_messages, references, _REWRITE_INSTRUCTION,
    )

# 學習標記用便宜的模型就夠（config.LEARNING_MODEL），忙線再改用主要模型
_LEARNING_MODELS = list(dict.fromkeys(m for m in (config.LEARNING_MODEL, config.CHAT_MODEL) if m))

def _record_learning(username: str, conversation_id: str, message_id: int, student_message: str,
                     reply: str, previous_reply: str) -> None:
    """
    在背景標記這一輪的學習狀況（單元、觀念、答對沒有…），存進 learning_store（見 learning_analysis.tag_turn）。
    回覆已經送到學生手上才做，不影響等待時間；標記失敗就算了，這一輪只是不列入學習紀錄。
    """
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

# 註冊帳號：只是把帳密存進資料庫（密碼會先雜湊過），不會自動幫你登入
@app.post("/api/register")
async def register_endpoint(auth: AuthRequest):
    # 「admin」保留給管理員：一般使用者不能拿來當帳號，也不能當密碼
    if auth_store.is_reserved_username(auth.username):
        return JSONResponse(status_code=400, content={"error": "這個帳號名稱是保留字，請換一個"})
    if auth_store.is_reserved_password(auth.password):
        return JSONResponse(status_code=400, content={"error": "不能使用「admin」當作密碼，請換一個"})
    if auth_store.register_user(auth.username, auth.password):
        logger.info(f"新帳號註冊成功: {auth.username}")
        return {"message": "註冊成功，請登入"}
    return JSONResponse(status_code=409, content={"error": "帳號已存在，或帳號密碼不可空白"})

# 登入：帳密核對成功後，發一組 session token 存進 cookie，之後 /api/chat 都靠這個 cookie 認人
@app.post("/api/login")
async def login_endpoint(auth: AuthRequest, response: Response):
    # 管理員只能從 /admin 登入；這裡一律當成帳密錯誤，不透露管理後台的存在
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

# 登出：把這組 token 從資料庫刪掉，並清掉瀏覽器的 cookie
@app.post("/api/logout")
async def logout_endpoint(http_request: Request, response: Response):
    auth_store.delete_session(http_request.cookies.get(SESSION_COOKIE_NAME))
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"message": "已登出"}

# 前端每次載入頁面時，靠這個 API 確認「現在算不算已登入、是哪個帳號」
@app.get("/api/me")
async def me_endpoint(http_request: Request):
    username = auth_store.resolve_session(http_request.cookies.get(SESSION_COOKIE_NAME))
    return {"username": username}

def _current_username(http_request: Request) -> Optional[str]:
    """從 cookie 查出目前登入的帳號；查不到（沒登入）回傳 None。給下面幾個 API 共用。"""
    return auth_store.resolve_session(http_request.cookies.get(SESSION_COOKIE_NAME))

# 刪除對話串或帳號之前，先把對話裡提到的圖片檔名都找出來——每張生成的圖片檔名都是
# 隨機亂數，不會被其他對話重複用到，所以對話一刪，裡面提到的圖片檔案也可以放心一起清掉，
# 不會再變成沒人記得、卻一直占空間的孤兒檔案。
def _collect_image_filenames(conversation_id: str) -> set:
    """找出某條對話串的訊息裡引用到的所有生成圖片檔名。"""
    filenames = set()
    for m in conversation_store.load_messages_for_display(conversation_id):
        filenames.update(_GENERATED_URL_RE.findall(m.get("text") or ""))
    return filenames

def _remove_generated_images(filenames) -> None:
    """刪掉 frontend/generated/ 底下的這些圖片檔；檔案已經不在就略過。"""
    for filename in filenames:
        try:
            os.remove(os.path.join(GENERATED_DIR, filename))
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"刪除對話串附帶圖片失敗（{filename}）: {e}")

def _delete_account_and_data(username: str) -> None:
    """
    刪除帳號：帳號、所有登入 session、所有對話串與訊息、學習紀錄、對話裡的圖片全部刪掉，無法復原。
    使用者自己刪除帳號、管理員刪除別人的帳號都走這裡，兩邊刪得一樣徹底。
    """
    image_filenames = set()
    for conv in conversation_store.list_conversations(username):
        image_filenames |= _collect_image_filenames(conv["id"])
        chat_sessions.pop(conv["id"], None)

    # 先刪對話、最後才刪帳號：萬一中途出錯，留下的是「還在、只是沒有對話的帳號」，
    # 可以再刪一次；反過來的話，會留下一堆沒有主人的對話，之後有人用同一個名字
    # 註冊，就會在清單裡看到前一個人的對話紀錄。學習紀錄同理，也在刪帳號之前刪。
    learning_store.delete_for_user(username)
    conversation_store.delete_all_conversations(username)
    auth_store.delete_user(username)
    _remove_generated_images(image_filenames)

# 使用者自己刪除帳號
@app.post("/api/account/delete")
async def delete_account_endpoint(
    request: DeleteAccountRequest, http_request: Request, response: Response
):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    # 再核對一次密碼：避免誤按，也避免別人拿你沒登出的電腦把帳號刪掉。
    # 用 403 而不是 401，前端才分得出「密碼打錯」和「登入已失效」。
    if not auth_store.verify_user(username, request.password):
        return JSONResponse(status_code=403, content={"error": "密碼錯誤"})

    _delete_account_and_data(username)
    response.delete_cookie(SESSION_COOKIE_NAME)
    logger.info(f"帳號已刪除: {username}")
    return {"message": "帳號已刪除"}

# 開一條新的對話串（左側「對話紀錄」清單裡的「+ 新對話」按鈕會呼叫這個）
@app.post("/api/conversations")
async def create_conversation_endpoint(http_request: Request):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    conversation_id = conversation_store.create_conversation(username)
    return {"id": conversation_id, "title": "新的對話"}

# 列出目前帳號所有的對話串，給左側「對話紀錄」清單顯示用
@app.get("/api/conversations")
async def list_conversations_endpoint(http_request: Request):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    return {"conversations": conversation_store.list_conversations(username)}

# 讀出某一條對話串的完整內容，切換到舊對話時用這個把畫面補回來
@app.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages_endpoint(conversation_id: str, http_request: Request):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    # 一定要確認這條對話串真的是這個帳號的，不然改網址裡的 id 就能偷看別人的對話紀錄
    if conversation_store.get_conversation_owner(conversation_id) != username:
        return JSONResponse(status_code=404, content={"error": "找不到這條對話"})
    messages = conversation_store.load_messages_for_display(conversation_id)
    # 老師的舊回覆也整理一次：文字整理是後來才加的，之前存進去的回覆裡可能還有 $a$ 這種 LaTeX
    for m in messages:
        if m["role"] == "model":
            m["text"] = clean_reply_text(m["text"])
    return {"messages": messages}

# 刪除一條對話串
@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation_endpoint(conversation_id: str, http_request: Request):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    if conversation_store.get_conversation_owner(conversation_id) != username:
        return JSONResponse(status_code=404, content={"error": "找不到這條對話"})

    # 圖片檔名要在刪除資料庫紀錄「之前」找出來，刪掉之後就查不到了
    image_filenames = _collect_image_filenames(conversation_id)
    # 這條對話的學習紀錄也一起刪：學生刪掉對話，就是不想留下這段紀錄
    learning_store.delete_for_conversation(conversation_id)
    conversation_store.delete_conversation(conversation_id)
    chat_sessions.pop(conversation_id, None)  # 記憶體快取裡也順便清掉，避免刪除後還殘留
    _remove_generated_images(image_filenames)
    return {"message": "已刪除"}

# 幫一條對話串改名（左側「對話紀錄」清單的鉛筆圖示會呼叫這個）
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

# ===== 學習紀錄（/learning 頁面；管理後台看單一學生時也用同一份報告）=====

_ADVICE_BUDGET_S = 45

def _learning_report(username: str) -> dict:
    """某個帳號的學習紀錄：學習標記＋訊息時間整理成的報告，加上最近一次的 AI 學習建議。"""
    report = learning_analysis.build_report(
        learning_store.events_for_user(username),
        [t for _, t in conversation_store.student_message_times(username)],
    )
    report["username"] = username
    report["advice"] = learning_store.get_advice(username)
    return report

def _generate_advice(username: str):
    """請 Gemini 依學習紀錄寫學習建議並存起來；紀錄太少就不寫（寫了也不準）。"""
    report = _learning_report(username)
    if not learning_analysis.has_enough_data(report):
        return JSONResponse(status_code=400, content={"error": "紀錄還太少，多和老師練習幾題，再來看學習建議吧！"})
    try:
        _ensure_client()
        # 有時限：模型忙線或卡住時，最多讓學生等 _ADVICE_BUDGET_S 秒就告訴他等一下再試
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

# 學生按「產生學習建議」才呼叫（每按一次就花一次 Gemini 的費用，所以不會自動產生）
@app.post("/api/learning/advice")
async def learning_advice_endpoint(http_request: Request):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    return _generate_advice(username)

# ===== 管理後台 API（/admin 頁面使用）=====
# 管理員的帳密來自 config（.env），不在 users 表裡；登入後拿到的是另一個 cookie，
# 所以學生的登入狀態完全拿不到這些 API，管理員的登入也不會變成某個學生帳號。

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

# 帳號列表：帳號、註冊時間、對話串數、訊息數、最後活動時間。
# 密碼是單向雜湊，連管理員也看不到原文，所以這裡不回傳任何密碼相關欄位。
@app.get("/api/admin/users")
async def admin_list_users_endpoint(http_request: Request):
    if not _is_admin(http_request):
        return JSONResponse(status_code=401, content={"error": "請先以管理員身分登入"})
    stats = conversation_store.stats_by_user()
    empty = {"conversation_count": 0, "message_count": 0, "last_active": None}
    users = [{**u, **stats.get(u["username"], empty)} for u in auth_store.list_users()]
    return {"users": users}

# 重設密碼：學生忘記密碼時，管理員幫他設一組新的；這個帳號所有裝置都會被登出
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

# 刪除帳號：管理員刪掉某個帳號，跟使用者自己刪除一樣徹底（對話、圖片、所有裝置的登入都刪掉），無法復原。
# 不用輸入那個帳號的密碼（管理員本來就不知道）；防止點錯人的確認步驟在 admin.js：要打一次帳號名稱。
@app.post("/api/admin/delete-user")
async def admin_delete_user_endpoint(request: DeleteUserRequest, http_request: Request):
    if not _is_admin(http_request):
        return JSONResponse(status_code=401, content={"error": "請先以管理員身分登入"})
    if not auth_store.user_exists(request.username):
        return JSONResponse(status_code=404, content={"error": "找不到這個帳號，可能已經被刪除了"})
    _delete_account_and_data(request.username)
    logger.info(f"管理員刪除了帳號: {request.username}")
    return {"message": "帳號已刪除"}

# 學習分析：全班總覽（活躍人數、最常卡住的單元、每個學生的概況、很久沒上線的學生）＋老師自我檢查的統計
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

# 某個學生的學習紀錄（跟學生自己看到的是同一份）。帳號放在查詢參數，帳號名稱有「/」也沒問題
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

# 老師自我檢查發現問題的紀錄：學生的問題、原稿、學生實際看到的回覆、發現了什麼問題
@app.get("/api/admin/reviews")
async def admin_reviews_endpoint(http_request: Request):
    if not _is_admin(http_request):
        return JSONResponse(status_code=401, content={"error": "請先以管理員身分登入"})
    return {"reviews": learning_store.recent_reviews()}

# ===== 學生按「停止」：撤銷這一輪問答 =====
# 前端按停止時會帶著這一輪的 request_id 呼叫 /api/chat/cancel。/api/chat 目前一次只處理一個請求
# （async 端點裡都是同步呼叫），所以取消通常要等這一輪跑完、問答已經存進資料庫之後才輪到它，
# 這時就把存進去的東西撤銷掉。取消也可能先到（例如以後改成可以同時處理多個請求），
# 那就先記下來，這一輪跑完時直接不存。兩邊都只記最近幾輪：停止通常是送出後幾十秒內的事。
_finished_turns = {}       # request_id → 這一輪存了哪些東西（撤銷時要刪掉）
_cancelled_requests = {}   # 還沒跑完就被取消的 request_id → 帳號
_MAX_REMEMBERED_TURNS = 200

def _remember(registry: dict, key: str, value) -> None:
    registry[key] = value
    while len(registry) > _MAX_REMEMBERED_TURNS:
        registry.pop(next(iter(registry)))  # dict 照放進去的順序排，最前面的就是最舊的

def _discard_turn(turn: dict) -> None:
    """
    撤銷一輪問答：刪掉這一輪存進資料庫的問與答、這一輪畫的圖；這一輪才開的新對話串整條刪掉。
    記憶體裡的聊天物件也還記得這一輪，直接丟掉，下一句話會從資料庫重新讀歷史，老師就不會記得。
    """
    conversation_id = turn["conversation_id"]
    # 這一輪的學習標記、自我檢查紀錄也一起刪（背景標記晚一點才做完的話，存的時候會發現訊息已經不在，不會存）
    if turn["created_conversation"]:
        learning_store.delete_for_conversation(conversation_id)
        conversation_store.delete_conversation(conversation_id)
    else:
        learning_store.delete_for_messages(turn["message_ids"])
        conversation_store.delete_messages(conversation_id, turn["message_ids"])
    chat_sessions.pop(conversation_id, None)
    # 回覆裡的圖可能是 Gemini 再次引用前幾輪的舊圖，還留著的訊息有用到的就不能刪
    _remove_generated_images(turn["images"] - _collect_image_filenames(conversation_id))

@app.post("/api/chat/cancel")
async def cancel_chat_endpoint(request: CancelChatRequest, http_request: Request):
    username = _current_username(http_request)
    if not username:
        return JSONResponse(status_code=401, content={"error": "請先登入"})
    turn = _finished_turns.get(request.request_id)
    if turn is None:
        # 這一輪還沒跑完（或根本沒送到）：先記下來，跑完時就不存
        _remember(_cancelled_requests, request.request_id, username)
        return {"message": "已停止"}
    if turn["username"] != username:
        return JSONResponse(status_code=404, content={"error": "找不到這一輪對話"})
    del _finished_turns[request.request_id]
    _discard_turn(turn)
    logger.info("學生按了停止，撤銷剛剛存進去的這一輪問答。")
    return {"message": "已停止"}

# 當前端網頁透過 /api/chat 送出問題時，就會觸發這裡
@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, http_request: Request, background_tasks: BackgroundTasks):
    logger.info(f"收到來自前端的問題: {request.message}")
    try:
        # 一定要先登入：用 cookie 裡的 session token 查出是哪個帳號在問問題。
        # 查不到（沒登入、或 token 過期/被登出）就直接拒絕，不再像以前那樣自動發一個匿名身分。
        username = auth_store.resolve_session(http_request.cookies.get(SESSION_COOKIE_NAME))
        if not username:
            return JSONResponse(status_code=401, content={"error": "請先登入"})

        # 找出這句話要接在哪一條對話串底下：
        # 前端有帶 conversation_id → 先確認真的是這個帳號的，不能用別人的 id 亂接話；
        # 沒有帶（例如全新登入後的第一句話）→ 後端自動幫忙開一條新的。
        conversation_id = request.conversation_id
        created_conversation = False  # 這一輪才開的新對話串：學生按「停止」時要整條刪掉
        if conversation_id:
            if conversation_store.get_conversation_owner(conversation_id) != username:
                return JSONResponse(status_code=404, content={"error": "找不到這條對話"})
        else:
            conversation_id = conversation_store.create_conversation(username)
            created_conversation = True
            logger.info(f"沒有帶 conversation_id，自動開一條新對話串：{conversation_id[:8]}...")

        # 這個判斷同時用在兩個地方：
        # ① 是不是要跳過查課本（畫圖句子的用詞常常跟幾何題目語意很像，硬塞課本內容反而會岔題）
        # ② 這輪 Gemini 若沒有真的畫出圖，後端要不要事後補畫（見下方安全網；
        #    要不要畫圖本身還是先交給 Gemini 自己判斷，維持 Agent 的自主性）
        drawing_keywords = ["畫", "繪製", "draw", "plot", "graph", "sketch", "diagram", "figure"]
        msg_lower = request.message.lower()
        looks_like_drawing_request = any(kw in msg_lower for kw in drawing_keywords)
        prefetched = None if looks_like_drawing_request else prefetch_context(request.message)

        # 準備要傳送給老師的訊息內容
        message_parts = []
        if prefetched:
            message_parts.append(
                "[系統自動檢索到以下可能相關的課本內容，這是自動比對出來的，不一定符合學生"
                "「這次」的真正意圖。只有在內容確實直接對應學生這次的問題時才使用，並讓學生知道"
                "這是依據國中課本的內容（不要說頁碼、章節或例題編號，也不要說「我們的課本／講義」，"
                "學生手上的課本版本不一定跟這份一樣）；如果學生其實是在要求你做某件事（例如畫圖），或者這份資料主題對不上，"
                "就完全忽略它、不要提到它，直接處理學生原本的請求]\n" + prefetched
            )
        # 每一輪都明確標出「這是學生現在真正要問的內容」，避免老師在對話拉長之後，
        # 一直卡在自己上一輪還沒被回答的反問，而忽略學生這次問的新東西。
        message_parts.append(
            "【學生這次實際問的內容如下，請務必針對這句話本身回答；如果這句話明顯跟"
            "你上一輪問過的問題不同主題，就直接切換過去處理這次的新內容，不要忽略它、"
            "也不要繼續糾結在你自己上一輪還沒被回答的反問上。如果這句話看起來就是在"
            "回答你上一輪的提問，才正常接續下去】\n" + request.message
        )
        if request.image_data and request.mime_type:
            try:
                # 解析 Base64 圖片
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
                
        # 把問題傳給老師，並等老師回答。
        # 主要模型如果遇到「忙線中/額度超過」這類暫時性錯誤，會先在原模型重試幾次，
        # 重試用盡才自動改用備援模型（見 get_or_create_chat 對 (conversation_id, model) 的快取邏輯）。
        # pre_len 要在「真正成功送出的那個模型」對應的 chat 上算，所以放進 lambda 裡面一起做。
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
            # 文字整理：Gemini 偶爾還是會用 LaTeX（$a$、\frac{1}{3}），或在中文裡夾一個日文的「の」，
            # 前端顯示不出來，這裡換成一般符號（見 reply_cleanup.py）
            reply = clean_reply_text(reply)
            # 圖片檢查：Gemini 有時沒呼叫畫圖工具（或工具畫失敗了），卻自己編一個圖片網址
            # （例如 /generated/pythagorean_theorem.png），學生只會看到破圖；也可能工具畫好了，
            # 回覆裡卻抄錯或漏掉網址。這裡把回覆裡的每張圖都對過一遍，見 _fix_reply_images()。
            reply = _fix_reply_images(reply, _images_drawn_this_turn(chat, pre_len), request.message)

        # 安全網：要不要畫圖、要不要呼叫工具，維持交給 Gemini 自己判斷（保留 Agent 的自主性）。
        # 但如果學生訊息裡有「畫」、Gemini 這輪卻沒有真的產生圖片，後端才事後補畫一張——
        # 這裡不干涉 Gemini 的判斷過程，只在它真的漏掉時介入，不然實測「務必畫圖」這種
        # 純文字指令仍只有約六成會照做。經過上面的檢查，回覆裡剩下的圖片都指到真的檔案。
        if looks_like_drawing_request and not _IMAGE_MARKDOWN_RE.search(reply or ""):
            logger.warning("學生要求畫圖，但這輪回覆沒有圖片，後端直接補畫一張。")
            # 用明確的祈使句包一層再丟給畫圖工具——學生原句常常是疑問句
            # （例如「...要怎麼畫才會準？」），疑問句直接拿去產生程式碼，
            # 有機會被誤解成「回答問題」而不是「真的畫一張圖」，包成祈使句比較穩定。
            fallback_image = generate_math_image(f"請畫出以下描述對應的數學圖形：{request.message}")
            if fallback_image.startswith("!["):
                reply = f"{fallback_image}\n\n{reply or ''}".strip()

        # 「有沒有翻講義」＝ 主動預查有沒有命中，或老師這輪有沒有真的呼叫 search_math_materials。
        # 注意：不能用「歷史紀錄多了幾句」去猜——呼叫 generate_math_image（純畫圖，沒查課本）
        # 造成的歷史成長量跟呼叫 search_math_materials 一樣，用長度猜會把「只有畫圖」誤判成「有查講義」。
        used_tool = bool(prefetched) or _called_search_tool(chat, pre_len)

        # 反思機制：回覆送出前先自我檢查（直接給答案、算錯、跟課本不一致、答非所問），有問題就改寫。
        # 學生只會看到改好的版本；檢查結果等這一輪存好後記下來，管理後台看得到（見 reflection.py）。
        recent_messages = conversation_store.load_messages_for_display(conversation_id)
        reflected = None
        if reply and config.REPLY_REVIEW:
            references = "\n---\n".join(t for t in (prefetched, _references_this_turn(chat, pre_len)) if t)
            reflected = _reflect_on_reply(reply, request.message, recent_messages, references)
            if reflected.status == learning_store.REVIEW_REVISED:
                reply = clean_reply_text(reflected.reply)
                # 聊天物件記得的是原稿：丟掉，下一句話從資料庫（存的是改寫後的版本）重新讀歷史
                chat_sessions.pop(conversation_id, None)

        turn = {"username": username, "conversation_id": conversation_id, "created_conversation": created_conversation,
                "images": set(_GENERATED_URL_RE.findall(reply or "")), "message_ids": []}
        # 學生在老師回完之前就按了「停止」，而且取消比這一輪先處理到：這一輪不存，老師也不會記得
        if request.request_id and _cancelled_requests.pop(request.request_id, None) == username:
            _discard_turn(turn)
            logger.info("學生按了停止，這一輪問答不存。")
            return JSONResponse(status_code=409, content={"error": "這一輪已經停止了"})

        # 把這一輪的問與答存進資料庫，下次（甚至伺服器重啟後）才接得回來。
        # 只存乾淨的一問一答文字，不存查課本／畫圖當下的工具呼叫細節——
        # 老師之後只需要記得「聊過什麼」，不需要重新跑一次當初的工具呼叫。
        user_message_id = conversation_store.append_message(conversation_id, "user", request.message)
        reply_message_id = conversation_store.append_message(conversation_id, "model", reply)
        turn["message_ids"] = [i for i in (user_message_id, reply_message_id) if i is not None]
        if request.request_id:
            _remember(_finished_turns, request.request_id, turn)  # 學生之後按「停止」時，才知道要撤銷什麼

        if reflected is not None:
            learning_store.add_review(username, conversation_id, user_message_id, reply_message_id,
                                      reflected.status, reflected.problems, reflected.draft, reflected.seconds)
        # 學習歷程：回覆送出之後，在背景標記這一輪的單元、觀念、答對沒有（不影響學生的等待時間）
        if user_message_id is not None and reply:
            previous_reply = next((m["text"] for m in reversed(recent_messages) if m["role"] == "model"), "")
            background_tasks.add_task(_record_learning, username, conversation_id, user_message_id,
                                      request.message, reply, previous_reply)

        # 把老師的回答、有沒有翻講義、以及這句話存進了哪條對話串，打包傳回給網頁
        return ChatResponse(reply=reply, used_tool=used_tool, conversation_id=conversation_id)
    except Exception as e:
        logger.error(f"模型回應失敗: {e}")
        # 如果發生任何當機或錯誤，就溫柔地回報錯誤訊息
        return ChatResponse(reply=f"[系統錯誤] 老師好像有點累了，請稍後再試。({str(e)})")

# 告訴系統，我們的網頁檔案 (HTML, CSS 等等) 放在哪裡
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

# 當使用者打開網站首頁 (/) 時，把 index.html 這個網頁傳給他看
@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(frontend_dir, "index.html"))

# 管理後台：和學生的登入頁分開，網址是 /admin
@app.get("/admin")
async def serve_admin():
    return FileResponse(os.path.join(frontend_dir, "admin.html"))

# 學生的「我的學習紀錄」頁（側欄的「學習紀錄」連過來；沒登入時頁面自己會帶回首頁）
@app.get("/learning")
async def serve_learning():
    return FileResponse(os.path.join(frontend_dir, "learning.html"))

# 其他像是圖片、樣式表 (CSS)、或者是網頁邏輯檔 (JS)，都統統交由系統自己去 frontend 目錄下找
app.mount("/", StaticFiles(directory=frontend_dir), name="frontend")
