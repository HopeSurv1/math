---
name: project-guide
description: >-
  「引導式國中數學 AI 家教」專案的完整導覽：專案在做什麼、前端 / 後端 / 帳號與對話串 / RAG / 繪圖 /
  重試備援 / 反思機制 / 學習歷程分析各部分怎麼運作、每個檔案的職責、怎麼啟動、怎麼匯入教材、有哪些已知問題與可改進處。
  第一次接觸這個 repo，或要動到對話流程、帳號、對話紀錄、教材向量庫、切割、檢索、繪圖、反思機制、
  學習紀錄、管理後台、前端聊天介面時，先讀這份。
---

# 專案導覽：引導式國中數學 AI 家教

## 一句話

學生註冊登入後，在網頁聊天室問數學問題 → 後端 Gemini 扮演「蘇格拉底式」國中數學老師，
**不直接給答案、一步步反問引導**，依 6 冊國中數學課本（RAG）作答，
需要時用 matplotlib 畫出精確的幾何示意圖。對話分成多條對話串，存在 SQLite。
回覆送出前先**自我檢查**（反思機制），送出後在背景**標記學習歷程**，學生和管理員都看得到學習分析。

## 技術骨架

| 層 | 用什麼 |
|----|--------|
| 前端 | 原生 HTML / CSS / JavaScript（無框架），由後端直接提供 |
| 後端 | FastAPI + Uvicorn |
| AI | Google GenAI SDK（`google-genai`）— Gemini 對話、Embedding |
| 向量庫 | ChromaDB（本機，存在 `data/chroma_db/`） |
| 帳號 / 對話 / 學習紀錄 | SQLite（`data/conversations.db`） |
| 繪圖 | matplotlib + numpy（Gemini 寫程式碼、後端受限 exec 執行） |
| PDF 解析 | PyMuPDF (`fitz`) |
| 另一條路 | `google-adk`（僅 `src/agents/math_tutor/agent.py` 用到，見下） |

---

## 資料流

```
前端 (src/frontend/index.html + app.js)
   │  cookie: session_id
   │  fetch POST /api/chat   { message, image_data?, mime_type?, conversation_id? }
   ▼
FastAPI (src/api/main.py)
   │  auth_store.resolve_session()      → 認帳號（沒登入 401）
   │  conversation_store                → 擁有者檢查、讀寫歷史
   │  prefetch_context()                → 非畫圖請求才主動預查課本（距離 < 0.58 才附上）
   │  _with_retry_and_fallback()        → 503/429 重試 3 次，再換備援模型；每次最多等 90 秒，逾時直接換模型
   │     └ get_or_create_chat(conversation_id, model) → genai.chats，掛 2 個工具
   ▼
Gemini Chat ── 依 system_instruction 決定要不要用工具
   ├── 問到課本內容 ──► search_math_materials()  (src/rag_tools.py)
   │                        ├─► EmbeddingService ─► Google GenAI Embedding
   │                        └─► VectorDBService  ─► ChromaDB
   └── 需要圖形   ──► generate_math_image()      (src/api/main.py)
                            ├─► Gemini 產生 matplotlib 程式碼
                            ├─► 受限 exec ─► 存 PNG 到 src/frontend/generated/
                            └─► 自動檢查：程式查空白／被切掉／文字重疊／變形／漏標點名稱／缺字方框 → Gemini 看圖檢查
                                 → 有問題就附上問題重畫（最多 DRAW_MAX_FIXES 次，更好才換上去）
   │
   ▼  文字整理：LaTeX（$a$、\frac{1}{3}）→ 一般符號（a、1/3），中文裡混進的日文「の」→「的」
   ▼  圖片檢查：回覆裡的圖片網址必須指到真的檔案；Gemini 編出來的網址 → 換成這輪真畫的圖，或照說明補畫
   ▼  畫圖安全網：學生要畫圖但回覆沒圖 → 後端補畫一張
   ▼  反思機制（REPLY_REVIEW）：reflection.reflect() 對照「最近的對話＋學生這句＋這輪查到的課本」檢查草稿
   │     檢查先問 REVIEW_MODEL（預設備援模型，省主要模型的免費額度），改寫照常從主要模型問起
   │     有「直接給答案／數學錯誤／跟課本不一致／答非所問」→ 附上意見請老師改寫（圖片先換成 [圖1] 再交出去）
   │     檢查與改寫都走 _call_gemini(optional=True, budget_s=…)，合計最多約 40 秒；做不成就送原稿
   │     改寫過 → 丟掉 chat_sessions 快取（聊天物件記得的是原稿）
   ▼  問答純文字存進 SQLite；自我檢查結果存進 reply_reviews，回傳 { reply, used_tool, conversation_id }
   ▼  回應送出後（BackgroundTasks）：_record_learning() → learning_analysis.tag_turn() 用 LEARNING_MODEL
         標記單元／觀念／作答對錯／在解哪一題 → learning_store.add_event()（學生那則訊息已被撤銷就不存）
```

學習紀錄（跟聊天分開）：
```
GET /learning（learning.html + learning.js）      GET /admin 的「學習分析」「老師自我檢查」分頁（admin_learning.js）
   │  GET /api/learning/report                      │  GET /api/admin/learning/overview、/report?username=、/api/admin/reviews
   ▼                                                ▼
learning_analysis.build_report(events, 訊息時間)   build_overview(所有帳號, 所有標記, 所有訊息時間) + review_stats()
   ▼  兩邊都用 learning_report.js 畫（管理員看不到「回到當時的對話」）
   ▼  POST /api/learning/advice（或 /api/admin/learning/advice）→ write_advice() → study_advice 表
```

離線流程（跟前端無關）：
```
python -m src.scripts.ingest_data
   PDF → DocumentParser → EmbeddingService(批次) → VectorDBService → ChromaDB
```

---

## 每個檔案在幹嘛

### 後端核心
| 檔案 | 職責 | 備註 |
|------|------|------|
| [src/api/main.py](../../../src/api/main.py) | **主進入點**。帳號 API、對話串 API、`POST /api/chat`、老師人設、`get_or_create_chat()`、`generate_math_image()`、`_with_retry_and_fallback()`、`_reflect_on_reply()`、`_record_learning()`、學習紀錄 API | 老師人設是模組層的 `_TUTOR_PERSONA` + `_TUTOR_TOOL_RULES` + `_TUTOR_TEACHING_RULES`；聊天用 `TUTOR_INSTRUCTION`（三段全部），反思改寫用 `_REWRITE_INSTRUCTION`（沒有工具規則） |
| [src/services/reflection.py](../../../src/services/reflection.py) | 反思機制：`reflect(call_gemini, draft, …)` 檢查草稿、有問題就改寫，回傳 `Reflection`（學生看到的回覆、`ok`/`revised`/`flagged`/`skipped`、問題、原稿、秒數）。`hide_images`/`restore_images` 把圖片換成 `[圖N]` 再換回來 | `call_gemini` 由 main.py 傳入，測試換假的；時限 `REVIEW_BUDGET_S`、`TOTAL_BUDGET_S` |
| [src/services/learning_analysis.py](../../../src/services/learning_analysis.py) | 學習歷程：`tag_turn()`（AI 標記一輪）、`normalize_tag()`（整理成固定選項、決定題目編號）、`build_report()`／`build_overview()`（純函式，算報告）、`write_advice()`（AI 學習建議） | 學習時間是估計：訊息隔 >20 分鐘算另一次，每次 +3 分鐘；台灣時間算日期 |
| [src/services/learning_store.py](../../../src/services/learning_store.py) | `learning_events`（學習標記）、`reply_reviews`（自我檢查紀錄）、`study_advice`（學習建議）三張表；停止／刪對話／刪帳號時跟著刪 | 共用 `conversation_store._get_connection()`（同一個 DB 檔，可以 JOIN messages） |
| [src/curriculum.py](../../../src/curriculum.py) | 7 上～9 下 60 個單元（照課本目次整理），`normalize_unit()` 把 AI 寫的「八上3–2」之類整理成「8上 3-2」 | 整章只有一節的用「7上 4」「8上 5」 |
| [src/config.py](../../../src/config.py) | 讀 `.env`，集中所有設定：路徑、模型名稱（含備援）、切割、批次、檢索門檻 | |
| [src/rag_tools.py](../../../src/rag_tools.py) | `search_math_materials(query)`（給 Gemini 呼叫）、`prefetch_context(query)`（後端主動預查，有距離門檻），回傳帶「[出處：國中數學 8上]」的參考資料 | 只標冊別（`curriculum.SOURCE_BOOKS`），不給檔名和頁碼，見常見坑 22 |
| [src/services/auth_store.py](../../../src/services/auth_store.py) | 註冊、PBKDF2 密碼雜湊、登入 session token（users / sessions 表） | |
| [src/services/conversation_store.py](../../../src/services/conversation_store.py) | 對話串與訊息持久化；第一句話自動當標題；舊版資料自動遷移；`load_history()` 轉成 Gemini 格式；`student_message_times()` 給學習紀錄算使用時間 | 與 auth_store、learning_store 共用 `data/conversations.db` |
| [src/services/embedding_service.py](../../../src/services/embedding_service.py) | 呼叫 Gemini Embedding；`embed_text()` 單筆、`embed_texts()` 批次（每段各包一個 `Content`，否則 gemini-embedding-2 會合併成 1 組向量）；`rate_limit_wait` 控制 429 時等多久 | 輸出 3072 維 |
| [src/services/vector_db_service.py](../../../src/services/vector_db_service.py) | ChromaDB 連線；`upsert()`（含 metadata）、`query()`、`reset_collection()` | |
| [src/utils/document_parser.py](../../../src/utils/document_parser.py) | PDF 逐頁抽取 → `clean_text()` 清版面雜訊 → `chunk_text()` 重疊切割 → 附來源頁碼 | 見下方「切割流程」 |
| [src/scripts/ingest_data.py](../../../src/scripts/ingest_data.py) | 教材匯入主流程：掃 PDF → 批次轉向量 → 寫入 DB（**開頭會清空整個集合**） | |
| [src/utils/reply_cleanup.py](../../../src/utils/reply_cleanup.py) | `clean_reply_text()`：老師回覆的最後整理。LaTeX（`$a$`、`$a^2+b^2=c^2$`、`\frac{1}{3}`、`90^\circ`）→ 一般符號（a、a²+b²=c²、1/3、90°）；線段 `\overline{AB}` → A̅B̅（字母後面接組合上橫線 U+0305，前端 `formatInline` 再用 `.seg` 的 CSS 畫成連續橫線，因為直接顯示在微軟正黑體會歪）；中文裡混進的日文「の」→「的」。新回覆存檔前、開啟舊對話時都會跑 | 金額 `$30`、`^^` 表情、整段日文不動 |
| [src/utils/logger.py](../../../src/utils/logger.py) | 全域 logger（名稱 `math_rag`，輸出 stdout） | |

### HTTP API（全在 main.py）
| 路徑 | 作用 |
|------|------|
| `POST /api/register` / `POST /api/login` / `POST /api/logout` / `GET /api/me` | 註冊、登入（發 httponly cookie，180 天）、登出、查目前帳號 |
| `POST /api/account/delete` | 刪除帳號（body `{password}`，錯誤回 403）。先刪全部對話與訊息，再刪帳號與**所有** session，最後刪圖片檔 |
| `GET /admin`、`POST /api/admin/login` / `logout`、`GET /api/admin/me` | 管理後台頁面與登入。帳密來自 `.env`（預設 admin/admin），獨立的 `admin_session_id` cookie，8 小時失效 |
| `GET /api/admin/users` / `POST /api/admin/reset-password` | 帳號列表（註冊時間、對話數、最後活動；無密碼資料）、重設密碼（該帳號全部 session 作廢） |
| `POST /api/admin/delete-user` | 管理員刪除帳號（body `{username}`，不存在回 404）。跟使用者自己刪除走同一個 `_delete_account_and_data()`：學習紀錄、對話與訊息、帳號與所有 session、圖片檔全刪。防點錯人的確認（照打帳號名稱）在 admin.js |
| `GET /api/admin/learning/overview` | 全班總覽（`build_overview`）＋老師自我檢查統計（`reflection`） |
| `GET /api/admin/learning/report?username=` / `POST /api/admin/learning/advice` | 某個學生的學習紀錄（跟學生自己看到的同一份）、幫他產生學習建議（body `{username}`，不存在回 404） |
| `GET /api/admin/reviews` | 最近發現問題的自我檢查（`revised`／`flagged`），附學生的問題、原稿、學生看到的回覆 |
| `GET /learning`、`GET /api/learning/report`、`POST /api/learning/advice` | 學生自己的學習紀錄頁與報告；學習建議按按鈕才產生（標記少於 3 筆回 400、不呼叫 AI；忙線回 503） |

註冊與一般登入都拒絕保留字「admin」（不分大小寫，帳號和密碼都不行）。
| `POST /api/conversations` / `GET /api/conversations` | 開新對話串、列出自己的對話串 |
| `GET /api/conversations/{id}/messages` | 讀出某對話串內容 |
| `PATCH /api/conversations/{id}` / `DELETE /api/conversations/{id}` | 改名、刪除（刪除時一併清掉該對話引用的圖片檔和學習紀錄） |
| `POST /api/chat` | 對話；沒帶 `conversation_id` 會自動開新的。選填 `request_id`（前端每次送出產生的亂數），按停止時用 |
| `POST /api/chat/cancel` | 學生按「停止」：body `{request_id}`，撤銷這一輪（刪掉存進去的問答、這輪的學習標記與自我檢查紀錄、這輪畫的圖、這輪才開的對話串，丟掉 `chat_sessions` 快取讓老師忘記）。撤銷通常在這一輪存好後才到（`_finished_turns`）；先到的話記在 `_cancelled_requests`，這輪跑完直接不存 |

對話串相關 API 一律檢查擁有者，不是自己的回 404。

### 前端（`src/frontend/`）
| 檔案 | 職責 |
|------|------|
| [index.html](../../../src/frontend/index.html) | 登入／註冊畫面；聊天介面：左側可收合側欄（開新對話、「學習紀錄」連結、近期對話清單的切換／改名／刪除、帳號與登出）、右側置中對話欄（空白時顯示問候語與範例問題）、底部圓角輸入框（圖片上傳、數學符號鍵盤、語音鈕 + 中/EN 切換、送出鈕） |
| [style.css](../../../src/frontend/style.css) | 青綠 × 靛藍配色的簡潔樣式（淺色／深色模式、手機版抽屜側欄；π 標誌取代吉祥物）。`index.html` 用 `?v=` query 控制快取，改完 CSS/JS 記得同步改版本號 |
| [app.js](../../../src/frontend/app.js) | 全部前端邏輯：登入／註冊、對話紀錄清單、送出訊息（`handleSend`：一次只能等一則回覆，Enter／傳送鈕／範例問題都在這裡擋；等待中傳送鈕變「停止」鈕，`stopReply` 把問題收回輸入框並呼叫 `/api/chat/cancel`；等待中換對話，回覆不會畫進別的對話）、打字動畫、圖片轉 base64、數學符號鍵盤與「次方模式」、Web Speech API 語音輸入、依 `used_tool` 顯示「📚 已查閱講義」、401 時退回登入畫面、帳號設定對話框（刪除帳號）、網址 `/?c=<對話 id>`（學習紀錄頁連過來）時先打開那條對話 |

| [speech_math.js](../../../src/frontend/speech_math.js) | 語音輸入的數學講法 → 數學鍵盤上的符號（`SpeechMath.convert(text, lang)`，中英文）：「二的平方」→ 2²、「根號二」→ √2、「2拍r」→ 2πr、「三角形ABC」→ △ABC。只有運算詞旁邊有數字或變數才轉，講觀念的「什麼是平方」、「平方根」「平方公尺」「一元二次方程式」都不動。`SpeechMath.pick(candidates, lang)` 從語音辨識的多個候選（maxAlternatives）挑最像算式的。app.js 的 `onresult` 呼叫它們；電腦上用連續聆聽、停頓 2.5 秒自動結束，辨識候選會印在瀏覽器主控台（`[語音輸入]`） |
| [admin.html / admin.js / admin.css](../../../src/frontend/admin.html) | 管理後台（`/admin`）：管理員登入、三個分頁（帳號管理／學習分析／老師自我檢查，切換在 admin.js 的 `showTab`）、帳號列表與搜尋、詳細資訊（含「查看學習紀錄」）、重設密碼、刪除帳號（另開確認框，要照打帳號名稱才按得下去）。重用 style.css 的顏色與元件；改完記得同步改 admin.html 的 `?v=` |
| [admin_learning.js](../../../src/frontend/admin_learning.js) | 管理後台的「學習分析」（全班總覽、點學生看報告、幫學生產生建議）與「老師自我檢查」（統計、問題類型、原稿／改寫版）兩個分頁 |
| [learning.html / learning.js](../../../src/frontend/learning.html) | 學生的「我的學習紀錄」頁（`/learning`）；沒登入導回首頁；「回到當時的對話」連到 `/?c=<id>` |
| [learning_report.js / learning.css](../../../src/frontend/learning_report.js) | 學習紀錄報告的畫面，學生頁和管理後台共用（`LearningReport.render(container, report, options)`）：統計方塊、近 8 週直條圖、錯誤類型橫條、各單元表格、AI 學習建議。圖表只有一組資料：單色 `--chart-1`（淺／深色都驗過對比與彩度）、不放圖例、只標這週的數字、滑鼠移上或 Tab 選到顯示數字，每張圖都有「看數字」表格 |

### Agent（另一種執行方式）
| 檔案 | 職責 |
|------|------|
| [src/agents/math_tutor/agent.py](../../../src/agents/math_tutor/agent.py) | `google-adk` 的 `root_agent`。**只有用 `adk web` / `adk run src/agents/math_tutor` 才會跑到**，FastAPI 完全沒 import 它 |

> ⚠️ `agent.py` 和 `main.py` 是**兩套獨立的老師定義，而且已經漂移**：
> 兩者都用 `config.CHAT_MODEL`，但 `agent.py` 沒有繪圖工具、沒有主動預查、沒有重試備援，教學紀律文字也較舊。
> 動老師人設時要想清楚改的是哪一套。建議長期擇一為準。

### 測試 / 雜項
| 檔案 | 職責 |
|------|------|
| [tests/test_document_parser.py](../../../tests/test_document_parser.py) | `clean_text` / `chunk_text` 單元測試，不需金鑰：`python -m unittest tests.test_document_parser -v` |
| [tests/api_test_base.py](../../../tests/api_test_base.py) | API 測試共用基底：每個測試換成暫存資料庫、管理員帳密固定為 admin/admin；**反思機制（`REPLY_REVIEW`）和背景學習標記（`_record_learning`）預設關掉**，不然每個聊天測試都會去呼叫真的 Gemini |
| [tests/test_reflection.py](../../../tests/test_reflection.py) | 反思機制：通過、改寫、檢查／改寫失敗送原稿、時間不夠不改寫、圖片換成 [圖N] 再換回來、透過 /api/chat 存的是改寫版、停止時刪掉紀錄、管理員看得到：`python -m unittest tests.test_reflection -v` |
| [tests/test_call_timeout.py](../../../tests/test_call_timeout.py) | 等待上限：卡住的模型不重試、直接換備援；忙線照舊重試；老師回答和一般呼叫都帶 90 秒上限：`python -m unittest tests.test_call_timeout -v` |
| [tests/test_learning.py](../../../tests/test_learning.py) | 學習歷程：單元清單、標記整理、報告（台灣時間算日期、學習時間、需要加強的單元、觀念、錯誤類型）、全班總覽、API 權限、學習建議、背景標記、刪除時跟著清：`python -m unittest tests.test_learning -v` |
| [tests/test_embedding_service.py](../../../tests/test_embedding_service.py) | `embed_texts` 批次與 429 重試的單元測試，用假的 API：`python -m unittest tests.test_embedding_service -v` |
| [tests/test_rag_tools.py](../../../tests/test_rag_tools.py) | 查課本的結果交給老師前的整理：只標冊別、不出現檔名和頁碼（查課本工具和主動預查都檢查），用假的查詢結果：`python -m unittest tests.test_rag_tools -v` |
| [tests/test_admin.py](../../../tests/test_admin.py) | 管理後台（登入、帳號列表、重設密碼、刪除帳號）與 admin 保留字的 API 測試：`python -m unittest tests.test_admin -v` |
| [tests/test_reply_images.py](../../../tests/test_reply_images.py) | 回覆圖片檢查（編造的網址會被換掉或補畫）、繪圖 exec、畫圖自動檢查與重畫（版面檢查、缺字方框、看圖檢查、忙線時換備援模型、卡住時有後備答案、不超過時限）的測試，用假的 Gemini：`python -m unittest tests.test_reply_images -v` |
| [tests/test_reply_cleanup.py](../../../tests/test_reply_cleanup.py) | 回覆文字整理的測試（LaTeX → 符號、「の」→「的」、不該動的不動），用假的 Gemini：`python -m unittest tests.test_reply_cleanup -v` |
| [tests/test_speech_math.py](../../../tests/test_speech_math.py) | 語音數學符號的測試：用本機 Chrome / Edge 無頭模式執行 speech_math.js，另外載入真正的 index.html + app.js、換上假的語音辨識跑整條流程；找不到瀏覽器就略過。要加新講法時，把「該轉的」和「不該轉的」句子都加進這裡：`python -m unittest tests.test_speech_math -v` |
| [tests/test_delete_endpoints.py](../../../tests/test_delete_endpoints.py) | 刪除帳號／刪除對話的 API 測試，TestClient + 暫存資料庫，不需金鑰：`python -m unittest tests.test_delete_endpoints -v` |
| [tests/test_stop_reply.py](../../../tests/test_stop_reply.py) | 按「停止」撤銷一輪問答的 API 測試（存好後撤銷、撤銷先到就不存、新對話整條刪、只刪這輪的圖、不能停別人的），假的 Gemini + 暫存資料庫：`python -m unittest tests.test_stop_reply -v` |
| [tests/test_retrieval.py](../../../tests/test_retrieval.py) | 不啟動 Agent，單獨測某問句的檢索結果與距離分數。直接 `python tests/test_retrieval.py` |
| [tests/test_reflection_experiment.py](../../../tests/test_reflection_experiment.py) | 反思機制比較實驗的測試（跑情境、判讀表 A/B 排列、5 項數據計分、判讀網頁），假的 Gemini：`python -m unittest tests.test_reflection_experiment -v` |
| [experiments/reflection_eval/](../../../experiments/reflection_eval/README.md) | 專刊用的反思機制開／關比較實驗：`run_experiment.py`（100 題情境走 /api/chat，每題同時記下原稿＝無反思、最後回覆＝有反思）→ `make_sheet.py`（判讀網頁（預設 A＝無反思、B＝有反思，--blind 隨機））→ `score.py`（5 項數據）。結果在 `results/`，用實驗專用資料庫 |
| [scratch_test.py](../../../scratch_test.py) | 終端機版工具呼叫煙霧測試（送「什麼是質數？」） |
| [architecture_guide.py](../../../architecture_guide.py) | 純註解的架構說明檔（跟這份 SKILL 內容重疊，維護時兩邊一起改） |
| [update.py](../../../update.py) | 更新紀錄：每次更新的日期與修正／新增了什麼（新的寫在最上面）；`python update.py` 會印出來。每次改完功能記得補一筆 |
| [README.md](../../../README.md) | 使用者向的安裝、啟動、常見問題 |

---

## 怎麼啟動

```bash
# 0. 安裝
pip install -r requirements.txt

# 1. 設定金鑰：複製 .env.example 成 .env，填入
#    GEMINI_API_KEY=你的金鑰
#    （選填）CHAT_MODEL / FALLBACK_CHAT_MODEL / CHROMA_DB_DIR

# 2. 匯入教材（PDF 放 data/raw_docs/；第一次、換了 PDF、或改了切割邏輯後）
python -m src.scripts.ingest_data

# 3. 啟動網站
uvicorn src.api.main:app --reload
#    → 開 http://127.0.0.1:8000，註冊登入後使用

# （選）測試
python -m unittest tests.test_document_parser -v
python -m unittest tests.test_delete_endpoints -v
python -m unittest tests.test_stop_reply -v
python -m unittest tests.test_admin -v
python -m unittest tests.test_embedding_service -v
python -m unittest tests.test_rag_tools -v
python -m unittest tests.test_reply_images -v
python -m unittest tests.test_reply_cleanup -v
python -m unittest tests.test_reflection -v
python -m unittest tests.test_learning -v
python -m unittest tests.test_call_timeout -v
python -m unittest tests.test_speech_math -v
python tests/test_retrieval.py
python scratch_test.py
```

---

## 匯入教材細節

- 把 PDF 放進 `data/raw_docs/`（有版權，只放在私人 repo），跑 `python -m src.scripts.ingest_data`。
- **全量重建**：開頭 `reset_collection()` 會清空整個集合，不是增量。加一份新 PDF 也要整個重跑。
- 約 1500 個區塊、約 75 秒。
- 產物在 `data/chroma_db/`，有進版控，clone 下來就能直接用；重新 ingest 後記得一起 commit。

### 切割流程（document_parser.py）

`process_file(path)` → `[{"text", "metadata": {"source", "page", "chunk_index"}}, ...]`

1. `extract_pages` — PyMuPDF 逐頁抽文字，保留頁碼。
2. `clean_text` — 刪圖形座標軸數字 / 頁尾章名 / 純頁碼 / 交叉引用標記（`自評 P21`），正規化全形空白。
3. `chunk_text` — 重疊視窗：目標 `CHUNK_SIZE` 字、重疊 `CHUNK_OVERLAP` 字，優先在換行斷、其次中文句號。
4. 中文字 < `CHUNK_MIN_CJK` 的區塊丟棄。

> 改切割邏輯或參數後**一定要重新 ingest** 才生效（DB 是快照）。

---

## 可調參數

`.env`：

| 變數 | 預設 | 作用 |
|------|------|------|
| `GEMINI_API_KEY` | —（必填） | Gemini 金鑰 |
| `CHAT_MODEL` | `gemini-3.6-flash` | 對話與繪圖程式碼共用的主模型 |
| `FALLBACK_CHAT_MODEL` | `gemini-3.5-flash-lite` | 主模型 503/429 重試用盡後的備援；跟 `CHAT_MODEL` 同一個就沒有備援 |
| `DRAW_MAX_FIXES` | `1` | 畫圖自動檢查發現畫錯時最多重畫幾次；`0` = 不檢查（每張圖少一次看圖呼叫） |
| `REPLY_REVIEW` | `1` | 反思機制開關；`0` = 老師回覆不自我檢查（每輪少一次呼叫、快 2～4 秒） |
| `REVIEW_MODEL` | 同 `FALLBACK_CHAT_MODEL` | 反思機制「檢查」先問的模型（忙線再換主要模型）；改寫還是從 `CHAT_MODEL` 問起 |
| `LEARNING_MODEL` | 同 `FALLBACK_CHAT_MODEL` | 背景學習標記用的模型（忙線再換 `CHAT_MODEL`） |
| `CHROMA_DB_DIR` | `data/chroma_db` | 向量庫位置（不可含中文） |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `admin` | 管理後台帳密，公開部署前務必修改 |

`config.py` 內固定：

| 參數 | 預設 | 作用 |
|------|------|------|
| `CHUNK_SIZE` / `CHUNK_OVERLAP` / `CHUNK_MIN_CJK` | 500 / 100 / 20 | 切割 |
| `EMBED_BATCH_SIZE` | 32 | 一次送幾段給 Embedding API |
| `EMBEDDING_MODEL` | `gemini-embedding-2` | Embedding 模型（正式版；preview 版額度很低，實測每分鐘約 5～6 次，見常見坑 0） |
| `COLLECTION_NAME` | `math_materials` | ChromaDB 集合名稱 |
| `RETRIEVAL_N_RESULTS` | 4 | 每次檢索取幾段 |
| `RETRIEVAL_MAX_DISTANCE` | 0.58 | 主動預查門檻（課本概念約 0.37～0.46，無關內容約 0.63～0.80） |

重試次數（3）與退避間隔（1s、2s）寫在 `main.py` 的 `_with_retry_and_fallback()`；逾時（`_is_timeout_error`：httpx 的 TimeoutException 或訊息含 timed out）不重試，直接換下一個模型。
一般呼叫（老師回答、第一次寫繪圖程式碼）每次最多等 `_CALL_TIMEOUT_S`（90 秒）：聊天物件的 config 和 `_call_gemini()` 非加分項的路徑都會帶 `http_options.timeout`（`_with_timeout()`）。
畫圖加分項的時限寫在 `main.py`：`_OPTIONAL_CALL_BUDGET_S`（30 秒總時限）、`_OPTIONAL_HEDGE_AFTER_S`（15 秒沒回應就同時問備援）、`_OPTIONAL_MIN_CALL_S`（剩不到 5 秒就不再開新呼叫）。
反思機制的時限寫在 `reflection.py`：`REVIEW_BUDGET_S`（檢查 25 秒）、`TOTAL_BUDGET_S`（檢查＋改寫 40 秒）；學習建議 `_ADVICE_BUDGET_S`（45 秒）在 `main.py`；背景標記每次呼叫 60 秒逾時（`learning_analysis._TAG_TIMEOUT_MS`）。
實測（`gemini-3.6-flash`）：檢查通過約 2～4 秒；發現問題＋改寫約 10～15 秒。

---

## 常見坑

0. **Embedding 批次一定要每段各包一個 `types.Content`。** 直接傳字串清單，SDK 會把它們合併成一份內容，匯入時出現 `Unequal lengths ... embeddings: 1`。免費額度每分鐘不高，匯入碰到 429 會等 60 秒重試；匯入完要重啟伺服器。**Embedding 要用正式版 `gemini-embedding-2`**：`gemini-embedding-2-preview` 額度很低，實測每分鐘只過得了約 5～6 次呼叫（429 訊息 `online_prediction_requests_per_base_model`），一批 32 段就超過，聊天時的檢索也會跟著 429。換 Embedding 模型一定要重新 ingest，而且 ingest 一開始就清空集合，中途失敗向量庫就是空的，要重跑到「全部完成」。
1. **ChromaDB 的 hnsw 索引不支援非 ASCII（中文）路徑。** 專案資料夾若在中文路徑下，`ingest` 會報 `Error loading hnsw index`。解法：`.env` 設 `CHROMA_DB_DIR=` 指到純英數路徑。
2. **程式只讀 `.env`，不讀 `.env.example`。** 忘了複製會出現 `No API key was provided`。
3. **模型名稱打錯是 404 `NOT_FOUND`**，不會觸發重試。可用名稱以 `client.models.list()` 為準。
4. **只有 `.env` 不進版控。** `data/`（教材 PDF、向量庫、`conversations.db`）和 `src/frontend/generated/` 都有進版控，所以 **repo 必須維持私人**：教材有版權，`conversations.db` 裡有帳號、密碼雜湊和登入憑證。資料庫在伺服器執行時會變動，commit 前先關掉伺服器。
5. **`ingest` 是全量重來**，不是增量。
6. **改 `style.css` / `app.js` 後要同步改 `index.html` 的 `?v=` 版本號**，否則瀏覽器讀舊快取。
7. **資料庫只存純文字問答**，不存工具呼叫過程；聊天物件重建後，模型看不到當初查到的課本原文。
8. **Gemini 會自己編圖片網址。** 它知道圖片語法長什麼樣子，有時沒呼叫 `generate_math_image` 就直接寫 `![...](/generated/xxx.png)`。`_fix_reply_images()` 會把不存在的網址換成真的圖或補畫，所以**不要用「回覆裡有沒有 `/generated/`」判斷有沒有圖**，要檢查檔案真的存在。
9. **圖片檔不在資料庫裡**，在 `src/frontend/generated/`。只搬 `conversations.db` 不搬這個資料夾，舊對話的圖就會變成破圖。
10. **系統提示擋不住所有格式問題。** 就算寫了「不要用 LaTeX」，Gemini 偶爾還是會寫 `$a$`，也偶爾把「的」寫成日文「の」。這類問題在 `reply_cleanup.py` 用程式確定修掉；遇到新的格式問題，優先加在那裡並補測試，而不是只改提示。
11. **畫圖的「加分項」不能拖時間，但要盡量做成。** 看圖檢查、以及已經有圖時的重畫，都走 `_call_gemini(optional=True)` → `_call_gemini_within_budget()`：總共最多多等 30 秒，這段時間內主要、備援模型輪流問（503/429 就換模型，問 15 秒沒回應就同時問備援當後備，主要模型的答案優先），時間到才沿用原本的圖。模型大塞車時一次 503 可能要等一分多鐘，走一般的重試＋備援會讓學生多等好幾分鐘。**Gemini 不接受少於 10 秒的等待上限（回 400 INVALID_ARGUMENT）**，所以時限由迴圈把關，不能把每次呼叫的 `http_options.timeout` 設成剩下的秒數。
12. **`CHAT_MODEL` 和 `FALLBACK_CHAT_MODEL` 設成同一個模型就沒有備援**，那個模型一忙線，對話和畫圖都會直接失敗。
13. **重畫過的圖不會再看圖檢查一次**（`DRAW_MAX_FIXES=1` 時）。程式檢查發現問題就直接重畫、不問模型，所以這種圖從頭到尾沒有被模型看過；程式檢查的誤判會讓看圖檢查被跳過，新增程式檢查時要寧可漏抓、不要誤判。
14. **matplotlib 的備用字型要寫在 `rcParams["font.family"]`，不是 `font.sans-serif`。** `font.family` 的每一項各是一套字型，缺字時依序往後找；`font.sans-serif` 清單只會挑出第一套找得到的字型。以前只設了 `font.sans-serif`，微軟正黑體沒有的 ≅（全等）、∼（相似）、⇒、⇔、✓ 全都畫成方框（方框裡的小圖案是字型在提示缺字的類別：上下箭頭＝箭頭類、√＝數學符號類）。現在由 matplotlib 內建的 DejaVu Sans 補上；連 DejaVu 也沒有的字（例如 emoji ✅）由 `_layout_problems` 從畫圖時的缺字警告抓出來、請 Gemini 換寫法重畫。
15. **擋重複送出要擋在 `handleSend` 本身，不能只把傳送鈕 disabled。** Enter 鍵和歡迎畫面的範例問題卡片都直接呼叫 `handleSend()`，以前只 disabled 按鈕，狂按 Enter 就能一直送。「停止」也不能只在前端中斷請求：後端照樣會把這一輪存起來、老師也會記得，所以要呼叫 `/api/chat/cancel` 撤銷。
16. **改寫過的回覆，聊天物件記得的還是原稿。** `chats.create()` 的歷史裡最後一句是 Gemini 自己寫的草稿，資料庫存的是改寫版；不丟掉 `chat_sessions` 快取的話，老師下一輪會「記得」自己直接給過答案。改寫後一定要 `chat_sessions.pop(conversation_id)`，讓下一句話從資料庫重讀。
17. **反思機制的判斷比老師準一點，但不是保證。** 實測它抓得到「直接給答案」「9+16 算成 24」「學生答 x=-3 老師卻說完全正確」這類問題；檢查員自己也可能誤判，所以提示裡寫明哪些情況「不算」直接給答案（確認學生算出的答案、解釋觀念、學生卡很久時示範一步），避免把正常的引導也改掉。改寫過的不再檢查第二次。
18. **學習標記在背景做：TestClient 會等它做完才回應，正式伺服器不會。** `BackgroundTasks` 在回應送出後才跑，所以用 TestClient 量「一輪要多久」會把背景標記的時間也算進去。標記存進資料庫前會確認學生那則訊息還在（`add_event` 的 `WHERE EXISTS`），學生在標記做完前按「停止」也不會留下孤兒紀錄。
19. **觀念名稱要沿用同一種寫法，統計才不會被拆散。** 同一個觀念，AI 可能寫成「因式分解法」「因式分解法解方程式」好幾種，所以標記時會把這個學生之前標過的觀念（`known_concepts`）一起給它，請它照抄。單元則只能從 `curriculum.UNITS` 挑，`normalize_unit()` 對不上就留空。
20. **目前刻意用免費方案（2026-09 起，先用免費額度）。** 429 訊息裡出現 `free_tier_requests` / `FreeTier` 是正常的：`gemini-3.6-flash` 一天只有 20 次，用完時對話會落到備援模型（每輪會先重試幾次，變慢一點）。所以新功能要算清楚每輪用幾次主要模型：反思機制的檢查預設走 `REVIEW_MODEL`（備援模型）、學習標記走 `LEARNING_MODEL`（備援模型），主要模型只留給老師回答和改寫。之後改成付費方案，想讓檢查更準，可以把 `REVIEW_MODEL` 設成 `CHAT_MODEL`。
21. **沒有等待上限的呼叫會拖垮整個網站。** `/api/chat` 是 async 端點但裡面全是同步呼叫，一次卡住，其他學生的請求也跟著排隊。實測模型偶爾卡 4 分鐘以上才回，所以每個呼叫都要有上限：一般呼叫 `_CALL_TIMEOUT_S`、加分項有總時限、背景標記 60 秒。新增 Gemini 呼叫時別忘了。
22. **不要讓老師看到頁碼。** 每個學生用的課本版本不一樣（不同出版社、不同學校的講義），頁碼、章節和例題編號都對不上。以前參考資料標著「[出處：8_1.pdf 第 91 頁]」，透明度規則又要老師「讓學生知道有根據講義」，老師就會說「根據我們的課本講義（第 91 頁）」。現在 `_format_hits` 只標冊別；透明度規則、主動預查的提示、`search_math_materials` 的回傳開頭都寫明不要說頁碼、章節或例題編號，也不要說「我們的課本／講義」。學習建議（`ADVICE_INSTRUCTION`）也只寫冊別和單元名稱，不寫 3-2 這類編號。區塊內文本身還是可能帶著章節編號（例如目次「3-2 解一元一次方程式 168」），這部分只能靠提示擋。

---

## 已知問題 / 可改進

| 項目 | 位置 | 說明 |
|------|------|------|
| 兩套老師定義漂移 | `main.py` vs `agent.py` | 工具、預查、紀律文字不一致，應擇一為準 |
| async 端點裡做阻塞呼叫 | `main.py` 的 `chat_endpoint` | Gemini SDK、SQLite、重試的 `time.sleep` 都是同步的，會卡住事件迴圈；多人使用時應改成一般 `def` 或改用非同步 SDK |
| 「停止」打斷不了正在跑的那一輪 | `main.py` 的 `/api/chat/cancel` | Gemini 呼叫是同步的，只能等它跑完再撤銷，停止後馬上重送要排隊；`_finished_turns` / `_cancelled_requests` 在記憶體裡，多個 worker 不共用、重啟就忘 |
| 聊天快取無上限 | `main.py` 的 `chat_sessions` | 沒有過期或 LRU，長時間運行會累積 |
| session 不過期、無登入限流 | `auth_store.py` | 伺服器端 token 永久有效；登入失敗沒有次數限制 |
| exec 不是完整沙盒 | `main.py` 的 `_render_matplotlib_code` | 公開部署前應改到獨立行程／容器 |
| 切割仍混入版面碎片 | [document_parser.py](../../../src/utils/document_parser.py) | 教科書側邊欄小標；可改用 `get_text("blocks")` 依位置過濾 |
| 檢索結果沒有重排序 | `rag_tools.py` | 直接取前 N，可加 rerank 提升精度 |
| 相依未鎖版本 | [requirements.txt](../../../requirements.txt) | 沒有 `==` 版本號，重現性有風險 |
| 學習標記只看文字 | `learning_analysis.tag_turn` | 學生上傳題目照片時，標記的 AI 看不到圖，只能從老師的回覆推測單元和對錯 |
| 學習建議的數字偶爾會「四捨五入」 | `learning_analysis.write_advice` | 提示已要求天數、次數照抄，實測仍可能寫成「這幾天」這類模糊說法；要精確的數字看報告本身 |
| 單元代號是某一版課本的章節編號 | `curriculum.UNITS`、學習紀錄頁 | 「8上 3-2」照 `data/raw_docs/` 那一版課本的目次編，別的版本章節編號可能不同。學習建議已改成只寫冊別和單元名稱，但學習紀錄頁的單元表格還是顯示代號 |
