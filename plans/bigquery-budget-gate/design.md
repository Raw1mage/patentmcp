# Design: bigquery-budget-gate

## Context

BigQuery client (`src/patent_mcp_server/google/bigquery_client.py`) 目前每次查詢只套 `maximum_bytes_billed=10GB`（單次封頂），無月累積感知。`patents.py` 暴露 8 個 `google_*` 工具，其中 5 個是全表 LIKE 掃描（燒錢），3 個是單號取文（安全）。

## Goals

- 月用量可查、可作為使用/拒用 BQ 的依據
- 移除所有 BQ 專屬燒錢工具
- 超額硬擋全部 BQ（fail-fast，無 silent fallback）

## Non-Goals

- 不重建檢索能力到 BQ（走 GPSS/EPO）
- 不串即時帳單 API

## Decisions

- **DD-1**: 用量來源採「混合」——本地 SQLite 自記帳（每次查詢後累加 `total_bytes_billed`）當低延遲快取；`INFORMATION_SCHEMA.JOBS_BY_PROJECT` 當權威校正（免費、含 MCP 外部用量）。budget_status 回傳時標明 `source`（cached / authoritative）與 `last_reconciled_at`。
- **DD-2**: 校正時機——`google_budget_status` 被呼叫時、以及每次 budget gate 檢查時若快取超過 TTL（預設 15 分鐘）就觸發一次 INFORMATION_SCHEMA reconcile。reconcile 失敗（權限不足/查不到）時降級用本地快取值並在回傳標 `source=cached-degraded`，**不**靜默假裝 0。
- **DD-3**: 超額行為——硬擋全部 BQ 工具。budget gate 在 `_execute_query` 入口檢查，超額擲 `BudgetExceededError`，工具層轉成結構化錯誤 `{success: false, error_code: "BQ_BUDGET_EXCEEDED", monthly_used_bytes, monthly_budget_bytes, suggestion: "改用 GPSS/EPO"}`。符合禁止 silent fallback 天條。
- **DD-4**: 移除 5 個 `google_search_*`（`google_search_patents` / `google_search_by_inventor` / `google_search_by_assignee` / `google_search_by_cpc`，注意 patents.py 是前綴 `google_search_patents` + `google_search_by_*`）。client 層對應 `search_patents` / `search_by_inventor` / `search_by_assignee` / `search_by_cpc` 方法一併移除。
- **DD-5**: `get_claim1` / `get_pubnum` fallback 鏈中的 BQ 分支（patents.py:1437, 2654）受 budget gate 保護——超額時 BQ 分支被跳過（這裡是 fallback 鏈內部，跳過下一個 source 不算 silent fallback，因為 budget gate 會 log 並且 BQ 本就是降級層；但仍 log warning 標明 BQ 因預算跳過）。
- **DD-6**: 收斂 `google_get_patent` 的 `SELECT *`。BigQuery 按 SELECT 欄位計費，`SELECT *` 對 publications 表掃所有欄位最貴。改為明確列出書目欄位集（與 search_patents 既有欄位集一致），避免掃 claims/description 等巨大 nested 欄位。
- **DD-7**: 新增 config：`BIGQUERY_MONTHLY_BUDGET_BYTES`（預設 1 TiB = 1099511627776）、`BIGQUERY_USAGE_DB_PATH`（本地記帳 sqlite 路徑）、`BIGQUERY_RECONCILE_TTL_SECONDS`（預設 900）。

## Risks

- **R1**: INFORMATION_SCHEMA 需 `bigquery.jobs.list`，service account 可能沒有 → 降級本地快取（DD-2），不阻斷。
- **R2**: 移除 5 工具是破壞性 API 變更 → skill 已標註不該用，影響面小；event log + skill 同步。
- **R3**: 本地記帳 sqlite 在容器重啟後可能遺失 → reconcile 從 INFORMATION_SCHEMA 補回月累積真值。
- **R4**: 超額硬擋會讓「單號取文備援」也失效。已與使用者確認（決策二選硬擋全部）。

## Critical Files

- `src/patent_mcp_server/google/bigquery_client.py` — budget gate + 記帳 + INFORMATION_SCHEMA + 移除 search
- `src/patent_mcp_server/patents.py` — 移除 5 工具、新增 google_budget_status、收斂 get_patent
- `src/patent_mcp_server/config.py` — 新增 budget 設定
- `skills/patentworks/SKILL.md` — 更新 BigQuery 段落

## Code Anchors

- bigquery_client.py:87-124 `_execute_query`（budget gate 注入點）
- bigquery_client.py:100-103 `maximum_bytes_billed`（保留）
- bigquery_client.py:126-664 `search_patents` / `search_by_*`（移除）
- patents.py:686-951 5 個 search 工具 @mcp.tool（移除）
- patents.py:1437-1450 get_claim1 BQ 分支（加 gate log）
- patents.py:2654-2656 get_pubnum BQ 分支（加 gate log）
- config.py:27-34 BigQuery 設定區
