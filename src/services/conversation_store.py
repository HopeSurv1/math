# -*- coding: utf-8 -*-
"""
src/services/conversation_store.py
功能簡介：對話紀錄持久化服務。每個帳號可以開很多條「對話串」（類似 ChatGPT 左側那份歷史清單），
          可以開新對話、切換到舊的、查看內容、刪除。每一條對話串的訊息各自獨立保存，
          重新整理網頁或伺服器重啟都不會消失。
主要函數：
  - create_conversation(username): 開一條新的對話串，回傳它的 id。
  - list_conversations(username): 列出某帳號所有對話串（最新更新的排最前面）。
  - get_conversation_owner(conversation_id): 查這條對話串是哪個帳號的，用來做權限檢查
    （不能讓 A 帳號看到或刪除 B 帳號的對話）。
  - delete_conversation(conversation_id): 刪除一條對話串（含裡面所有訊息）。
  - delete_all_conversations(username): 刪除某帳號的所有對話串與訊息（刪除帳號時用）。
  - stats_by_user(): 每個帳號的對話串數、訊息數、最後活動時間（管理後台用，不含對話內容）。
  - student_message_times(username): 學生每則訊息的送出時間（學習紀錄算使用天數、時間用，不含內容）。
  - rename_conversation(conversation_id, title): 使用者手動幫對話串改名。
  - append_message(conversation_id, role, text): 存一筆訊息，回傳它的 id；如果這是這條對話串的第一則
    使用者訊息，順便拿它的前面幾個字當作標題（就像 ChatGPT 自動幫對話命名一樣）。
  - delete_messages(conversation_id, message_ids): 刪掉指定的幾則訊息（學生按「停止」撤銷一輪問答時用）。
  - load_history(conversation_id): 讀出某對話串的完整內容，轉成 Gemini SDK 看得懂的格式，
    用在「重新建立聊天室」時餵回歷史紀錄。
  - load_messages_for_display(conversation_id): 讀出某對話串的完整內容，給前端顯示用
    （單純的 [{role, text}, ...]，不是 Gemini 的格式）。

資料庫相容性：這個檔案原本只有一張「訊息表」，session_id 直接存帳號名稱，一個帳號只能有
一條對話串。加入「多對話串」功能時，_get_connection() 會自動偵測舊資料、幫舊訊息各自
建立一條對話串保留下來，不會弄丟任何人先前的對話。
相依模組：
  - sqlite3、uuid（皆為 Python 內建）
  - google.genai.types（組出 Gemini 要的 Content/Part 格式）
  - src.config（資料庫檔案放哪裡）
"""

import sqlite3
import uuid
from typing import List, Optional
from google.genai import types
from src.config import config

DB_PATH = config.DATA_DIR / "conversations.db"

# 開新對話串時的預設標題；使用者送出第一則訊息後會自動改成那則訊息的內容
_DEFAULT_TITLE = "新的對話"
_TITLE_MAX_LEN = 24


def _get_connection() -> sqlite3.Connection:
    """每次呼叫都開一個新連線，用完即關——SQLite 檔案很小，這樣做最簡單也最安全。"""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '新的對話',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            conversation_id TEXT,
            role TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # 相容舊資料：如果 messages 表是舊版（沒有 conversation_id 欄位），先補上這個欄位——
    # 這一步一定要在建立 conversation_id 的索引「之前」做，不然索引會找不到這個欄位而炸掉。
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    if "conversation_id" not in existing_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN conversation_id TEXT")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_username ON conversations(username)")

    # 把「屬於真實帳號、但還沒有對話串」的舊訊息，各自搬進一條新建立的對話串裡，
    # 標題統一叫「先前的對話」，避免舊資料就此消失不見。
    # （session_id 曾經直接存帳號名稱；如果查不到對應帳號，代表是登入系統上線前的
    # 測試殘留資料，不屬於任何人，這裡不處理。）
    orphaned_usernames = conn.execute(
        """
        SELECT DISTINCT m.session_id FROM messages m
        JOIN users u ON u.username = m.session_id
        WHERE m.conversation_id IS NULL
        """
    ).fetchall()
    for (username,) in orphaned_usernames:
        legacy_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO conversations (id, username, title) VALUES (?, ?, ?)",
            (legacy_id, username, "先前的對話"),
        )
        conn.execute(
            "UPDATE messages SET conversation_id = ? WHERE session_id = ? AND conversation_id IS NULL",
            (legacy_id, username),
        )
    if orphaned_usernames:
        conn.commit()

    return conn


def create_conversation(username: str) -> str:
    """幫這個帳號開一條新的對話串，回傳它的 id。"""
    conversation_id = uuid.uuid4().hex
    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO conversations (id, username, title) VALUES (?, ?, ?)",
            (conversation_id, username, _DEFAULT_TITLE),
        )
    return conversation_id


def list_conversations(username: str) -> List[dict]:
    """列出這個帳號所有的對話串，最近更新的排最前面。"""
    with _get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, updated_at FROM conversations
            WHERE username = ? ORDER BY updated_at DESC
            """,
            (username,),
        ).fetchall()
    return [{"id": r[0], "title": r[1], "updated_at": r[2]} for r in rows]


def get_conversation_owner(conversation_id: str) -> Optional[str]:
    """查這條對話串是哪個帳號的；查不到就回傳 None（用來擋掉猜 id 亂讀/亂刪別人資料的請求）。"""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT username FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    return row[0] if row else None


def delete_conversation(conversation_id: str) -> None:
    """刪除一條對話串，連同裡面所有訊息一起刪掉。"""
    with _get_connection() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))


def delete_all_conversations(username: str) -> None:
    """刪除這個帳號的所有對話串，連同裡面所有訊息（刪除帳號時用）。"""
    with _get_connection() as conn:
        conn.execute(
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE username = ?)",
            (username,),
        )
        conn.execute("DELETE FROM conversations WHERE username = ?", (username,))


def stats_by_user() -> dict:
    """
    統計每個帳號的對話串數、訊息數與最後活動時間，給管理後台的帳號列表用。
    只回傳數字，不回傳任何對話內容。沒有對話過的帳號不會出現在結果裡。
    回傳 {username: {"conversation_count", "message_count", "last_active"}}。
    """
    with _get_connection() as conn:
        rows = conn.execute(
            """
            SELECT c.username, COUNT(DISTINCT c.id), COUNT(m.id), MAX(c.updated_at)
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.username
            """
        ).fetchall()
    return {
        r[0]: {"conversation_count": r[1], "message_count": r[2], "last_active": r[3]}
        for r in rows
    }


def student_message_times(username: Optional[str] = None) -> List[tuple]:
    """
    學生每則訊息的送出時間 [(帳號, UTC 時間字串), ...]，依時間排序，給學習紀錄算使用天數、時間用。
    只回傳時間，不回傳內容；username 不給就是全部帳號（管理後台的全班統計）。
    """
    sql = (
        "SELECT c.username, m.created_at FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        "WHERE m.role = 'user'"
    )
    params: tuple = ()
    if username is not None:
        sql += " AND c.username = ?"
        params = (username,)
    with _get_connection() as conn:
        return conn.execute(sql + " ORDER BY m.created_at ASC, m.id ASC", params).fetchall()


def rename_conversation(conversation_id: str, title: str) -> None:
    """使用者手動幫這條對話串改名（左側「對話紀錄」清單的鉛筆圖示會呼叫這個）。"""
    title = title.strip().replace("\n", " ")[:_TITLE_MAX_LEN] or _DEFAULT_TITLE
    with _get_connection() as conn:
        conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)
        )


def append_message(conversation_id: str, role: str, text: str) -> Optional[int]:
    """
    把一筆訊息存進資料庫，並把這條對話串的更新時間往後推，回傳這筆訊息的 id（text 是空的就不存，回傳 None）。
    如果這是這條對話串的第一則使用者訊息，順便拿它的前面幾個字當標題。
    """
    if not text:
        return None
    with _get_connection() as conn:
        # 舊版資料庫的 session_id 欄位是 NOT NULL（SQLite 沒辦法事後移除這個限制），
        # 新邏輯已經完全不靠 session_id 查資料了，這裡單純填 conversation_id 進去
        # 讓舊的欄位限制不會擋下寫入，之後也不會被讀取或依賴。
        message_id = conn.execute(
            "INSERT INTO messages (session_id, conversation_id, role, text) VALUES (?, ?, ?, ?)",
            (conversation_id, conversation_id, role, text),
        ).lastrowid
        conn.execute(
            "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (conversation_id,),
        )
        if role == "user":
            row = conn.execute(
                "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if row and row[0] == _DEFAULT_TITLE:
                title = text.strip().replace("\n", " ")[:_TITLE_MAX_LEN]
                conn.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)
                )
    return message_id


def delete_messages(conversation_id: str, message_ids: List[int]) -> None:
    """
    刪掉這條對話串裡指定的幾則訊息（學生按「停止」、撤銷一輪問答時用）。
    刪完如果一則都不剩，標題改回預設——標題是拿第一則訊息自動取的，那則訊息已經不在了。
    """
    with _get_connection() as conn:
        conn.executemany(
            "DELETE FROM messages WHERE id = ? AND conversation_id = ?",
            [(message_id, conversation_id) for message_id in message_ids],
        )
        remaining = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()[0]
        if remaining == 0:
            conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?", (_DEFAULT_TITLE, conversation_id)
            )


def load_history(conversation_id: str) -> List[types.Content]:
    """
    讀出某條對話串過去的訊息，依時間順序組成 Gemini 看得懂的 Content 清單。
    用在「重新建立聊天室」的時候餵給 chats.create(history=...)，讓老師接得上之前聊到哪裡。
    只存純文字的一問一答，不重播當初呼叫工具（查課本／畫圖）的中間過程——
    老師只需要記得「聊過什麼」，不需要重新跑一次當初的工具呼叫。
    """
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT role, text FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
    return [types.Content(role=role, parts=[types.Part(text=text)]) for role, text in rows]


def load_messages_for_display(conversation_id: str) -> List[dict]:
    """讀出某條對話串過去的訊息，給前端顯示用（單純的角色+文字，不是 Gemini 的格式）。"""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT role, text FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
    return [{"role": role, "text": text} for role, text in rows]
