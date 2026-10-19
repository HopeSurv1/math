# -*- coding: utf-8 -*-
"""
src/services/embedding_service.py
功能簡介：向量生成服務（Embedding Service）。封裝對 Google GenAI Embedding API 的呼叫，並提供自動重試機制。
主要類別與方法：
  - EmbeddingService: 處理向量模型的初始化與文本向量轉換。
    - embed_text(text, retries): 將單筆文字轉換為高維度實數向量，失敗時會進行重試。
    - embed_texts(texts, retries, rate_limit_wait): 批次將多筆文字一次送出轉換，大幅加快匯入速度。
      每段文字各自包成一個 Content，確保「送幾段就拿回幾組向量」。
  - is_rate_limit_error(e): 判斷是不是 429（API 額度用完）。
相依模組：
  - google.genai (Google 官方 GenAI SDK)
  - src.config (取得 API 金鑰與模型名稱)
  - src.utils.logger (錯誤與進度日誌輸出)
"""

import time
from typing import List
from google import genai
from google.genai import types
from src.config import config
from src.utils.logger import logger


def is_rate_limit_error(e: Exception) -> bool:
    """429／RESOURCE_EXHAUSTED：API 額度（每分鐘或每天）用完了。"""
    return "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)


class EmbeddingService:
    def __init__(self):
        if not config.GEMINI_API_KEY:
            logger.error("未設定 GEMINI_API_KEY，請檢查 .env 檔案。")
            raise ValueError("Missing GEMINI_API_KEY")

        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.model_name = config.EMBEDDING_MODEL

    def embed_text(self, text: str, retries: int = 3) -> List[float]:
        """呼叫 Gemini 的向量模型把單筆文字轉成高維度向量 (附帶自動重試機制)"""
        return self.embed_texts([text], retries=retries)[0]

    def embed_texts(self, texts: List[str], retries: int = 3, rate_limit_wait: int = 0) -> List[List[float]]:
        """
        批次把多筆文字轉成向量。一次 API 呼叫處理整個 batch，回傳順序與輸入一致。
        :param rate_limit_wait: 遇到 429（額度用完）時等幾秒再重試。聊天時維持 0，用一般的
            短重試（不能讓學生等一分鐘）；批次匯入時設成 60，等每分鐘的額度重置。
        """
        if not texts:
            return []

        # 每段文字一定要各自包成一個 Content。直接傳字串清單的話，SDK 碰到 gemini-embedding-2
        # 系列會把連續的字串合併成「一份有很多段的內容」，32 段課文只會拿回 1 組向量。
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
            # 不重試：這是呼叫方式的問題，重試也一樣，直接說清楚比讓資料庫丟出看不懂的錯誤好
            raise RuntimeError(f"送出 {len(texts)} 段文字，卻只拿回 {len(vectors)} 組向量")
        return vectors
