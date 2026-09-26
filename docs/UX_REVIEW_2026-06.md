# UX Review — PatentMind 前端實作審查（2026-06-12）

> 範圍：`frontend/src/` 全部元件（以 DraftEditor 三態簽核重構後的現檔為準）對照既有五份 UX 研究文件
> （`UX_RESEARCH.md`、`UX_PERSONA_JOURNEYS.md`、`DESIGN_SYSTEM.md`、`ACCESSIBILITY_AND_I18N.md`、`AI_TRANSPARENCY_UX.md`）
> 與 `docs/screenshots/delivery/real_*.png` 實機畫面。
>
> **方法與誠實聲明**：本報告無真實使用者測試數據。每項發現標注證據等級——
> **[程式碼]** = 有具體檔案行號可指認的事實；**[推導]** = 由 CSS/版面數學推算、未實測；
> **[推測]** = 依 persona 文件或業界經驗推論的假設，需 `UX_PERSONA_JOURNEYS.md` §7 的訪談驗證。
>
> 嚴重度定義：**P0** 阻礙使用或會直接摧毀信任；**P1** 顯著摩擦／與已定原則矛盾；**P2** 打磨。
> 工作量：**S** < 1 天、**M** 1–3 天、**L** > 3 天。

---

## 0. 總評

落地品質整體高於同期 POC 水準：三欄佈局、claim tree、verifier banner、三態逐句簽核（接受/排除/撤銷 + A/E/X/U 快捷鍵）、引用跨欄連動、深色模式、雙 live-region toast，都是研究文件 spec 過後真的做出來的。**本次審查最重要的結論是：剩下的問題多數不是「缺功能」，而是「信任訊號的最後一哩不誠實或不一致」**——對一個把 trust 當賣點的法律產品，這比缺功能更危險。三個代表：政策 chips 寫死 `true`（T1）、降級模式仍可簽核匯出（T2）、非稽核角色看到「紀錄已驗證」但其實沒驗（T4）。

---

## 1. 律師工作流效率

### W1 — 多核駁案件必須逐 rejection 簽核、逐 rejection 匯出，無全案合併
- **嚴重度**：P1 **[程式碼]**
- **位置**：`frontend/src/components/analyze/DraftsPane.jsx`（一次只渲染 `activeRejection` 的一個 `DraftEditor`）；`frontend/src/components/DraftEditor.jsx:150`（`api.exportDraft` 以單一 `rejection_id` 為單位）；`downloadTxt` 產出 `${caseId}-${rejectionId}.txt`
- **問題**：實務上一份 OA 答辯書是**一份文件**回應全部核駁理由。現在 3 個 rejection = 3 次簽核流程 + 3 個 .txt，律師還得自己在 Word 裡拼裝，且各 rejection 的簽核狀態互相不可見——切到 §102 分頁後，§103 簽到哪了完全沒指示（`DraftEditor` 的 `lines` state 在 `initialDraft` 變更時整個 reset，分頁切換間靠 React 保留，但 UI 無進度匯總）。
- **建議**：
  1. `DraftsPane` 的 `RejectionTabs` 每個 tab 加簽核進度點（pending=amber dot / 全決定=emerald check），資料就是各 `DraftEditor` 的 `decidedCount`——需把 lines state 提升到 `Analyze.jsx` 以 `rejection_id` 為 key 的 map。
  2. 新增「匯出全案答辯書」按鈕（放 `ResultSummaryBar` 右側），disabled 直到所有 rejection 都簽核完；後端 `exportDraft` 接受 `segments` 按 rejection 分組的 payload，產一份合併文件。
- **工作量**：M

### W2 — 匯出格式只有 .txt，沒有 DOCX / USPTO 劃線格式 / TIPO 修正頁
- **嚴重度**：P1 **[程式碼]**
- **位置**：`DraftEditor.jsx:171-182`（`downloadTxt`：`Blob([...], 'text/plain')`）
- **問題**：`UX_RESEARCH.md` §5 #4 列為 must-have、`UX_PERSONA_JOURNEYS.md` Journey B stage 9 的 watershed。.txt 是律師**無法直接使用**的格式——後續還有 25 分鐘的「format tax」（persona 文件實測描述）。本產品最後一步把前面省下的時間還回去了一半。
- **建議**：後端用 `python-docx` 出 DOCX（gateway 已有 export endpoint，加 `format=docx|txt` 參數）；claim 修正文字支援 USPTO underline/strikethrough 與一般 track-changes 兩種 view（`UX_RESEARCH.md` §4.3 已有 spec）。前端只是把「下載 .txt」換成格式下拉。
- **工作量**：M（後端為主）

### W3 — 分析進度面板的階段計時寫死舊模型的時間，與實機不符
- **嚴重度**：P1 **[程式碼]**
- **位置**：`DraftsPane.jsx:349-357`（`STAGES`：`parse untilSec:60、draft untilSec:200、verify untilSec:290` — 註解明寫「observed on CPU llama3.1:8b」）；`frontend/src/lib/i18n.js` `analyze.drafts.running_note`（「地端 llama3.1:8b……約 5–7 分鐘」）
- **問題**：CLAUDE.md §6 實機鏈路是 Dify → qwen2.5:7b，全鏈路 25–28 秒。實際跑時進度永遠停在「解析 OA」階段就結束了——**進度指示器從頭到尾都在說謊**，而文案還承諾 5–7 分鐘。對「latency 是 churn 風險」的林冠廷 persona，一個不準的進度條比沒有進度條更傷。
- **建議**：短期（S）：把 `STAGES` 的秒數改為可由 env/`import.meta.env` 注入的 profile，並把 `running_note` 兩個語系的模型名與時間改成 qwen2.5:7b / 約 30 秒。中期（M）：gateway orchestrator 在每階段完成時寫 stage event，前端輪詢或 SSE 顯示真實階段——audit row 已記錄各階段，資料存在。
- **工作量**：S（短期）/ M（真實進度）

### W4 — 1366×768（事務所常見筆電）下三欄擁擠
- **嚴重度**：P2 **[推導]**（未實測，由 CSS 推算）
- **位置**：`Analyze.jsx:272`（`xl:grid-cols-[3fr_4fr_3fr]`，xl=1280 即啟用三欄）；`AppShell.jsx:421`（NavRail 展開 `sm:w-60` = 240px）；`DraftEditor.jsx:454`（IconAction 文字標籤 `hidden sm:inline`，640px 以上即顯示）
- **推算**：1366 − 240（rail）= 1126px 給三欄 → 中欄（草稿）約 450px，再扣行號欄 24px、padding、右側「接受/改寫/排除/撤銷」四顆帶中文標籤的按鈕群（約 150–180px），**實際文字行寬剩約 230–260px**，中文約 16–18 字就折行。垂直方向：768 − TopBar 56 − TrustBand ~40 − ResultSummaryBar ~36 − sticky footer ~32 − pane header ~40 = 工作區約 560px。
- **建議**：
  1. NavRail 在 `< 2xl`（1536px）預設 `collapsed`（改 `AppShell.jsx:56` 的初始值為依視窗寬判斷），省 176px。
  2. `IconAction` 文字標籤改 `hidden 2xl:inline`，1366 筆電上只顯示 icon（已有 `aria-label` + `title`，可及性不退步）。
  3. sticky footer（StackStatus）對 attorney/paralegal 角色預設摺疊成單一小圖示，點開才展開四燈（demo 價值對 IT/稽核角色才存在，見 M3）。
- **工作量**：S–M

### W5 — 無 Cmd/Ctrl+K 命令面板與全域鍵盤導覽
- **嚴重度**：P2 **[程式碼]**（全 codebase 無任何全域 keydown 處理；`Grep` 證實快捷鍵只存在於 DraftEditor 行內）
- **位置**：缺；spec 已完整寫在 `docs/ACCESSIBILITY_AND_I18N.md` §3.3/§3.5
- **問題**：UX_RESEARCH 定為 2026 業界 baseline（Harvey/Linear）；林冠廷 persona（Vim 使用者）的 churn 條件。DraftEditor 的 A/E/X/U 證明團隊會做快捷鍵，但進到那一行之前全是滑鼠。
- **建議**：v1 範圍收斂：`Cmd/Ctrl+K` 開 palette（項目：切到 Analyze/Audit/Cases、切語言、切主題、focus OA 輸入框、focus 第 N 個 rejection tab）；`Cmd/Ctrl+1/2/3` focus 三個 pane。**務必加 `e.isComposing` guard**（見 A2）。
- **工作量**：M

### W6 — 批次處理多核駁「案件」層級不存在
- **嚴重度**：P2 **[推測]**（依 persona 文件，無使用者數據）
- **位置**：`App.jsx:147-191`（`/cases` 是 placeholder）
- **問題**：陳麗華 Journey A 的「3 items need your sign-off」inbox、deadline 批次視圖都掛在 cases 路由上。目前一次只能處理一份 OA、結果存在 React state、重新整理即消失（`Analyze.jsx:87` `useState(null)`）——連單案的工作都不能中斷恢復。
- **建議**：Phase 4 範圍，但**先做最小持久化**：analyze 結果以 `case_id` 為 key 存 sessionStorage/IndexedDB，重新整理後可恢復，這是 S 級工作量、立即消除「分析 28 秒後誤按 F5 全沒了」的災難路徑。
- **工作量**：S（持久化）/ L（完整 cases）

### W7 — 引用 pill 點擊在無對應卡片時靜默失敗
- **嚴重度**：P2 **[程式碼]**
- **位置**：`frontend/src/components/analyze/ReferencesPane.jsx:33-34`（`match === -1` 直接 `return`，無任何回饋）；且 `hits` 只包含 **active rejection** 的 `cited_prior_art`（line 27-28），pill 引用的專利若屬於別的 rejection 就找不到
- **建議**：match 失敗時改在全部 `related_prior_art` 找；找到但屬於別的 rejection → 自動 `setActiveRejectionId` 切過去再捲動；真的沒有 → `toast.info('此引用不在目前檢索結果中')`。
- **工作量**：S

---

## 2. 信任與透明 UX（對照 `docs/AI_TRANSPARENCY_UX.md`）

### T1 — ResultSummaryBar 的政策 chips 是寫死的常數，不是真實 policy_decisions
- **嚴重度**：**P0**（信任失真）**[程式碼]**
- **位置**：`Analyze.jsx:338-347`：
  ```js
  const policyChips = useMemo(() => [
    ['authz_passed', true], ['rate_limit_passed', true], ['quota_passed', true],
    ['cache_hit', result.cost_meta.cache_hit], ['circuit_open', false],
  ], [result]);
  ```
- **問題**：五顆 chip 只有 `cache_hit` 讀真值，其餘寫死。語意上「請求成功 = 閘門必過」勉強說得通，但這正是 DESIGN_SYSTEM §5.6 警告的 ornamental badge——AuditView 同一批欄位讀的是後端真實 `policy_decisions`（`AuditView.jsx:234`），同一產品內一真一假。採購端的 Marcus persona 看 source 或 devtools 一眼就會發現，「trust signaling everywhere」整個敘事反噬。
- **建議**：後端 `AnalysisResponse` 若已含 `policy_decisions`（audit row 有），直接透傳並改讀；沒有就加欄位。前端改動只有把字面常數換成 `result.policy_decisions?.[k]`。
- **工作量**：S

### T2 — 降級（DEGRADED）結果仍可逐句簽核並匯出
- **嚴重度**：P1 **[程式碼]**
- **位置**：`DraftsPane.jsx:78`（`isDegraded` 只用於 banner）；banner 文案自己說「不可作為實際法律分析使用」，但下方 `DraftEditor` 的簽核與匯出完全照常（`canExport` 只看 role）
- **問題**：警示與行為矛盾。一個 mock 引擎產的草稿被律師簽核、寫進 audit chain、匯出成檔，是法律與稽核上最不該存在的路徑。
- **建議**：`isDegraded` 傳入 `DraftEditor` 為 `exportBlocked` prop：匯出鈕 disabled + 理由文案「降級結果不可簽核匯出」；逐句標記仍可操作（讓律師先讀），但 sign-off checkbox 鎖定。後端 export endpoint 同步檢查 `model` 含 `-DEGRADED-` 時回 409（雙保險，符合 repo「不靜默吞掉」慣例）。
- **工作量**：S

### T3 — Verifier 紅牆「看得見、擋不住」：含 [CITATION_REMOVED] 的句子可直接接受並匯出
- **嚴重度**：P1 **[程式碼]**
- **位置**：`DraftEditor.jsx:137-141`（`doExport` 閘門只檢查 `reviewed`、`pendingCount`、`acceptedCount`）；`DraftsPane.jsx` `VerificationBanner`（純顯示）；`CitationHighlighter:581-589` 把 `[CITATION_REMOVED]` 渲染成紅 chip 但無互動
- **問題**：違反 `AI_TRANSPARENCY_UX.md` §10 原則 3「verifier disagreement is never silent——紅 ribbon 應 block sign-off，直到 re-ground / remove / 明示 override 並留紀錄」。現在律師按 `A` 一鍵接受一句含被移除引用的殘句，匯出文件裡會出現字面 `[CITATION_REMOVED]`。
- **建議**：`splitIntoLines` 時偵測句內含 `[CITATION_REMOVED]` → 該行禁用「接受」（A 鍵與按鈕都擋），只能「改寫」或「排除」；行旁顯示 rose 提示「引用已被驗證器移除——請改寫或排除此句」。這同時自然滿足「override 必留痕」：改寫後 provenance 變 `attorney_edited`。
- **工作量**：S–M

### T4 — 非稽核角色的鏈驗證 chip 顯示「紀錄已驗證」但從未驗證
- **嚴重度**：P1 **[程式碼]**
- **位置**：`AppShell.jsx:311-315`（`canCallAudit === false` 時 label 仍取 `t('shell.audit_chip.ok')`，僅顏色變灰）
- **問題**：attorney/paralegal 登入即看到「紀錄已驗證」字樣，但 verify query `enabled: false`（line 67-70）。灰色不足以傳達「未驗證」；文字直接過度宣稱。
- **建議**：i18n 加 `shell.audit_chip.enabled: '稽核鏈啟用中' / 'Audit chain active'`，非稽核角色用此字串；tooltip 改「鏈驗證由稽核角色執行——最近一次結果見稽核頁」。三行修改。
- **工作量**：S

### T5 — 裸數字信心分數，違反「No single-number confidence」原則
- **嚴重度**：P2 **[程式碼]**
- **位置**：`DraftsPane.jsx:192`（「信心 87%」）、`:230`（「驗證器信心 {{pct}}%」）、`ReferencesPane.jsx:155-157`（`score 0.834`）
- **問題**：`AI_TRANSPARENCY_UX.md` §10 原則 2 + F4：裸數字 prime 接受、不給下一步行動。87% 對律師無操作意義。
- **建議**：檢索分數改三檔 pips（`●●●` ≥0.80 / `●●○` 0.60–0.80 / `●○○` <0.60，門檻照 §3 映射表），tooltip 寫對應行動（「建議閱讀原文段落」）；verifier 信心併入 VerificationBanner 的色帶語意，不再單列百分比。保留 raw score 於 tooltip 供進階使用者。
- **工作量**：S–M

### T6 — 缺「Show reasoning」揭示面板（retrieval trace / skipped hits / 各步模型）
- **嚴重度**：P2 **[程式碼]**（未實作；spec 在 `AI_TRANSPARENCY_UX.md` §4）
- **位置**：應落在 `DraftsPane.jsx` `RejectionDetail` 草稿下方
- **問題**：這是透明文件三大 ship 項之一，也是 ABA 512 監督義務（哪個模型產哪段）的落點。後端 `verifier_model` 已透傳（`VerificationBanner` 用到），但 parse/draft 的模型歸屬與「檢索到但沒用」清單沒有 UI。
- **建議**：預設收合的 `▸ 顯示推理過程` disclosure：rejection 規則、top-N 檢索 hits（rank/score/selected|skipped）、各步模型。後端需在 response 加 skipped 原因欄位——前端先做「有什麼顯示什麼」的容錯版。
- **工作量**：M（前端 S + 後端欄位）

### T7 — 引用 pill 的摘錄只放在原生 `title` 屬性：鍵盤、觸控、螢幕報讀器都拿不到
- **嚴重度**：P1 **[程式碼]**（兼可及性與信任：這是 Journey A 的 watershed moment）
- **位置**：`DraftEditor.jsx:568`、`:576`（`title={...patent_no / section / text}`）
- **問題**：陳麗華在 iPad 上 tap 引用 pill 想看 Tanaka 原文段落——`title` tooltip 在觸控裝置**永遠不會出現**，點擊行為是跳去右欄（行動版還整頁切到 refs tab），「<300ms 看到引文」的信任時刻不存在。鍵盤 focus 同樣看不到摘錄；NVDA 對 `title` 的播報不可靠。
- **建議**：pill 改 popover 模式：focus/hover/tap 開啟（`role="tooltip"` + `aria-describedby`、Esc 關閉、tap-outside 關閉），內容 = 專利號 + section + 前 240 字摘錄 + 「開啟全文」與「在右欄定位」兩個 action（後者沿用現有 `onCitationClick`）。共用 `ReferenceModal` 已有的 native `<dialog>` 模式或輕量 popover 即可，不必引 radix。
- **工作量**：M

### T8 — 律師改寫句子後，原 AI 引用 pill 原樣保留、不重新驗證
- **嚴重度**：P1 **[程式碼]**
- **位置**：`DraftEditor.jsx:81-99`（`commitEdit` 只改 `source`/`edited_from`/`text`，引用 token 隨文字字串保留）
- **問題**：`AI_TRANSPARENCY_UX.md` §2.9/§8 明列的 Mata v. Avianca 結構性風險：律師把句子的主張改掉、但 `[GROUNDED_REF_2]` 還掛在句尾，匯出後引用背書的是一句驗證器沒看過的話。
- **建議**：`commitEdit` 時 diff 新舊文字：若引用 token 仍在但周邊文字實質變更（去 token 後 similarity 低於門檻，簡單版：字元差異 > 30%），把該 pill 渲染為 amber「引用未對改寫後內容重新驗證」狀態，提供「重新驗證」按鈕呼叫後端 verify endpoint（已存在）。
- **工作量**：M

### T9 — EN 信任 tooltip 洩漏內部實作字串；zh-TW 版過簡，雙語不對等
- **嚴重度**：P2 **[程式碼]**
- **位置**：`i18n.js:375-385`（EN：「(CLAUDE.md §4 invariant)」「data/redaction_mapping.db — NEVER leaves on-prem (CLAUDE.md §9)」）vs zh-TW（`:53-59`，一句話帶過）
- **建議**：兩語系統一為使用者語言：「遮罩對應表僅存於貴所主機（on-prem），系統不會外傳」等；內部文件代號移除。EN 的具體性（提到 mapping db 在地）其實是好的信任素材——zh 版應補齊到同等資訊量，而不是 EN 砍到 zh 的程度。
- **工作量**：S

### 資訊層級總評（過度曝光 vs 不足）
- **不足**：上述 T1–T8——該硬的牆（verifier、degraded）只做了視覺層。
- **過度**：每頁常駐的信任 chrome 偏多——TrustBand 三 chip + tenant chip + TopBar chain chip + footer 四燈，垂直吃掉約 70–80px。對 Marcus 是賣點、對天天用 8 小時的王俊豪是噪音。建議：TrustBand 維持（DESIGN_SYSTEM P1 要求），但 footer StackStatus 角色化（見 W4-3 / M3），(Q13)(Q16)(Q18) 這類**內部決策編號出現在正式 UI**（`InputPane.jsx:230`「配額 (Q18)」、`DraftsPane` 簽核標籤「Q16」、AuditView「(Q13)」）應移除或移到 tooltip——使用者不知道 Q18 是什麼，看起來像沒清乾淨的工程註記。**[程式碼]** P2 / S。

---

## 3. 可及性

### A1 — 對比違規：`text-slate-400`（2.84:1）大量用於可讀內容
- **嚴重度**：P1 **[程式碼]**（DESIGN_SYSTEM §2.2 明文：slate-400 是 print-only token；ACCESSIBILITY §1.2 列為 AVOID）
- **位置**（非窮舉）：
  - `DraftEditor.jsx:239`（行號 `text-slate-400`）、`:211`（快捷鍵提示 `text-2xs text-slate-400` — 11px + 2.84:1 雙重失格）、`:305`（「檢視 AI 原文」連結）
  - `AppShell.jsx:142`（footer 文字 `text-2xs text-slate-400 dark:text-slate-500`；深色 slate-500 on slate-900 ≈ 4.0:1，11px 下不足）
  - `Analyze.jsx:422` 起（deadline 明細 `dt` 全為 slate-400）
  - `InputPane.jsx:348`（budget 表頭）
- **建議**：機械式替換規則——凡承載資訊的文字：淺色 `text-slate-400 → text-slate-500`（4.79:1）、深色 `dark:text-slate-500 → dark:text-slate-400`（5.3:1）；純裝飾（chevron、分隔符）可留。一次 PR 全 repo grep 處理，並在 eslint/stylelint 加 ban 規則（DESIGN_SYSTEM §10.4 已 spec）。
- **工作量**：S

### A2 — IME composition guard 全面缺失：注音輸入中按 Esc 會關閉編輯器、丟失組字
- **嚴重度**：P1 **[程式碼]**（ACCESSIBILITY §5.9 自評為「TW 使用者最常見 bug 來源」，目標用戶用微軟新注音/嘸蝦米）
- **位置**：
  - `DraftEditor.jsx:247-250`（編輯 textarea 的 `Escape` → `setEditingIdx(null)`、`Ctrl+Enter` → `commitEdit`，皆未檢查 `e.isComposing`）——選字中按 Esc 應取消組字，現在會直接關掉編輯框，**未儲存的改寫內容消失**
  - `DraftEditor.jsx:118-135`（`lineKeyDown` 的 A/E/X/U 單鍵）——行本身非輸入框風險較低，但若未來加行內搜尋就會踩
- **建議**：所有 keydown handler 第一行加 `if (e.isComposing || e.keyCode === 229) return;`。建議抽成 `lib/keyboard.js` 的 `guardIme(handler)` 包裝器，未來 Cmd+K（W5）直接複用。
- **工作量**：S

### A3 — ClaimTree 未用 tree 語意與 roving tabindex；逐節點 tab stop
- **嚴重度**：P2 **[程式碼]**
- **位置**：`ClaimTree.jsx:190-200`（每個 rejected row `tabIndex={0}` + `role="button"`；clean/cascade 列完全不可聚焦）
- **問題**：ACCESSIBILITY §3.2 明定 roving tabindex（「one tab-stop per node 在 30+ claims 時不可用」）。且 clean 列不可聚焦 = 螢幕報讀器用戶無法逐項聽完整棵樹（`aria-level`、`aria-posinset` 全缺）。
- **建議**：容器 `role="tree"` + `aria-label`，每列 `role="treeitem"` + `aria-level={node.depth+1}`，↑/↓ 移動 focus、Enter/Space 觸發、整棵樹單一 tab stop。狀態（rejected/cascade/clean）放進 `aria-label` 文字，不只靠顏色（顏色 + chip 目前已有，這點及格）。
- **工作量**：M

### A4 — 兩處 tab 元件不符 APG tabs 模式
- **嚴重度**：P2 **[程式碼]**
- **位置**：`Analyze.jsx:476-505`（MobileTabBar：有 `role="tab"`/`aria-selected` 但無 `aria-controls`/`id` 配對、無 ←/→ 鍵盤導覽）；`DraftsPane.jsx:131-155`（RejectionTabs：純 button，完全無 tablist 語意——這是多核駁案的**主導覽**）
- **建議**：兩者補 `role="tablist"`、`aria-controls`、←/→/Home/End roving；RejectionTabs 每個 tab 的 accessible name 加上核駁類型全名與 claims（現在只有「§103 claims 1,2,3」的視覺縮寫）。
- **工作量**：S

### A5 — 無 skip-link；`<main>` 無 id；三欄無 region 標記
- **嚴重度**：P2 **[程式碼]**
- **位置**：`AppShell.jsx:122`（`<main className="min-w-0 flex-1">`）；`Analyze.jsx:246/272` 的兩個 `<main>`（**一頁兩個 main landmark**，AppShell 已有一個，巢狀 main 本身是違規）
- **建議**：Analyze 內層兩個 `<main>` 改 `<div>`；AppShell `<main id="main">` 前加 `sr-only focus:not-sr-only` skip-link；三 pane 各加 `role="region"` + `aria-label={t('analyze.pane_*')}`（i18n key 已存在）。
- **工作量**：S

### A6 — `prefers-reduced-motion` 未處理
- **嚴重度**：P2 **[程式碼]**
- **位置**：`animate-spin`/`animate-pulse` 多處（DraftsPane RunningPanel、Skeleton）；`ReferencesPane.jsx:38`（`scrollIntoView({behavior:'smooth'})`）
- **建議**：`index.css` 加全域 `@media (prefers-reduced-motion: reduce) { *, ::before, ::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; scroll-behavior: auto !important; } }`；`scrollIntoView` 的 behavior 改讀 `matchMedia` 結果。
- **工作量**：S

### A7 — 10–11px 字級（text-2xs/3xs）承載需閱讀的內容，主用戶 45–55 歲
- **嚴重度**：P2 **[程式碼]**
- **位置**：快捷鍵提示（`DraftEditor.jsx:211-213`）、SHA-256 hash（`:507`，text-3xs=10px）、magic token（`Login.jsx:272`）、StackStatus 全部、TrustBand tenant chip
- **建議**：分級規則——使用者**需要讀懂才能操作**的（快捷鍵提示、簽核 hint）至少 `text-xs`(12px)；可複製的識別碼（hash、token）可留小字但必須配「複製」按鈕（hash 目前 10px 又不能一鍵複製，等於要求肉眼抄 64 字元）。
- **工作量**：S

### A8 — 行動版（< sm）完全無法切換語言與主題
- **嚴重度**：P2 **[程式碼]**
- **位置**：`AppShell.jsx:248`（LanguageToggle `hidden ... sm:flex`）、`:275`（ThemeToggle `hidden ... sm:inline-flex`）
- **建議**：< sm 收進 TopBar 右側的單一 overflow 選單（⋯）而非直接消失。
- **工作量**：S

### 已做對、不要退步的（鍵盤/SR 正面清單）
- 三態簽核的動作鈕**常駐顯示**（opacity-60 → hover/focus 100%）而非 hover-only——觸控與鍵盤皆可用（`DraftEditor.jsx:321`）。
- 逐行 `tabIndex=0` + `aria-label` 含行號與全文；progressbar 帶 aria-value*；決定計數 `aria-live="polite"`。
- toast 雙 live-region（assertive/polite 分流，`toast.jsx:71-81`）是教科書級實作。
- `ReferenceModal` 用原生 `<dialog>` 取得免費 focus trap + Esc。
- 語言切換有 `aria-pressed`；`document.documentElement.lang` 與 i18n 同步（`zh-Hant`），`index.html` 預載 script 防 FOUC/錯誤 lang。

---

## 4. i18n 品質

### I1 — zh-TW 資源內嵌雙語字串，因 e2e 測試以文案為 selector
- **嚴重度**：P1 **[程式碼]**
- **位置**：`i18n.js`——`analyze.pane_input: '輸入 OA / Input'`、`pane_drafts/pane_refs`、`signoff.review_each: '我已逐項確認 / I have reviewed each item'`、`verifier.*` 整組（註解明寫「e2e 的斷言、keep verbatim」）、`magic.link_cta`、`landing.tagline` 的全形空白拼接
- **問題**：語言切換功能存在，但 zh-TW 介面到處殘留英文尾巴、EN 介面殘留中文（`upload.element_table_title: 'Figure elements / 圖式元件'`），讓「i18n 完成」的宣稱在第一眼就破功；對陳麗華這類 persona 是「不夠正式」的訊號。
- **建議**：e2e 改鎖 `data-testid`（codebase 已大量使用 testid，慣例現成），然後把所有 `A / B` 式字串拆成單語。一次 PR：i18n.js 清理 + `frontend/tests/e2e` 同步改 selector。
- **工作量**：S–M（風險在 e2e 改寫，Playwright 73 條全跑一輪）

### I2 — 法律術語半翻譯與不一致
- **嚴重度**：P2 **[程式碼]**（術語正確性部分屬 **[推測]**，建議由 TW 專利師審校）
- **位置與建議對照表**：

| 現況 | 位置 | 建議 | 理由 |
|---|---|---|---|
| `預覽 redaction` | `i18n.js analyze.input.preview_redaction` | `預覽遮罩結果` | 半翻譯；redaction 非律師日常詞 |
| `Examiner 論點` | `analyze.drafts.examiner_argument` | `審查意見（Examiner）`；TW 案件用「審查委員意見」 | TIPO 用語為審查委員；USPTO 慣稱審查官 |
| `nav.audit: 'Audit'`（zh） | `i18n.js:21` | `稽核` | 同檔 `role_badge.auditor` 已譯「稽核」，自相矛盾 |
| `法務助理`（paralegal） | `shell.role_badge.paralegal` | `專利工程師／助理` | persona 文件明示 TW 事務所層級是「助理工程師」，「法務助理」是公司法務的用語 |
| `RAG retrieval (Q6, Q7, Q14 grounding)` | `analyze.refs.rag_title`（zh 也用英文） | `相關先前技術（系統檢索）` | RAG/Q 編號是工程語言 |
| `cache 命中`相關（`Cache hit`/`Fresh` 硬編碼） | `Analyze.jsx:51-57 SECURITY_BADGE` | 進 i18n：`快取命中`/`即時產生` | 見 I4 |
| EN `landing.value_classify` 寫 TW 法條（§22-2, §26-2） | `i18n.js:495` | 兩語系一致：各自舉當地法條或都不舉 | EN 使用者看 TW 條號困惑；zh 版反而沒列 |

- **工作量**：S（文案）+ 專利師審校半天

### I3 — 硬編碼未進 i18n 的英文字串
- **嚴重度**：P2 **[程式碼]**
- **位置**：`DraftsPane.jsx:84-86`（meta 行 `request: … · model: … · tokens …`）、`:189`（`Claims {…}`）、`RejectionTabs:148`（`claims {…}`）、`ClaimTree.jsx:215`（badge `indep`）、`Analyze.jsx:51-57`（SECURITY_BADGE 五組標籤）、`Login.jsx:10-39`（`'Attorney · tenant_a'` 等角色行）、`AppShell.jsx:385`（trust band `tenant` 字樣）
- **建議**：全部入 `i18n.js`；`indep` 改 `獨立項`/`indep.`。
- **工作量**：S

### I4 — 複數處理用 "(s)" 而非 i18next 複數鍵
- **嚴重度**：P2 **[程式碼]**
- **位置**：`i18n.js` EN `verifier.removed_title: '{{count}} citation(s) removed'`、`undecided_hint: '{{count}} sentence(s)…'`
- **建議**：改 `_one`/`_other` 鍵（i18next 原生支援，zh-TW 只需 `_other`）。
- **工作量**：S

### I5 — 日期呈現
- **嚴重度**：P2 **[程式碼]**
- **位置**：`Analyze.jsx:358`（`toLocaleDateString('zh-TW')` → `2025/8/12` 斜線格式）
- **建議**：期日是「算錯即喪權」的欄位，統一 `YYYY-MM-DD`（ISO，兩語系皆無歧義；ACCESSIBILITY §6.3 規則「never slash dates」）或 zh 用 `2025 年 8 月 12 日`。沿用一個 `lib/format.js` 集中（該檔尚不存在，doc §7.1 已 spec）。
- **工作量**：S

### I6 — 登入頁無語言切換
- **嚴重度**：P2 **[程式碼]**
- **位置**：`Login.jsx`（LanguageToggle 只在 AppShell，登入前不可達；首次造訪的 EN 使用者只能看 zh-TW）
- **建議**：Login header 右側放同一顆 LanguageToggle（抽成共用 export，`AppShell.jsx:223` 的元件直接搬出來用）。
- **工作量**：S

---

## 5. 行動 / 平板體驗（< xl 單欄 + tab）

### M1 — 平板簽核流程基本可用，但「引文查驗」在觸控上斷裂
- 同 **T7**——iPad 是陳麗華 persona 的主要簽核裝置，引用 pill 的 `title` tooltip 在觸控上不存在、tap 直接跳頁。這是行動體驗最大的單點。**[程式碼]**

### M2 — 手機上固定 64px 側欄 + 常駐 sticky footer 擠壓 360–390px 視窗
- **嚴重度**：P2 **[程式碼 + 推導]**
- **位置**：`AppShell.jsx:421`（`w-16` 在 < sm 仍常駐，註解說是為了 e2e 在 iPhone X 上要有 Audit 鈕）；`AppShell.jsx:139`（footer `sticky bottom-0`）
- **推算**：390px（iPhone 14）− 64 = 326px 內容寬；TrustBand chips `flex-wrap` 在窄幅下疊 2–3 行，加 footer，**首屏內容不到 60%**。
- **建議**：< sm 把 NavRail 改為底部 tab bar（Analyze/Cases/Audit 三鈕，44×44 觸控目標順便達標 WCAG 2.5.8），footer 併入其中一格或移除；TrustBand 在 < sm 收成單行可橫捲。e2e 的「iPhone X 上可點 Audit」契約由底部 tab bar 繼續滿足。
- **工作量**：M

### M3 — StackStatus 每 30 秒對三個外部 port 發 no-cors probe
- **嚴重度**：P2 **[程式碼]**
- **位置**：`StackStatus.jsx:27-49`（probe `127.0.0.1:8011` / `localhost:18080` / `localhost:8088`，`POLL_INTERVAL_MS = 30s`）
- **問題**：在任何非本機 demo 的部署（含行動裝置開啟）這三個 probe 必失敗——白耗電、console 噪音、且四燈永遠灰=資訊量零。這是 demo 元件混進產品 chrome。
- **建議**：`VITE_SHOW_STACK_STATUS` flag 控制渲染（預設 off，demo script 開）；或僅 it_admin/auditor 角色顯示。
- **工作量**：S

### M4 — 行動版 768–1024（iPad 直立）為 tab 模式：可用性可，但缺 pane 間快速往返
- **嚴重度**：P2 **[推測]**
- **問題**：簽核時需要「草稿 ↔ 引證」高頻往返，tab 切換每次整頁重繪心智成本高。citation pill 點擊已會自動切到 refs（`Analyze.jsx:108-110`），但**回程**沒有對應捷徑（看完引文要手動點回草稿 tab，且草稿捲動位置因 pane 重掛而保留與否未驗證——`mobileTab` 切換是條件渲染，state 在但 DOM 捲動位置會丟）。
- **建議**：refs pane 在「由 pill 觸發進入」時頂部顯示「← 返回草稿」浮動鈕；或改條件渲染為 CSS 隱藏（`hidden` class）保留捲動位置。
- **工作量**：S

---

## 6. 業界對照（依公開資訊與訓練知識，標注 [推測]；競品細節以 `UX_RESEARCH.md` 為準，此處只列「現檔尚未吸收」的差距與「已領先」項）

### 已領先、應守住
1. **逐句三態簽核 + 多角色 provenance**（`DraftEditor`：ai_generated / attorney_edited / paralegal_edited / *_added + edited_from 可展開原文）——Harvey、Spellbook、DeepIP、Solve 都沒有逐句歸屬。王俊豪 persona 的「系統要記得我做了什麼」已實作（paralegal 來源會出現在 export 統計，`ExportResultPanel:496-505`）。**這是產品護城河，T2/T3/T8 的修補都該圍繞它做，不要重構掉。**
2. **使用者可自行驗證的 audit chain**（AuditView hero metrics + 客戶端可再驗）——CoCounsel 的 citation ledger 是 vendor-attested，我們是 user-verifiable。
3. **期日計算可解釋**（ResultSummaryBar「計算依據」展開：起算日/法定/建議內部/假日表版本）——Anaqua 等 docketing 系統只給日期不給理由。

### 值得借鏡、現檔還沒有
| 競品模式 | 對應缺口 | 建議落點 | 工作量 |
|---|---|---|---|
| Harvey/Linear `⌘K` | W5 | 全域 palette | M |
| CoCounsel「先看它讀了什麼、再看它寫了什麼」live ledger | T6 | reasoning disclosure | M |
| Patlytics 引證 pop-out（第二螢幕釘住） | ReferenceModal 只能 modal | `window.open('/refs/:id?popout=1')` 無 chrome 路由（ACCESSIBILITY §2.6 已 spec） | M |
| Spellbook 的 firm playbooks（事務所自訂論證模板） | 無 | Phase 4/5；與 RAG 案例庫結合 | L |
| DeepIP objection ranking（核駁理由按勝算/嚴重度排序triage） | RejectionTabs 按後端順序排列 | tab 依 affected_claims 數 + 獨立項命中排序，或顯示嚴重度 chip | S–M |
| docketing 整合的最小可行版：**期日匯出 .ics** | 期日算完只能用眼睛抄進 Outlook | ResultSummaryBar 加「加入行事曆」產 .ics（含內部建議完成日雙事件） | S |

最後一列特別提出：**期日 .ics 匯出是全報告 CP 值最高的 S 級功能**——期日算錯=喪權，而現在這個算對的日期必須人工轉抄，轉抄就是錯誤源。

---

## 7. 其他發現

### X1 — Google Fonts CDN 外連，與 on-prem 敘事矛盾
- **嚴重度**：P1 **[程式碼]**
- **位置**：`frontend/index.html:17-22`（`fonts.googleapis.com` / `fonts.gstatic.com`）
- **問題**：Marcus persona 的明文紅線：「A single 3rd-party JS CDN on the login page」即出局——字型 CSS CDN 同屬對外 egress，且 air-gapped 部署時 Inter/Noto Sans TC/JetBrains Mono 全部 fallback、整套排版規格失效。CLAUDE.md §7 已知 Tailwind CDN 是 POC 捷徑，字型同罪。
- **建議**：改 `@fontsource/inter`、`@fontsource/noto-sans-tc`、`@fontsource/jetbrains-mono` npm 自托管，woff2 subset 進 build。
- **工作量**：S

### X2 — 交付截圖組過期/誤標
- **嚴重度**：P2 **[程式碼]**（本次以 Read 檢視證實）
- **位置**：`docs/screenshots/delivery/real_07_audit.png` 內容實為**登入頁**（與 real_01 相同畫面），非稽核頁
- **建議**：重新 capture 整組 real_*（Playwright 截圖腳本應已存在於 visual_regression.spec.js 基礎上）；demo/簡報引用前先校對。
- **工作量**：S

### X3 — 主題機制與 DESIGN_SYSTEM 的 `data-theme` 規格尚未 reconcile
- **嚴重度**：P2 **[程式碼]**
- **位置**：`frontend/src/lib/theme.jsx`（class="dark"）vs `DESIGN_SYSTEM.md` §11.2（要求 data-theme + audit 區獨立 theme scope）
- **建議**：照 §11.2 的過渡方案執行即可，非急迫；但新元件不要再寫死依賴 `.dark` selector 的特例。
- **工作量**：S（過渡 alias）

---

## 8. Top 10 優先執行清單

| # | 項目 | 嚴重度 | 位置 | 工作量 | 為什麼是現在 |
|---|---|---|---|---|---|
| 1 | **T1** 政策 chips 改讀真實 `policy_decisions` | P0 | `Analyze.jsx:338-347` | S | 寫死的信任訊號被識破一次，整個 trust 敘事歸零 |
| 2 | **T2** DEGRADED 結果禁止簽核匯出（前端 disable + 後端 409） | P1 | `DraftsPane.jsx:78`、`DraftEditor.jsx:137` | S | mock 草稿可被律師簽核是法律風險路徑 |
| 3 | **T3** 含 `[CITATION_REMOVED]` 的句子禁止「接受」，只能改寫/排除 | P1 | `DraftEditor.jsx`（splitIntoLines + setStatus 閘門） | S–M | verifier 硬牆從「看得見」變「擋得住」，補齊透明原則 #3 |
| 4 | **A2** 全部 keydown handler 加 `isComposing` guard | P1 | `DraftEditor.jsx:118-135, 247-250` | S | 注音輸入丟失改寫內容 = TW 用戶第一週就會踩的資料遺失 |
| 5 | **W3** 修正進度面板計時 profile 與 running_note 模型文案 | P1 | `DraftsPane.jsx:349-357`、`i18n.js` | S | 進度條與文案對實機全錯，demo 時就會被看穿 |
| 6 | **A1** slate-400 對比違規全面替換 + lint 規則 | P1 | 多檔（見 §3 A1 清單） | S | 45–55 歲主用戶；規格文件早已明文禁止 |
| 7 | **T4** 非稽核角色 ChainChip 文案改「稽核鏈啟用中」 | P1 | `AppShell.jsx:311-315`、`i18n.js` | S | 三行修掉一個過度宣稱 |
| 8 | **X1** 字型自托管（@fontsource），移除 Google Fonts CDN | P1 | `frontend/index.html:17-22` | S | on-prem 賣點的採購紅線；air-gapped 部署排版會崩 |
| 9 | **W1+W2** 多 rejection 簽核進度匯總 + 全案合併匯出（DOCX） | P1 | `DraftsPane.jsx`、`DraftEditor.jsx`、gateway export | M | 工作流的「最後一哩」：沒有它，省下的時間被 format tax 吃回去 |
| 10 | **T7** 引用 pill 改可及 popover（focus/tap 可開、含摘錄與雙 action） | P1 | `DraftEditor.jsx:550-595` | M | Journey A 的 watershed：iPad 簽核者目前完全看不到引文 |

候補（緊接其後）：I1 拆雙語字串 + e2e 改 testid（S–M）、期日 .ics 匯出（S）、T5 信心分數改 pips（S–M）、W4 1366×768 佈局鬆綁（S–M）、T6 reasoning disclosure（M）。

---

## 附錄：本次審查覆蓋清單

- 元件（17/17）：AppShell、Analyze、DraftEditor、AuditView、OAUpload、StackStatus、Login、EmptyState、ErrorBanner、Skeleton、analyze/{ClaimTree, InputPane, DraftsPane, ReferencesPane, ReferenceModal}、ui/{button, badge}
- lib：i18n.js、theme.jsx、toast.jsx；App.jsx；tailwind.config.js；index.html
- 文件：UX_RESEARCH、UX_PERSONA_JOURNEYS、DESIGN_SYSTEM、ACCESSIBILITY_AND_I18N、AI_TRANSPARENCY_UX、CLAUDE.md
- 截圖：real_01/05/06/07（其中 real_07 證實誤標，見 X2）
- 未覆蓋：實機 1366×768 量測（W4 為推導）、螢幕報讀器實測（A 系列依 ARIA 靜態分析）、真實使用者行為（W6/M4 等標 [推測] 項）
