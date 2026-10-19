# -*- coding: utf-8 -*-
"""
tests/test_delete_endpoints.py
功能簡介：「刪除帳號」與「刪除對話串」API 的測試。用 FastAPI TestClient 直接呼叫後端，
          資料庫換成暫存檔，不會動到 data/conversations.db，也不需要 API 金鑰或網路。
執行方式：python -m unittest tests.test_delete_endpoints -v
"""

import os
import sys
import unittest

# 將 project 根目錄加入 sys.path 以便 import src 與 tests
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import auth_store, conversation_store
from tests.api_test_base import ApiTestCase, PASSWORD, USERNAME


class TestDeleteAccount(ApiTestCase):

    def delete_account(self, password):
        return self.client.post("/api/account/delete", json={"password": password})

    def test_requires_login(self):
        self.assertEqual(self.delete_account(PASSWORD).status_code, 401)

    def test_wrong_password_keeps_everything(self):
        self.register_and_login()
        conversation_id, image = self.add_conversation_with_image()

        res = self.delete_account("wrong-password")

        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.client.get("/api/me").json()["username"], USERNAME)
        self.assertEqual(conversation_store.get_conversation_owner(conversation_id), USERNAME)
        self.assertTrue(image.exists())

    def test_deletes_account_conversations_images_and_sessions(self):
        token = self.register_and_login()
        conversation_id, image = self.add_conversation_with_image()

        res = self.delete_account(PASSWORD)

        self.assertEqual(res.status_code, 200)
        self.assertIsNone(self.client.get("/api/me").json()["username"])  # 這個瀏覽器被登出
        self.assertIsNone(auth_store.resolve_session(token))                # 舊 cookie 失效
        self.assertFalse(auth_store.verify_user(USERNAME, PASSWORD))        # 不能再登入
        self.assertIsNone(conversation_store.get_conversation_owner(conversation_id))
        self.assertEqual(conversation_store.load_messages_for_display(conversation_id), [])
        self.assertFalse(image.exists())

    def test_same_username_can_register_again_with_nothing_left_over(self):
        old_token = self.register_and_login()
        self.add_conversation_with_image()
        self.assertEqual(self.delete_account(PASSWORD).status_code, 200)

        self.register_and_login(password="a-new-password")

        self.assertEqual(self.client.get("/api/conversations").json()["conversations"], [])
        self.assertIsNone(auth_store.resolve_session(old_token))  # 舊 cookie 不會變成登入新帳號


class TestDeleteConversation(ApiTestCase):

    def test_deletes_conversation_and_its_images(self):
        self.register_and_login()
        conversation_id, image = self.add_conversation_with_image()

        res = self.client.delete(f"/api/conversations/{conversation_id}")

        self.assertEqual(res.status_code, 200)
        self.assertIsNone(conversation_store.get_conversation_owner(conversation_id))
        self.assertFalse(image.exists())
        self.assertEqual(self.client.get("/api/me").json()["username"], USERNAME)  # 帳號不受影響


if __name__ == "__main__":
    unittest.main()
