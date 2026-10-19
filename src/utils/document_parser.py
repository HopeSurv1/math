# -*- coding: utf-8 -*-
"""
src/utils/document_parser.py
功能簡介：教材文件解析器。負責提取 PDF（或純文字檔）的內容、清理版面雜訊，
          並以「重疊視窗」方式切割成適合檢索的文字區塊（Chunking），同時保留來源頁碼。
主要類別與方法：
  - DocumentParser:
    - extract_pages(file_path): 逐頁讀取檔案。PDF 以 PyMuPDF 萃取每頁文字，回傳 [(頁碼, 文字), ...]。
    - clean_text(text): 移除圖形座標、頁首頁尾、交叉引用標記等雜訊，並正規化空白。
    - chunk_text(text, size, overlap): 以目標長度 size、重疊 overlap 將長文字切成區塊清單。
    - process_file(file_path): 完整流程，回傳 [{"text": 區塊文字, "metadata": {來源, 頁碼, 段落序}}, ...]。
相依模組：
  - fitz (PyMuPDF 套件，用於解析 PDF 檔案)
  - src.config (讀取切割參數)
  - src.utils.logger (操作與錯誤日誌記錄)
"""

import os
import re
from typing import List, Dict, Tuple, Any
from src.config import config
from src.utils.logger import logger

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# --- 清理用的樣式 ---------------------------------------------------------------

# 需要整行刪除的雜訊：純頁碼、章名頁尾、交叉引用（自評 P21 / 課 P8 例 1 ...）
_NOISE_LINE_PATTERNS = [
    re.compile(r"^第?\s*[一二三四五六七八九十\d]*\s*章?\s*$"),          # 「第 章」「1」等殘留
    re.compile(r"^(自評|自我評量|課|課本|習作|練習本|附件)\s*P?\d.*$"),   # 交叉引用標記
    re.compile(r"^\d{1,3}\s*$"),                                          # 單獨的頁碼
]

# 一行若「很短且不含中文」通常是圖形座標軸標籤 (0 1 2 -1 O x y ...)，刪掉
_AXIS_LINE = re.compile(r"^[\dOo\-−－.\s xy]{1,3}$")

_CJK = re.compile(r"[一-鿿]")
# 需要壓成一般空白的特殊空白 / 控制字元
_WEIRD_SPACE = re.compile(r"[　    ​\x07\x08\t]")


class DocumentParser:

    # ------------------------------------------------------------------ 讀取
    @staticmethod
    def extract_pages(file_path: str) -> List[Tuple[int, str]]:
        """逐頁讀取檔案，回傳 [(頁碼(1起算), 該頁純文字), ...]"""
        if not os.path.exists(file_path):
            logger.error(f"找不到檔案: {file_path}")
            raise FileNotFoundError(f"找不到檔案: {file_path}")

        if file_path.lower().endswith(".pdf"):
            if fitz is None:
                logger.error("找不到 PyMuPDF 套件，請先執行 pip install pymupdf")
                raise ImportError("Missing PyMuPDF")

            doc = fitz.open(file_path)
            logger.info(f"偵測到 {len(doc)} 頁，啟動 PDF 逐頁純文字萃取模式...")
            pages = [(i + 1, page.get_text()) for i, page in enumerate(doc)]
            doc.close()
            return pages

        # 純文字檔：整份當成第 1 頁
        with open(file_path, "r", encoding="utf-8") as f:
            return [(1, f.read())]

    # ------------------------------------------------------------------ 清理
    @staticmethod
    def clean_text(text: str) -> str:
        """移除版面雜訊並正規化空白，回傳以單一換行分隔的乾淨文字"""
        text = _WEIRD_SPACE.sub(" ", text)
        cleaned_lines: List[str] = []
        for raw in text.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if _AXIS_LINE.match(line):
                continue
            if any(p.match(line) for p in _NOISE_LINE_PATTERNS):
                continue
            line = re.sub(r" {2,}", " ", line)
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

    # ------------------------------------------------------------------ 切割
    @staticmethod
    def chunk_text(text: str,
                   size: int = None,
                   overlap: int = None) -> List[str]:
        """以目標長度 size、重疊 overlap 把長文字切成區塊。
        優先在換行、句號、逗號等自然邊界斷開，避免把一個句子攔腰切斷。"""
        size = size or config.CHUNK_SIZE
        overlap = overlap or config.CHUNK_OVERLAP

        # 先切成「段」：以換行為主，再把過長的段依標點細切
        segments: List[str] = []
        for para in text.split("\n"):
            para = para.strip()
            if not para:
                continue
            if len(para) <= size:
                segments.append(para)
            else:
                # 過長的段落，用中文標點再切
                parts = re.split(r"(?<=[。！？；])", para)
                buf = ""
                for part in parts:
                    if len(buf) + len(part) <= size:
                        buf += part
                    else:
                        if buf:
                            segments.append(buf.strip())
                        # 單一句子還是太長就硬切
                        while len(part) > size:
                            segments.append(part[:size])
                            part = part[size:]
                        buf = part
                if buf.strip():
                    segments.append(buf.strip())

        # 把「段」貪婪打包成 chunk，並在 chunk 之間保留 overlap
        chunks: List[str] = []
        current = ""
        for seg in segments:
            candidate = seg if not current else current + "\n" + seg
            if len(candidate) <= size:
                current = candidate
                continue
            if current:
                chunks.append(current)
            # 從上一個 chunk 的尾端取 overlap 字元當作新 chunk 的開頭
            tail = current[-overlap:] if overlap and current else ""
            current = (tail + "\n" + seg).strip() if tail else seg
        if current:
            chunks.append(current)

        return chunks

    # ------------------------------------------------------------------ 主流程
    @classmethod
    def process_file(cls, file_path: str) -> List[Dict[str, Any]]:
        """完整流程：逐頁讀取 → 清理 → 切割 → 附上來源 metadata。
        回傳 [{"text": ..., "metadata": {"source": 檔名, "page": 頁碼, "chunk_index": 序}}, ...]"""
        logger.info(f"開始處理文件: {file_path}")
        source = os.path.basename(file_path)
        results: List[Dict[str, Any]] = []

        for page_no, page_text in cls.extract_pages(file_path):
            cleaned = cls.clean_text(page_text)
            if not cleaned:
                continue
            for chunk in cls.chunk_text(cleaned):
                chunk = chunk.strip()
                # 丟掉中文字太少的雜訊區塊
                if len(_CJK.findall(chunk)) < config.CHUNK_MIN_CJK:
                    continue
                results.append({
                    "text": chunk,
                    "metadata": {
                        "source": source,
                        "page": page_no,
                        "chunk_index": len(results),
                    },
                })

        logger.info(f"{source}：清理切割後共產生 {len(results)} 個有效區塊。")
        return results
