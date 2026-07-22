# Proposal: patentmcp_gpss-account-rotation

## Why

- GPSS REST API 配額按**輸出筆數**計、**時段制重置**（上班 08–18 窄上限 10,000、下班+週末寬 30,000；SKILL.md §「官方實證」）。單一帳號的時段額度用盡後，`patent_search` / `patent_bulk` 的 GPSS 梯即整段失效，只能枯等時段重置。
- 目前 `GPSSClient` 只讀單一 `GPSS_USER_CODE`（`gpss/client.py:94`），無多帳號、無 rotation、無額度感知。使用者已擁有第二個 TIPO 帳號驗證碼（<account-redacted>），要把「一個帳號額度用盡就自動換下一個」做成可擴充機制，額度加倍。

## Original Requirement Wording (Baseline)

- "把mcp改成兩個帳號rotate切換使用，直到兩個帳號的日額度都用盡"
- "更進一步的說，讓這個機制可以擴充更多api key帳號"

## Effective Requirement Description

1. `GPSSClient` 支援 **N 個 userCode 帳號池**，依序 rotate。
2. 當某帳號回傳「額度用盡」訊號時，**即時切下一個帳號並重試同一請求**；已用盡帳號在本次 process 內不再嘗試。
3. 全部帳號都用盡時，回傳明確的「所有帳號額度用盡」錯誤（fail-fast，不靜默降級、不 fallback）。
4. 帳號池以 `.env` 單一變數 `GPSS_USER_CODES`（逗號分隔）設定；**相容舊 `GPSS_USER_CODE`**（單碼仍可用）。新增帳號只需在尾部加一個碼。

## Scope

### IN
- `GPSSClient` 內建 N 帳號 rotation state machine（額度偵測 → 換帳號重試 → 全部用盡 fail-fast）。
- `.env` / `.env.example` 帳號池設定格式（`GPSS_USER_CODES` + 向後相容 `GPSS_USER_CODE`）。
- 額度用盡偵測：依 GPSS 回傳 message 含 `Over download quantity`（官方時段配額用盡訊號）。
- 單元測試（Fake GPSS：額度用盡 → 換帳號 → 成功 / 全部用盡 → fail-fast）。

### OUT
- 跨 process 持久化用盡狀態（本次 process 內記憶即可；重啟重新開始，因時段重置本就會恢復）。
- 時段感知的主動排程（不預測重置時間，被動偵測用盡才換）。
- gpss3/gpss4 網頁路徑（零 API 額度，本就與 REST 額度無關，不在此範疇）。

## Non-Goals

- 精算每帳號剩餘筆數（GPSS 不回傳剩餘額度，只能被動偵測用盡）。
- 負載平衡（依序用盡式，非輪流分攤）。

## Constraints

- 對所有呼叫端透明：`patents.py` / `search_dispatcher.py` 共用單一 `gpss_client` 實例，rotation 必須內建於 `search()` 內，呼叫端零改動。
- 無 fallback 天條：全帳號用盡回結構化錯誤，不偽裝成「查無資料」。
- 額度偵測字樣必須對準官方訊號 `Over download quantity`，不得誤判「查無資料」message 為用盡。

## What Changes

- `GPSSClient.__init__`：`user_code` 單值 → `user_codes` 清單（rotation 游標 + 本次 process 用盡集合）。
- `GPSSClient.search`：包一層 rotation 迴圈——偵測到額度用盡 message → 標記當前帳號用盡 → 換下一個未用盡帳號重試；全部用盡 → fail-fast。
- `.env` / `.env.example`：`GPSS_USER_CODES` 設定 + 註解。

## Capabilities

### New Capabilities
- N 帳號 rotation：額度用盡自動換帳號，可擴充帳號數。

### Modified Capabilities
- `GPSSClient.search`：額度用盡時自動 rotate 重試（原為單帳號直接失敗）。

## Impact

- `src/patent_mcp_server/gpss/client.py`（核心）
- `.env` / `.env.example`（設定）
- `src/patent_mcp_server/gpss/__init__.py` docstring（單碼 → 帳號池）
- `tests/`（新增 rotation 測試）
