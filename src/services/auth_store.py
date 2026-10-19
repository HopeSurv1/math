# -*- coding: utf-8 -*-
"""
src/services/auth_store.py
功能簡介：帳號系統。負責註冊、登入驗證，以及登入後的 session token 管理。
          密碼不會以明文儲存，而是用加鹽雜湊（PBKDF2）處理過再存進資料庫。
主要函數：
  - register_user(username, password): 建立新帳號，帳號重複或帳密空白會回傳 False。
  - verify_user(username, password): 檢查帳號密碼是否正確。
  - create_session(username): 登入成功後發一組隨機 token，回傳給前端存成 cookie。
  - resolve_session(token): 用 token 查回是哪個帳號，token 無效或沒登入回傳 None。
  - delete_session(token): 登出時把 token 作廢。
  - delete_user(username): 刪除帳號，連同這個帳號在所有裝置上的登入 session。
  - user_exists(username): 這個帳號存不存在（管理員刪除帳號前先確認）。
  - is_reserved_username / is_reserved_password: 「admin」是保留字，一般帳號不能拿來當帳號或密碼。
管理員（管理後台 /admin 用，帳密來自 config，不在 users 表裡）：
  - verify_admin(username, password): 核對管理員帳密。
  - create_admin_session / resolve_admin_session / delete_admin_session: 管理員登入狀態，
    存在獨立的 admin_sessions 表，ADMIN_SESSION_HOURS 小時後自動失效。
  - list_users(): 列出所有帳號與註冊時間（不含密碼雜湊）。
  - set_password(username, new_password): 管理員幫使用者重設密碼，並登出他所有的裝置。
相依模組：
  - sqlite3、hashlib、secrets（皆為 Python 內建，不需要額外安裝）
  - src.config（資料庫檔案放哪裡；跟對話紀錄共用同一個 SQLite 檔案，只是不同資料表）
"""

import hashlib
import secrets
import sqlite3
from typing import List, Optional
from src.config import config

DB_PATH = config.DATA_DIR / "conversations.db"
_PBKDF2_ITERATIONS = 200_000
ADMIN_SESSION_HOURS = 8  # 管理員登入的有效時間，比一般使用者（180 天）短很多

# 一般帳號不能使用的保留字（不分大小寫、前後空白不算）
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
    """加鹽雜湊密碼（PBKDF2-HMAC-SHA256，20 萬次疊代），資料庫裡不會出現明文密碼。"""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)


def register_user(username: str, password: str) -> bool:
    """
    建立新帳號。
    帳號已經存在、或帳號/密碼是空字串，會回傳 False（不會覆蓋既有帳號）。
    """
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
        return False  # 帳號已經存在


def verify_user(username: str, password: str) -> bool:
    """檢查帳號密碼是否吻合。用 secrets.compare_digest 比對，避免時間差攻擊。"""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT salt, password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
    if not row:
        return False
    salt, expected_hash = row
    return secrets.compare_digest(_hash_password(password, salt), expected_hash)


def create_session(username: str) -> str:
    """登入成功後呼叫：發一組隨機 token 代表這次登入，回傳給後端存成 cookie 給瀏覽器。"""
    token = secrets.token_hex(32)
    with _get_connection() as conn:
        conn.execute("INSERT INTO sessions (token, username) VALUES (?, ?)", (token, username))
    return token


def resolve_session(token: Optional[str]) -> Optional[str]:
    """用瀏覽器帶來的 token 查出是哪個帳號在用；查不到（沒登入或 token 無效）回傳 None。"""
    if not token:
        return None
    with _get_connection() as conn:
        row = conn.execute("SELECT username FROM sessions WHERE token = ?", (token,)).fetchone()
    return row[0] if row else None


def delete_session(token: Optional[str]) -> None:
    """登出時把這組 token 作廢，之後這個 cookie 就不能再用了。"""
    if not token:
        return
    with _get_connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def delete_user(username: str) -> None:
    """
    刪除帳號，並作廢這個帳號在所有裝置上的登入 session。
    session 一定要一起刪：不然舊 cookie 還查得到這個帳號名稱，之後如果有人用同一個名字
    重新註冊，拿著舊 cookie 的瀏覽器就會直接變成登入那個新帳號。
    對話紀錄不在這裡刪（見 conversation_store.delete_all_conversations）。
    """
    with _get_connection() as conn:
        conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
        conn.execute("DELETE FROM users WHERE username = ?", (username,))


def user_exists(username: str) -> bool:
    """這個帳號存不存在。"""
    with _get_connection() as conn:
        row = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    return row is not None


def is_reserved_username(username: str) -> bool:
    """「admin」和管理員自己的帳號名稱不能被一般使用者註冊或登入（不分大小寫）。"""
    name = (username or "").strip().lower()
    return name in _RESERVED_WORDS or name == config.ADMIN_USERNAME.strip().lower()


def is_reserved_password(password: str) -> bool:
    """一般使用者不能用「admin」當密碼（不分大小寫）。
    刻意不把 config.ADMIN_PASSWORD 也列進來：不然有人可以一直換密碼註冊，
    從「這個密碼不能用」的提示反推出管理員密碼。"""
    return (password or "").strip().lower() in _RESERVED_WORDS


# ===== 管理員 =====

def verify_admin(username: str, password: str) -> bool:
    """核對管理員帳密（來自 config / .env）。用 compare_digest 比對，避免時間差攻擊。"""
    username_ok = secrets.compare_digest((username or "").encode("utf-8"), config.ADMIN_USERNAME.encode("utf-8"))
    password_ok = secrets.compare_digest((password or "").encode("utf-8"), config.ADMIN_PASSWORD.encode("utf-8"))
    return username_ok and password_ok


def create_admin_session() -> str:
    """管理員登入成功後發一組 token；順便清掉已經過期的舊 token。"""
    token = secrets.token_hex(32)
    with _get_connection() as conn:
        conn.execute(
            "DELETE FROM admin_sessions WHERE created_at < datetime('now', ?)",
            (f"-{ADMIN_SESSION_HOURS} hours",),
        )
        conn.execute("INSERT INTO admin_sessions (token) VALUES (?)", (token,))
    return token


def resolve_admin_session(token: Optional[str]) -> bool:
    """這組 token 是不是有效（而且還沒過期）的管理員登入。"""
    if not token:
        return False
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM admin_sessions WHERE token = ? AND created_at >= datetime('now', ?)",
            (token, f"-{ADMIN_SESSION_HOURS} hours"),
        ).fetchone()
    return row is not None


def delete_admin_session(token: Optional[str]) -> None:
    """管理員登出。"""
    if not token:
        return
    with _get_connection() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))


def list_users() -> List[dict]:
    """列出所有帳號與註冊時間（最新註冊的在前），給管理後台用。不會回傳密碼雜湊。
    created_at 是 SQLite 的 UTC 時間（YYYY-MM-DD HH:MM:SS），由前端轉成當地時間顯示。"""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT username, created_at FROM users ORDER BY created_at DESC, username"
        ).fetchall()
    return [{"username": r[0], "created_at": r[1]} for r in rows]


def set_password(username: str, new_password: str) -> bool:
    """
    管理員幫使用者重設密碼：換一組新的鹽與雜湊，並作廢這個帳號所有的登入 session，
    讓所有裝置都要用新密碼重新登入。帳號不存在時回傳 False。
    """
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
