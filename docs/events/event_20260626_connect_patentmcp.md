# Event: 2026-06-26 設定 VSCode Antigravity 串接 patentmcp

## 需求與背景
使用者希望在 VSCode 中將 Antigravity IDE 串接 `patentmcp` MCP 伺服器，以便能使用專利檢索與管理工具。

## 範圍 (Scope)
* **IN**:
  * 讀取並修改 Antigravity IDE 的全域 MCP 設定檔：`/home/pkcs12/.gemini/antigravity-ide/mcp_config.json`。
  * 將 `.mcp.json` 裡的 `patentmcp` 配置項目合併進去。
* **OUT**:
  * 修改 `patentmcp` 的本體程式碼或其依賴項。

## 任務清單 (Task List)
- [x] 申請讀取 `/home/pkcs12/.gemini/antigravity-ide/mcp_config.json` 權限。
- [x] 讀取現有的 `mcp_config.json`（偵測到尚未建立）。
- [x] 合併 `patentmcp` 伺服器配置（含啟動指令與環境變數）。
- [x] 將合併後的配置寫回 `mcp_config.json`。
- [x] 提示使用者如何重新載入或重啟 MCP 伺服器並驗證結果。

## Debug Checkpoints 三段式

### 1. Baseline（修改前）
* **症狀**：VSCode Antigravity 尚未串接 `patentmcp`，IDE 對話無法取得專利檢索工具的支援。
* **重現步驟**：於 Antigravity 對話中詢問或列出可用 MCP 工具，無 `patentmcp` 註冊之工具。
* **影響範圍**：無法在對話中使用 `patentmcp` 的工具。

### 2. Execution（修正中）
* **關鍵改動**：新建 `/home/pkcs12/.gemini/antigravity-ide/mcp_config.json` 並寫入完整的 `patentmcp` MCP 設定。
* **第一個錯誤與處置**：
  * *錯誤*：讀取 `mcp_config.json` 時，系統回報 `no such file or directory`。
  * *處置*：確認為首次配置，故不進行合併，直接新建該檔案並寫入配置。

### 3. Validation（修正後）
* **驗證方式**：請使用者重啟 VSCode 或重新載入 Antigravity IDE。
* **預期結果**：在 Antigravity 的工具清單（或可用 MCP 伺服器）中，將會載入並顯示 `patentmcp` 及其底下提供的工具（如 `gpatents_search` 等）。
