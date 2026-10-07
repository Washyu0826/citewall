# 地端單機部署（docker compose）

事務所地端一台機器跑整套 PatentMind（Q22/Q23）。本機 GPU 給 Ollama（地端 LLM），
其餘服務全部在容器裡。

## 一鍵啟動

```bash
cp .env.example .env          # 第一次：填入下列必填值
docker compose --profile app up -d --build
# 加上監控（Prometheus + Grafana）：
docker compose --profile app --profile monitoring up -d --build
```

瀏覽器開 `http://<這台機器>:8080`（`FRONTEND_PORT`）。只有前端這個埠對辦公室網路開放；
gateway `:8010`、ai_engine `:8011`、Qdrant、Postgres、Redis、Keycloak、RustFS、
Prometheus `:9090`、Grafana `:3000` 都只綁 127.0.0.1。

不加 `--profile` 的 `docker compose up -d` 行為不變：只起基礎設施容器（給
`scripts/start_demo.sh` / `start_delivery.sh` 這種主機直跑模式用）。

## `.env` 必填

| 變數 | 說明 |
|---|---|
| `JWT_SECRET`、`INTERNAL_TOKEN` | `openssl rand -hex 32` |
| `AUDIT_HMAC_KEY` 或 `AUDIT_HMAC_KEYS` + `AUDIT_HMAC_ACTIVE_KID` | 稽核鏈 HMAC 金鑰；非 mock 模式沒設不啟動。輪替見下方 |
| `MAPPING_ENCRYPTION_KEY` | 可還原遮罩對照表的主金鑰；與 DR 資料一起備份 |
| `METRICS_TOKEN` | `/metrics` bearer token；monitoring profile 的 Prometheus 用同一值 |
| `GRAFANA_ADMIN_PASSWORD` | 只有 monitoring profile 需要；沒設 Grafana 拒絕啟動 |

預設 `LLM_MODE=local`，ai_engine 經 `host.docker.internal:11434` 連主機上的 Ollama
（`ollama pull qwen2.5:7b`）。要改走 Dify：`.env` 設 `LLM_MODE=dify` 與 Dify 相關變數。

## 資料與 volume

| Volume | 內容 |
|---|---|
| `gateway_data` → `/app/data` | 稽核 DB、遮罩對照表、案件登錄檔、備份、outbox、WORM 封存 |
| `ai_engine_data` → `/app/data` | 假日曆、Contextual Retrieval 快取、Hugging Face 模型快取 |

容器啟動時 `docker/seed-data.sh` 會：假日曆每次以映像檔內版本覆蓋（新映像＝新假日表）；
`case_registry.json`、`tenant_dicts/` 只在不存在時複製，之後以管理頁或檔案修改為準。

## 映像檔

- `docker/gateway.Dockerfile`、`docker/ai_engine.Dockerfile`：多階段、`python:3.13-slim`、
  非 root（uid 10001）、內建 healthcheck、不含測試套件。ai_engine 預設裝 CPU 版 torch +
  sentence-transformers（`AI_ENGINE_INSTALL_ML=false` 可出精簡版）。
- `frontend/Dockerfile`：node 24 build → `nginx-unprivileged`（uid 101、:8080），`/api/*`
  轉給 gateway。CSP 在 build 時計算 `index.html` inline script 的 sha256，不開
  `'unsafe-inline'` script；`object-src`/`frame-src` 只放 `blob:`（PDF 預覽）。
  StackStatus 的開發用埠探測在正式環境會被 CSP 擋掉，顯示「未偵測」屬預期。

## 稽核金鑰輪替（Q21）

1. 目前單一 `AUDIT_HMAC_KEY` 視為 kid `k1`。
2. 改成金鑰環：`AUDIT_HMAC_KEYS=k1:<舊>,k2:<新>`、`AUDIT_HMAC_ACTIVE_KID=k2`，重啟 gateway。
3. 新列以 k2 簽章並記錄 `hash_key_id`；舊列仍用 k1 驗證。**舊金鑰不可移出金鑰環**，
   否則那些列會被回報為 `unverifiable`（同時列入 `broken`，不會被當成已驗證）。

## 案件登錄管理（Q27）

IT 管理員（`it_admin`）登入後，左側導覽「案件登錄」可新增案件、調整機密等級、停用
（不能刪除）。每次變更寫一筆稽核紀錄，含變更前後的等級。API：`/v1/admin/cases`
（case_id 一律放在 JSON body，不進 URL）。

## 已知限制

- Keycloak（`OIDC_MODE=keycloak`）：issuer 預設 `http://localhost:8081`，gateway 容器內
  連不到主機的 localhost。容器化部署要把 `KC_HOSTNAME` 與 `OIDC_KEYCLOAK_ISSUER` 改成
  瀏覽器與容器都能解析的主機名稱。
- 所有瀏覽器流量經 nginx 進 gateway，gateway 看到的來源 IP 都是 frontend 容器；
  登入的每 IP 速率限制因此由全辦公室共用。
- 案件登錄檔是單一 JSON（原子寫入），適用單一 gateway 行程；多副本需改資料庫。
- 映像檔 tag 在撰寫時因 registry 連線逾時未能逐一驗證，首次 build 請確認可拉取。
