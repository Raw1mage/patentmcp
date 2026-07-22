# Proposal: bigquery-budget-gate

## Why

- BigQuery 本月用量已超出免費額度（1 TiB/月）。系統目前只有 `maximum_bytes_billed=10GB` 的單次封頂，**沒有任何月累積用量感知**，所以無法在超額時阻止繼續燒錢。
- BigQuery 後端有 5 個全表 `LIKE` 掃描檢索工具，是燒錢元兇（曾有單次 10 TB ≈ $60 案例）。這些工具是 BigQuery 專屬，且檢索能力 GPSS/EPO 都有。

## Original Requirement Wording (Baseline)

- "目前bigquery月用量已爆。api要有辦法查知這個狀況來決定能不能用它。確實只能做單檔精確手術查詢，做為下載文件或代表圖的備援方案之一"
- "這些工具是 big query 專屬的嗎？如果是，全移除。不要讓 big query 有任何燒錢的工具"

## Requirement Revision History

- 2026-06-28: initial draft created via plan-init.ts

## Effective Requirement Description

1. API 要能查知本月 BigQuery 用量狀態，據以決定能否使用 BQ。
2. 移除所有 BigQuery 專屬的全表掃描（燒錢）工具。
3. BQ 限縮為「單號精確手術查詢」，作為取文/代表圖的備援方案之一。
4. 超額時硬擋全部 BQ 工具並回明確錯誤（禁止 silent fallback）。

## Scope

### IN
- 月用量感知：本地 SQLite 自記帳（快取）+ `INFORMATION_SCHEMA.JOBS_BY_PROJECT` 校正（權威、免費、含外部用量）
- 新增 `google_budget_status` 查詢工具
- BQ 查詢前置 budget gate：超額 fail-fast，回結構化錯誤
- 移除 5 個 `google_search_*` 全表掃描工具
- 收斂 `google_get_patent` 的 `SELECT *` 以降低單號掃描量
- config 新增月門檻設定

### OUT
- 不動 GPSS / EPO / PPUBS / gpatents 既有路徑
- 不改 `maximum_bytes_billed=10GB` 單次封頂（保留）
- 不做 GCP project-level quota 設定（屬使用者 ops，文件已記載）

## Non-Goals

- 不重建檢索能力到 BQ（檢索一律走 GPSS/EPO，本來就是 source priority）
- 不做即時帳單 API 串接（INFORMATION_SCHEMA 已足夠權威）

## Constraints

- 禁止 silent fallback（使用者天條）：超額必須顯式報錯。
- `INFORMATION_SCHEMA` 查詢需 service account 有 `bigquery.jobs.list`；查不到時降級到本地自記帳並標記 source。
- bytes 計費以 `total_bytes_billed` 為準（不是 processed），最小計費單位 10 MB。

## What Changes

- `bigquery_client.py`：新增用量記帳 + INFORMATION_SCHEMA 查詢 + budget gate 包進 `_execute_query`
- `patents.py`：移除 5 個 search 工具、新增 `google_budget_status`、收斂 get_patent 欄位
- `config.py`：新增 `BIGQUERY_MONTHLY_BUDGET_BYTES` 等設定
- `patentworks` SKILL.md：更新 BigQuery 段落（工具清單、budget 行為）

## Capabilities

### New Capabilities
- `google_budget_status`: 回本月 BQ 用量 / 門檻 / 剩餘 / 是否超額 / 來源
- budget gate: 每次 BQ 查詢前檢查月用量，超額擲出結構化錯誤

### Modified Capabilities
- `google_get_patent`: `SELECT *` → 收斂欄位
- `get_claim1` fallback：BQ 分支受 budget gate 保護
- BigQuery 工具集：8 → 4（3 取文 + 1 budget status）

## Impact

- 移除工具是破壞性 API 變更（5 個 `google_search_*` 消失）；下游若有人呼叫會 tool-not-found。skill 已標註這些不該用。
- `patents.py` get_claim1 / get_pubnum fallback 鏈不變順序，只是 BQ 分支多一道 gate。
