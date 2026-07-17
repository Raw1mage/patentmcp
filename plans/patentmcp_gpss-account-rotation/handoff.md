# Handoff: patentmcp_gpss-account-rotation

## Execution Contract

- 交付：`GPSSClient` 支援 N 帳號池 + 額度用盡自動 rotate，全部用盡 fail-fast。**Done 定義**：tasks.md 全 4 phase 勾完、`tests/test_gpss_rotation.py` 通過、全套既有測試不回歸、`.env`/`.env.example` 設定就緒、docstring 同步。

## Required Reads

- `src/patent_mcp_server/gpss/client.py`（rotation 核心所在）
- `plans/patentmcp_gpss-account-rotation/design.md`（DD-1..DD-6 契約）

## Stop Gates In Force

- 無外部 approval 閘；額度偵測字樣（DD-2）為關鍵正確性點，測試須釘死防誤判。

## Execution-Ready Checklist

- [x] 額度用盡官方訊號已由 KB 確認（`Over download quantity`）
- [x] 帳號池設定格式已定（`GPSS_USER_CODES` 逗號分隔）
- [x] 兩帳號驗證碼已備（新 c2d198B6924a37D6 / 舊 f77fB093dfdb34FD）
