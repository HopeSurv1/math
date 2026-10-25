import sqlite3
import uuid
from typing import List, Optional
from google.genai import types
from src.config import config

DB_PATH = config.DATA_DIR / "conversations.db"

_DEFAULT_TITLE = "新的對話"
_TITLE_MAX_LEN = 24


def _get_connection() -> sqlite3.Connection:
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
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    if "conversation_id" not in existing_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN conversation_id TEXT")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_username ON conversations(username)")

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
    conversation_id = uuid.uuid4().hex
    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO conversations (id, username, title) VALUES (?, ?, ?)",
            (conversation_id, username, _DEFAULT_TITLE),
        )
    return conversation_id


def list_conversations(username: str) -> List[dict]:
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
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT username FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    return row[0] if row else None


def delete_conversation(conversation_id: str) -> None:
    with _get_connection() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))


def delete_all_conversations(username: str) -> None:
    with _get_connection() as conn:
        conn.execute(
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE username = ?)",
            (username,),
        )
        conn.execute("DELETE FROM conversations WHERE username = ?", (username,))


def stats_by_user() -> dict:
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
    title = title.strip().replace("\n", " ")[:_TITLE_MAX_LEN] or _DEFAULT_TITLE
    with _get_connection() as conn:
        conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)
        )


def append_message(conversation_id: str, role: str, text: str) -> Optional[int]:
    if not text:
        return None
    with _get_connection() as conn:
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
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT role, text FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
    return [types.Content(role=role, parts=[types.Part(text=text)]) for role, text in rows]


def load_messages_for_display(conversation_id: str) -> List[dict]:
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT role, text FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
    return [{"role": role, "text": text} for role, text in rows]
