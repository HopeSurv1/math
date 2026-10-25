import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import config
from src.services import embedding_service
from src.services.embedding_service import EmbeddingService

RATE_LIMIT = Exception("429 RESOURCE_EXHAUSTED. You exceeded your current quota")


class FakeModels:

    def __init__(self, errors=(), vectors_per_call=None):
        self.errors = list(errors)
        self.vectors_per_call = vectors_per_call
        self.calls = []

    def embed_content(self, model, contents):
        self.calls.append(contents)
        if self.errors:
            raise self.errors.pop(0)
        n = self.vectors_per_call if self.vectors_per_call is not None else len(contents)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[float(i)]) for i in range(n)])


class TestEmbedTexts(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.object(config, "GEMINI_API_KEY", "fake-key-for-tests")
        patcher.start()
        self.addCleanup(patcher.stop)
        sleep_patcher = mock.patch.object(embedding_service.time, "sleep")
        self.sleep = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)
        self.svc = EmbeddingService()

    def use(self, fake_models):
        self.svc.client = SimpleNamespace(models=fake_models)
        return fake_models

    def test_each_text_is_sent_as_its_own_content(self):
        fake = self.use(FakeModels())
        vectors = self.svc.embed_texts(["畢氏定理", "質因數分解", "一元一次方程式"])

        self.assertEqual(len(vectors), 3)
        sent = fake.calls[0]
        self.assertEqual(len(sent), 3)
        self.assertEqual([c.parts[0].text for c in sent], ["畢氏定理", "質因數分解", "一元一次方程式"])

    def test_mismatched_vector_count_raises_without_retrying(self):
        fake = self.use(FakeModels(vectors_per_call=1))
        with self.assertRaisesRegex(RuntimeError, "送出 3 段文字，卻只拿回 1 組向量"):
            self.svc.embed_texts(["a", "b", "c"])
        self.assertEqual(len(fake.calls), 1)

    def test_rate_limit_waits_long_when_asked(self):
        fake = self.use(FakeModels(errors=[RATE_LIMIT, RATE_LIMIT]))
        vectors = self.svc.embed_texts(["a", "b"], retries=5, rate_limit_wait=60)

        self.assertEqual(len(vectors), 2)
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [60, 60])

    def test_chat_path_keeps_short_retries_on_rate_limit(self):
        self.use(FakeModels(errors=[RATE_LIMIT]))
        self.svc.embed_texts(["a"])
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [3])

    def test_gives_up_after_max_retries(self):
        fake = self.use(FakeModels(errors=[RATE_LIMIT] * 3))
        with self.assertRaises(Exception):
            self.svc.embed_texts(["a"], retries=3, rate_limit_wait=60)
        self.assertEqual(len(fake.calls), 3)


if __name__ == "__main__":
    unittest.main()
