# -*- coding: utf-8 -*-
"""
scratch_test.py
功能簡介：終端機版簡易 Agent 對話功能測試指令稿。
          此腳本用於在終端機直接測試 config.CHAT_MODEL 指定的 Gemini 模型，並掛載教材檢索工具，模擬國中數學老師與學生的簡單問答。
主要功能：
  - 建立 Gemini 聊天客戶端與連線
  - 設定 "國中數學老師" 系統提示語，並載入 `search_math_materials` 作為 RAG 檢索工具
  - 發送測試訊息「什麼是質數？」以驗證 RAG 工具呼叫（Tool/Function Calling）流程是否暢通
相依模組：
  - src.config.config (環境變數設定)
  - src.rag_tools.search_math_materials (RAG 檢索工具)
"""

import os
import asyncio
from google import genai
from google.genai import types
from src.config import config
from src.rag_tools import search_math_materials

async def main():
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    chat = client.chats.create(
        model=config.CHAT_MODEL,
        config=types.GenerateContentConfig(
            system_instruction="You are a math tutor.",
            tools=[search_math_materials],
            temperature=0,
        )
    )
    
    print("Sending message...")
    response = chat.send_message("什麼是質數？")
    
    print("--- History ---")
    used_tool = False
    history = chat.get_history()
    for msg in history[-4:] if history else []:
        print(f"Role: {msg.role}")
        for part in msg.parts:
            if hasattr(part, 'function_call') and part.function_call:
                print(f"  Function Call: {part.function_call.name}")
                used_tool = True
            elif hasattr(part, 'function_response') and part.function_response:
                print(f"  Function Response: {part.function_response.name}")
            else:
                print(f"  Text: {part.text[:50]}...")
                
    print(f"Used tool? {used_tool}")

if __name__ == "__main__":
    asyncio.run(main())
