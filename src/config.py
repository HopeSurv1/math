import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(dotenv_path=BASE_DIR / ".env")

class Config:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    
    DATA_DIR = BASE_DIR / "data"
    RAW_DOCS_DIR = DATA_DIR / "raw_docs"
    CHROMA_DB_DIR = Path(os.getenv("CHROMA_DB_DIR") or (DATA_DIR / "chroma_db"))
    
    CHAT_MODEL = os.getenv("CHAT_MODEL", "gemini-3.6-flash")
    FALLBACK_CHAT_MODEL = os.getenv("FALLBACK_CHAT_MODEL", "gemini-3.5-flash-lite")
    EMBEDDING_MODEL = "gemini-embedding-2"

    DRAW_MAX_FIXES = int(os.getenv("DRAW_MAX_FIXES", "1"))

    REPLY_REVIEW = os.getenv("REPLY_REVIEW", "1") != "0"
    REVIEW_MODEL = os.getenv("REVIEW_MODEL") or FALLBACK_CHAT_MODEL

    LEARNING_MODEL = os.getenv("LEARNING_MODEL") or FALLBACK_CHAT_MODEL

    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
    COLLECTION_NAME = "math_materials"

    CHUNK_SIZE = 500
    CHUNK_OVERLAP = 100
    CHUNK_MIN_CJK = 20

    EMBED_BATCH_SIZE = 32

    RETRIEVAL_N_RESULTS = 4
    RETRIEVAL_MAX_DISTANCE = 0.58

config = Config()
