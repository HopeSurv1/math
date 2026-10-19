# -*- coding: utf-8 -*-
"""
tests/api_test_base.py
功能簡介：API 測試共用的基底類別（檔名不是 test_ 開頭，所以不會被當成測試執行）。
          每個測試都換成一個全新的暫存 SQLite 資料庫，不會動到 data/conversations.db，
          也把管理員帳密固定成 admin / admin，不受本機 .env 的設定影響。
          老師回覆的自我檢查（反思機制）和背景的學習標記預設關掉，這兩個都會呼叫 Gemini；
          要測它們的測試自己打開、換成假的 Gemini（見 test_reflection.py、test_learning.py）。
"""

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

# 將 project 根目錄加入 sys.path 以便 import src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from src.api import main
from src.config import config
from src.services import auth_store, conversation_store

USERNAME = "小華"
PASSWORD = "pw-1234"
GENERATED_DIR = Path(main.__file__).resolve().parent.parent / "frontend" / "generated"


class ApiTestCase(unittest.TestCase):

    def setUp(self):
        # 兩個 store 共用同一個 SQLite 檔，測試時一起換成暫存資料庫
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = Path(self._tmpdir.name) / "test.db"
        self._orig_db_paths = (auth_store.DB_PATH, conversation_store.DB_PATH)
        auth_store.DB_PATH = db_path
        conversation_store.DB_PATH = db_path
        self._orig_admin = (config.ADMIN_USERNAME, config.ADMIN_PASSWORD)
        config.ADMIN_USERNAME, config.ADMIN_PASSWORD = "admin", "admin"
        for patcher in (mock.patch.object(config, "REPLY_REVIEW", False),
                        mock.patch.object(main, "_record_learning", lambda *args: None)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(main.app)
        self._created_images = []

    def tearDown(self):
        self.client.close()
        auth_store.DB_PATH, conversation_store.DB_PATH = self._orig_db_paths
        config.ADMIN_USERNAME, config.ADMIN_PASSWORD = self._orig_admin
        for image in self._created_images:
            image.unlink(missing_ok=True)
        self._tmpdir.cleanup()

    def register(self, username=USERNAME, password=PASSWORD):
        return self.client.post("/api/register", json={"username": username, "password": password})

    def login(self, username=USERNAME, password=PASSWORD):
        return self.client.post("/api/login", json={"username": username, "password": password})

    def register_and_login(self, username=USERNAME, password=PASSWORD):
        """註冊並登入，回傳這次登入拿到的 session token。"""
        self.assertEqual(self.register(username, password).status_code, 200)
        res = self.login(username, password)
        self.assertEqual(res.status_code, 200)
        return res.cookies.get(main.SESSION_COOKIE_NAME)

    def add_conversation_with_image(self, username=USERNAME):
        """建一條對話串，老師的回覆裡引用一張（假的）生成圖片，回傳 (對話 id, 圖片路徑)。"""
        conversation_id = conversation_store.create_conversation(username)
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        image = GENERATED_DIR / f"{uuid.uuid4().hex}.png"
        image.write_bytes(b"not really a png")
        self._created_images.append(image)
        conversation_store.append_message(conversation_id, "user", "幫我畫一個三角形")
        conversation_store.append_message(conversation_id, "model", f"![三角形](/generated/{image.name})\n畫好了！")
        return conversation_id, image
