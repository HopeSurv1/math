import os
import sys

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
            print(doc[:300])
            print("-" * 40)
            
    except Exception as e:
        logger.error(f"測試失敗: {e}")

if __name__ == "__main__":
    test_query("質因數分解")
