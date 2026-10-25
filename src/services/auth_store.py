import hashlib
import secrets
import sqlite3
from typing import List, Optional
from src.config import config

DB_PATH = config.DATA_DIR / "conversations.db"
_PBKDF2_ITERATIONS = 200_000
ADMIN_SESSION_HOURS = 8

_RESERVED_WORDS = {"admin"}


def _get_connection() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            salt BLOB NOT NULL,
            password_hash BLOB NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_sessions (
            token TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return conn


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)


def register_user(username: str, password: str) -> bool:
    username = (username or "").strip()
    if not username or not password:
        return False
    salt = secrets.token_bytes(16)
    password_hash = _hash_password(password, salt)
    try:
        with _get_connection() as conn:
            conn.execute(
                "INSERT INTO users (username, salt, password_hash) VALUES (?, ?, ?)",
                (username, salt, password_hash),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def verify_user(username: str, password: str) -> bool:
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT salt, password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
    if not row:
        return False
    salt, expected_hash = row
    return secrets.compare_digest(_hash_password(password, salt), expected_hash)


def create_session(username: str) -> str:
    token = secrets.token_hex(32)
    with _get_connection() as conn:
        conn.execute("INSERT INTO sessions (token, username) VALUES (?, ?)", (token, username))
    return token


def resolve_session(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    with _get_connection() as conn:
        row = conn.execute("SELECT username FROM sessions WHERE token = ?", (token,)).fetchone()
    return row[0] if row else None


def delete_session(token: Optional[str]) -> None:
    if not token:
        return
    with _get_connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def delete_user(username: str) -> None:
    with _get_connection() as conn:
        conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
        conn.execute("DELETE FROM users WHERE username = ?", (username,))


def user_exists(username: str) -> bool:
    with _get_connection() as conn:
        row = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    return row is not None


def is_reserved_username(username: str) -> bool:
    name = (username or "").strip().lower()
    return name in _RESERVED_WORDS or name == config.ADMIN_USERNAME.strip().lower()


def is_reserved_password(password: str) -> bool:
    return (password or "").strip().lower() in _RESERVED_WORDS


def verify_admin(username: str, password: str) -> bool:
    username_ok = secrets.compare_digest((username or "").encode("utf-8"), config.ADMIN_USERNAME.encode("utf-8"))
    password_ok = secrets.compare_digest((password or "").encode("utf-8"), config.ADMIN_PASSWORD.encode("utf-8"))
    return username_ok and password_ok


def create_admin_session() -> str:
    token = secrets.token_hex(32)
    with _get_connection() as conn:
        conn.execute(
            "DELETE FROM admin_sessions WHERE created_at < datetime('now', ?)",
            (f"-{ADMIN_SESSION_HOURS} hours",),
        )
        conn.execute("INSERT INTO admin_sessions (token) VALUES (?)", (token,))
    return token


def resolve_admin_session(token: Optional[str]) -> bool:
    if not token:
        return False
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM admin_sessions WHERE token = ? AND created_at >= datetime('now', ?)",
            (token, f"-{ADMIN_SESSION_HOURS} hours"),
        ).fetchone()
    return row is not None


def delete_admin_session(token: Optional[str]) -> None:
    if not token:
        return
    with _get_connection() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))


def list_users() -> List[dict]:
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT username, created_at FROM users ORDER BY created_at DESC, username"
        ).fetchall()
    return [{"username": r[0], "created_at": r[1]} for r in rows]


def set_password(username: str, new_password: str) -> bool:
    salt = secrets.token_bytes(16)
    password_hash = _hash_password(new_password, salt)
    with _get_connection() as conn:
        updated = conn.execute(
            "UPDATE users SET salt = ?, password_hash = ? WHERE username = ?",
            (salt, password_hash, username),
        ).rowcount
        if updated:
            conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
    return bool(updated)
