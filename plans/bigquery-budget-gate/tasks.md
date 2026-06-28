# Tasks: bigquery-budget-gate

## 1. Config 與用量記帳基礎

- [x] 1.1 config.py 新增 `BIGQUERY_MONTHLY_BUDGET_BYTES`(預設 1 TiB)、`BIGQUERY_USAGE_DB_PATH`、`BIGQUERY_RECONCILE_TTL_SECONDS`(預設 900)
- [x] 1.2 bigquery_client.py 新增本地 SQLite 記帳：query 後累加當月 `total_bytes_billed`(以 YYYYMM 為 key)
- [x] 1.3 bigquery_client.py 新增 `BudgetExceededError` 例外類別

## 2. INFORMATION_SCHEMA 校正 + budget gate

- [x] 2.1 新增 `_reconcile_usage()`：查 `INFORMATION_SCHEMA.JOBS_BY_PROJECT` 當月 SUM(total_bytes_billed)，寫回本地快取；權限不足時降級標記 source
- [x] 2.2 新增 `get_monthly_usage()`：回 {used_bytes, budget_bytes, source, last_reconciled_at, exceeded}；TTL 過期時觸發 reconcile
- [x] 2.3 在 `_execute_query` 入口插入 budget gate：超額擲 `BudgetExceededError`(reconcile-aware)

## 3. 移除燒錢工具

- [x] 3.1 bigquery_client.py 移除 `search_patents` / `search_by_inventor` / `search_by_assignee` / `search_by_cpc` 方法
- [x] 3.2 patents.py 移除 5 個 @mcp.tool：`google_search_patents` / `google_search_by_inventor` / `google_search_by_assignee` / `google_search_by_cpc`(注意確認實際工具數與名稱)
- [x] 3.3 清理相關 import / Defaults / GooglePatentsCountries 未用引用(若僅 search 用到)

## 4. 限縮單號取文 + budget status 工具

- [x] 4.1 收斂 `google_get_patent` 的 `SELECT *` 為明確書目欄位集(DD-6)
- [x] 4.2 新增 `google_budget_status` @mcp.tool：回月用量/門檻/剩餘/source/exceeded
- [x] 4.3 工具層把 `BudgetExceededError` 轉成結構化錯誤 `{success:false, error_code:"BQ_BUDGET_EXCEEDED", ...}`

## 5. fallback 鏈整合

- [x] 5.1 get_claim1 BQ 分支(patents.py:1437)：budget 超額時跳過並 log warning(BQ 因預算跳過)
- [x] 5.2 get_pubnum BQ 分支(patents.py:2654)：同上處理

## 6. 驗證與文件同步

- [x] 6.1 lint / import 檢查：`python3 -c "import patent_mcp_server.patents"` 不報錯
- [x] 6.2 單元驗證：budget gate 超額擲錯、未超額放行、reconcile 降級路徑
- [x] 6.3 `/tools` 端點確認 5 工具消失、google_budget_status 出現
- [x] 6.4 skills/patentworks/SKILL.md 更新 BigQuery 段落(工具清單、budget 行為、移除 search 警告)
- [x] 6.5 event_record 收尾 + 架構同步註記
