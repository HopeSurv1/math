# -*- coding: utf-8 -*-
"""
tests/test_retrieval.py
功能簡介：向量檢索功能獨立測試腳本。
          此腳本不啟動 FastAPI 或 Agent 大腦，僅手動測試指定問句在向量資料庫中的檢索狀況與相似度分數（距離分數）。
主要函數與流程：
  - test_query(question): 輸入問題，調用 EmbeddingService 與 VectorDBService，在 ChromaDB 檢索最相近的前3筆教材段落並印出其距離分數與內容。
  - __main__: 預設測試查詢「質因數分解」。
相依模組：
  - src.services.embedding_service.EmbeddingService (向量生成)
  - src.services.vector_db_service.VectorDBService (ChromaDB 查詢)
  - src.utils.logger (日誌輸出)
"""

import os
import sys

# 將 project 根目錄加入 sys.path 以便 import src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.embedding_service import EmbeddingService
from src.services.vector_db_service import VectorDBService
from src.utils.logger import logger

def test_query(question: str):
    logger.info(f"開始測試問題：{question}")
    
    try:
        embed_svc = EmbeddingService()
        db_svc = VectorDBService()
        
        vec = embed_svc.embed_text(question)
        results = db_svc.query(query_embeddings=[vec], n_results=3)
        
        print(f"\n🔍 問題：{question}")
        print("=" * 60)
        
        documents = results.get('documents', [[]])[0]
        distances = results.get('distances', [[]])[0]
        
        if not documents:
            print("❌ 找不到任何結果。")
            return

        for i, doc in enumerate(documents):
            distance = distances[i] if i < len(distances) else "N/A"
            print(f"\n[#{i+1}] 距離分數: {distance:.4f}" if isinstance(distance, float) else f"\n[#{i+1}] 距離分數: {distance}")
            print(doc[:300])  # 只印前300字
            print("-" * 40)
            
    except Exception as e:
        logger.error(f"測試失敗: {e}")

if __name__ == "__main__":
    test_query("質因數分解")
