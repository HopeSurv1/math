import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.document_parser import DocumentParser


class TestCleanText(unittest.TestCase):

    def test_removes_page_number_and_chapter_lines(self):
        text = "第一章\n自評 P21\n  123\n這是一段真正的教材內容，介紹質因數分解的觀念與範例。"
        cleaned = DocumentParser.clean_text(text)
        self.assertEqual(cleaned, "這是一段真正的教材內容，介紹質因數分解的觀念與範例。")

    def test_collapses_extra_spaces(self):
        text = "另一行  多個   空白   測試。"
        cleaned = DocumentParser.clean_text(text)
        self.assertEqual(cleaned, "另一行 多個 空白 測試。")

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(DocumentParser.clean_text(""), "")


class TestChunkText(unittest.TestCase):

    def test_short_text_returns_single_chunk(self):
        chunks = DocumentParser.chunk_text("hello world", size=500, overlap=100)
        self.assertEqual(chunks, ["hello world"])

    def test_long_text_splits_with_overlap(self):
        text = "AAAAAAAAAA\nBBBBBBBBBB\nCCCCCCCCCC"
        chunks = DocumentParser.chunk_text(text, size=20, overlap=5)
        self.assertEqual(
            chunks,
            ["AAAAAAAAAA", "AAAAA\nBBBBBBBBBB", "BBBBB\nCCCCCCCCCC"],
        )

    def test_no_chunk_exceeds_size_plus_overlap(self):
        text = "\n".join(f"segment-{i:03d}" for i in range(30))
        size, overlap = 30, 8
        chunks = DocumentParser.chunk_text(text, size=size, overlap=overlap)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), size + overlap + 1)


if __name__ == "__main__":
    unittest.main()
