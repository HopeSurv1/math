# 國中數學 AI 家教 (Math Tutor Agent)

這是一個基於 **FastAPI**、**Google Gemini** 與 **RAG（檢索增強生成）** 的引導式國中數學 AI 家教系統。

---

## 🌟 核心特色

- **蘇格拉底式引導教學**：AI 扮演有耐心的國中數學老師，不直接給答案，而是一步步反問，引導學生自己想出來。
- **RAG 教材知識庫**：6 冊國中數學課本（7～9 年級）切塊後存進 ChromaDB。檢索有兩條路：
  - **後端主動預查**：每句話送出前先查一次，相似度夠高才自動附上課本內容。
  - **模型自行查詢**：Gemini 可以自己呼叫 `search_math_materials` 工具。
  - 回答會標示「📚 已查閱講義」。交給老師的參考資料只標冊別（例如「8上」），不給檔名和頁碼：每個學生用的課本版本不一樣，老師不會說「我們的課本第 91 頁」這種學生對不上的話。
- **精確的數學繪圖**：Gemini 把圖形描述轉成 matplotlib 程式碼，後端在受限環境中執行後產生圖片。座標和數字都是算出來的，不是 AI 憑感覺畫的。學生要求畫圖而模型漏畫時，後端會自動補一張；模型自己編出不存在的圖片網址時，後端也會照它的圖片說明補畫，不會出現破圖。
  - **畫完自動檢查**：程式先檢查圖是不是空白、有沒有圖形被切掉、文字有沒有重疊、幾何圖形有沒有被拉長變形、描述裡的點（例如三角形 ABC 的 A、B、C）有沒有標出來、有沒有字型顯示不出來而變成方框的字，再請 Gemini 看圖確認有沒有畫錯（例如畢氏定理的正方形畫進三角形裡）。發現問題就附上問題重畫一次，重畫得更好才換上去。主要模型忙線時，看圖檢查和重畫會在 30 秒內改問備援模型，時間到才略過，學生最多只多等 30 秒。
  - **符號不會變方框**：圖上的中文用微軟正黑體；≅（全等）、∼（相似）、⇒、⇔、✓ 這類正黑體沒有的符號，會自動改用 matplotlib 內建的 DejaVu Sans 顯示。
- **反思機制（老師回覆前先自我檢查）**：老師的回覆送出前，會先請 Gemini 對照學生的問題、最近的對話和這一輪查到的課本內容檢查一遍：有沒有**直接給答案**、**數學錯誤**（包括把學生錯的答案說成對的）、**跟課本不一致**、**答非所問**。有問題就附上檢查意見請老師改寫，學生只會看到改好的版本。檢查和改寫都有時限（合計最多約 40 秒），模型忙線就送出原稿，不讓學生一直等。每次檢查的結果都記下來，管理後台看得到改了什麼。
- **學習歷程蒐集與分析**：每一輪問答送出後，在背景請 Gemini 標記這一輪的**單元**（照 6 冊課本目次整理的 60 個單元，例如「8上 3-2 利用十字交乘法因式分解」）、**觀念**、學生在做什麼（觀念提問／題目求助／作答／卡住）、**作答對錯與錯誤類型**、在解哪一題、有沒有解出來。不影響學生的等待時間。
  - **學生的「我的學習紀錄」**（側欄的「學習紀錄」，網址 `/learning`）：學習天數、提問次數、估計學習時間、近 8 週的使用量，答對率、解出幾題、平均來回幾次解出，需要加強的單元、常卡住的觀念（可以直接回到當時的對話）、錯誤類型、各單元紀錄。按按鈕可以請 AI 依紀錄寫一段學習建議。
  - **管理後台的「學習分析」**：全班的活躍人數、答對率、最常卡住的單元（幾個人需要加強）、每個學生的概況、超過 7 天沒上線的學生；點學生可以看他的學習紀錄（跟學生自己看到的是同一份，但看不到對話內容）。
- **帳號與多對話串**：可以註冊和登入，每個帳號能開多條對話串，並切換、改名、刪除。對話存在 SQLite，重新整理網頁或重啟伺服器都不會消失。
- **刪除帳號**：點左下角自己的名字打開「帳號設定」，再輸入一次密碼即可刪除帳號。所有對話紀錄、學習紀錄、老師畫的圖和各裝置上的登入狀態都會一起清除。刪除某一條對話時，那條對話的學習紀錄也會一起刪掉。
- **管理後台**：管理員從獨立的 `/admin` 頁面登入，分成三個分頁：
  - **帳號管理**：查看所有註冊帳號（帳號、註冊時間、對話數、最後活動）、幫忘記密碼的學生重設密碼、刪除帳號（連同對話紀錄和圖片一起永久刪除，要照打一次帳號名稱確認）。密碼以單向加密儲存，管理員也看不到原本的密碼。
  - **學習分析**：見上面的「學習歷程蒐集與分析」。
  - **老師自我檢查**：檢查了幾次、通過／改寫／沒改成各幾次、平均多花幾秒、各類問題各幾次，以及最近發現問題的回覆（學生的問題、原稿、改寫後的版本）。
- **Gemini 忙線自動恢復**：遇到 503（模型忙線）或 429（額度超過）時會自動重試，重試失敗再改用備援模型。每次呼叫最多等 90 秒，模型卡住沒回應就直接改問備援模型，學生不會一直轉圈，也不會拖累其他同學。
- **雙語支援**：配合學生使用的語言，以繁體中文或英文回答。
- **簡潔的聊天介面**：
  - 左側欄可收合，列出近期對話；手機上改成從左邊滑出的選單
  - 開新對話時顯示問候語和範例問題，點一下就能直接發問
  - 老師回覆完之前不能再送出下一句（連按 Enter 也不會重複送出），等待時可以先打下一句
  - 等待時傳送鈕會變成「停止」鈕：按下去，剛剛的問題會收回、放回輸入框，改一改可以直接再送，老師也不會記得這個收回的問題
  - 老師的回覆支援粗體、條列、標題等格式，數學式裡的 `<`、`>` 也能正常顯示
  - 會跟著系統自動切換淺色／深色模式
- **輸入輔助**：
  - 上傳圖片（例如拍下幾何題）
  - 語音輸入（中文／英文切換）；講「二的平方」「根號二」「x的平方加y的平方等於z的平方」會自動變成 2²、√2、x²+y²=z²，只講「平方」這種觀念詞則不會轉。電腦上講到一半停下來想不會被切斷，停頓約 2.5 秒才自動結束
  - 數學符號鍵盤與次方模式（輸入的數字自動轉成上標）

---

## 🛠️ 技術架構

| 層 | 使用技術 |
|----|----------|
| 後端 | Python 3.10+、FastAPI、Uvicorn |
| AI / LLM | Google GenAI SDK（`google-genai`）。對話預設使用 Gemini 3.6 Flash，備援使用 Gemini 3.5 Flash Lite；Embedding 使用 `gemini-embedding-2`（正式版） |
| 向量庫 | ChromaDB（本機） |
| 資料庫 | SQLite（帳號、登入 session、對話紀錄、學習標記、自我檢查紀錄、學習建議） |
| 繪圖 | matplotlib、numpy |
| PDF 解析 | PyMuPDF |
| 前端 | HTML5、CSS3、原生 JavaScript（不使用前端框架） |

完整的目錄結構、API 一覽與各流程說明請見 [architecture_guide.py](architecture_guide.py)；每次更新修正或增加了什麼，請見 [update.py](update.py)（也可以執行 `python update.py` 直接印出來）。

---

## 🚀 快速開始

### 1. 複製專案

```bash
git clone https://github.com/lianghandsome/math-agent.git
cd math-agent
```

### 2. 安裝相依套件

建議使用虛擬環境（venv）：

```bash
python -m venv venv
# Windows:
.\venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. 設定環境變數

複製 `.env.example`，命名為 `.env`：

```bash
# macOS/Linux
cp .env.example .env
# Windows (PowerShell)
Copy-Item .env.example .env
```

編輯 `.env`，填入你的 Google Gemini API Key：

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

> 可至 [Google AI Studio](https://aistudio.google.com/) 免費申請 API Key。
> 程式只會讀取 `.env`，不會讀 `.env.example`。

其他選填設定：

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `CHAT_MODEL` | `gemini-3.6-flash` | 主要對話模型（也用來寫繪圖程式碼、看圖檢查） |
| `FALLBACK_CHAT_MODEL` | `gemini-3.5-flash-lite` | 主要模型忙線時自動改用的備援模型。跟 `CHAT_MODEL` 設成同一個就等於沒有備援 |
| `DRAW_MAX_FIXES` | `1` | 畫圖自動檢查發現畫錯時，最多重畫幾次。設成 `0` 就不檢查，畫圖最快 |
| `REPLY_REVIEW` | `1` | 反思機制：老師回覆送出前先自我檢查、有問題就改寫。設成 `0` 就不檢查，回覆最快（每則少一次 AI 呼叫） |
| `REVIEW_MODEL` | 跟 `FALLBACK_CHAT_MODEL` 一樣 | 反思機制「檢查」先問的模型。預設用備援模型，把主要模型的免費額度留給老師回答；改成付費方案後想讓檢查更準，可以設成跟 `CHAT_MODEL` 一樣 |
| `LEARNING_MODEL` | 跟 `FALLBACK_CHAT_MODEL` 一樣 | 在背景標記學習紀錄用的模型，用便宜的就夠 |
| `CHROMA_DB_DIR` | `data/chroma_db` | 向量庫位置（路徑不可含中文） |
| `ADMIN_USERNAME` | `admin` | 管理後台帳號 |
| `ADMIN_PASSWORD` | `admin` | 管理後台密碼，**公開部署前務必修改** |
| `GOOGLE_GENAI_USE_VERTEXAI` | `FALSE` | 是否改用 Vertex AI |

### 4. 建立教材向量資料庫

教材 PDF（`data/raw_docs/`）和建好的向量庫（`data/chroma_db/`）都已經在 repo 裡，clone 下來就能直接用。
換了 PDF 或改了切割方式，才需要重新執行：

```bash
python -m src.scripts.ingest_data
```

> 每次執行都會**清空並全量重建**向量庫，約 1500 個區塊，約 75 秒。
> 沒有建立向量庫也能聊天，只是老師查不到課本內容。

### 5. 啟動伺服器

```bash
uvicorn src.api.main:app --reload
```

啟動後在瀏覽器開啟 `http://127.0.0.1:8000`，註冊帳號並登入後即可開始使用。

管理後台在 `http://127.0.0.1:8000/admin`，預設帳密是 `admin` / `admin`，可在 `.env` 用 `ADMIN_USERNAME`、`ADMIN_PASSWORD` 修改。一般使用者不能用 `admin` 註冊帳號，也不能拿它當密碼。

---

## 🧪 測試

```bash
# 切割邏輯單元測試（不需要 API Key）
python -m unittest tests.test_document_parser -v

# 刪除帳號／刪除對話的 API 測試（使用暫存資料庫，不會動到真正的對話紀錄；不需要 API Key）
python -m unittest tests.test_delete_endpoints -v

# 管理後台與 admin 保留字的 API 測試（同樣使用暫存資料庫，不需要 API Key）
python -m unittest tests.test_admin -v

# 按「停止」撤銷一輪問答的 API 測試（暫存資料庫 + 假的 Gemini，不需要 API Key）
python -m unittest tests.test_stop_reply -v

# Embedding 批次與重試邏輯的單元測試（用假的 API，不花額度、不需要 API Key）
python -m unittest tests.test_embedding_service -v

# 查課本的結果交給老師前的整理（只標冊別、不給檔名和頁碼）的測試（用假的查詢結果，不需要 API Key）
python -m unittest tests.test_rag_tools -v

# 回覆圖片檢查（編造的圖片網址會被補畫）、繪圖 exec、畫圖自動檢查與重畫的測試（用假的 Gemini，不需要 API Key）
python -m unittest tests.test_reply_images -v

# 回覆文字整理（LaTeX 的 $a$ 換成 a、中文裡的日文「の」換回「的」）的測試（不需要 API Key）
python -m unittest tests.test_reply_cleanup -v

# 反思機制（老師回覆前自我檢查、有問題就改寫）的測試（假的 Gemini，不需要 API Key）
python -m unittest tests.test_reflection -v

# 學習歷程（單元清單、學習標記、學習紀錄報告、全班總覽、學習建議、刪除時跟著清掉）的測試（假的 Gemini，不需要 API Key）
python -m unittest tests.test_learning -v

# 等待上限（模型卡住就換備援、每次呼叫最多等 90 秒）的測試（假的 Gemini，不需要 API Key）
python -m unittest tests.test_call_timeout -v

# 語音數學符號轉換的測試（用本機 Chrome / Edge 的無頭模式執行前端 JS；找不到瀏覽器會略過）
python -m unittest tests.test_speech_math -v

# 檢索測試：查看某個問句在向量庫的檢索結果與距離（需要 API Key 與向量庫）
python tests/test_retrieval.py

# 終端機版工具呼叫煙霧測試
python scratch_test.py
```

---

## ❓ 常見問題

| 錯誤訊息 | 原因與解法 |
|----------|------------|
| `No API key was provided` | 沒有 `.env` 檔，或 `.env` 裡沒有 `GEMINI_API_KEY`。請見步驟 3，改完重啟伺服器。 |
| `503 UNAVAILABLE` / `high demand` | Gemini 暫時忙線。系統會自動重試並改用備援模型；如果仍然失敗，稍後再試，或在 `.env` 換一個 `CHAT_MODEL`。 |
| `404 NOT_FOUND ... is not found` | `CHAT_MODEL` 或 `FALLBACK_CHAT_MODEL` 的模型名稱不存在。可用 `client.models.list()` 查詢可用的名稱。 |
| 老師回覆「圖片生成失敗：503 UNAVAILABLE」 | 畫圖時主要模型和備援模型都在忙線。如果 `.env` 把 `CHAT_MODEL` 設成跟 `FALLBACK_CHAT_MODEL` 同一個模型，就等於沒有備援，一忙線就失敗；建議兩個設成不同的模型。 |
| 畫圖比以前慢 | 每張圖畫好後會多一次「看圖檢查」，畫錯時還會重畫；模型忙線時會改問備援模型，最多多等 30 秒。不需要的話在 `.env` 設 `DRAW_MAX_FIXES=0` 關掉。 |
| 圖上的符號（例如 ≅、⇒）變成方框 | 字型裡沒有這個字（缺字）。現在正黑體沒有的數學符號會自動改用 DejaVu Sans 顯示；連 DejaVu 也沒有的字（例如表情符號）程式會抓出來，請 Gemini 換個寫法重畫。修正前畫好的舊圖不會自己變好，要請老師重新畫一次。 |
| 按了「停止」，剛剛的問題不見了 | 這是設計好的：停止＝收回這個問題，文字（和附圖）會放回輸入框，改一改可以直接再送，老師也不會記得。伺服器上正在跑的那一輪沒辦法中途打斷，所以停止後馬上重送，要等它跑完才會開始回覆新的問題。 |
| `Error loading hnsw index` | 向量庫路徑含有中文。請在 `.env` 設定 `CHROMA_DB_DIR` 指向純英數路徑。 |
| log 出現「向量庫無結果」「資料庫內沒有任何相關講義內容」 | 向量庫是空的或讀不到。確認 `data/raw_docs/` 裡有教材 PDF，再執行步驟 4 的匯入；若 `.env` 設了 `CHROMA_DB_DIR`，確認它指向的位置有資料。 |
| 匯入時出現 `429 RESOURCE_EXHAUSTED` | 免費方案的每分鐘額度用完了。匯入腳本會自動等 60 秒再繼續；如果一直失敗並顯示「匯入未完成」，多半是當天額度用完，隔天再執行一次。 |
| 匯入時一直 `429`，訊息寫 `online_prediction_requests_per_base_model` | 用到 `gemini-embedding-2-preview` 了：preview 版額度很低，實測每分鐘只過得了約 5～6 次呼叫。`config.py` 的 `EMBEDDING_MODEL` 改成正式版 `gemini-embedding-2`（同價格），再重新匯入一次。注意：匯入一開始就會清空向量庫，中途失敗的話老師會查不到課本，一定要重跑到「全部完成」。 |
| 匯入完成但聊天時還是查不到課本 | 匯入會重建向量庫，正在執行的伺服器還拿著舊的資料庫連線。請重啟伺服器。 |
| 429 訊息寫 `free_tier_requests` 或 `FreeTier` | 這把 API Key 所屬的專案在免費方案（例如 `gemini-3.6-flash` 一天只有 20 次），額度用完了。主要模型額度用完時會改用備援模型，所以還能回話，但每輪都會先重試幾次、變慢。反思機制的檢查和學習標記預設都用備援模型，不會吃主要模型的額度。如果其實已經付費，到 Google AI Studio 的 API Keys 頁面確認 `.env` 裡的金鑰屬於哪個專案、那個專案是不是付費方案。 |
| 老師回覆「[系統錯誤] 老師好像有點累了…(timed out)」 | 主要模型和備援模型都超過 90 秒沒有回應（Gemini 大塞車）。稍等一下再問一次。 |
| 老師回覆比以前慢幾秒 | 反思機制：回覆送出前多一次自我檢查（實測約 2～4 秒），發現問題要改寫時再多一次（合計約 10～15 秒）。不需要的話在 `.env` 設 `REPLY_REVIEW=0` 關掉。 |
| 學習紀錄頁是空的，或少了幾輪 | 學習標記是在每一輪回覆之後、在背景請 Gemini 做的：`REPLY_REVIEW` 關掉不影響它，但模型忙線或額度用完時這一輪就不會列入（log 會出現「學習標記失敗」）。按「停止」收回的問題、刪掉的對話也不會列入。 |
| 改了 CSS/JS 但畫面沒變 | 瀏覽器讀到舊快取。請同步修改 `index.html`（管理後台是 `admin.html`）裡 `style.css?v=` / `app.js?v=` 的版本號。 |
| 舊對話裡的圖片變成破圖 | 圖片檔存在 `src/frontend/generated/`，不在資料庫裡。只把 `data/conversations.db` 搬到新資料夾、沒一起搬這個資料夾，舊圖就找不到了；把舊資料夾的 `generated/` 內容複製過來即可。 |

---

## 🔒 安全注意事項

- `.gitignore` 只排除 `.env`（API Key 與管理後台帳密）、Python 快取和幾個早期測試殘留檔。`data/`（教材 PDF、向量庫、對話資料庫）和產生的圖片都有進版控，當作完整備份。
- **這個 repo 必須維持私人**：教材 PDF 有出版社版權；`data/conversations.db` 裡有帳號、密碼雜湊、登入憑證和對話內容。檔案一旦進了 git 歷史，之後刪掉也還查得到。
- 請勿把個人 API Key 提交到 Git，包括 `.env.example`（它會進版控，只能放佔位文字）。
- 密碼以 PBKDF2-HMAC-SHA256 加鹽雜湊後儲存。登入狀態使用 httponly cookie，每個 API 都會檢查對話串的擁有者。
- 管理後台使用獨立的登入 cookie，8 小時後自動失效；學生的登入狀態無法存取後台 API。預設密碼 `admin` 只適合本機測試，伺服器啟動時若仍是預設值會在 log 顯示警告。
- 刪除帳號必須再輸入一次密碼。刪除時會一併作廢這個帳號所有的登入 session，就算之後有人用同一個名字重新註冊，也看不到前一個人的任何資料。管理員從後台刪除帳號時要照打一次帳號名稱確認，刪得跟使用者自己刪除一樣徹底。
- `.env` 裡除了 API Key 還有管理後台的帳密，整個檔案都不進版控；`.env.example` 列出所有設定項目，但只放佔位文字。
- 管理員在「學習分析」只看得到統計數字、AI 標的單元與觀念，看不到學生的對話；但「老師自我檢查」會列出被檢查出問題的那一輪（學生的問題、老師的原稿與改寫版），方便確認反思機制有沒有改對。
- 繪圖功能會執行 AI 產生的 matplotlib 程式碼。雖然限制了可用的內建函式、禁止 import 與檔案存取，但這不是完整的沙盒；公開部署前請評估風險。
