# 失敗紀錄 2026-09

> 每發現一個失敗就立刻記錄：原因、影響、怎麼發現、修正狀態、教訓。
> 分類：**B** = 產品缺陷、**D** = 文件與程式不一致、**P** = 流程錯誤（含 Claude 自己的錯誤）、**E** = 環境。
> 不刪除、不淡化既有條目。

---

## B-1　Sentry 可能把未遮罩的 OA 原文送出本機（2026-09-29，已修正）

- **原因**：誤以為 `send_default_pii=False` 就不會送出內容。實際上它只管 cookie、header、IP；Python SDK 預設 `include_local_variables=True`、`max_request_body_size="medium"`，並會附上 logging breadcrumb。程式註解還寫「OA 內容已經遮罩過」，但在 `masking.redact()` 之前丟出的例外不成立。前端 SDK 也會附上例外訊息、console／fetch breadcrumb。
- **影響**：只要設定了 `SENTRY_DSN`（尤其是 sentry.io），例外發生時未遮罩的 OA 就會繞過遮罩、egress guard、機密路由（不變量 #3、#7）直接出境。預設沒有設定 DSN，所以尚未實際發生。
- **怎麼發現**：以「隱私、延遲最不能接受」為標準重新檢視系統時，讀 `observability.py:268`，再對照 Sentry 官方文件確認預設值。
- **修正**：後端關閉區域變數和請求 body，加上 `scrub_sentry_event()`；前端加上 `sentryScrub.js`。測試：後端 4 個、前端 3 個，全部通過。詳見 `docs/SECURITY_AUDIT.md` H-9。
- **教訓**：「關掉 PII」這類選項的範圍要查文件確認，不能看名字猜。第三方 SDK 是繞過自家防線最常見的路徑，現有測試抓不到，因為測試環境本來就沒有 DSN。

## B-2　稽核鏈在多個行程同時寫入時會分岔（2026-09-29 發現，2026-09-30 已修正）

- **原因**：「讀鏈尾 → 算 hash → 插入」只用 `threading.RLock` 保護，這把鎖只在單一行程內有效；讀鏈尾和插入也不在同一個資料庫交易裡。
- **影響**：部署多個 gateway 副本、共用同一個資料庫時，兩筆紀錄會接在同一個鏈尾之後，驗證時會被誤判成竄改。單機 demo 和既有的所有測試都在單一行程內，所以一直沒被發現。
- **怎麼發現**：以「從單機走向多副本」的角度審查設計時讀到 `audit.py:433`。**修正前實測重現**：4 個行程各寫 40 筆，160 筆紀錄只有 157 個不同的 `prev_row_hash`，分岔 3 次。
- **修正**：各 backend 實作 `_append_chained()`，讀鏈尾和插入放在同一個交易裡，並加上跨行程的鎖（SQLite `BEGIN IMMEDIATE`、Postgres `pg_advisory_xact_lock`）。新測試在舊程式上會失敗、在新程式上會通過。
- **未完成**：Postgres 路徑還沒有在真的資料庫上跑過。
- **教訓**：「測試全綠」只代表在測試的假設下正確。單一行程的測試證明不了多副本的正確性，要有真的開多個行程的測試。

## B-3　撤銷清單的 Redis 故障沒有處理（2026-09-29 發現，2026-09-30 已修正）

- **原因**：`RedisRevocationStore` 直接讓 Redis 的例外往上拋。
- **影響**：Redis 故障時回 500 而不是清楚的 503；登出也會出錯，使用者可能誤以為已經登出。
- **修正**：改成 `RevocationUnavailable`，回 503 加上 Retry-After，保持 fail-closed；登出失敗也會寫入稽核，不會回報成功。
- **附帶確認**：原本懷疑的「認證失敗不寫稽核」是真的，而且範圍比 Redis 故障更廣，**所有認證失敗都不會留下稽核紀錄**。已列為 `SECURITY_AUDIT.md` M-16，尚未修正。

## B-4　成本斷路器是全域的（2026-09-29 發現，2026-09-30 已修正）

- **原因**：`cost_circuit_state()` 只看全體的花費。雖然有記錄每個租戶的花費，但斷路器沒有使用。
- **影響**：一家事務所用量暴增，所有租戶都會被降級成便宜模型。
- **修正**：analyze 改用每租戶的斷路器（`COST_CIRCUIT_TENANT_DAILY_USD`）；全域門檻改為叢集的最後保險，預設從 100 提高到 1000。

## B-5　參考窗格看不到草稿引用的前案（2026-09-30 發現並修正）

- **原因**：`ReferencesPane` 用審查官引證的專利號（`cited_prior_art`）篩選檢索結果，但草稿的 `[GROUNDED_REF_n]` 是依核駁理由編號（`metadata.rejection_id` / `ref_index`，見 `lib/citations.js`）。兩者不一定重疊。
- **影響**：律師點草稿中的引用，右側參考窗格找不到對應的段落，無法核對來源；6 月實機截圖 `real_05` 就是「草稿有引用、右側顯示沒有命中」。對以「引用可核對」為核心的產品，這是信任訊號的破口。
- **怎麼發現**：前端改版時讀 `ReferencesPane.jsx` 與 `citations.js`，發現兩者的鍵不同。
- **修正**：新增 `hitsForRejection()`，依 `metadata.rejection_id` 取出該核駁的檢索結果（依 ref_index 排序），並標出哪些同時是審查官引證；舊版未標記的資料退回原本的篩選。測試 +2。
- **教訓**：同一份資料在兩個元件用不同的鍵對應時，要有一個共用函式當單一來源。

## D-1　稽核金鑰輪替已實作，文件仍寫「不支援」（2026-09-28 發現，2026-09-29 已修正）

- **原因**：`06e2b0e` 實作了金鑰輪替，隨後的 `22f9463` 也有修改 `CLAUDE.md`、`HANDOFF.md`，但沒有更新這一行。
- **影響**：接手的人會以為缺少這個功能，可能重做一次。
- **怎麼發現**：盤點「上次做到哪裡」時，把 commit 訊息和文件對照。
- **修正**：`CLAUDE.md` §3b、`HANDOFF.md` §28 第 6 點已改為「已支援」。
- **教訓**：功能落地的 commit，要同時搜尋文件中描述「未支援」的舊句子。

## D-2　`alignment.py` 門檻註解與常數不一致（2026-09-28 發現，2026-09-29 已修正）

- **原因**：常數從 0.20 調成 0.25 時，沒有同步更新註解。
- **影響**：閱讀程式碼的人會誤判目前的門檻。
- **修正**：註解改為 0.25。

## P-1　Claude 誤稱 mapping 加密是「全域一把金鑰」（2026-09-28 寫入，2026-09-29 更正）

- **原因**：寫 08 號文件的多租戶表時，沒有讀 `masking.py` 就下了結論。
- **實際情況**：已經是每租戶一把金鑰，由主金鑰以 HKDF 導出（`masking.py:937`）；真正的問題是「導出的金鑰刪不掉」，而不是「只有一把」。
- **影響**：設計討論的前提錯了一半，ADR-01 的論述差點建立在錯誤的現況上。
- **怎麼發現**：討論第三階段前，核對設定和程式碼時發現。
- **修正**：08 號文件的表格已更正，並在對話中說明。
- **教訓**：描述「現況」之前，先讀程式碼，不要憑印象。

## P-2　Glob 回報找不到 `tests/conftest.py`，但檔案存在（2026-09-29）

- **原因**：兩次 Glob（`tests/conftest.py`、`tests/**/conftest.py`）都回傳找不到，Claude 就據此判斷「不需要 conftest 的依賴」。
- **影響**：第一次跑 pytest 時，載入 conftest 失敗（缺 pydantic），多跑了一次。沒有其他損害。
- **怎麼發現**：pytest 的錯誤訊息。
- **修正**：補上 pydantic、fastapi、httpx 後重跑，通過。
- **教訓**：Glob 回傳「找不到」不代表檔案不存在，關鍵判斷要用 `Test-Path` 或直接讀檔確認。

## P-3　修正 H-10、M-14 時的小失誤（2026-09-30）

- 寫測試時以為 `auth.issue_token()` 接收 User 物件，實際上是 user_id 字串。第一次執行前讀程式碼時發現並修正。
- 對 pytest 加了 `--timeout=0`，但專案沒有安裝 pytest-timeout，指令直接報錯，重跑了一次。
- 第一次跑整套 unit 測試時沒有裝 `anthropic`，兩個測試檔在收集階段就中斷了整個執行。
- **教訓**：呼叫函式前先讀簽名；不確定的 pytest 參數不要加；跑整套測試前，先確認收集階段需要的套件都在。

## P-4　PowerShell 的 here-string 沒有送進 `git commit -F -`（2026-09-30）

- **原因**：在 PowerShell 裡把 `@'...'@` 接在 `git commit -F -` 後面，PowerShell 會把它當成命令列參數，不會送到 stdin。git 把訊息當成路徑，回報 `pathspec ... did not match`。
- **影響**：三組檔案都已加入暫存區，但沒有產生任何 commit；工作目錄沒有損失。
- **修正**：`git reset -q` 取消暫存後，改把訊息寫進暫存檔，用 `git commit -F <檔案>`。
- **教訓**：在 PowerShell 裡，多行 commit 訊息要用檔案，或把 here-string 用管線送進 `git commit -F -`。

## E-1　自動模式的安全檢查服務暫時故障（2026-09-28）

- **現象**：PowerShell 和 WebSearch 連續被擋，錯誤是「classifier gave no verdict」。這不是被拒絕，而是檢查服務沒有回應。
- **處理**：使用者切換權限模式後恢復。唯讀的工具（讀檔、搜尋程式碼）不受影響。

## E-2　這台機器沒有專案的執行環境（2026-09-29）

- **現象**：沒有專案 venv（系統只有 Python 3.14；CLAUDE.md 註明 3.14 缺部分 wheel），`patentmind-platform/frontend` 也沒有 node_modules。記憶體只剩約 3 GB（h2u 同時在跑）。
- **處理**：Python 測試用 uv 臨時環境（只裝 pytest、pydantic、fastapi、httpx）；前端測試把兩個檔案暫時複製到 poc repo（已有 node_modules）跑 vitest 和 eslint，跑完立刻刪除，並確認 poc 的 git status 沒有變動。刻意不建 junction（junction 曾經造成資料被清空）。
- **待辦**：資源空出後，在正式環境跑完整的 pytest、vitest、Playwright。
- **2026-09-30 更新**：用 uv 臨時環境（Python 3.14，加上 pymupdf、qdrant-client、anthropic 等，不含 torch）跑完整個後端測試：unit 1414 通過／23 略過，integration 264 通過／9 略過，0 失敗。缺 `fitz` 時會有 73 個 error，缺 `anthropic` 時會在收集階段中斷，都屬於環境問題。仍未跑：完整 vitest、Playwright、Postgres／Redis／MinIO 等需要容器的測試。

## E-3　TIPO「專利公開資訊查詢」系統說明頁讀取失敗（2026-09-28）

- **現象**：WebFetch 回傳「Socket is closed」。
- **影響**：網站使用條款（是否允許自動擷取）仍未確認，資料收集計畫卡在這一點。
- **待辦**：手動開啟網頁確認。

## E-4　MinIO 從 Docker Hub 移除映像檔，CI 的服務測試整個沒跑（2026-09-30）

- **現象**：推上 GitHub 後，CI 的 `backend-services` 在拉 `minio/minio:RELEASE.2025-04-22T22-12-26Z` 時失敗（pull access denied），後面的 Postgres／Redis／Qdrant 測試都沒有執行。
- **原因**：MinIO 自 2025-10 起改為只提供原始碼，並在 2026-09-11 到 14 日之間把 Docker Hub 上的 `minio/minio`、`minio/mc` 整個移除（多個開源專案同時回報）。
- **影響**：CI 無法驗證 Postgres 路徑，包括 H-10 稽核鏈的 advisory lock；`docker-compose.yml` 的 MinIO 服務也拉不到，稽核 WORM 封存（`ARCHIVE_BACKEND=s3`）在部署時沒有現成的映像檔可用。
- **暫時處理**：CI 的 MinIO 步驟改為 `continue-on-error`，S3 相關測試會自動略過，其他服務的測試照常執行。
- **待決定**：替換成支援 **S3 Object Lock** 的方案（需先查證各替代品是否真的支援 WORM），列入部署階段。

## 待確認的資料不一致

- RTX 3060 的顯存：HANDOFF 記錄 8GB，另一份記錄寫 12GB。
