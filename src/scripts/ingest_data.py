# -*- coding: utf-8 -*-
"""
src/scripts/ingest_data.py
功能簡介：教材資料批次載入 (Ingestion) 腳本。
          掃描 raw_docs 目錄下所有 PDF，解析清理切塊後批次轉成向量，連同來源頁碼存入 ChromaDB。
主要函數：
  - ingest_all_pdfs(reset): 掃描 raw_docs，逐檔切塊 → 批次 Embedding → 寫入向量庫。
    碰到 API 額度用完（429）會等 60 秒再重試；一直失敗就整個停下來並說明原因。
相依模組：
  - src.config (讀取資料庫、檔案目錄與批次大小)
  - src.utils.document_parser.DocumentParser (PDF 清理與重疊切割)
  - src.services.embedding_service.EmbeddingService (批次呼叫 Embedding 模型)
  - src.services.vector_db_service.VectorDBService (ChromaDB 寫入操作)
  - src.utils.logger (日誌紀錄)
"""

from pathlib import Path
from src.config import config
from src.utils.logger import logger
from src.utils.document_parser import DocumentParser
from src.services.embedding_service import EmbeddingService, is_rate_limit_error
from src.services.vector_db_service import VectorDBService

# 免費方案的每分鐘額度不高，一口氣送幾批就會碰到 429。碰到時等 60 秒讓額度重置再重試；
# 連續等了好幾次還是 429，多半是「每天」的額度用完了，這時就整個停下來。
RATE_LIMIT_WAIT_SECONDS = 60
EMBED_RETRIES = 6


def _batched(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def ingest_all_pdfs(reset: bool = True):
    """尋找 raw_docs 資料夾下的所有 pdf 並進行入庫"""
    embed_svc = EmbeddingService()
    db_svc = VectorDBService()

    if reset:
        # 切割方式已更新，先清掉舊區塊再重建
        db_svc.reset_collection()

    raw_docs_path = Path(config.RAW_DOCS_DIR)
    if not raw_docs_path.exists():
        logger.error(f"找不到資料夾: {raw_docs_path}")
        return

    pdf_files = sorted(raw_docs_path.glob("*.pdf"))
    if not pdf_files:
        logger.warning(f"{raw_docs_path} 目錄下沒有找到 PDF 檔案。")
        return

    grand_total = 0
    stopped_by_quota = False
    for pdf_file in pdf_files:
        logger.info(f"開始處理檔案: {pdf_file.name}")
        written = 0
        try:
            chunks = DocumentParser.process_file(str(pdf_file))
            if not chunks:
                logger.warning(f"檔案 {pdf_file.name} 沒有萃取出任何有效區塊。")
                continue

            for batch in _batched(chunks, config.EMBED_BATCH_SIZE):
                texts = [c["text"] for c in batch]
                vectors = embed_svc.embed_texts(
                    texts, retries=EMBED_RETRIES, rate_limit_wait=RATE_LIMIT_WAIT_SECONDS
                )
                ids = [
                    f"{pdf_file.name}_p{c['metadata']['page']}_{c['metadata']['chunk_index']}"
                    for c in batch
                ]
                metadatas = [c["metadata"] for c in batch]

                db_svc.upsert(
                    embeddings=vectors,
                    documents=texts,
                    ids=ids,
                    metadatas=metadatas,
                )
                written += len(batch)
                logger.info(f"[{pdf_file.name}] 進度 {written}/{len(chunks)}")

            grand_total += written
            logger.info(f"✅ {pdf_file.name} 成功寫入 {written} 個區塊！")
        except Exception as e:
            if is_rate_limit_error(e):
                # 額度用完的話，後面的檔案也一定會失敗，繼續跑只是白白浪費時間
                grand_total += written
                stopped_by_quota = True
                logger.error(f"處理 {pdf_file.name} 時 Gemini API 額度用完，停止匯入: {e}")
                break
            logger.error(f"處理檔案 {pdf_file.name} 時發生錯誤: {e}")

    if stopped_by_quota:
        logger.error(
            f"匯入未完成（只寫入 {grand_total} 個區塊）：Gemini API 的額度用完了，"
            "可能是每天的額度。請晚一點（或明天）再重新執行一次。"
        )
    else:
        logger.info(f"全部完成，共寫入 {grand_total} 個區塊。")


if __name__ == "__main__":
    logger.info("啟動資料注入腳本...")
    ingest_all_pdfs()
    logger.info("所有資料注入完畢！")
