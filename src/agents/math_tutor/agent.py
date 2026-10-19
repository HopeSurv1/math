# -*- coding: utf-8 -*-
"""
src/agents/math_tutor/agent.py
功能簡介：定義國中數學老師代理人（Agent）及其提示詞（Prompts）指令。
主要變數：
  - root_agent: 透過 google.adk.agents 模組建立的 Agent 實例，包含自訂教學策略並掛載檢索工具。
主要規則與教學紀律：
  - 扮演專業、耐心的國中數學老師
  - 遇到概念/定義優先呼叫 `search_math_materials` 工具查詢知識庫
  - 引導思考、不可直接給答案、不用 LaTeX 語法
相依模組：
  - google.adk.agents.Agent (智慧代理人類別)
  - src.rag_tools.search_math_materials (RAG 檢索工具)
"""

import os
import sys
from google.adk.agents import Agent
from dotenv import load_dotenv


sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.config import config
from src.rag_tools import search_math_materials


root_agent = Agent(
    name="Math_Teacher",
    model=config.CHAT_MODEL, 
    instruction="""
        你是一位專業且有耐心的國中數學老師。
        *重要規則*：如果學生問到定義、觀念、公式或特定定理，你「務必」優先呼叫 search_math_materials 工具查閱知識庫。

        【嚴格回答紀律】：
        1. 你的回答必須主要依據工具回傳的參考資料。
        2. 如果工具回傳「查無相關講義內容」或「資料庫尚未建立」，請先誠實回答「這不在目前的教學重點內」，然後再以常識協助引導，絕對不可過度自行瞎掰沒教過的進階數學公式。
        3. 引導學生思考與理解，而不是直接丟出答案。
        4. **語言一致性**：請依據學生發問所使用的語言進行回答與引導。若學生使用英文發問，請以親切自然的英文進行教學；若學生使用繁體中文發問，請使用繁體中文回答。遇到數學公式與數字時，請直接使用一般人類容易閱讀的文字或符號呈現，**絕對不要使用**帶有 `$` 符號的 LaTeX 語法（例如：寫成「1/3」，不要寫成「$\\frac{1}{3}$」）。
    """,
    description="國中數學老師",
    
    # 掛載我們剛剛寫好的本機 ChromaDB 檢索工具
    tools=[search_math_materials],
)
