import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import rag_tools


def fake_results(*hits):
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
        self.assertIn("[出處：國中數學教材]\n畢氏定理的證明", text)
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
