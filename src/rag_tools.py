# -*- coding: utf-8 -*-
"""
src/rag_tools.py
功能簡介：定義供 Gemini 大腦（Agent）使用的 RAG（檢索增強生成）本機工具，
          以及後端可直接呼叫的「確定性預查」函數。
主要函數：
  - search_math_materials(query): 給 Gemini 主動呼叫的工具。輸入查詢字串，轉成向量並向
    本機 ChromaDB 檢索出相近教材段落後回傳。要不要呼叫、呼叫與否，由 LLM 自行判斷。
  - prefetch_context(query): 給後端（src/api/main.py）在送出訊息「前」直接呼叫，
    不經過 LLM 決定。距離小於 config.RETRIEVAL_MAX_DISTANCE 才回傳內容，否則回傳 None。
    用意：LLM 用文字指令判斷「要不要查」不保證每次都照做（例如判斷超綱就直接跳過檢索），
    這個函數用程式碼做「一定會查一次」的保底，確保檢索不是完全交給模型的自由心證。
  - _get_services() / _query_db() / _format_hits(): 內部共用邏輯。
相依模組：
  - src.services.embedding_service.EmbeddingService (生成查詢詞向量)
  - src.services.vector_db_service.VectorDBService (連線與檢索本機資料庫)
  - src.config (檢索筆數、距離門檻)
  - src.utils.logger (日誌輸出)
"""

from typing import Any, Dict, Optional
from src.config import config
from src.curriculum import SOURCE_BOOKS
from src.services.embedding_service import EmbeddingService
from src.services.vector_db_service import VectorDBService
from src.utils.logger import logger

# 延遲初始化（Lazy initialization），確保有呼叫時才建立連線
_embedding_service = None
_vector_db_service = None

def _get_services():
    global _embedding_service, _vector_db_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    if _vector_db_service is None:
        _vector_db_service = VectorDBService()
    return _embedding_service, _vector_db_service

def _query_db(query: str, n_results: int) -> Dict[str, Any]:
    """內部共用：把 query 轉成向量並查詢 ChromaDB，回傳原始結果 dict。"""
    embed_svc, db_svc = _get_services()
    query_vector = embed_svc.embed_text(query)
    return db_svc.query(query_embeddings=[query_vector], n_results=n_results)

def _format_hits(results: Dict[str, Any]) -> str:
    """
    內部共用：把查詢結果組成帶「[出處：國中數學 8上]」標籤的參考資料字串。
    只標冊別，不給檔名和頁碼：每個學生用的課本版本不一樣（不同出版社、不同學校的講義），
    老師看到頁碼就會說「根據我們的課本第 91 頁」，學生翻自己的課本根本對不上。
    """
    texts = results.get('documents', [[]])[0]
    metadatas = (results.get('metadatas') or [[]])[0]
    blocks = []
    for i, text in enumerate(texts):
        meta = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
        book = SOURCE_BOOKS.get(meta.get("source", ""))
        label = f"[出處：國中數學 {book}]" if book else "[出處：國中數學教材]"
        blocks.append(f"{label}\n{text}")
    return "\n---\n".join(blocks)

def search_math_materials(query: str) -> str:
    """
    當學生問到數學定理、觀念或公式時，呼叫此工具查閱目前向量庫內的正統講義。
    傳入參數 query (例如 "什麼是畢氏定理")
    回傳：最相近的教材原文段落
    """
    logger.info(f"收到檢索請求: {query}")
    try:
        results = _query_db(query, config.RETRIEVAL_N_RESULTS)
    except Exception as e:
        logger.error(f"服務初始化或檢索失敗: {e}")
        return "[系統訊息] 資料庫似乎尚未建立或載入失敗，請提醒老師先放入教材。"

    try:
        if not results.get('documents', [[]])[0]:
            logger.warning("資料庫內沒有任何相關講義內容。")
            return "知識庫內查無相關講義內容。"

        context = _format_hits(results)
        logger.info("成功檢索並回傳相關教材段落。")
        return ("以下是從國中數學課本查出最相近的參考資料（學生手上的課本版本不一定跟這份一樣：回答時不要說頁碼、"
                f"章節或例題編號，也不要說「我們的課本／講義」）：\n{context}")
    except Exception as e:
        logger.error(f"檢索發生意外錯誤: {str(e)}")
        return f"[系統訊息] 檢索發生意外錯誤: {str(e)}"

def prefetch_context(query: str) -> Optional[str]:
    """
    後端主動、確定性地檢查這句話是否有課本裡足夠相近的內容 —— 不依賴 LLM 自己決定要不要查。
    只要最相近的距離小於 config.RETRIEVAL_MAX_DISTANCE，就回傳格式化好的參考資料字串；
    沒有夠近的內容則回傳 None（代表交給模型自行判斷，不強制塞資料）。
    """
    try:
        results = _query_db(query, config.RETRIEVAL_N_RESULTS)
    except Exception as e:
        logger.error(f"主動預查失敗: {e}")
        return None

    distances = (results.get('distances') or [[]])[0]
    if not distances or distances[0] > config.RETRIEVAL_MAX_DISTANCE:
        if distances:
            logger.info(f"主動預查「{query}」：最近距離 {distances[0]:.3f} 超過門檻 {config.RETRIEVAL_MAX_DISTANCE}，判定課本無相關內容，不強制附上。")
        else:
            logger.info(f"主動預查「{query}」：向量庫無結果。")
        return None

    logger.info(f"主動預查「{query}」：命中教材（最近距離 {distances[0]:.3f}），自動附上參考資料。")
    return _format_hits(results)
