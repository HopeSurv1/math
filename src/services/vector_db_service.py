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
        try:
            self.client.delete_collection(name=config.COLLECTION_NAME)
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(name=config.COLLECTION_NAME)
        logger.info(f"已重置集合: {config.COLLECTION_NAME}")

    def upsert(self,
               embeddings: List[List[float]],
               documents: List[str],
               ids: List[str],
               metadatas: List[Dict[str, Any]] = None):
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
        try:
            results = self.collection.query(
                query_embeddings=query_embeddings,
                n_results=n_results
            )
            return results
        except Exception as e:
            logger.error(f"檢索資料庫時發生錯誤: {e}")
            raise e
