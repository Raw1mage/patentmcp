# Handoff: patentmcp_gpss-web-login-db-scope

## Execution Contract

- 交付：`GPSS4Session`/`adv_search.py` 補 `set_search_databases(session, dbs)`（GET `_20_*` 設定頁→勾庫→存檔 POST→驗證跳回）+ `gpss4_advanced_search` tool 加 `databases: list[str]|None` 參數。done = 端到端 `databases=["CNA","CNB"]` 撈回 CN 純源池（非跨國混合），back-compat（None）行為不變。

## Required Reads

- `issues/BR_20260716_gpss4_adv_search_missing_peruser_database_scope_config.md`（本 BR 根因 + 建議修法）
- `src/patent_mcp_server/gpss4/adv_search.py`（flow docstring L18-39、`_ADV_TAB_RE`、`_submit_query`、`harvest`）
- `src/patent_mcp_server/gpss4/session.py`（`GPSS4Session.login`/`get`/`_refresh_chain`）
- `design.md`（DD-3/DD-6）、`tasks.md`

## Stop Gates In Force

- task 1 live 逆工需真實登入 GPSS4；若 `_20_*` 設定頁機制與 BR 假設不符（例如庫範圍非 checkbox 而是其他控制項），停下回報再定 DD。
- 若設定為 session-scoped（非帳號持久），DD-6 的獨立 tool 設計需重新決策。

## Execution-Ready Checklist

- [ ] `GPSS4_USERNAME` / `GPSS4_PASSWORD` 可用（env/.env）
- [ ] `.venv/bin/python` 有 httpx（登入 state machine 依賴）
- [ ] XDG scratch 目錄就緒（逆工 dump 落點，不落 /tmp）
