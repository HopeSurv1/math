# -*- coding: utf-8 -*-
"""
tests/test_stop_reply.py
功能簡介：學生按「停止」後，後端撤銷這一輪問答（/api/chat/cancel）的測試：
          存進去的問與答、這一輪畫的圖、這一輪才開的對話串都要刪掉，老師（聊天快取）也不能記得；
          取消比這一輪先處理到時，這一輪直接不存。Gemini 換成假的，不需要金鑰或網路。
執行方式：python -m unittest tests.test_stop_reply -v
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

# 將 project 根目錄加入 sys.path 以便 import src 與 tests
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from src.api import main
from src.services import conversation_store
from tests.api_test_base import ApiTestCase, USERNAME
from tests.test_reply_images import FakeImagesMixin


class TestStopReply(FakeImagesMixin, ApiTestCase):

    def setUp(self):
        super().setUp()
        self.register_and_login()
        # 每個測試各自從空的紀錄開始，不受其他測試留下的 request_id 影響
        for registry in (main._finished_turns, main._cancelled_requests):
            patcher = mock.patch.dict(registry, clear=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def chat(self, message, reply="好問題！你先想想看？", conversation_id=None, request_id="turn-1", client=None):
        """用假的 Gemini 聊天物件送出一句話，回傳 API 回應。"""
        fake_chat = SimpleNamespace(get_history=lambda: [], send_message=lambda parts: SimpleNamespace(text=reply))
        with mock.patch.object(main, "get_or_create_chat", return_value=fake_chat), \
             mock.patch.object(main, "prefetch_context", return_value=None):
            return (client or self.client).post("/api/chat", json={
                "message": message, "conversation_id": conversation_id, "request_id": request_id,
            })

    def stop(self, request_id="turn-1", client=None):
        return (client or self.client).post("/api/chat/cancel", json={"request_id": request_id})

    def texts(self, conversation_id):
        return [m["text"] for m in conversation_store.load_messages_for_display(conversation_id)]

    def test_stopping_a_saved_turn_removes_it_and_the_teacher_forgets(self):
        conversation_id, _ = self.add_conversation_with_image()
        before = self.texts(conversation_id)
        self.assertEqual(self.chat("3 的平方是多少", conversation_id=conversation_id).status_code, 200)
        main.chat_sessions[conversation_id] = ("假的聊天物件，還記得剛剛那一輪", "model")

        self.assertEqual(self.stop().status_code, 200)

        self.assertEqual(self.texts(conversation_id), before)  # 只刪掉這一輪，之前的對話都還在
        self.assertEqual(conversation_store.get_conversation_owner(conversation_id), USERNAME)
        self.assertNotIn(conversation_id, main.chat_sessions)  # 下一句話會從資料庫重讀，老師不會記得

    def test_stopping_the_first_turn_of_a_new_chat_removes_the_whole_conversation(self):
        conversation_id = self.chat("什麼是質數").json()["conversation_id"]

        self.stop()

        self.assertIsNone(conversation_store.get_conversation_owner(conversation_id))
        self.assertEqual(self.client.get("/api/conversations").json()["conversations"], [])

    def test_stop_that_arrives_first_means_the_turn_is_never_saved(self):
        self.stop()  # 取消先到（這一輪還沒跑完）
        res = self.chat("什麼是質數")

        self.assertEqual(res.status_code, 409)
        self.assertEqual(self.client.get("/api/conversations").json()["conversations"], [])

    def test_images_drawn_in_the_stopped_turn_are_deleted_but_older_ones_kept(self):
        conversation_id, old_image = self.add_conversation_with_image()
        new_url = self.make_image()
        # 這一輪畫了新圖，又再次引用前一輪的舊圖
        self.chat("再畫一次", reply=f"![新圖]({new_url})\n![舊圖](/generated/{old_image.name})",
                  conversation_id=conversation_id)

        self.stop()

        self.assertFalse(os.path.exists(os.path.join(main.GENERATED_DIR, new_url.rsplit("/", 1)[1])))
        self.assertTrue(old_image.exists())

    def test_cannot_stop_someone_elses_turn(self):
        conversation_id = self.chat("什麼是質數").json()["conversation_id"]
        other = TestClient(main.app)
        self.addCleanup(other.close)
        other.post("/api/register", json={"username": "小明", "password": "another-pw"})
        other.post("/api/login", json={"username": "小明", "password": "another-pw"})

        self.assertEqual(self.stop(client=other).status_code, 404)
        self.assertEqual(self.texts(conversation_id), ["什麼是質數", "好問題！你先想想看？"])

    def test_requires_login(self):
        self.client.post("/api/logout")
        self.assertEqual(self.stop().status_code, 401)

    def test_turns_without_a_request_id_are_saved_as_before(self):
        conversation_id = self.chat("什麼是質數", request_id=None).json()["conversation_id"]
        self.assertEqual(self.texts(conversation_id), ["什麼是質數", "好問題！你先想想看？"])
        self.assertEqual(main._finished_turns, {})


if __name__ == "__main__":
    unittest.main()
