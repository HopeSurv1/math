# -*- coding: utf-8 -*-
"""
================================================================================
                           專案架構說明檔案 (Architecture Guide)
================================================================================
本檔案完全由 Python 註解與文件字串（Docstrings）構成，用以說明整個專案的目錄結構、
模組功能、依賴關係與核心工作流程。內容對應 2026-09 的程式碼現況。

--------------------------------------------------------------------------------
0. 這個專案在做什麼 (What is this)
--------------------------------------------------------------------------------
一個「引導式國中數學 AI 家教」的網頁應用：

  - 學生註冊／登入後進入聊天室，可以開很多條互不干擾的「對話串」，
    左側清單可切換、改名、刪除；對話存在 SQLite，重新整理或伺服器重啟都不會消失。
  - 學生輸入數學問題（可附圖片、可用語音、可用數學符號鍵盤）。
  - 後端把問題交給 Gemini 模型，模型被設定成一位「蘇格拉底式」的國中數學老師：
    不直接給答案，而是一步一步反問、引導學生自己想出來。
  - 課本內容來自一個裝了 6 冊國中數學教科書（翰林版 7~9 年級）的向量資料庫（RAG），
    兩條路並行：
      (1) 後端「主動預查」：每句話送出前先檢索一次，距離夠近就自動附上課本內容；
      (2) 模型「自行呼叫」search_math_materials 工具查課本。
  - 需要圖形輔助時，Gemini 會把描述轉成 matplotlib 程式碼，後端在受限環境執行後
    產生精確的示意圖（不是用圖片生成模型「畫」出來的）。
  - Gemini 忙線（503）或額度超過（429）時，會自動重試並切換到備援模型。
  - 反思機制：老師的回覆送出前先自我檢查（直接給答案、數學錯誤、跟課本不一致、答非所問），
    有問題就改寫，學生只看到改好的版本（流程 H）。
  - 學習歷程：每一輪問答在背景標記單元、觀念、作答對錯，整理成學生自己的「我的學習紀錄」
    和管理後台的「學習分析」（流程 I）。

技術骨架：FastAPI（後端）＋ 原生 HTML/CSS/JS（前端）＋ ChromaDB（本機向量庫）
          ＋ SQLite（帳號與對話紀錄）＋ matplotlib（繪圖）
          ＋ Google GenAI / Gemini（對話、Embedding）。

--------------------------------------------------------------------------------
1. 目錄結構 (Directory Structure)
--------------------------------------------------------------------------------
project/
│
├── data/
│   ├── raw_docs/                # 原始教材 PDF（7_1 ~ 9_2；有版權，只放在私人 repo）
│   ├── chroma_db/               # ChromaDB 向量庫（ingest 產生；有進版控，clone 下來就能用）
│   └── conversations.db         # SQLite：帳號、登入 session、對話串與訊息、學習標記、自我檢查紀錄、
│                                #   學習建議（有進版控；repo 不可公開）
│
├── src/
│   │
│   ├── api/
│   │   └── main.py              # ★ 主要進入點：FastAPI 伺服器。
│   │                            #   - 帳號 API：/api/register、/api/login、/api/logout、/api/me
│   │                            #   - 對話串 API：/api/conversations（新增／列出／讀取／改名／刪除）
│   │                            #   - 對話 API：POST /api/chat
│   │                            #   - 老師人設（system_instruction）、get_or_create_chat()
│   │                            #   - generate_math_image()：matplotlib 繪圖工具 + 受限 exec
│   │                            #     + 自動檢查（程式查版面、Gemini 看圖），畫錯就重畫
│   │                            #   - _with_retry_and_fallback()：503/429 重試與備援模型
│   │                            #   - _reflect_on_reply()：反思機制（回覆送出前自我檢查、改寫）
│   │                            #   - _record_learning()：回應送出後在背景標記學習歷程
│   │                            #   - 學習紀錄 API：/api/learning/*、/api/admin/learning/*、/api/admin/reviews
│   │
│   ├── frontend/                # 靜態前端（由 main.py 直接 mount 提供）
│   │   ├── index.html           # 登入／註冊畫面 + 聊天介面（可收合側欄、置中對話欄、底部輸入框）
│   │   ├── style.css            # 樣式：顏色集中在 :root 變數，含深色模式與手機版版面
│   │   │                        #   （index.html 用 ?v= 版本號控制快取）
│   │   ├── admin.html / admin.js / admin.css
│   │   │                        # 管理後台（網址 /admin）：管理員登入、分頁（帳號管理／學習分析／老師自我檢查）、
│   │   │                        #   帳號列表、詳細資訊、重設密碼、刪除帳號
│   │   ├── admin_learning.js    # 管理後台的「學習分析」「老師自我檢查」分頁
│   │   ├── learning.html / learning.js
│   │   │                        # 學生的「我的學習紀錄」頁（網址 /learning）
│   │   ├── learning_report.js / learning.css
│   │   │                        # 學習紀錄報告的畫面與樣式（學生頁、管理後台共用）
│   │   ├── app.js               # 前端邏輯：登入／註冊、側欄與對話紀錄清單、歡迎畫面與範例問題、
│   │   │                        #   送出訊息（一次只能等一則回覆、可按停止）、思考中動畫、簡易 Markdown 呈現、
│   │   │                        #   圖片上傳(base64)、數學符號鍵盤、次方模式、Web Speech API 語音輸入（中／英切換）
│   │   ├── speech_math.js       # 語音講的數學 → 數學鍵盤上的符號（二的平方 → 2²、根號二 → √2）
│   │   └── generated/           # 繪圖工具產生的圖片（執行期建立；有進版控）
│   │
│   ├── agents/math_tutor/
│   │   ├── __init__.py
│   │   └── agent.py             # 另一種執行方式：google-adk 的 root_agent。
│   │                            #   僅供 `adk web` / `adk run` 使用，FastAPI 不會 import 它。
│   │                            #   （教學設定與 main.py 已有出入，見第 5 節）
│   │
│   ├── scripts/
│   │   └── ingest_data.py       # 教材匯入腳本（流程 A）
│   │
│   ├── services/
│   │   ├── auth_store.py        # 帳號系統：註冊、PBKDF2 密碼雜湊、登入 session token、刪除帳號
│   │   ├── conversation_store.py# 對話串與訊息的 SQLite 持久化；自動命名、舊資料遷移
│   │   ├── embedding_service.py # Google GenAI Embedding 串接；embed_text()/embed_texts()、429 重試
│   │   ├── vector_db_service.py # ChromaDB 連線；upsert()/query()/reset_collection()
│   │   ├── reflection.py        # 反思機制：reflect() 檢查回覆草稿、有問題就改寫（流程 H）
│   │   ├── learning_analysis.py # 學習歷程：tag_turn() 標記一輪、build_report()/build_overview() 算報告、
│   │   │                        #   write_advice() 寫學習建議（流程 I）
│   │   └── learning_store.py    # 學習標記、自我檢查紀錄、學習建議三張表（跟對話紀錄同一個 SQLite 檔）
│   │
│   ├── utils/
│   │   ├── document_parser.py   # PDF 逐頁抽取 → 清版面雜訊 → 重疊切割 → 附來源頁碼
│   │   ├── reply_cleanup.py     # 老師回覆的文字整理：LaTeX（$a$、\frac{1}{3}）→ 一般符號、日文「の」→「的」
│   │   └── logger.py            # 全域 logger（名稱 "math_rag"，輸出到 stdout）
│   │
│   ├── config.py               # 讀 .env，集中管理路徑、模型名稱、切割/批次/檢索參數
│   ├── curriculum.py           # 7 上～9 下 60 個單元（照課本目次整理），學習標記只能從這裡挑單元
│   └── rag_tools.py            # search_math_materials()（給 Gemini 呼叫）、
│                               #   prefetch_context()（後端主動預查，有距離門檻）
│
├── tests/
│   ├── test_document_parser.py  # clean_text / chunk_text 單元測試（unittest，不需金鑰）
│   ├── api_test_base.py         # API 測試共用基底：暫存資料庫、固定管理員帳密、註冊登入小工具
│   ├── test_delete_endpoints.py # 刪除帳號／刪除對話 API 測試（TestClient + 暫存資料庫，不需金鑰）
│   ├── test_admin.py            # 管理後台與 admin 保留字 API 測試（不需金鑰）
│   ├── test_stop_reply.py       # 按「停止」撤銷一輪問答（/api/chat/cancel）的 API 測試（假的 Gemini，不需金鑰）
│   ├── test_embedding_service.py# embed_texts 批次與重試單元測試（假的 API，不需金鑰）
│   ├── test_rag_tools.py        # 查課本的結果交給老師前的整理：只標冊別、不給檔名和頁碼（不需金鑰）
│   ├── test_reply_images.py     # 回覆圖片檢查、繪圖 exec、畫圖自動檢查與重畫（假的 Gemini，不需金鑰）
│   ├── test_reply_cleanup.py    # 回覆文字整理：LaTeX → 符號、「の」→「的」（不需金鑰）
│   ├── test_reflection.py       # 反思機制：檢查、改寫、失敗送原稿、圖片保護、存檔與撤銷（假的 Gemini）
│   ├── test_learning.py         # 學習歷程：單元、標記、報告計算、全班總覽、API、學習建議、刪除（假的 Gemini）
│   ├── test_call_timeout.py     # 等待上限：卡住就換模型、忙線照舊重試、每個呼叫都有 90 秒上限（假的 Gemini）
│   ├── test_speech_math.py      # 語音數學符號轉換（用本機 Chrome / Edge 無頭模式；找不到就略過）
│   └── test_retrieval.py        # 檢索測試腳本（需金鑰與向量庫，直接 python 執行）
│
├── scratch_test.py             # 終端機版工具呼叫煙霧測試（送「什麼是質數？」）
├── .claude/skills/project-guide/SKILL.md
│                               # 給 Claude Code 讀的專案導覽（與本檔內容重疊）
├── .env                        # GEMINI_API_KEY、管理後台帳密等機密（不進 git）
├── .env.example                # .env 範本
├── .gitignore
├── README.md
├── architecture_guide.py       # 本檔：架構說明（純註解）
├── update.py                   # 更新紀錄：每次更新的日期與修正／新增了什麼（python update.py 可印出）
└── requirements.txt

--------------------------------------------------------------------------------
2. 核心模組關係與依賴 (Module Relationships)
--------------------------------------------------------------------------------
    [前端 index.html / app.js]
           │  cookie: session_id（登入後由後端發放）
           │  fetch POST /api/chat  { message, image_data?, mime_type?, conversation_id? }
           ▼
    [FastAPI  src/api/main.py]
           ├── auth_store.resolve_session()      → 確認是哪個帳號（沒登入回 401）
           ├── conversation_store                → 權限檢查、讀寫歷史訊息
           ├── prefetch_context()（rag_tools）    → 主動預查課本，命中就附在訊息前面
           │
           │  _with_retry_and_fallback(MODEL_CANDIDATES, ...)
           │     └─ get_or_create_chat(conversation_id, model) → genai.chats，掛載 2 個工具
           ▼
    [Gemini Chat 模型]  ── 依 system_instruction 判斷要不要用工具
           ├── 需要課本內容 ────────────► search_math_materials()  (src/rag_tools.py)
           │                                     │
           │                                     ├──► EmbeddingService ──► Google GenAI Embedding
           │                                     └──► VectorDBService  ──► ChromaDB (data/chroma_db)
           │
           └── 需要圖形輔助 ────────────► generate_math_image()   (src/api/main.py)
                                                 ├──► Gemini 產生 matplotlib 程式碼
                                                 └──► 受限 exec 執行 ──► 存 PNG 到 frontend/generated/
           │
           ▼  文字整理 → 圖片檢查 → 畫圖安全網
    [反思機制 reflection.reflect()]  檢查草稿 → 有問題就改寫（有時限，做不成送原稿）
           ▼  存進 SQLite（messages、reply_reviews），回應給前端
    [背景 _record_learning()]  learning_analysis.tag_turn() ──► learning_store（learning_events）

    學習紀錄（跟聊天分開）：
    [learning.html / 管理後台] ──► /api/learning/report、/api/admin/learning/* ──► build_report()/build_overview()
                                   （learning_store 的標記 ＋ conversation_store 的訊息時間）

    離線流程（不經過前端）：
    [ingest_data.py] ──► DocumentParser ──► EmbeddingService(批次) ──► VectorDBService.upsert ──► ChromaDB

--------------------------------------------------------------------------------
3. API 一覽 (HTTP Endpoints)  —— 全部定義在 src/api/main.py
--------------------------------------------------------------------------------
  帳號（auth_store.py）
    POST   /api/register                        註冊（帳號重複或空白回 409；不會自動登入）
    POST   /api/login                           登入成功後發 session_id cookie（httponly，180 天）
    POST   /api/logout                          作廢 token 並清 cookie
    GET    /api/me                              回傳目前登入的帳號（未登入為 null）
    POST   /api/account/delete                  刪除帳號，body 為 { password }；密碼錯誤回 403。
                                                連同所有對話、訊息、圖片與登入 session 一起刪除
    ※ 註冊與一般登入都拒絕保留字「admin」（不分大小寫）：不能當帳號，也不能當密碼。

  管理後台（需要 admin_session_id cookie，否則回 401）
    GET    /admin                               管理後台頁面（admin.html）
    POST   /api/admin/login                     管理員登入，帳密比對 config.ADMIN_USERNAME / ADMIN_PASSWORD
    POST   /api/admin/logout                    管理員登出
    GET    /api/admin/me                        { admin: true/false }
    GET    /api/admin/users                     所有帳號：username、created_at、conversation_count、
                                                message_count、last_active（不含任何密碼資料）
    POST   /api/admin/reset-password            body { username, new_password }；重設後該帳號所有裝置登出
    POST   /api/admin/delete-user               body { username }；帳號不存在回 404。連同所有對話、訊息、
                                                學習紀錄、圖片與登入 session 一起刪除（跟 /api/account/delete 同一套）
    GET    /api/admin/learning/overview         全班總覽（build_overview）＋ reflection（自我檢查統計）
    GET    /api/admin/learning/report?username= 某個學生的學習紀錄（跟學生自己看到的同一份）；不存在回 404
    POST   /api/admin/learning/advice           body { username }；幫這個學生產生學習建議
    GET    /api/admin/reviews                   最近發現問題的自我檢查（附學生的問題、原稿、學生看到的回覆）

  學習紀錄（皆需登入，只看得到自己的）
    GET    /learning                            「我的學習紀錄」頁（learning.html）
    GET    /api/learning/report                 自己的學習紀錄（build_report ＋ 最近一次的學習建議）
    POST   /api/learning/advice                 按按鈕才產生學習建議；標記少於 3 筆回 400（不呼叫 AI），忙線回 503

  對話串（conversation_store.py；皆需登入，並檢查對話串擁有者，不是自己的回 404）
    POST   /api/conversations                   開新對話串
    GET    /api/conversations                   列出自己的對話串（最近更新的在前）
    GET    /api/conversations/{id}/messages     讀出某對話串的訊息（切換舊對話時補回畫面）
    PATCH  /api/conversations/{id}              改名
    DELETE /api/conversations/{id}              刪除（連同訊息、學習紀錄與該對話產生的圖片檔）

  對話
    POST   /api/chat                            送出問題；沒帶 conversation_id 會自動開一條新的。
                                                回傳 { reply, used_tool, conversation_id }。
                                                request_id（選填）是前端每次送出產生的亂數，按停止時用
    POST   /api/chat/cancel                     學生按「停止」：body { request_id }，撤銷這一輪問答
                                                （見流程 C 最後的「停止」）

  靜態檔
    GET    /                                    index.html；其餘路徑由 StaticFiles 提供 frontend/

--------------------------------------------------------------------------------
4. 核心流程解析 (Core Workflows)
--------------------------------------------------------------------------------

流程 A：教材向量化入庫 (Data Ingestion)
- 目的：把 PDF 教材轉成向量存進 ChromaDB，供問答時檢索。
- 啟動：`python -m src.scripts.ingest_data`（需先在 .env 設好 GEMINI_API_KEY）
- 步驟：
  1. ingest_data.py 先呼叫 VectorDBService.reset_collection() 清空整個集合
     （本流程是「全量重建」，不是增量更新）。
  2. 掃描 data/raw_docs/ 下所有 .pdf，逐檔呼叫 DocumentParser.process_file()：
     a. extract_pages()：PyMuPDF 逐頁抽取文字，保留頁碼。
     b. clean_text()：移除圖形座標軸數字、頁尾章名、純頁碼、交叉引用標記
        （如「自評 P21」「課 P8 例 1」），並正規化全形空白／控制字元。
     c. chunk_text()：以「重疊視窗」切割 —— 目標長度 config.CHUNK_SIZE（500 字），
        相鄰區塊重疊 config.CHUNK_OVERLAP（100 字），優先在換行、其次中文句號斷開。
     d. 丟棄中文字少於 config.CHUNK_MIN_CJK（20）的雜訊區塊。
     e. 每個區塊回傳 {"text", "metadata": {"source": 檔名, "page": 頁碼, "chunk_index": 序}}。
  3. 每 config.EMBED_BATCH_SIZE（32）段為一批，呼叫 EmbeddingService.embed_texts()
     一次送出（大幅減少 API 往返），得到 3072 維向量。
     - 每段文字必須各自包成一個 types.Content。直接傳字串清單的話，SDK 碰到
       gemini-embedding-2 系列會把連續字串合併成「一份多段內容」，32 段只拿回 1 組向量；
       embed_texts() 也會檢查回傳數量，對不上就直接報錯。
     - 免費方案每分鐘額度不高：碰到 429 會等 60 秒再重試（最多 6 次）；還是失敗就
       整個停下來、顯示「匯入未完成」，多半代表當天額度用完。
     - 要用正式版 gemini-embedding-2，不要用 gemini-embedding-2-preview：preview 版的額度很低，
       實測每分鐘只過得了約 5～6 次呼叫（429 訊息是 online_prediction_requests_per_base_model），
       一批 32 段就超過；正式版連送好幾批都沒問題。
     - 開頭就清空集合，所以中途失敗時向量庫是空的（或只有一部分），老師查不到課本，
       一定要重跑到「全部完成」。
       聊天時的檢索不走這個長等待，只做 3 秒、6 秒的短重試。
  4. VectorDBService.upsert() 把 向量＋原文＋metadata＋ID 寫入 ChromaDB。
     ID 格式：「{檔名}_p{頁碼}_{區塊序}」。
  5. 完成後資料落在 data/chroma_db/（chroma.sqlite3 ＋ hnsw 索引子目錄）。
  ※ 全量約 1500 個區塊；額度夠時約 75 秒，碰到每分鐘額度限制會多等幾分鐘。
    改切割邏輯或參數後一定要重新 ingest；匯入後要重啟伺服器（它還拿著被重建前的集合）。

流程 B：帳號與對話串 (Auth & Conversations)
- 註冊：auth_store.register_user() 以 PBKDF2-HMAC-SHA256（20 萬次、16 bytes 隨機鹽）
  雜湊密碼後存入 users 表，資料庫裡不會有明文密碼。
- 登入：verify_user() 用 secrets.compare_digest 比對；成功後 create_session() 發一組
  64 字元隨機 token 存進 sessions 表，並寫成瀏覽器 cookie。之後所有 API 都用
  resolve_session(token) 查出帳號。
- 對話串：每個帳號可有多條 conversations；messages 表以 conversation_id 關聯。
  使用者送出第一句話時，自動拿該句前 24 字當標題（類似 ChatGPT 自動命名）。
- 資料庫相容：conversation_store._get_connection() 會自動替舊版「一帳號一條對話」
  的訊息補建對話串（標題「先前的對話」），不會遺失舊資料。
- 刪除帳號（POST /api/account/delete）：
  1. 用 cookie 認出帳號，再用 verify_user() 核對一次密碼（錯誤回 403，前端才分得出
     「密碼打錯」與「登入已失效」的 401）。
  2. 找出所有對話串裡引用到的圖片檔名，並清掉記憶體裡的 chat_sessions 快取。
  3. 先 conversation_store.delete_all_conversations() 刪對話與訊息，
     再 auth_store.delete_user() 刪帳號與「所有」登入 session，最後刪圖片檔。
     順序是刻意的：中途出錯只會留下「沒有對話的帳號」，可以再刪一次；反過來則會留下
     沒有主人的對話，之後有人用同名註冊就會看到。session 全刪則是避免舊 cookie
     在同名帳號重新註冊後變成登入新帳號。
  4. 清掉瀏覽器 cookie，前端回到登入畫面並顯示「帳號已刪除」。
- 帳號與對話共用同一個 SQLite 檔：data/conversations.db。

流程 C：對話與教材檢索 (RAG Chat)
- 目的：學生發問時，老師結合課本內容、以引導方式教學。
- 啟動：`uvicorn src.api.main:app --reload` 後開瀏覽器；或 `python scratch_test.py` 做煙霧測試。
- 步驟：
  1. 前端 app.js 把問題（與選填的 base64 圖片、目前的 conversation_id）POST 到 /api/chat。
  2. main.py 用 cookie 認出帳號（沒登入回 401，前端會退回登入畫面），並確認
     conversation_id 屬於該帳號；沒帶 id 就自動開一條新的。
  3. 判斷是不是「畫圖請求」（訊息含 畫／繪製／draw／plot／graph／sketch／diagram／figure）。
     不是畫圖請求時，呼叫 prefetch_context() 主動預查：
     - 最近距離 < config.RETRIEVAL_MAX_DISTANCE（0.58）才把課本內容附在訊息前面，
       並註明「不一定符合學生意圖，對不上就忽略」；否則不附。
     - 畫圖請求跳過預查，因為畫圖句子常跟幾何題語意相近，硬塞課本內容反而會岔題。
  4. 訊息本體會包一段「這是學生這次實際問的內容」的提示，避免老師卡在上一輪的反問。
  5. 透過 _with_retry_and_fallback() 送出：
     - get_or_create_chat(conversation_id, model) 取出／建立 genai.chats 物件，設定
       system_instruction（老師人設 + 教學紀律）並掛載
       [search_math_materials, generate_math_image] 兩個工具。
     - 快取 chat_sessions 以 conversation_id 為 key、記錄 (chat, model)；記憶體被清空
       （如伺服器重啟）或換了模型時，會從 conversation_store.load_history() 讀回歷史重建。
     - 模型自行決定是否發起 Function Call。
  6. 若呼叫 search_math_materials()（src/rag_tools.py）：
     - EmbeddingService 把問句轉成向量。
     - VectorDBService.query() 在 ChromaDB 取回距離最近的 config.RETRIEVAL_N_RESULTS（4）個區塊。
     - 每段前面標上「[出處：國中數學 7上]」後組成參考資料字串回傳給模型。
       只標冊別，不給檔名和頁碼：每個學生用的課本版本不一樣，老師看到頁碼就會說
       「根據我們的課本第 91 頁」，學生對不上。老師的透明度規則也寫明不要說頁碼、章節或例題編號。
  7. 若呼叫 generate_math_image()：見流程 D。
  8. 文字整理 clean_reply_text()（src/utils/reply_cleanup.py）：系統提示要求不要用 LaTeX，
     但 Gemini 偶爾還是會寫 $a$、$a^2+b^2=c^2$、\frac{1}{3}，前端不會排版 LaTeX，學生就會看到一堆 $；
     這裡換成 a、a²+b²=c²、1/3。中文裡偶爾混進日文的「の」（股2の平方）也換回「的」。
     金額（一斤 $30）、「^^」這種表情、整段真的是日文的內容都不動。
     開啟舊對話時（GET /api/conversations/{id}/messages），老師的舊回覆也會整理一次。
     接著做圖片檢查 _fix_reply_images()：回覆裡每個圖片網址都要指到 generated/ 裡真的存在的檔案。
     Gemini 有時沒呼叫畫圖工具（或工具畫失敗），卻自己編一個網址（例如
     /generated/pythagorean_theorem.png），學生只會看到破圖。處理方式：
     - 這輪工具確實畫了圖（Gemini 抄錯網址）→ 換成工具畫的那張（從 function_response 找）。
     - 這輪沒畫出圖 → 照 Gemini 寫的圖片說明當場補畫；補畫失敗就拿掉那段語法。
     - 工具畫了、回覆卻完全沒放 → 補在回覆最前面。
  9. 畫圖安全網：學生要求畫圖、但檢查後回覆裡仍沒有圖片時，後端自動補畫一張放在回覆最前面
     （實測純文字「務必畫圖」指令只有約六成會被照做）。
  10. used_tool ＝ 主動預查有命中，或這輪歷史裡真的出現 search_math_materials 的 function_call
      （逐一檢查新增回合，不用「歷史長度成長」去猜，避免把純畫圖誤判成查講義）。
      前端據此顯示「📚 已查閱講義」標籤。
  11. 反思機制（config.REPLY_REVIEW，預設開）：回覆送出前自我檢查，有問題就改寫，見流程 H。
  12. 把這一輪的「使用者原句」與「老師回覆」純文字存進 SQLite（不存工具呼叫細節），
      自我檢查的結果存進 reply_reviews，回傳 { reply, used_tool, conversation_id }。
  13. 回應送出之後，在背景（FastAPI BackgroundTasks）標記這一輪的學習歷程，見流程 I。
  14. 任何例外都會被接住，回傳「[系統錯誤] 老師好像有點累了，請稍後再試。(錯誤訊息)」。
- 一次只等一則回覆、可以按停止（app.js 的 handleSend / stopReply）：
  - 老師還沒回完時不能再送：Enter、傳送鈕、歡迎畫面的範例問題都走 handleSend，一律在那裡擋
    （以前只把傳送鈕 disabled，Enter 繞過它，可以一直連續送出）。等待中打字不受影響。
  - 等待中傳送鈕變成「停止」鈕。按下去：中斷請求、問題從畫面收回並放回輸入框（連同附圖），
    再呼叫 POST /api/chat/cancel 請後端撤銷這一輪：刪掉存進去的問與答、這一輪的學習標記與
    自我檢查紀錄、這一輪畫的圖
    （前幾輪的舊圖還有訊息在用就保留）、這一輪才開的新對話串，並丟掉 chat_sessions 快取，
    下一句話從資料庫重讀歷史，老師不會記得收回的問題。
  - /api/chat 一次只處理一個請求，所以撤銷通常在這一輪跑完、存好之後才輪到（用 _finished_turns
    記下每輪存了什麼）；萬一撤銷先到，就記在 _cancelled_requests，這一輪跑完時直接不存。
    前端按停止後的下一則訊息會等撤銷做完才送，老師才不會看到被撤銷的那一輪。
  - 等待中換到別的對話或開新對話：回覆照樣存進原本的對話串，但不會畫在現在的畫面上
    （以前會畫進別的對話，還把 currentConversationId 換回去，下一句就送錯對話）。
    登出時不算停止，這一輪照樣存起來（跟直接關掉網頁一樣）。

流程 D：繪圖 (generate_math_image)
  1. _write_plot_code()：把描述連同 _MATPLOTLIB_CODE_INSTRUCTION 送給 Gemini，請它只回傳
     matplotlib 程式碼（不准 import、不准 plt.show()/savefig()、不准讀寫檔案）。
     指示裡特別寫了幾何圖的畫法，這些是實際畫錯過的地方：
     - 先用 np.array 算出每個頂點座標，所有線段、標示都由座標算出來，不要憑感覺猜位置。
     - 一定要 ax.set_aspect('equal')，不然正方形會變長方形、直角看起來不直。
     - 在邊的「外側」畫圖形（例如畢氏定理的三個正方形），方向要算：邊的向量轉 90 度，
       並確認指向遠離重心的一側。（曾經發生過斜邊上的正方形畫進三角形裡。）
     - 座標軸範圍要包住所有圖形和文字、文字不要互相重疊。
  2. 去掉可能殘留的 ``` 圍籬後，_render_matplotlib_code() 用 exec 執行：
     - globals 只給 plt / np / math，__builtins__ 只給白名單（abs、range、len、sorted…），
       沒有 __import__、open、eval、exec，降低任意程式碼執行風險（但不是完整沙盒）。
     - globals 和 locals 用同一個 dict；分開的話，程式碼裡的 def / lambda 看不到最外層的
       變數（例如 ax），一用就 NameError、整張圖畫不出來。
     - 存檔前 _layout_problems() 先用程式檢查（不用呼叫模型，Gemini 忙線也一定查得到）：
       圖是不是空白的、有沒有圖形超出座標軸範圍被切掉、文字標示有沒有互相重疊、
       幾何圖形有沒有因為沒設 set_aspect('equal') 被拉長變形（長條圖、直方圖、箭頭不算）、
       描述裡用「三角形ABC」「點P」「∠B」這類說法提到的點名稱，圖上有沒有標出來、
       有沒有字型顯示不出來而畫成方框的字（看畫圖當下 matplotlib 發出的缺字警告）。
     - 文字超出座標軸不算問題：存檔用 bbox_inches="tight"，圖片會自動放大把文字包進去。
     - 字型：中文用 Microsoft JhengHei（沒有就用 Noto Sans TC）；正黑體沒有的符號（≅ 全等、∼ 相似、
       ⇒、⇔、✓）由 matplotlib 內建的 DejaVu Sans 補上。備用字型要寫在 rcParams["font.family"]
       （每一項各是一套字型，缺字時依序往後找）；寫在 font.sans-serif 清單裡只會挑出第一套找得到的，
       沒有備用效果——以前就是這樣，「⇒ △ABC ≅ △DEF」的 ⇒、≅ 畫成了方框。
  3. 存成 src/frontend/generated/<uuid>.png（dpi 150），回傳 Markdown 圖片語法
     `![描述](/generated/xxx.png)`，前端 render 成 <img>。描述會去掉 [ ] 與換行並截到 40 字，
     前端才認得出這段語法，Gemini 抄進回覆時也比較不會抄錯。
  4. 自動檢查與重畫（最多 config.DRAW_MAX_FIXES 次，預設 1；設 0 就完全不檢查）：
     - 程式碼跑不動（例如 NameError）、或第 2 步的程式檢查發現問題 → 直接重畫。
     - 都沒問題 → _review_image() 把圖交給 Gemini 看圖檢查（回傳 JSON：ok、problems），
       看圖形、位置關係、標示對不對，只挑會讓學生看錯的問題。
     - 有問題就把「問題清單 + 上一版程式碼」附在指示後面（_MATPLOTLIB_FIX_INSTRUCTION）請它重寫。
       重畫的圖先存成暫存檔，比原本好（畫得出來、而且程式檢查沒問題）才換上去，檔名不變；
       重畫得更糟就沿用原本那張。重畫過的圖不會再看圖檢查一次（控制等待時間）。
     - 看圖檢查、以及「已經有圖時的重畫」都是加分項：_call_gemini(optional=True) 走
       _call_gemini_within_budget()，學生最多多等 30 秒（_OPTIONAL_CALL_BUDGET_S），這段時間內盡量問到答案：
       · 主要模型回 503／429 → 稍等 1、2、4 秒換下一個模型，主要、備援輪流問。
       · 問了 15 秒還沒回應（_OPTIONAL_HEDGE_AFTER_S）→ 同時問下一個模型當後備。
       · 主要模型的答案優先：後備先答就先收著，主要模型失敗或時間到才用。
       · 時間到都沒答案才放棄、沿用原本的圖。模型大塞車時（每次 503 可能要等一分多鐘），
         學生也不會為了檢查多等好幾分鐘。
       · Gemini 不接受少於 10 秒的等待上限（回 400），所以時限由迴圈把關，
         每次呼叫本身的等待上限設成「剩下的時間 + 5 秒」。
     - 代價：每張圖多一次看圖的呼叫，畫錯時再多一次重寫。
  5. 刪除對話串時，會一併刪掉該對話訊息裡引用到的圖片檔。

流程 E：Gemini 忙線時的重試與備援 (Retry & Fallback)
  - MODEL_CANDIDATES ＝ [config.CHAT_MODEL, config.FALLBACK_CHAT_MODEL]（去重）。
    兩個設成同一個模型（例如 .env 的 CHAT_MODEL 也設成 gemini-3.5-flash-lite）就等於沒有備援：
    那個模型一忙線，對話和畫圖都會直接失敗。
  - _with_retry_and_fallback() 依序嘗試每個模型：
    - 錯誤訊息含 503／UNAVAILABLE／429／RESOURCE_EXHAUSTED／overloaded 才算暫時性錯誤，
      同一模型最多試 3 次，間隔 1 秒、2 秒（指數退避），用盡才換下一個模型。
    - 等太久沒回應（逾時，_is_timeout_error）：不在卡住的模型上重試，直接換下一個模型。
  - 等待上限：老師回答（聊天物件的 config）和一般的 _call_gemini()（例如第一次寫繪圖程式碼）
    每次呼叫最多等 _CALL_TIMEOUT_S（90）秒。以前沒有上限，實測模型偶爾卡 4 分鐘以上，
    而 /api/chat 一次只處理一個請求，其他學生也會跟著卡住。平常回答約 5～30 秒，不受影響；
    查課本、畫圖這些工具在兩次呼叫之間執行，不算在這 90 秒裡。
    - 其他錯誤（例如 404 模型名稱錯誤、金鑰錯誤）不重試，直接拋出。
  - 對話（/api/chat）與繪圖工具都走這條路；繪圖的看圖檢查和重畫改走有總時限的
    _call_gemini_within_budget()（見流程 D 第 4 步）。

流程 F：前端介面 (Frontend)
  - 版面：左側欄（收合按鈕、發起新對話、近期對話清單、帳號與登出）＋ 右側置中的對話欄
    ＋ 底部輸入框（圖片上傳、數學符號鍵盤、語音語言切換、麥克風、傳送鈕）。
  - 側欄：桌機可收合成只剩圖示，狀態記在 localStorage（讀寫都包 try/catch，被封鎖也不影響）；
    手機（寬度 ≤ 768px）改成從左側滑出的抽屜，點背景或選了對話就自動關上。
  - 對話清單：滑鼠移上去才顯示改名／刪除圖示；目前所在的對話會標示出來。
  - 帳號設定：點側欄左下角的名字，用原生 <dialog> 開啟對話框；刪除帳號要輸入密碼，
    密碼錯誤時留在對話框顯示錯誤，成功後回到登入畫面。按 Esc 或點背景可關閉。
  - 歡迎畫面：沒有訊息時顯示「嗨，使用者名稱」與 4 個範例問題，點了直接送出。
  - 訊息呈現：老師的回覆以 π 標誌當頭像、不加泡泡；學生的訊息是靠右的泡泡。
    app.js 的 formatText() 先跳脫 HTML，再處理簡易 Markdown（段落、# 標題、- / 1. 清單、
    **粗體**、`行內程式碼`、圖片）；圖片只接受站內路徑（/generated/...）或 data:image，
    避免插入外部網址。
  - 等待回覆時顯示跳動圓點與「老師正在想怎麼引導你…」；有查講義時顯示「📚 已查閱講義」標籤。
  - 傳送鈕在輸入框有字或有附圖時才亮起。
  - 語音輸入的數學講法會自動換成數學鍵盤上的符號（speech_math.js 的 SpeechMath.convert()，
    中英文都支援）：「二的平方」→ 2²、「二的三次方」→ 2³、「x的平方加y的平方等於z的平方」
    → x²+y²=z²、「根號二」→ √2、「負三的平方」→ (-3)²、「三角形ABC」→ △ABC、「角A」→ ∠A、
    「2拍r」→ 2πr（π 唸「拍」，辨識成「派」也認得）、「左括號…右括號」→ ( )。
    - 提高辨識成功率：電腦上用連續聆聽（continuous），講到一半停下來想也不會被切斷，
      停頓 2.5 秒沒有新的字才自動結束；手機瀏覽器的連續模式常重複前面的字，維持單句模式。
      maxAlternatives = 5，每段拿好幾個候選，SpeechMath.pick() 挑最像算式的（「二的評分」vs「二的平方」）。
      每句辨識完會在瀏覽器主控台印出「[語音輸入] 辨識候選」，有講法沒轉成功時可以看到實際聽到什麼。
    - 送出訊息時如果還在聽，用 abort() 丟掉還沒回來的結果，免得送出後輸入框又被填回去。
    - 只有在列算式才轉：運算詞旁邊要有數字或變數（「的平方」前面要有東西、「加」「等於」
      兩邊都要有東西）。「什麼是平方」「平方根是什麼」「三角形的內角和」這種講觀念的句子不動。
    - 「五平方公尺」「十六的平方根」「一元二次方程式」「平方差公式」這些詞也刻意不轉；
      「十六的平方根」是 ±4，跟 √16 不一樣。
    - 中文數字只有在算式裡才寫成阿拉伯數字，「三角形」「一個」「一起」不會變成 3角形、1個。
    - 「除」只轉「除以」：「a除b」其實是 b÷a，容易弄反。分數（三分之二）不轉。
  - 顏色全部定義在 style.css 的 :root 變數，prefers-color-scheme 為 dark 時自動換成深色。

流程 G：管理後台 (Admin)
  - 網址 /admin，和學生的登入頁完全分開，頁面本身不在學生介面上放連結。
  - 管理員帳密來自 config（.env 的 ADMIN_USERNAME / ADMIN_PASSWORD，預設 admin / admin），
    不在 users 表裡。verify_admin() 用 compare_digest 比對；登入後發的 token 存在獨立的
    admin_sessions 表、放在獨立的 admin_session_id cookie（samesite=strict），
    auth_store.ADMIN_SESSION_HOURS（8）小時後失效。學生的 cookie 拿不到後台 API，
    管理員登入也不會變成任何學生帳號。
  - 保留字：is_reserved_username() 擋掉「admin」與 ADMIN_USERNAME；is_reserved_password()
    只擋「admin」，刻意不擋 ADMIN_PASSWORD，避免有人從註冊的錯誤訊息反推出管理員密碼。
  - 帳號列表：auth_store.list_users() ＋ conversation_store.stats_by_user()（只有數字，
    管理員看不到對話內容）。時間是 SQLite 的 UTC，由 admin.js 轉成瀏覽器時區顯示。
  - 密碼：資料庫只有 PBKDF2 雜湊，任何人都還原不回原文，所以詳細資訊只顯示「已加密儲存」。
    替代做法是「重設密碼」：set_password() 換新的鹽與雜湊，並刪除該帳號所有 session。
  - 刪除帳號：和使用者自己刪除帳號共用 main.py 的 _delete_account_and_data()，順序是
    先刪對話與訊息 → 再刪帳號與所有 session → 最後刪圖片檔，所以被刪的學生下一個請求就是 401、
    畫面退回登入頁；之後有人用同一個名字註冊，也看不到任何舊資料。
    管理員不知道學生的密碼，所以不像學生自己刪除那樣要輸入密碼；防點錯人的確認放在 admin.js：
    另開確認框，要照打一次帳號名稱，「永久刪除帳號」按鈕才會亮起來。
  - admin.js 一律用 textContent 放入帳號名稱，避免使用者取的名字被當成 HTML 執行。
  - 分頁：帳號管理（admin.js）、學習分析與老師自我檢查（admin_learning.js），見流程 H、I。
    帳號詳細資訊裡的「查看學習紀錄」直接換到學習分析分頁、打開那個學生。

流程 H：反思機制 (Reflection：回覆送出前自我檢查)
  - 位置：chat_endpoint 在文字整理、圖片檢查、畫圖安全網之後，存檔之前呼叫 _reflect_on_reply()，
    它再呼叫 src/services/reflection.py 的 reflect()（call_gemini 從 main.py 傳進去，測試換成假的）。
  1. 檢查：把 REVIEW_INSTRUCTION ＋「最近 6 則對話（每則前 600 字）、學生這次說的話、這一輪查到的
     課本內容（主動預查 ＋ search_math_materials 的回傳，前 4000 字）、回覆草稿」送給 Gemini，
     用 JSON（ReplyReview：ok、problems[kind, detail]）回答。四種問題：
     直接給答案／數學錯誤（包括把學生錯的答案說成對的）／跟課本不一致／答非所問。
     提示裡寫明哪些「不算」直接給答案（確認學生自己算出的答案、解釋觀念、學生卡很久時示範一步、
     舉不同的例子），避免把正常的引導也改掉。kind 對不上四種就記成「其他」。
  2. 有問題 → 改寫：同一位老師（_REWRITE_INSTRUCTION ＝ 身分 ＋ 教學紀律，沒有工具規則）拿到
     「背景資料、草稿、檢查意見」，只修正有問題的地方。改寫過的不再檢查第二次。
  3. 圖片：草稿裡的 ![說明](/generated/xxx.png) 先換成 [圖1]、[圖2] 才交給 Gemini，改寫完再換回來；
     改寫時漏掉的圖補在最前面，Gemini 自己寫的圖片語法直接拿掉（它本來就容易抄錯網址）。
  4. 時限：檢查最多 REVIEW_BUDGET_S（25）秒、檢查＋改寫合計 TOTAL_BUDGET_S（40）秒，
     都走 _call_gemini(optional=True, budget_s=…)（主要、備援模型輪流問）；剩不到 10 秒就不改寫。
     模型：檢查先問 config.REVIEW_MODEL（預設備援模型，免費方案下主要模型一天只有 20 次，留給
     學生直接看到的回答和改寫），改寫照常從主要模型問起。reflect() 呼叫時會告訴 main.py 是哪一步
     （STEP_REVIEW／STEP_REWRITE）。
     檢查沒做成 → skipped；發現問題但改寫沒做成 → flagged；兩種都送出原稿。
  5. 改寫過（revised）：再跑一次 clean_reply_text()，並丟掉 chat_sessions 快取——聊天物件的歷史裡
     是原稿，不丟掉的話老師下一輪會「記得」自己直接給過答案；下一句話從資料庫重讀（存的是改寫版）。
  6. 存檔後把結果存進 reply_reviews（狀態、問題、原稿、花了幾秒）；只有改寫過或該改沒改成的才留原稿。
     學生按「停止」撤銷這一輪時一起刪掉。
  - 實測（gemini-3.6-flash）：通過約 2～4 秒；發現問題＋改寫約 10～15 秒。
    抓到過的例子：學生才剛問就把答案寫完、9+16 算成 24、學生答 x=-3（錯）老師卻說「完全正確」。
  - 管理後台「老師自我檢查」分頁：各種結果的次數、平均秒數、各類問題的次數（review_stats）、
    最近發現問題的回覆（recent_reviews：JOIN messages 拿學生的問題和學生看到的回覆）。

流程 I：學習歷程蒐集與分析 (Learning Analytics)
  1. 蒐集：chat_endpoint 存好這一輪之後，用 BackgroundTasks 排 _record_learning()，回應送出後才執行，
     不影響學生的等待時間。它呼叫 learning_analysis.tag_turn()，用 config.LEARNING_MODEL
     （預設跟備援模型一樣的便宜模型，忙線再換主要模型；每次呼叫 60 秒逾時）標記：
       unit（只能從 src/curriculum.py 的 60 個單元挑，normalize_unit() 整理寫法，對不上就留空）、
       concept（答錯或卡住時寫錯在哪個觀念；會附上這個學生之前標過的觀念請它沿用同一種寫法）、
       activity（觀念提問／題目求助／作答／卡住／其他）、result（作答時：正確／部分正確／錯誤）、
       error_type（計算錯誤／觀念錯誤／看錯題目／其他）、problem（在解哪一題）、
       same_problem（還在解上一輪那題 → 沿用題目編號 problem_id）、solved（自己得到正確的最終答案）。
     給它看的是：老師上一輪說的話、學生這一輪說的話、老師這一輪的回覆（學生答對沒有，看老師怎麼評論最準）。
     learning_store.add_event() 用 WHERE EXISTS 確認學生那則訊息還在才存：標記做完前學生按了「停止」，
     這一輪就不會留下紀錄。標記失敗只記 log，不影響學生。
  2. 報告（純函式，給資料就算，方便測試）：
     - build_report(events, 訊息時間)：
       使用情形：學習天數（台灣時間算日期）、提問次數、估計學習時間（訊息隔超過 20 分鐘算另一次，
       每次加 3 分鐘看回覆）、近 7 天、最後上線、近 8 週每週的量（週一起算）。
       練習表現：作答次數、答對率、解出幾題（依 problem_id 分組）、平均來回幾輪解出、說自己卡住幾次。
       需要加強的單元：答錯算 1、部分正確算 0.5、卡住算 1，≥ 1 才列，最多 3 個，附上原因文字。
       常卡住的觀念（連到最近那次的對話）、錯誤類型、最近答錯的 5 題、各單元統計。
     - build_overview(所有帳號, 所有標記, 所有訊息時間)：全班人數、近 7 天活躍人數與提問數、全班答對率、
       最常卡住的單元（幾個人練習過、幾個人需要加強）、每個學生的概況、超過 7 天沒上線的學生。
  3. 學習建議：學生（或管理員）按按鈕才呼叫 write_advice()：把報告整理成文字（只有數字和單元、
     觀念名稱，不含對話內容）請 Gemini 寫 250 字以內的建議，存進 study_advice（每人最新一份），
     下次打開直接顯示。標記少於 3 筆不寫；有 45 秒時限。
  4. 畫面：learning_report.js 的 LearningReport.render() 學生頁和管理後台共用；管理員版不顯示
     「回到當時的對話」（管理員看不到對話內容）。學生頁的連結是 /?c=<對話 id>，app.js 進聊天室時
     先打開那條對話再把網址清掉。圖表只有一組資料，所以只用 --chart-1 一個顏色（淺色 #0a8f83、
     深色 #12a594，對比 ≥ 3、彩度與明度都驗過）、不放圖例，只標這週的數字，滑鼠移上或 Tab 選到
     顯示數字，每張圖都有「看數字」表格。窄螢幕的表格會藏掉次要欄位。
  5. 刪除：學生按「停止」刪這一輪的紀錄、刪除對話刪那條對話的紀錄、刪除帳號全部刪（含學習建議）。
  - 標記是 AI 判斷的，不會百分之百準；頁面上有提醒，適合看趨勢。

--------------------------------------------------------------------------------
5. 設定 (config.py / .env)
--------------------------------------------------------------------------------
  .env 可設定：
    GEMINI_API_KEY              必填
    GOOGLE_GENAI_USE_VERTEXAI   預設 FALSE
    CHAT_MODEL                  預設 gemini-3.6-flash（對話與繪圖程式碼共用）
    FALLBACK_CHAT_MODEL         預設 gemini-3.5-flash-lite（主模型忙線時的備援；跟 CHAT_MODEL 一樣就沒有備援）
    DRAW_MAX_FIXES              預設 1（畫圖自動檢查發現畫錯時最多重畫幾次；0 = 不檢查，畫圖最快）
    REPLY_REVIEW                預設 1（反思機制；0 = 老師回覆不自我檢查，每輪少一次呼叫）
    REVIEW_MODEL                預設跟 FALLBACK_CHAT_MODEL 一樣（反思機制「檢查」先問的模型）
    LEARNING_MODEL              預設跟 FALLBACK_CHAT_MODEL 一樣（背景標記學習歷程用的模型）
    CHROMA_DB_DIR               預設 data/chroma_db（路徑不可含中文，見第 6 節）
    ADMIN_USERNAME              預設 admin（管理後台帳號）
    ADMIN_PASSWORD              預設 admin（管理後台密碼；仍是預設值時啟動會記錄警告）

  config.py 內固定參數：
    EMBEDDING_MODEL = gemini-embedding-2     COLLECTION_NAME = math_materials
    CHUNK_SIZE = 500   CHUNK_OVERLAP = 100   CHUNK_MIN_CJK = 20   EMBED_BATCH_SIZE = 32
    RETRIEVAL_N_RESULTS = 4
    RETRIEVAL_MAX_DISTANCE = 0.58   # 課本有教的概念約 0.37~0.46；無關內容約 0.63~0.80

--------------------------------------------------------------------------------
6. 常見坑 (Gotchas)
--------------------------------------------------------------------------------
- ChromaDB 的 hnsw 索引不支援非 ASCII（中文）路徑：專案若放在中文資料夾下，
  請用 CHROMA_DB_DIR 指到純英數路徑。
- 程式只讀 .env，不讀 .env.example；忘了複製會出現「No API key was provided」。
- CHAT_MODEL 名稱打錯會出現 404 NOT_FOUND；可用的名稱以 client.models.list() 為準。
- CHAT_MODEL 和 FALLBACK_CHAT_MODEL 設成同一個模型就沒有備援；那個模型大塞車（503）時，
  對話和畫圖都會直接失敗，學生看到的就是「圖片生成失敗」或系統錯誤。
- 只有 .env 不進 git。data/（教材 PDF、向量庫、對話資料庫）和 frontend/generated/ 都有進版控，
  所以 repo 必須維持私人（教材有版權；conversations.db 有帳號、密碼雜湊和登入憑證）。
  資料庫在伺服器執行時會一直變動，commit 前先關掉伺服器。
- 改 style.css / app.js 後要同步改 index.html 的 ?v= 版本號，否則瀏覽器讀舊快取。
  （learning.html、admin.html 也各自載入 style.css、learning.css、learning_report.js，版本號要一起改。）
- 目前刻意用免費方案（先用免費額度）：429 訊息出現 free_tier_requests / FreeTier 是正常的，
  gemini-3.6-flash 一天只有 20 次，用完會落到備援模型。所以反思機制的檢查（REVIEW_MODEL）和學習標記
  （LEARNING_MODEL）預設都用備援模型，主要模型只留給老師回答和改寫。新增 Gemini 呼叫時要算清楚
  每輪會多用幾次主要模型。
- 每個 Gemini 呼叫都要有等待上限（一般呼叫 _CALL_TIMEOUT_S、加分項有總時限、背景標記 60 秒）；
  沒有上限的話，一次卡住會讓所有學生一起等。
- API 測試（tests/api_test_base.py）預設關掉反思機制和背景標記，不然每個聊天測試都會呼叫真的 Gemini；
  TestClient 會等 BackgroundTasks 跑完才回應，量時間時要記得把背景標記扣掉。

--------------------------------------------------------------------------------
7. 已知落差與待改進 (Known Gaps / TODO)
--------------------------------------------------------------------------------
- 兩套老師定義並存且已漂移：src/api/main.py（實際在用，含繪圖工具、主動預查、
  重試備援）與 src/agents/math_tutor/agent.py（ADK，只有檢索工具、教學紀律較舊）。
  應擇一為準，或讓 agent.py 重用 main.py 的人設字串。
- /api/chat 是 async 函式，但裡面呼叫的 Gemini SDK、SQLite、time.sleep（重試等待）
  都是同步阻塞的，會卡住整個事件迴圈；多人同時使用時應改成一般 def（交給執行緒池）
  或改用非同步 SDK。
- 「停止」沒辦法打斷伺服器上正在跑的那一輪（Gemini 呼叫是同步的），只能等它跑完再撤銷；
  停止後馬上重送的問題要排在它後面。撤銷用的 _finished_turns / _cancelled_requests 放在
  記憶體裡，只在單一行程下有效（uvicorn 開多個 worker 時不共用，伺服器重啟後也會忘記）。
- chat_sessions 記憶體快取沒有上限或過期機制，長時間運行會一直累積。
- 登入 session 在伺服器端沒有過期時間（只有 cookie 的 180 天），也沒有登入失敗次數限制
  （管理員登入也一樣沒有次數限制；預設密碼 admin 很容易被猜到，公開部署前一定要改）。
- 繪圖用的受限 exec 不是完整沙盒；若要對外公開服務，建議改在獨立行程／容器中執行。
- 存進資料庫的只有純文字問答，不含工具呼叫過程；重建聊天物件後，模型看不到當初
  查到的課本原文。
- document_parser 對排版很重的教科書，側邊欄小標／圖說殘片仍會混入少量區塊；
  可改用 page.get_text("blocks") 依版面位置過濾。
- 檢索結果直接取前 N 名，沒有 rerank。
- requirements.txt 未鎖定版本，重現性有風險。
- 學習標記只看文字：學生上傳題目照片時，標記的 AI 看不到圖，只能從老師的回覆推測。
"""

# 此檔案僅作為說明架構使用，無實質可執行代碼。
if __name__ == "__main__":
    print("本檔案為專案架構說明（完全註解），請閱讀程式碼中的註解了解詳情。")
