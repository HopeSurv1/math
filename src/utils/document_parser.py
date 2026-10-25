import os
import re
from typing import List, Dict, Tuple, Any
from src.config import config
from src.utils.logger import logger

try:
    import fitz
except ImportError:
    fitz = None


_NOISE_LINE_PATTERNS = [
    re.compile(r"^第?\s*[一二三四五六七八九十\d]*\s*章?\s*$"),
    re.compile(r"^(自評|自我評量|課|課本|習作|練習本|附件)\s*P?\d.*$"),
    re.compile(r"^\d{1,3}\s*$"),
]

_AXIS_LINE = re.compile(r"^[\dOo\-−－.\s xy]{1,3}$")

_CJK = re.compile(r"[一-鿿]")
_WEIRD_SPACE = re.compile(r"[　    ​\x07\x08\t]")


class DocumentParser:

    @staticmethod
    def extract_pages(file_path: str) -> List[Tuple[int, str]]:
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

        with open(file_path, "r", encoding="utf-8") as f:
            return [(1, f.read())]

    @staticmethod
    def clean_text(text: str) -> str:
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

    @staticmethod
    def chunk_text(text: str,
                   size: int = None,
                   overlap: int = None) -> List[str]:
        size = size or config.CHUNK_SIZE
        overlap = overlap or config.CHUNK_OVERLAP

        segments: List[str] = []
        for para in text.split("\n"):
            para = para.strip()
            if not para:
                continue
            if len(para) <= size:
                segments.append(para)
            else:
                parts = re.split(r"(?<=[。！？；])", para)
                buf = ""
                for part in parts:
                    if len(buf) + len(part) <= size:
                        buf += part
                    else:
                        if buf:
                            segments.append(buf.strip())
                        while len(part) > size:
                            segments.append(part[:size])
                            part = part[size:]
                        buf = part
                if buf.strip():
                    segments.append(buf.strip())

        chunks: List[str] = []
        current = ""
        for seg in segments:
            candidate = seg if not current else current + "\n" + seg
            if len(candidate) <= size:
                current = candidate
                continue
            if current:
                chunks.append(current)
            tail = current[-overlap:] if overlap and current else ""
            current = (tail + "\n" + seg).strip() if tail else seg
        if current:
            chunks.append(current)

        return chunks

    @classmethod
    def process_file(cls, file_path: str) -> List[Dict[str, Any]]:
        logger.info(f"開始處理文件: {file_path}")
        source = os.path.basename(file_path)
        results: List[Dict[str, Any]] = []

        for page_no, page_text in cls.extract_pages(file_path):
            cleaned = cls.clean_text(page_text)
            if not cleaned:
                continue
            for chunk in cls.chunk_text(cleaned):
                chunk = chunk.strip()
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
