from typing import Any, Dict, Optional
from src.config import config
from src.curriculum import SOURCE_BOOKS
from src.services.embedding_service import EmbeddingService
from src.services.vector_db_service import VectorDBService
from src.utils.logger import logger

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
    embed_svc, db_svc = _get_services()
    query_vector = embed_svc.embed_text(query)
    return db_svc.query(query_embeddings=[query_vector], n_results=n_results)

def _format_hits(results: Dict[str, Any]) -> str:
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
