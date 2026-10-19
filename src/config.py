# -*- coding: utf-8 -*-
"""
src/config.py
功能簡介：專案之設定管理模組。負責載入 .env 環境變數，並集中定義資料夾路徑與模型參數。
主要類別：
  - Config: 封裝所有全域設定值（如 API 金鑰、向量庫目錄、模型名稱等）
外部依賴：
  - dotenv (載入 .env 環境變數檔案)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 取得專案根目錄 (src 的上一層)
BASE_DIR = Path(__file__).resolve().parent.parent

# 載入環境變數
load_dotenv(dotenv_path=BASE_DIR / ".env")

class Config:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    
    # 目錄設定
    DATA_DIR = BASE_DIR / "data"
    RAW_DOCS_DIR = DATA_DIR / "raw_docs"
    # 向量資料庫存放位置：預設在專案內的 data/chroma_db。
    # 注意：ChromaDB 的 hnsw 索引不支援含有非 ASCII（如中文）字元的路徑，
    # 若專案被放在含中文的資料夾下，請在 .env 設定 CHROMA_DB_DIR 指向一個純英數路徑。
    CHROMA_DB_DIR = Path(os.getenv("CHROMA_DB_DIR") or (DATA_DIR / "chroma_db"))
    
    # 模型設定
    CHAT_MODEL = os.getenv("CHAT_MODEL", "gemini-3.6-flash")
    # 備援模型：主要模型遇到「503 忙線中／429 額度超過」這類暫時性錯誤、重試用盡後，
    # 會自動改用這個模型再試一次，避免整個對話直接失敗（見 main.py 的 _with_retry_and_fallback）。
    FALLBACK_CHAT_MODEL = os.getenv("FALLBACK_CHAT_MODEL", "gemini-3.5-flash-lite")
    # 用正式版，不要用 gemini-embedding-2-preview：preview 版的額度很低（2026/9 實測每分鐘只過得了約 5～6 次呼叫），
    # 匯入一批 32 段就 429；正式版同樣價格、同樣 3072 維，連送好幾批都不會 429。
    # 換模型後向量不能混用，一定要重新 ingest（查詢和課本要用同一個模型轉向量）。
    EMBEDDING_MODEL = "gemini-embedding-2"

    # 畫圖的自動檢查：每張圖畫好後，程式先查有沒有空白、被切掉、文字重疊、變形、漏標點名稱、缺字方框，再請 Gemini 看圖檢查
    # 有沒有畫錯（例如正方形畫進三角形裡）。有問題就附上問題重畫，最多重畫這麼多次。
    # 每張圖會多一次看圖的呼叫（重畫時再多一次）；設成 0 就完全不檢查，畫圖最快（見 main.py 的 generate_math_image）。
    DRAW_MAX_FIXES = int(os.getenv("DRAW_MAX_FIXES", "1"))

    # 反思機制：老師的回覆送出前，先請 Gemini 檢查有沒有直接給答案、算錯、跟課本不一致、答非所問，
    # 有問題就附上檢查意見請老師改寫，學生只會看到改好的版本（見 main.py 的 _reflect_on_reply）。
    # 每則回覆多一次呼叫（要改寫時兩次）；設成 0 就不檢查，回覆最快。
    REPLY_REVIEW = os.getenv("REPLY_REVIEW", "1") != "0"
    # 自我檢查先問哪個模型（忙線再換主要模型）。預設用備援模型：免費方案下主要模型一天只有 20 次，
    # 留給學生直接看到的「老師回答」和「改寫回覆」；檢查只回答有沒有問題，用便宜的模型比較省額度。
    REVIEW_MODEL = os.getenv("REVIEW_MODEL") or FALLBACK_CHAT_MODEL

    # 學習歷程：每一輪問答送出後，在背景請這個模型標記「單元、觀念、學生答對沒有」，給學習紀錄頁分析用
    # （見 learning_analysis.py）。不影響學生的等待時間，用便宜的模型就夠；預設跟備援模型一樣。
    LEARNING_MODEL = os.getenv("LEARNING_MODEL") or FALLBACK_CHAT_MODEL

    # 管理後台（/admin）的帳密。預設 admin / admin，公開部署前請務必在 .env 改掉。
    # 這組帳密不存在 users 表裡，跟一般使用者的登入完全分開（見 auth_store.verify_admin）。
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
    COLLECTION_NAME = "math_materials"

    # 切割設定 (Chunking)
    CHUNK_SIZE = 500        # 每個文字區塊的目標長度 (字元數)
    CHUNK_OVERLAP = 100     # 相鄰區塊間的重疊長度，避免概念被切斷
    CHUNK_MIN_CJK = 20      # 區塊內至少要有的中文字數，否則視為雜訊丟棄

    # Embedding 批次設定
    EMBED_BATCH_SIZE = 32   # 一次送多少段文字給 Embedding API

    # 檢索設定 (Retrieval)
    RETRIEVAL_N_RESULTS = 4        # 每次檢索取幾段
    # 後端「主動預查」時的門檻：最近距離超過此值就視為課本沒教，不強制把內容塞給模型。
    # 校準依據（gemini-embedding-2，距離越小越相近）：
    #   課本有教的概念 約 0.37～0.46（「平行四邊形的面積」偏高，約 0.57）；「sin/cos」等超綱但沾邊的詞 約 0.56；
    #   完全無關/課本沒有的內容（天氣、微積分、單純算術）約 0.63～0.80
    RETRIEVAL_MAX_DISTANCE = 0.58

config = Config()
