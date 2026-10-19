# -*- coding: utf-8 -*-
"""
tests/test_rag_tools.py
功能簡介：檢索結果交給老師（Gemini）之前的整理。用假的查詢結果，不會真的呼叫 Embedding 或 ChromaDB，
          也不需要金鑰。重點：參考資料只標冊別，不能出現檔名和頁碼——每個學生用的課本版本不一樣，
          老師看到頁碼就會說「根據我們的課本第 91 頁」，學生翻自己的課本根本對不上。
執行方式：python -m unittest tests.test_rag_tools -v
"""

import os
import sys
import unittest
from unittest import mock

# 將 project 根目錄加入 sys.path 以便 import src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import rag_tools


def fake_results(*hits):
    """模擬 ChromaDB 的查詢結果；每個 hit 是 (來源檔名, 頁碼, 距離, 內文)。"""
    return {
        "documents": [[text for _, _, _, text in hits]],
        "metadatas": [[{"source": source, "page": page, "chunk_index": 0} for source, page, _, _ in hits]],
        "distances": [[distance for _, _, distance, _ in hits]],
    }


HITS = fake_results(("8_1.pdf", 91, 0.40, "直角三角形兩股的平方和等於斜邊的平方。"),
                    ("7_1.pdf", 16, 0.45, "正數與負數"),
                    ("補充講義.pdf", 3, 0.50, "畢氏定理的證明"))


class TestReferencesForTheTutor(unittest.TestCase):

    def assert_no_page_or_file_name(self, text):
        self.assertNotRegex(text, r"第\s*\d+\s*頁")
        self.assertNotIn(".pdf", text)
        self.assertNotIn("補充講義", text)

    def test_each_passage_is_labelled_with_its_book_only(self):
        text = rag_tools._format_hits(HITS)
        self.assertIn("[出處：國中數學 8上]\n直角三角形兩股的平方和等於斜邊的平方。", text)
        self.assertIn("[出處：國中數學 7上]\n正數與負數", text)
        self.assertIn("[出處：國中數學教材]\n畢氏定理的證明", text)  # 不在 6 冊課本裡的檔案，連檔名也不給
        self.assert_no_page_or_file_name(text)

    def test_search_tool_tells_the_tutor_not_to_cite_pages(self):
        with mock.patch.object(rag_tools, "_query_db", return_value=HITS):
            text = rag_tools.search_math_materials("畢氏定理")
        self.assertIn("不要說頁碼", text)
        self.assert_no_page_or_file_name(text)

    def test_prefetched_references_have_no_pages_either(self):
        with mock.patch.object(rag_tools, "_query_db", return_value=HITS):
            text = rag_tools.prefetch_context("畢氏定理是什麼")
        self.assertIn("[出處：國中數學 8上]", text)
        self.assert_no_page_or_file_name(text)


if __name__ == "__main__":
    unittest.main()
