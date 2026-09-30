# 前端改版計畫（CiteWall，2026-09-30 起）

> 決策（負責人 2026-09-30）：目的 = 面試展示 + 事務所實用兼顧；風格 = 專業沉穩（延續深藍 + 琥珀，
> 依 `docs/DESIGN_SYSTEM.md`）；範圍 = 全面重做（含資訊架構）；部署 = 公開 demo 網址 + 一行指令本機部署。
> 依據文件：`docs/DESIGN_SYSTEM.md`、`docs/UX_REVIEW_2026-06.md`、`docs/UX_RESEARCH.md`、`docs/ACCESSIBILITY_AND_I18N.md`。

## 不可違反的限制

- **案號不進網址**（CLAUDE.md §9）：選中的案件存在 app 狀態，不用 `/cases/<id>` 路由。
- 所有新增的後端 API：case ACL、角色閘門、一請求一稽核列（不變量 #4、#6）。
- 介面不出現內部決策編號（Q16、Q18 …），改放 tooltip 或文件。
- 信任訊號必須是真值（UX_REVIEW T1）；不過度宣稱。

## 階段與狀態

| 階段 | 內容 | 狀態 |
|---|---|---|
| 0 設計基礎 | token 整理、基礎元件統一、可及性（對比、focus、reduced-motion） | 完成（已看 CI 截圖） |
| 1 資訊架構 | 角色化導覽、首頁儀表板、案件列表、`GET /v1/cases` | 完成（e2e 通過） |
| 2 分析工作台 | 步驟式流程、1366×768 佈局、引用彈出視窗、移除內部編號 | 完成（e2e 通過） |
| 3 審閱與匯出 | 全案簽核進度、合併匯出 DOCX | 完成（e2e 通過） |
| 4 其他頁面 | 登入、稽核、案件登錄、手機版 | 程式完成，待 CI |
| 5 部署 | `docker compose up`（mock 模式）驗證；公開 demo（平台待定，建議 Cloud Run）；**MinIO 映像檔已從 Docker Hub 移除，需改用支援 S3 Object Lock 的替代方案**（見 FAILURE_LOG E-4） | 待做 |
| 6 說明書 | 自動截圖 → `docs/USER_GUIDE.md`、README 更新 | 待做 |

## 進度紀錄

- 2026-09-30：前端品牌改名 CiteWall（標題、圖示 CW、favicon、i18n、ics、e2e 選擇器）；vitest 76 passed、eslint 0 errors。
  注意：Playwright 視覺基準圖（`tests/e2e/__screenshots__`）因標題文字改變需重新產生。
- 2026-09-30：**階段 0**
  - `index.css`：語意化 token（`bg-surface*`、`text-fg*`、`border-line*`、status／confidential），用 `@theme inline`
    讓 `.dark` 覆寫能傳到 utility；`rounded-brand`（6px）、`shadow-elev-*`；reduced-motion、`text-autospace`、
    tabular-nums、列印樣式。舊的 shadcn hsl token 無人使用，已移除。
  - `components/ui/`：button、badge 改用 token；新增 card、field（Input/Textarea/Select/Label/Field）、tabs、
    overlay（Dialog/Popover/Tooltip/DropdownMenu，Radix）、page（Page/PageHeader/Stat/Kbd）。
  - 新增相依：`@radix-ui/react-{popover,dialog,tabs,tooltip,dropdown-menu}`。
- 2026-09-30：**階段 1**
  - 後端：`backend/gateway/case_summary.py`（案件摘要表，只存中繼資料）、`GET /v1/cases`（ACL 範圍、伺服器端
    機密等級、角色檢查在稽核框內）、`auth.case_scope()`；分析成功後寫摘要（失敗不影響分析）。
    測試 `tests/integration/test_case_list.py`（6）；後端全套 1684 passed。
  - 前端：`AppShell` 重寫（案件切換器、帳號選單含語言／主題、角色化導覽、路由晶片改讀伺服器機密等級、
    skip link、StackStatus 只給 IT／稽核）；新頁 `pages/Home.jsx`（儀表板）、`pages/Cases.jsx`（案件列表）；
    `lib/cases.js`（+8 測試）、`lib/currentCase.jsx`（目前案件只存記憶體）、`lib/i18nPages.js`。
    登入後：律師／助理 → `/home`、稽核 → `/audit`、IT → `/admin/cases`。
  - 已知待辦：
    - 分析頁的案號仍是自由輸入（階段 2 改成選單），目前只單向接收外框選的案件。
    - `backend/minimal` 沒有 `/v1/cases`，首頁在該模式會顯示錯誤。
    - e2e 測試需更新：導覽文字（分析 → 分析工作台、Audit → 稽核紀錄）、登入後落點（/home）、登出改在帳號選單。
    - 主 bundle 235 → 356 KB（gzip +37 KB），之後把頁面改為 lazy load。
- 2026-09-30：**階段 2**
  - 工作台改為兩種模式：設定（案件、OA 上傳／貼上、期限資料、遮罩預覽、用量）與審閱（結果頂部、核駁清單、審閱區、前案）。
    上方步驟列：輸入 OA → 確認遮罩 → 分析 → 逐句審閱 → 簽核匯出。
  - 版面：≥1536px 三欄；1280–1535px（含 1366×768）兩欄，前案改用對話框；<1280px 核駁清單改為橫向選單。
  - 新元件（`components/analyze/`）：Stepper、SetupPanel、ResultHeader、RejectionRail、RejectionReview、ReferencesPanel、
    RunningPanel；刪除 InputPane、DraftsPane、ReferencesPane、ReferenceModal。
  - `DraftEditor`：邏輯不變；引用改為可點開的彈出視窗（鍵盤／觸控可用，UX_REVIEW T7）；新增 `onProgress`，
    核駁清單顯示每條與全案的簽核進度（W1 的一部分）；焦點在引用按鈕時不再觸發整句快捷鍵。
  - 修正 **B-5**：前案面板改用 `hitsForRejection()`，草稿引用的段落一定看得到（+2 測試）。
  - 介面文字移除 Q 編號與中英混雜（`i18nPages.js` 覆寫舊值）；閘道判斷晶片放在結果頂部，一定可見。
  - 案件切換不再重新掛載工作台：保留已輸入的 OA 文字，清除舊結果。
  - 驗證：eslint 0 錯誤 0 警告、build 成功、vitest 86 passed。
  - e2e 待改：「計算依據 / Why」→「計算依據」、手機版三個分頁已移除、DraftsPane／ReferencesPane 相關註解與斷言、
    `/v1/cases` 需加入 mock_backend。
- 2026-09-30：**建立公開 repo** https://github.com/Washyu0826/citewall（描述 B 版、7 個 topics）；舊 repo
  `shin-lee-patent-rag` README 加上後續專案連結。CI：MinIO 映像檔已從 Docker Hub 移除，MinIO 步驟改為
  continue-on-error（FAILURE_LOG E-4）。
- 2026-09-30：**階段 3**
  - 後端 `POST /v1/oa/export_response`：整份申復書一次匯出 DOCX（沿用 export 的所有閘門；角色檢查在稽核框內；
    雜湊取自純文字，稽核只存統計與雜湊）；`signoff.assemble_response` / `build_response_docx`；測試 +5。
  - 前端 `ResponseExportCard`：每條核駁都決定完、至少接受一句、勾選確認、律師身分、非降級結果才能匯出；
    `DraftEditor.onProgress` 附帶逐句決定；`lib/responseExport.js`（+3 測試）。
  - 修正：進度必須在送出分析時清空，不能在 effect 裡清（子元件 effect 先執行，會把掛載時的回報蓋掉）。
  - vitest 89 passed。
- 2026-10-01：**e2e 改寫後第一次 CI**：桌面 61 passed；手機 40 passed、1 failed（FAILURE_LOG P-5／B-7）；
  視覺 13 個全是「還沒有基準圖」。用 CI 的 Linux 截圖做了第一次畫面檢查（本機資源不足，不跑 Playwright），發現並修正：
  - **B-6** 上方切換器顯示「尚未選擇案件」，但工作台和信任帶用 CASE-2025-001。
  - 深色模式的主要按鈕和頂列同色（navy-950），幾乎看不見 → 新增 `primary` token（深色 blue-700，白字 6.7:1），
    按鈕、步驟列、篩選鈕改用；頂列維持 `brand`。
  - 答辯策略段落直接顯示 `[GROUNDED_REF_1]` → 改用草稿同一個引用元件（`CitationText`）。
  - 首頁「即將到期」卡片被右欄撐高 → grid `items-start`；信心點點跟著標題放大 → 固定 `text-sm`。
- 2026-10-01：**階段 4**
  - 登入：改用 token 與 Card；角色、租戶分開顯示並在地化（原本是英文 `Attorney · tenant_a`）；每個身分的說明改寫成
    「能做什麼、不能做什麼」；magic link 移除中英並列。
  - 稽核：頁首標題、動作按鈕（重新整理、立即驗證）；三個 Stat；表格欄位在地化、移除 Q 編號、時間改成
    `YYYY-MM-DD HH:mm:ss` 不換行；閘道判斷改為在地化標籤 + ✓/✗，並補上螢幕報讀文字（原本只有圖示）。
  - 案件登錄：新增表單改用 Field；停用改用對話框確認（原本 `window.confirm`）；右欄說明「預設一律機密」與萬用規則；
    **B-7** 格式不對的回應不再讓整個 app 當掉（`normalizeRegistry`，+3 測試）。
  - 手機版：`admin_cases` e2e 取消「只測桌面」，兩個專案都跑。
  - 驗證：eslint 0、vitest 92 passed、build 成功。
