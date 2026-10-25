import time
from typing import List
from google import genai
from google.genai import types
from src.config import config
from src.utils.logger import logger


def is_rate_limit_error(e: Exception) -> bool:
    return "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)


class EmbeddingService:
    def __init__(self):
        if not config.GEMINI_API_KEY:
            logger.error("未設定 GEMINI_API_KEY，請檢查 .env 檔案。")
            raise ValueError("Missing GEMINI_API_KEY")

        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.model_name = config.EMBEDDING_MODEL

    def embed_text(self, text: str, retries: int = 3) -> List[float]:
        return self.embed_texts([text], retries=retries)[0]

    def embed_texts(self, texts: List[str], retries: int = 3, rate_limit_wait: int = 0) -> List[List[float]]:
        if not texts:
            return []

        contents = [types.Content(parts=[types.Part(text=t)]) for t in texts]

        for attempt in range(1, retries + 1):
            try:
                result = self.client.models.embed_content(model=self.model_name, contents=contents)
                break
            except Exception as e:
                if attempt == retries:
                    logger.error(f"向量轉換失敗，已達最大重試次數: {e}")
                    raise
                if rate_limit_wait and is_rate_limit_error(e):
                    wait = rate_limit_wait
                    logger.warning(f"Gemini API 額度暫時用完（429），{wait} 秒後重試 (嘗試 {attempt}/{retries})")
                else:
                    wait = 3 * attempt
                    logger.warning(f"向量轉換失敗，{wait} 秒後重試 (嘗試 {attempt}/{retries}): {e}")
                time.sleep(wait)

        vectors = [e.values for e in result.embeddings]
        if len(vectors) != len(texts):
            raise RuntimeError(f"送出 {len(texts)} 段文字，卻只拿回 {len(vectors)} 組向量")
        return vectors
