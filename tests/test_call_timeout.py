# -*- coding: utf-8 -*-
"""
tests/test_call_timeout.py
功能簡介：Gemini 呼叫的等待上限。以前老師回答、第一次寫繪圖程式碼都沒有上限，實測模型偶爾卡 4 分鐘以上，
          學生一直轉圈、其他學生也跟著卡住。現在每次最多等 main._CALL_TIMEOUT_S 秒，
          逾時就直接換下一個模型（不在卡住的模型上重試）。Gemini 一律換成假的，不需要金鑰或網路。
執行方式：python -m unittest tests.test_call_timeout -v
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import httpx

# 將 project 根目錄加入 sys.path 以便 import src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.genai import types

from src.api import main

STUCK = httpx.ReadTimeout("The read operation timed out")
BUSY = Exception("503 UNAVAILABLE. This model is currently experiencing high demand.")
PRIMARY, BACKUP = "primary-model", "backup-model"


def calls_with(outcomes):
    """假的呼叫：依序回傳（或拋出）準備好的結果，並記下每次問了哪個模型。"""
    outcomes, asked = list(outcomes), []

    def call(model):
        asked.append(model)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return call, asked


class TestRetryOnTimeout(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.object(main.time, "sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_stuck_model_is_not_retried_the_backup_answers(self):
        call, asked = calls_with([STUCK, "備援模型的回答"])
        result, model = main._with_retry_and_fallback([PRIMARY, BACKUP], call)
        self.assertEqual((result, model), ("備援模型的回答", BACKUP))
        self.assertEqual(asked, [PRIMARY, BACKUP])  # 卡住的模型只問一次，不再等第二次
        self.sleep.assert_not_called()

    def test_busy_model_is_still_retried_before_switching(self):
        call, asked = calls_with([BUSY, BUSY, BUSY, "備援模型的回答"])
        main._with_retry_and_fallback([PRIMARY, BACKUP], call)
        self.assertEqual(asked, [PRIMARY, PRIMARY, PRIMARY, BACKUP])  # 忙線照舊重試 3 次

    def test_every_model_stuck_raises_the_timeout(self):
        call, asked = calls_with([STUCK, STUCK])
        with self.assertRaises(httpx.TimeoutException):
            main._with_retry_and_fallback([PRIMARY, BACKUP], call)
        self.assertEqual(asked, [PRIMARY, BACKUP])

    def test_timeout_errors_are_recognised(self):
        for error in (STUCK, httpx.ConnectTimeout("connect"), TimeoutError(), Exception("Request timed out")):
            with self.subTest(error=error):
                self.assertTrue(main._is_timeout_error(error))
        self.assertFalse(main._is_timeout_error(BUSY))


class TestEveryCallHasATimeout(unittest.TestCase):

    def test_normal_calls_wait_at_most_the_limit(self):
        configs = []

        def generate_content(model, contents, config=None):
            configs.append(config)
            return SimpleNamespace(text="ok")

        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
        with mock.patch.object(main, "global_client", client):
            main._call_gemini("畫一個三角形")
            main._call_gemini("看圖", types.GenerateContentConfig(temperature=0))
            main._call_gemini("自己有設上限", types.GenerateContentConfig(http_options=types.HttpOptions(timeout=20_000)))

        self.assertEqual([c.http_options.timeout for c in configs],
                         [main._CALL_TIMEOUT_S * 1000, main._CALL_TIMEOUT_S * 1000, 20_000])
        self.assertEqual(configs[1].temperature, 0)  # 原本的設定保留
        self.assertGreaterEqual(main._CALL_TIMEOUT_S, main._GEMINI_MIN_TIMEOUT_S)  # Gemini 不接受少於 10 秒

    def test_teacher_chat_waits_at_most_the_limit(self):
        created = []
        client = SimpleNamespace(chats=SimpleNamespace(create=lambda **kwargs: created.append(kwargs) or "chat"))
        with mock.patch.object(main, "global_client", client), \
             mock.patch.object(main.conversation_store, "load_history", return_value=[]), \
             mock.patch.dict(main.chat_sessions, clear=True):
            main.get_or_create_chat("some-conversation", PRIMARY)
        self.assertEqual(created[0]["config"].http_options.timeout, main._CALL_TIMEOUT_S * 1000)


if __name__ == "__main__":
    unittest.main()
