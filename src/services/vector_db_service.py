# -*- coding: utf-8 -*-
"""
src/services/vector_db_service.py
功能簡介：本機向量資料庫服務（Vector Database Service）。封裝對 ChromaDB 的連接、寫入與相似度查詢。
主要類別與方法：
  - VectorDBService: 管理與 ChromaDB 持久化連接，以及集合 (Collection) 的初始化。
    - upsert(embeddings, documents, ids): 將向量與段落文本存入向量資料庫。
    - query(query_embeddings, n_results): 依據查詢向量檢索最相近的 n_results 筆記錄。
相依模組：
  - chromadb (本機輕量級向量資料庫客戶端)
  - src.config (取得資料庫目錄路徑與集合名稱)
  - src.utils.logger (操作與錯誤日誌記錄)
"""

import chromadb
from typing import List, Dict, Any
from src.config import config
from src.utils.logger import logger

class VectorDBService:
    def __init__(self):
        try:
            self.client = chromadb.PersistentClient(path=str(config.CHROMA_DB_DIR))
            self.collection = self.client.get_or_create_collection(name=config.COLLECTION_NAME)
            logger.info(f"成功連接至 ChromaDB 集合: {config.COLLECTION_NAME}")
        except Exception as e:
            logger.error(f"初始化 ChromaDB 失敗: {e}")
            raise e

    def reset_collection(self):
        """清空並重建集合。切割方式改變時使用，避免舊區塊殘留造成檢索污染。"""
        try:
            self.client.delete_collection(name=config.COLLECTION_NAME)
        except Exception:
            pass  # 集合原本就不存在時忽略
        self.collection = self.client.get_or_create_collection(name=config.COLLECTION_NAME)
        logger.info(f"已重置集合: {config.COLLECTION_NAME}")

    def upsert(self,
               embeddings: List[List[float]],
               documents: List[str],
               ids: List[str],
               metadatas: List[Dict[str, Any]] = None):
        """將資料（含來源 metadata）存入向量資料庫"""
        try:
            self.collection.upsert(
                embeddings=embeddings,
                documents=documents,
                ids=ids,
                metadatas=metadatas
            )
            logger.info(f"成功寫入 {len(ids)} 筆資料至資料庫。")
        except Exception as e:
            logger.error(f"寫入資料庫時發生錯誤: {e}")
            raise e

    def query(self, query_embeddings: List[List[float]], n_results: int = 2) -> Dict[str, Any]:
        """從資料庫檢索最相似的段落"""
        try:
            results = self.collection.query(
                query_embeddings=query_embeddings,
                n_results=n_results
            )
            return results
        except Exception as e:
            logger.error(f"檢索資料庫時發生錯誤: {e}")
            raise e
