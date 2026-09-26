# 安全政策 / Security Policy

PatentMind 是「受規範領域中安全、可稽核的 LLM 流程」參考架構。我們重視每一份安全回報，也感謝負責任的揭露。

## 支援版本

| 版本 | 是否提供安全修補 |
|---|---|
| `main` 分支最新版 | ✅ |
| 其他分支、舊快照 | ❌ |

本專案仍屬 **概念驗證（PoC）**，尚未有正式版號。

## ⚠️ 專案狀態與部署前提

預設設定只適合**本機（localhost）**示範，不可直接暴露到共用或公開網路。部署前至少要：

- 設定 `JWT_SECRET`、`INTERNAL_TOKEN`、`MAPPING_ENCRYPTION_KEY`、`AUDIT_HMAC_KEY`（非 mock 模式下缺 `AUDIT_HMAC_KEY` gateway 會拒絕啟動）。
- 關閉示範登入：`demo-<user_id>` 密碼只在 `LLM_MODE=mock` 生效；magic-link 在非 mock 模式改以 email 寄送。
- 將真實案件登錄到 `data/case_registry.json`（未登錄的案件一律視為機密、強制走地端模型）。
- 更換 `keycloak/realm-patentmind.json` 內的開發用 client secret 與 demo 使用者密碼（僅供本機開發 realm 使用）。
- 為 `/metrics` 設定 `METRICS_TOKEN`；使用 `scripts/start_ngrok.sh` 時一律啟用 basic-auth。

完整的自我稽核（含 `file:line` 證據）見 [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md)，強化清單見 [`CLAUDE.md`](CLAUDE.md) §3–§4。

## 回報漏洞

**請勿以公開 GitHub issue 回報安全漏洞。** 請改用：

- **GitHub Security Advisories**：在 repository 的 **Security** 分頁按「Report a vulnerability」（建議）。
- 或私訊 repository 擁有者。

回報內容請包含：問題描述與影響、重現步驟（最小 PoC、`file:line` 或請求序列）、建議的修補方式（如有）。

我們會在 **5 個工作天內**回覆收件，並於分級後提供修補時程；請在修補完成前勿公開揭露。

## 範圍

範圍內：

- [`CLAUDE.md` §4](CLAUDE.md) 的設計不變量遭繞過：遮罩略過、無據引用、缺少稽核列、跨租戶洩漏、`case_id` 權限繞過、機密案件送往雲端模型、配額／成本斷路器繞過。
- 認證／授權、租戶隔離、稽核鏈完整性（含 HMAC v2）、個資遮罩（含 NER）、提示注入突破 `<untrusted_input>`。

範圍外（已知並已記錄的 PoC 限制）：

- 依文件運作的 mock 認證、mock LLM、記憶體內儲存。
- 已列於 [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md) 的項目（歡迎直接送 PR 修正）。

## 敏感資料處理

本專案存在的理由，就是客戶專利資料絕不能外洩：

- **禁止提交**真實或未公開的審查意見通知函、專利申請、審查委員聯絡資訊、客戶名稱或任何密鑰。所有 fixture 必須是合成資料（`data/cases/synthetic_cases.py`、`synthetic_cases_epjp.py`）。
- repository 附有 `.gitleaks.toml`，提交前可用 `gitleaks dir .` 自我檢查。
- 若發現 repository 或其歷史中有敏感資料，請視同安全回報、私下聯絡維護者。

---

*English summary:* report vulnerabilities privately via GitHub Security Advisories; do not open public issues. Only the latest `main` is supported. The project is a PoC — see the deployment prerequisites above before exposing it beyond localhost.
