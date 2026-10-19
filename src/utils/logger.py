# -*- coding: utf-8 -*-
"""
src/utils/logger.py
功能簡介：系統日誌（Logger）設定。提供一個統一格式的全域日誌記錄器，輸出至標準輸出（Stdout）。
主要函數與變數：
  - setup_logger(name): 初始化並建立指定名稱的 Logger，設定日誌層級（INFO）與自訂輸出格式。
  - logger: 預先建立的全域 Logger 實例，供其他模組直接導入使用。
"""

import logging
import sys

def setup_logger(name: str = "math_rag") -> logging.Logger:
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # 建立控制台處理器
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        
        # 設定日誌格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger

# 提供一個全域的 logger 實例供其他模組使用
logger = setup_logger()
