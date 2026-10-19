# -*- coding: utf-8 -*-
"""
src/services/learning_store.py
功能簡介：學習歷程與反思機制的資料保存。跟帳號、對話紀錄共用 data/conversations.db，多三張表：
  - learning_events：每一輪問答的學習標記（單元、觀念、學生在做什麼、答對沒有、在解哪一題）。
    由 learning_analysis.tag_turn() 在背景標記，一輪一筆，對應學生那則訊息（message_id）。
  - reply_reviews：老師回覆送出前的自我檢查結果（通過／改寫過／發現問題但沒改成／沒檢查成），
    改寫過的會留下原稿，管理後台看得到改了什麼。
  - study_advice：每個帳號最近一次產生的 AI 學習建議（按按鈕才產生，存起來下次打開直接看）。
主要函數：
  - add_event / last_event / events_for_user / all_events：學習標記的寫入與讀取。
  - add_review / review_stats / recent_reviews：自我檢查紀錄的寫入與統計。
  - save_advice / get_advice：AI 學習建議。
  - delete_for_messages / delete_for_conversation / delete_for_user：學生按「停止」、刪除對話、
    刪除帳號時，跟著刪掉對應的紀錄，不留下沒有主人的資料。
相依模組：sqlite3、json（Python 內建）、src.services.conversation_store（共用它的資料庫連線）
"""

import json
import sqlite3
from typing import List, Optional

from src.services import conversation_store

# 每一筆學習標記有哪些欄位（除了 id、帳號、對話串、訊息 id、時間）
EVENT_FIELDS = ("unit", "concept", "activity", "result", "error_type", "problem_id", "problem", "solved")

# 自我檢查的結果
REVIEW_OK = "ok"              # 檢查過，沒問題
REVIEW_REVISED = "revised"    # 有問題，已經改寫，學生看到的是改寫後的版本
REVIEW_FLAGGED = "flagged"    # 有問題，但改寫沒成功（忙線、逾時），學生看到的是原稿
REVIEW_SKIPPED = "skipped"    # 檢查本身沒做成（忙線、逾時），學生看到的是原稿


def _get_connection() -> sqlite3.Connection:
    """
    用 conversation_store 的連線（同一個資料庫檔，它會先建好 conversations、messages 表），
    再補上這裡的三張表：存學習標記時要確認學生那則訊息還在、列出自我檢查時要 JOIN 出問答內容。
    """
    conn = conversation_store._get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            unit TEXT NOT NULL DEFAULT '',
            concept TEXT NOT NULL DEFAULT '',
            activity TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL DEFAULT '',
            error_type TEXT NOT NULL DEFAULT '',
            problem_id TEXT NOT NULL DEFAULT '',
            problem TEXT NOT NULL DEFAULT '',
            solved INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reply_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            user_message_id INTEGER,
            reply_message_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL,
            problems TEXT NOT NULL DEFAULT '[]',
            draft TEXT NOT NULL DEFAULT '',
            seconds REAL NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS study_advice (
            username TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_learning_events_username ON learning_events(username)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_learning_events_conversation ON learning_events(conversation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reply_reviews_username ON reply_reviews(username)")
    return conn


def _event_row_to_dict(row) -> dict:
    keys = ("id", "username", "conversation_id", "message_id", "created_at") + EVENT_FIELDS
    event = dict(zip(keys, row))
    event["solved"] = bool(event["solved"])
    return event


_EVENT_COLUMNS = "id, username, conversation_id, message_id, created_at, " + ", ".join(EVENT_FIELDS)


def add_event(username: str, conversation_id: str, message_id: int, tag: dict) -> bool:
    """
    存一筆學習標記。標記是在背景做的，做完時這一輪可能已經被學生按「停止」撤銷了——
    學生那則訊息已經不在，就不存（回傳 False），免得留下對應不到任何對話的紀錄。
    """
    values = [tag.get(field, "") for field in EVENT_FIELDS]
    values[EVENT_FIELDS.index("solved")] = 1 if tag.get("solved") else 0
    with _get_connection() as conn:
        cursor = conn.execute(
            f"""
            INSERT INTO learning_events (username, conversation_id, message_id, {", ".join(EVENT_FIELDS)})
            SELECT ?, ?, ?, {", ".join("?" for _ in EVENT_FIELDS)}
            WHERE EXISTS (SELECT 1 FROM messages WHERE id = ? AND conversation_id = ?)
            """,
            (username, conversation_id, message_id, *values, message_id, conversation_id),
        )
    return cursor.rowcount == 1


def last_event(conversation_id: str) -> Optional[dict]:
    """這條對話串最近一筆學習標記（判斷「還是不是在解同一題」用）。"""
    with _get_connection() as conn:
        row = conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM learning_events WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
    return _event_row_to_dict(row) if row else None


def events_for_user(username: str) -> List[dict]:
    with _get_connection() as conn:
        rows = conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM learning_events WHERE username = ? ORDER BY id ASC", (username,)
        ).fetchall()
    return [_event_row_to_dict(r) for r in rows]


def all_events() -> List[dict]:
    with _get_connection() as conn:
        rows = conn.execute(f"SELECT {_EVENT_COLUMNS} FROM learning_events ORDER BY id ASC").fetchall()
    return [_event_row_to_dict(r) for r in rows]


def add_review(username: str, conversation_id: str, user_message_id: Optional[int],
               reply_message_id: Optional[int], status: str, problems: list, draft: str = "",
               seconds: float = 0.0) -> None:
    """存一筆自我檢查紀錄。problems 是 [{"kind", "detail"}, ...]；改寫過（或該改沒改成）才留原稿。"""
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO reply_reviews
                (username, conversation_id, user_message_id, reply_message_id, status, problems, draft, seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (username, conversation_id, user_message_id, reply_message_id, status,
             json.dumps(problems, ensure_ascii=False), draft, round(seconds, 2)),
        )


def review_stats() -> dict:
    """全部自我檢查的統計：各種結果各幾次、各類問題各幾次、平均多花幾秒。"""
    with _get_connection() as conn:
        rows = conn.execute("SELECT status, problems, seconds FROM reply_reviews").fetchall()
    counts = {REVIEW_OK: 0, REVIEW_REVISED: 0, REVIEW_FLAGGED: 0, REVIEW_SKIPPED: 0}
    kinds = {}
    for status, problems, _ in rows:
        counts[status] = counts.get(status, 0) + 1
        for problem in json.loads(problems or "[]"):
            kind = problem.get("kind") or "其他"
            kinds[kind] = kinds.get(kind, 0) + 1
    seconds = [r[2] for r in rows if r[0] != REVIEW_SKIPPED]
    return {
        "total": len(rows),
        **counts,
        "by_kind": [{"kind": k, "count": n} for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])],
        "avg_seconds": round(sum(seconds) / len(seconds), 1) if seconds else None,
    }


def recent_reviews(limit: int = 30) -> List[dict]:
    """最近發現問題的自我檢查（改寫過、或該改沒改成），附上學生的問題、原稿、學生實際看到的回覆。"""
    with _get_connection() as conn:
        rows = conn.execute(
            """
            SELECT r.id, r.username, r.created_at, r.status, r.problems, r.draft, r.seconds,
                   q.text, a.text
            FROM reply_reviews r
            LEFT JOIN messages q ON q.id = r.user_message_id
            LEFT JOIN messages a ON a.id = r.reply_message_id
            WHERE r.status IN (?, ?)
            ORDER BY r.id DESC LIMIT ?
            """,
            (REVIEW_REVISED, REVIEW_FLAGGED, limit),
        ).fetchall()
    return [
        {"id": r[0], "username": r[1], "created_at": r[2], "status": r[3],
         "problems": json.loads(r[4] or "[]"), "draft": r[5], "seconds": r[6],
         "question": r[7] or "", "final": r[8] or ""}
        for r in rows
    ]


def save_advice(username: str, text: str) -> dict:
    with _get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO study_advice (username, text, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (username, text),
        )
    return get_advice(username)


def get_advice(username: str) -> Optional[dict]:
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT text, created_at FROM study_advice WHERE username = ?", (username,)
        ).fetchone()
    return {"text": row[0], "created_at": row[1]} if row else None


def delete_for_messages(message_ids: List[int]) -> None:
    """學生按「停止」撤銷一輪問答時：刪掉這幾則訊息對應的學習標記和自我檢查紀錄。"""
    ids = [(message_id,) for message_id in message_ids]
    with _get_connection() as conn:
        conn.executemany("DELETE FROM learning_events WHERE message_id = ?", ids)
        conn.executemany("DELETE FROM reply_reviews WHERE user_message_id = ? OR reply_message_id = ?",
                         [(i, i) for (i,) in ids])


def delete_for_conversation(conversation_id: str) -> None:
    with _get_connection() as conn:
        conn.execute("DELETE FROM learning_events WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM reply_reviews WHERE conversation_id = ?", (conversation_id,))


def delete_for_user(username: str) -> None:
    with _get_connection() as conn:
        conn.execute("DELETE FROM learning_events WHERE username = ?", (username,))
        conn.execute("DELETE FROM reply_reviews WHERE username = ?", (username,))
        conn.execute("DELETE FROM study_advice WHERE username = ?", (username,))
