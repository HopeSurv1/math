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
