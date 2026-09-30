# 架構討論紀錄：Dify + digiRunner + 多租戶 + RAG 方向

> **這份是什麼**：2026-09-28 與專案負責人的架構討論紀錄（只有討論，程式碼未變動）。
> 前提：本專案**指定使用 Dify 與 digiRunner**；模型**不會只用 7B**；要有**完善的多租戶設計**。
> 對應既有文件：`docs/DECISIONS.md`（Q1–Q20）、`docs/PHASE3_MIGRATION.md`、`07_深入方向_roadmap.md`。

---

## 1. 已確認的方向

| 項目 | 決定 | 理由 |
|---|---|---|
| 流程編排 | **Dify**（指定） | 對應 Q2 混合策略；workflow DSL 由 `prompts/*.yaml` 生成，維持單一來源 |
| API 閘道 / 認證 | **digiRunner**（指定） | 認證 + 把租戶身分以 header 帶給 gateway（Day 8C upstream-header auth） |
| RAG 框架 | **不改用 LangChain**，維持自寫檢索服務 | 見 §2 |
| 模型 | 一般案件可走雲端模型；機密案件走較大的地端模型（例如 vLLM 上的 30B 級） | 不再以 qwen2.5:7b 為唯一模型 |

## 2. RAG：為什麼不用 LangChain

- **層級重疊**：LangChain 主要解決「流程編排 + RAG 元件」；編排已指定交給 Dify，兩者並用 = 兩套編排框架。
- **差異化在專利特化邏輯**：claim-tree 切塊、CJK 段落標題、依申請日 fail-closed 前案過濾、per-tenant collection + 租戶加鹽 embedding、引用硬牆需精確掌握 grounded set。LangChain 沒有這些，且抽象層會讓 grounded set 較難追蹤。
- **維護成本**：LangChain API 改版頻繁。
- **若真要用框架**：LlamaIndex 比 LangChain 更聚焦 RAG，但也只取單一元件（例如 loader），不讓它主導檢索流程。

**檢索放哪裡 — 三個選項**

| 選項 | 評估 |
|---|---|
| A. Dify 內建知識庫 | 省事，但做不到 claim-tree / fail-closed 日期過濾；資料存在 Dify 內（違反不變量 #2）；隔離、稽核、ACL 不在我方控制 |
| B. ai_engine 內改用 LangChain | 現有功能大多已自寫且為專利特化版本；增加依賴與不透明度 |
| **C. 自有檢索服務，Dify 以 API 呼叫（採用）** | 現行 Phase 3 DSL 已是此設計（`analyze_oa.workflow.json` 的 HTTP 節點呼叫 `/v1/retrieve_prior_art`）；可選改接 Dify External Knowledge API。專利邏輯、租戶隔離、ACL、稽核都留在我方；換掉 Dify 時檢索不受影響 |

面試說法：「框架解決通用問題；差異化在專利特化檢索與引用接地，必須自己掌控；通用編排交給 Dify。」

## 3. 多租戶設計

原決策 Q5：single-tenant data plane + multi-tenant control plane。討論後建議**分級**：

| 等級 | 對象 | 隔離方式 |
|---|---|---|
| Silo | 大型事務所、堅持地端機房 | 整套 stack 部署在客戶內網 |
| Bridge | 一般事務所 | 共用基礎設施，每租戶獨立 collection / schema / 金鑰 |

| 層 | 做法 | 現況 |
|---|---|---|
| digiRunner | 每租戶一個 client；租戶身分**只從 OIDC token 取出**再注入 header，不接受前端自帶；限流以租戶為單位 | upstream-header auth 已完成 |
| Gateway | case ACL、每租戶配額、遮罩字典、稽核 | 大多完成 |
| Dify | **不存任何租戶資料**，只放共用 workflow；租戶資訊由 gateway 以 input 傳入，隔離由我方檢索服務負責 | 待定（見 §5） |
| Qdrant | 租戶少（數十家）→ 每租戶一個 collection（現況）；租戶很多 → 單一 collection + payload 分區 + tenant index | per-collection 已完成 |
| Postgres | 每租戶一個 schema，或 Row-Level Security | 目前只有 tenant_id 欄位 |
| 金鑰 | 改為**每租戶獨立金鑰**（存 KMS / Vault）；刪除金鑰 = 刪除租戶資料（crypto-shredding） | mapping 加密已是每租戶金鑰，但由單一主金鑰以 HKDF 導出（`masking.py:937`），刪不掉；稽核 HMAC 為全域金鑰環 |
| 模型服務 | 每租戶並發上限，避免單一租戶塞滿地端 GPU | 尚未做 |

**機密路由不能只靠 Dify**：Dify 設定可在介面上被修改。三道防線全部保留 —— digiRunner AI gateway 規則、Dify IF/ELSE 節點、`llm_client` 斷言（不變量 #7）。

## 4. 深化方向（依建議順序）

1. **評測先行**：三層指標 —— 決策（核駁類型）、引用（法條精確度、引用準確度）、品質（LLM 評審 + 抽樣人工）。不用 ROUGE（PatRe：與人工評分相關僅 τ≈0.14）。
2. **輸入端接地**：parse_oa 抽出的每條核駁都要對應回 OA 原文位置，沒有依據就丟棄（PatRe 顯示模型會「過度核駁」，§112 捏造率 60%）。
3. **驗證升級**：逐句對齊加上 NLI / 交叉編碼器判斷蘊含；字面比對保留為最低防線。判定分四類：存在、適用、支持、放棄回答（對應 "Legal Warrant" 論文框架）。
4. **重新定義檢索目標**：審查官已指定引證文獻，答辯要找的是 (a) 引證文獻中的關鍵段落、(b) 本案說明書中可支持修正的段落。
5. **特徵級檢索**：請求項拆成技術特徵，逐特徵檢索與比對（可用 PatentMatch 評測）；進步性的多篇組合 = 覆蓋問題，長期可延伸到特徵圖（GraphRAG）。
6. **租戶私有知識庫**：事務所歷史答辯書，嚴格限定於該租戶。
7. **需 GPU（延後）**：bge-m3 / Qwen3 embedding + reranker、vLLM + streaming 降低 25–28 秒延遲。

## 5. 待決定

1. **部署形態**：自營 SaaS（多家共用）還是裝進各事務所機房？→ 決定以 bridge 或 silo 為主。
2. **Dify 版本**：社群版或企業版？（印象中社群版只支援單一 workspace，多 workspace 為企業版功能，**需向 Dify / TPIsoftware 確認**）
3. **預計租戶數**：決定 Qdrant 用 per-collection 或 payload 分區。

## 6. 支持此設計的研究（2026-09-28 查詢）

| 論文 | 與本設計的關係 |
|---|---|
| [Legal LLM Hallucination as Failure of Legal Warrant](https://arxiv.org/abs/2609.17546)（2026-09） | 只檢查引用存在不夠，需檢查適用、現行、支持，並能放棄回答 —— 對應引用硬牆 + 跨管轄偵測 + 逐句對齊 + unverifiable |
| [PatRe](https://arxiv.org/html/2605.03571)（2026-05） | 480 件 USPTO 案；答辯遠比當審查官容易；引用準確度 Oracle > BM25 >> 無文獻 —— 支持 RAG + 引用接地 |
| [TW-LegalBench](https://arxiv.org/html/2606.18699v1)（2026-06） | 最佳模型法條引用準確率 <10%；在地資料勝過更大通用模型；**不含專利法**（台灣專利 AI 仍是空白） |
| [How Much Do Legal RAG Systems Still Hallucinate?](https://arxiv.org/abs/2608.14210)（2026-08） | 法律 RAG 幻覺率 <10% 到近一半 |
| [PEDANTIC](https://arxiv.org/abs/2505.21342) / [PatentMatch](https://arxiv.org/abs/2012.13919) | 可作 §26-2 明確性、特徵級前案比對的評測參考（皆為英文） |
| [TW Legal RAG](https://github.com/aa0101181514/tw-legal-rag) | 台灣判決 RAG 開源；自承引用驗證只能確認案號存在 —— 逐句對齊正好補上這層 |

## 7. 討論中發現的文件不一致（2026-09-29 已修正）

- `CLAUDE.md` §3b 與 `HANDOFF.md` §28 第 6 點原寫「稽核 HMAC 金鑰輪替不支援」，但 `06e2b0e` 已實作（`AUDIT_HMAC_KEYS` / `AUDIT_HMAC_ACTIVE_KID`，見 `ops/README.md`）→ 已改為「已支援」，並註明後續為每租戶金鑰。
- `backend/ai_engine/alignment.py:57` 註解原寫門檻 0.20，常數實為 `SUPPORT_THRESHOLD = 0.25` → 註解已改為 0.25。

---

# 第三階段討論（2026-09-29）

範圍：多租戶完整化、狀態外部化與可靠性、GPU 推論優化。順序：**先決定部署形態** → 狀態外部化 → 多租戶隔離 → 每租戶並發與工作佇列（與非同步改造合併）→ vLLM / GPU。

## 8. ADR-01：租戶資料刪除 vs. 稽核保存

**狀態**：提議（未實作）

**背景**
- 租戶離開或當事人要求刪除時，資料必須真的不可復原；但律所稽核紀錄依法需保存 5–10 年且可驗證未被竄改。
- 稽核列（`backend/gateway/audit.py:60`）不存原文（只有 request/response hash、遮罩規則 ID、模型、token、延遲、policy），**但含識別資訊**：`user_id`（律師帳號，屬個資）、`case_id`（可能透露客戶）、`tenant_id`。
- 現況：mapping 加密已是每租戶金鑰，但由單一主金鑰以 HKDF 導出（`masking.py:937`），主金鑰在就能重算，**無法刪除**。

**決定：依用途分開金鑰（信封加密）**

| 金鑰 | 保護什麼 | 租戶離開時 |
|---|---|---|
| DEK_content（每租戶隨機產生） | OA 原文、草稿、mapping 原值 | 刪除 → 資料不可解密 |
| DEK_identity（每租戶隨機產生） | 稽核中的 user_id / case_id（先化名再存） | 刪除 → 稽核列無法對應回真實身分 |
| 稽核完整性金鑰（HMAC 金鑰環） | 稽核鏈 | **保留** → 鏈仍可驗證 |
| KEK（Vault / KMS；silo 可用 HSM） | 加密上面的 DEK | 保留 |

- 稽核 HMAC 對「化名後的值」計算 → 刪除身分金鑰後鏈仍完整，但無法還原身分。
- 核心論點：**完整性與可識別性是兩個獨立性質，用不同金鑰管理，就能同時滿足保存與刪除。**
- 選 crypto-shredding 而非刪除資料列：資料會存在每日備份、WAL 封存、replica 中，逐一刪除不可行；刪除金鑰讓所有備份中的密文同時失效。
- 可接既有 Q27 `erase_subject` / `subject_hmac` 機制。

**後果 / 風險**
- KMS 不可用 → 無法解密內容，採 fail-closed（暫停服務，不退回明文）。
- DEK 可能殘留於行程記憶體、log、core dump → 限制快取時間，絕不寫入 log。
- 法律依據：稽核保存屬「履行法定義務」例外，需寫入隱私政策與合約。
- 待確認：`request_hash` 若為對短內容的未加鹽 SHA-256，可被字典攻擊還原 → 應改用 keyed HMAC。

## 9. ADR-02：外部狀態故障時 fail-open / fail-closed

**狀態**：部分已實作，部分提議

**判斷原則**：比較「錯誤放行」與「錯誤拒絕」的後果 —— 安全控制 fail-closed；效能優化 fail-open；預算控制 fail-closed 或降級。

| 元件 | 建議 | 現況（2026-09-29 讀程式碼） | 待辦 |
|---|---|---|---|
| 快取 | fail-open | ✅ 出錯視為未命中（`redis_cache.py`） | 無 |
| 限流 / 配額 | fail-closed（或降級） | ✅ 預設 closed，`RATE_LIMIT_REDIS_DEGRADE` 可設 open（`rate_limit.py:380`；config 註解說明與快取相反的理由） | 無 |
| JWT 撤銷清單 | 短效 access token + refresh 時檢查撤銷、Redis 故障回 503 | ✅ 2026-09-30：Redis 故障回 503 + Retry-After，登出失敗會寫稽核且不回報成功（M-14） | 短效 token + refresh 仍待做 |
| 稽核寫入 | 依操作類型區分 | ⚠️ `_safe_audit_write` 一律吞掉錯誤，由 outbox 後備 | 見下 |
| 金鑰服務（KMS） | fail-closed | 尚未導入 | 導入時一併設計 |

**撤銷清單**
- 現況結果上是 fail-closed（不會放行已撤銷 token），但：可能回 500 而非 503 + Retry-After；Redis 故障時登出也會出錯，使用者可能誤以為已登出；Redis 成為全系統單點故障。
- 選項：(1) 明確 fail-closed 回 503；**(2) 短效 access token（5–15 分鐘）+ refresh token，只在 refresh 時檢查撤銷（建議）**，Redis 故障只影響換發，已撤銷 token 最多再有效一個 access token 週期；(3) 每副本本機快取撤銷清單（有同步延遲）。
- 另加 Redis 高可用（Sentinel）。

**稽核寫入**
- 現況為可用性優先：寫入失敗仍回應成功。若 outbox 也失敗 → 出現無稽核紀錄的操作。
- 建議折衷：唯讀操作維持可用性優先；**會產生或輸出內容的操作（分析、上傳、匯出）改為合規優先 —— outbox 也寫不進去就拒絕請求**。

**共同要求**
- 每次降級都發 metric + 告警，並寫入 `policy_decisions`，讓稽核看得出請求是在降級狀態下處理。
- 以混沌測試驗證：docker 中實際關閉 Redis / Postgres，逐一確認上表行為。

## 11. 隱私與延遲優先（2026-09-29）

負責人把**隱私**和**延遲**列為最不能接受的兩項。原則：**讓隱私的路徑本身就很快** —— 機密案被強制走地端，若地端最慢，就是越重要的案件體驗越差；方向是投資地端推論，不是為了速度放寬路由。

**隱私**：Sentry 洩漏風險已修正（`SECURITY_AUDIT.md` H-9）。其餘待辦：雲端路徑加一層地端 NER 當第二道檢查；稽核化名與 `request_hash` 改 HMAC（ADR-01、L-8、L-9）；雲端 prompt caching 寫入揭露條款。

**延遲**：`orchestrator.py` 目前是關卡式編排（全部檢索 → 全部起草 → 全部驗證 → 期限 → 請求項樹 → 特徵表），每一階段都等最慢的核駁，且無關步驟被串行。改為**每條核駁各自走 檢索→起草→驗證，期限／請求項樹／特徵表同時進行**，總時間約等於「解析 + 最慢的一條核駁」。其他：每步耗時量測、串流與漸進顯示、vLLM、依步驟選模型、案件建檔時預先建索引、案件層級快取、共用 `httpx.AsyncClient`（目前每次呼叫都新建，`orchestrator.py:154`）。

**分散式正確性問題**（同日審查，列於 `SECURITY_AUDIT.md` addendum）：H-10 稽核鏈多副本分岔、M-12 全域成本斷路器、M-13 稽核驗證全表掃描、M-14 撤銷清單無 Redis 故障處理、M-15 AI Engine 預設有狀態。

## 10. 待驗證（資源空出後）

1. ~~撤銷清單 Redis 故障時的實際 HTTP 狀態碼~~ → 已修正為 503 + Retry-After（M-14，2026-09-30）。
2. ~~認證階段失敗是否漏寫稽核~~ → **已確認會漏寫**，且範圍是所有認證失敗（過期、無效、撤銷），列為 `SECURITY_AUDIT.md` M-16，尚未修正。
3. ~~`request_hash` 的計算方式~~ → 已確認為未加金鑰的 SHA-256（`audit.py:321`），列為 L-8。
4. RTX 3060 實際 VRAM（HANDOFF 記 8GB、另一份紀錄寫 12GB）。
