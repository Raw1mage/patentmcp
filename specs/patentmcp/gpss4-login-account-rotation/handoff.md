# Handoff: patentmcp_gpss4-login-account-rotation

## Execution Contract

- 交付：`GPSS4Session` 支援 N 組登入帳號池 + 登入失敗自動 rotate，全部失敗 fail-fast。**Done 定義**：tasks.md 全 4 phase 勾完、`tests/test_gpss4_login_rotation.py` 通過、全套既有測試不回歸、`.env`/`.env.example`/`docker-compose.yml` 設定就緒、docstring 同步。

## Required Reads

- `src/patent_mcp_server/gpss4/session.py`（rotation 核心所在）
- `plans/patentmcp_gpss4-login-account-rotation/design.md`（DD-1..DD-6 契約）

## Stop Gates In Force

- 無外部 approval 閘；DD-2 觸發條件（登入失敗，非額度）與 DD-6（re-login 不誤換）為關鍵正確性點，測試須釘死。

## Execution-Ready Checklist

- [x] 第二登入帳號憑證已備（憑證存於 `.env`，不入版控）
- [x] 同構參照：patentmcp/gpss-account-rotation（REST rotation 已完成）
- [x] 成對憑證編號式設定格式已定
