# -*- coding: utf-8 -*-
"""
tests/test_admin.py
功能簡介：管理後台與「admin 保留字」的 API 測試。用 FastAPI TestClient 直接呼叫後端，
          資料庫換成暫存檔、管理員帳密固定為 admin / admin，不需要 API 金鑰或網路。
執行方式：python -m unittest tests.test_admin -v
"""

import os
import sys
import unittest

# 將 project 根目錄加入 sys.path 以便 import src 與 tests
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api import main
from src.services import auth_store, conversation_store
from tests.api_test_base import ApiTestCase, PASSWORD, USERNAME


class TestReservedAdminWord(ApiTestCase):

    def test_cannot_register_admin_as_username(self):
        for name in ("admin", "Admin", "  ADMIN  "):
            with self.subTest(name=name):
                self.assertEqual(self.register(username=name).status_code, 400)
        self.assertEqual(auth_store.list_users(), [])

    def test_cannot_register_admin_as_password(self):
        for password in ("admin", "ADMIN"):
            with self.subTest(password=password):
                self.assertEqual(self.register(password=password).status_code, 400)
        self.assertEqual(auth_store.list_users(), [])

    def test_admin_credentials_do_not_work_on_student_login(self):
        res = self.login("admin", "admin")
        self.assertEqual(res.status_code, 401)
        self.assertIsNone(res.cookies.get(main.SESSION_COOKIE_NAME))


class TestAdminLogin(ApiTestCase):

    def admin_login(self, username="admin", password="admin"):
        return self.client.post("/api/admin/login", json={"username": username, "password": password})

    def test_admin_page_is_served_separately(self):
        res = self.client.get("/admin")
        self.assertEqual(res.status_code, 200)
        self.assertIn("管理員登入", res.text)

    def test_wrong_password_is_rejected(self):
        self.assertEqual(self.admin_login(password="nope").status_code, 401)
        self.assertFalse(self.client.get("/api/admin/me").json()["admin"])

    def test_login_and_logout(self):
        res = self.admin_login()
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(res.cookies.get(main.ADMIN_COOKIE_NAME))
        self.assertIsNone(res.cookies.get(main.SESSION_COOKIE_NAME))  # 不會變成某個學生帳號
        self.assertTrue(self.client.get("/api/admin/me").json()["admin"])

        self.client.post("/api/admin/logout")
        self.assertFalse(self.client.get("/api/admin/me").json()["admin"])

    def test_admin_session_expires(self):
        token = self.admin_login().cookies.get(main.ADMIN_COOKIE_NAME)
        with auth_store._get_connection() as conn:  # 把登入時間往前調到有效期限之前
            conn.execute(
                "UPDATE admin_sessions SET created_at = datetime('now', ?)",
                (f"-{auth_store.ADMIN_SESSION_HOURS + 1} hours",),
            )
        self.assertFalse(auth_store.resolve_admin_session(token))
        self.assertEqual(self.client.get("/api/admin/users").status_code, 401)


class TestAdminUserList(ApiTestCase):

    def test_requires_admin_not_just_a_student_login(self):
        self.register_and_login()
        self.assertEqual(self.client.get("/api/admin/users").status_code, 401)

    def test_lists_accounts_with_details_but_no_password_data(self):
        self.register_and_login()
        self.add_conversation_with_image()
        self.register(username="小明", password="another-pw")
        self.client.post("/api/admin/login", json={"username": "admin", "password": "admin"})

        res = self.client.get("/api/admin/users")

        self.assertEqual(res.status_code, 200)
        users = {u["username"]: u for u in res.json()["users"]}
        self.assertEqual(set(users), {USERNAME, "小明"})
        self.assertEqual(users[USERNAME]["conversation_count"], 1)
        self.assertEqual(users[USERNAME]["message_count"], 2)
        self.assertIsNotNone(users[USERNAME]["last_active"])
        self.assertEqual(users["小明"]["conversation_count"], 0)
        self.assertIsNone(users["小明"]["last_active"])
        for user in users.values():
            self.assertRegex(user["created_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
            self.assertEqual(set(user), {"username", "created_at", "conversation_count", "message_count", "last_active"})


class TestAdminResetPassword(ApiTestCase):

    def setUp(self):
        super().setUp()
        self.student_token = self.register_and_login()
        self.client.post("/api/admin/login", json={"username": "admin", "password": "admin"})

    def reset(self, new_password, username=USERNAME):
        return self.client.post("/api/admin/reset-password", json={"username": username, "new_password": new_password})

    def test_new_password_works_old_one_does_not_and_devices_are_logged_out(self):
        self.assertEqual(self.reset("brand-new-pw").status_code, 200)

        self.assertTrue(auth_store.verify_user(USERNAME, "brand-new-pw"))
        self.assertFalse(auth_store.verify_user(USERNAME, PASSWORD))
        self.assertIsNone(auth_store.resolve_session(self.student_token))

    def test_rejects_reserved_or_empty_password_and_unknown_account(self):
        self.assertEqual(self.reset("admin").status_code, 400)
        self.assertEqual(self.reset("").status_code, 400)
        self.assertEqual(self.reset("whatever", username="不存在的人").status_code, 404)
        self.assertTrue(auth_store.verify_user(USERNAME, PASSWORD))  # 原密碼沒被動到

    def test_requires_admin(self):
        self.client.post("/api/admin/logout")
        self.assertEqual(self.reset("brand-new-pw").status_code, 401)
        self.assertTrue(auth_store.verify_user(USERNAME, PASSWORD))


class TestAdminDeleteUser(ApiTestCase):

    def setUp(self):
        super().setUp()
        self.student_token = self.register_and_login()
        self.conversation_id, self.image = self.add_conversation_with_image()
        # 另一個帳號：刪除別人時，它的東西不能被波及
        self.register(username="小明", password="another-pw")
        self.other_conversation_id, self.other_image = self.add_conversation_with_image(username="小明")
        self.client.post("/api/admin/login", json={"username": "admin", "password": "admin"})

    def delete_user(self, username=USERNAME):
        return self.client.post("/api/admin/delete-user", json={"username": username})

    def test_deletes_account_conversations_images_and_sessions(self):
        self.assertEqual(self.delete_user().status_code, 200)

        self.assertFalse(auth_store.user_exists(USERNAME))
        self.assertFalse(auth_store.verify_user(USERNAME, PASSWORD))   # 不能再登入
        self.assertIsNone(auth_store.resolve_session(self.student_token))  # 所有裝置都被登出
        self.assertIsNone(conversation_store.get_conversation_owner(self.conversation_id))
        self.assertEqual(conversation_store.load_messages_for_display(self.conversation_id), [])
        self.assertFalse(self.image.exists())
        usernames = {u["username"] for u in self.client.get("/api/admin/users").json()["users"]}
        self.assertEqual(usernames, {"小明"})

    def test_other_accounts_are_untouched(self):
        self.delete_user()
        self.assertTrue(auth_store.verify_user("小明", "another-pw"))
        self.assertEqual(conversation_store.get_conversation_owner(self.other_conversation_id), "小明")
        self.assertTrue(self.other_image.exists())

    def test_deleted_student_is_logged_out_right_away(self):
        # 同一個瀏覽器（TestClient）也帶著學生的 cookie：刪除後馬上變成未登入，聊天會被擋下
        self.delete_user()
        self.assertIsNone(self.client.get("/api/me").json()["username"])
        self.assertEqual(self.client.get("/api/conversations").status_code, 401)

    def test_same_username_registered_again_starts_empty(self):
        self.delete_user()
        self.register_and_login(password="a-new-password")
        self.assertEqual(self.client.get("/api/conversations").json()["conversations"], [])

    def test_unknown_account_is_404(self):
        res = self.delete_user("不存在的人")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(len(self.client.get("/api/admin/users").json()["users"]), 2)

    def test_requires_admin_not_just_a_student_login(self):
        self.client.post("/api/admin/logout")  # 瀏覽器裡只剩學生的登入
        self.assertEqual(self.delete_user("小明").status_code, 401)
        self.assertTrue(auth_store.user_exists("小明"))
        self.assertTrue(self.other_image.exists())


if __name__ == "__main__":
    unittest.main()
