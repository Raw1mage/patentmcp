# Event: 2026-06-26 設定 VSCode Antigravity 串接 bodesign, docxmcp, drawmiat, specbase

## 需求與背景
使用者希望在 VSCode 中將 Antigravity IDE 串接 `bodesign`、`docxmcp`、`drawmiat`、`specbase` 四個 MCP 伺服器，使這些工具能在對話中使用。

## 範圍 (Scope)
* **IN**:
  * 搜尋並取得四個 MCP 伺服器的啟動設定（路徑、指令、環境變數）。
  * 讀取並修改 `/home/pkcs12/.gemini/antigravity-ide/mcp_config.json`，將這些伺服器配置合併進去。
* **OUT**:
  * 調整這些 MCP 伺服器本身的內部邏輯或代碼。

## 任務清單 (Task List)
- [x] 搜尋專案與系統以取得 `bodesign`、`docxmcp`、`drawmiat`、`specbase` 的啟動設定。
- [x] 讀取現有的全域 `mcp_config.json` 內容。
- [x] 將這四個伺服器配置合併至 `mcp_config.json`。
- [x] 將更新後的配置寫回 `mcp_config.json`。
- [x] 提示使用者如何重新載入或重啟 MCP 伺服器並驗證結果。

## Debug Checkpoints 三段式

### 1. Baseline（修改前）
* **症狀**：Antigravity 僅設定了 `patentmcp`，無其餘四個 MCP 伺服器的連結，無法在對話中使用它們的工具（例如 `docxmcp_` 或 `drawmiat_` 等）。
* **重現步驟**：在對話中呼叫上述 MCP 的工具，系統回報找不到該工具。
* **影響範圍**：無法進行圖表繪製、報告解構與 PCB copilot 設計。

### 2. Execution（修正中）
* **關鍵改動**：在 `/home/pkcs12/.gemini/antigravity-ide/mcp_config.json` 中併入四個 MCP 伺服器的 stdio 啟動指令與虛擬環境 Python 路徑。
* **第一個錯誤與處置**：
  * *觀察*：發現專案的原始 `mcp.json` 或 `mcp-apps.json` 中，`drawmiat`、`docxmcp`、`bodesign` 設定的傳輸模式是 `streamable-http` / UDS Socket 並且指令設為 `/bin/false`。
  * *處置*：經由對各專案代碼進行檢索，確認這三個伺服器皆具備 `--transport stdio` 或 stdio 入口點。因此在 `mcp_config.json` 中將它們轉換為標準的 stdio 調用配置，成功克服了客戶端不支援 UDS 直連的限制。

### 3. Validation（修正後）
* **驗證方式**：請使用者重新載入 VSCode 視窗或重新載入 Antigravity IDE。
* **預期結果**：在 Antigravity 的工具面板或可用工具中，成功出現以下工具組：
  * `specbase_` 系列工具 (例如 `specbase_event_search`)
  * `drawmiat_` 系列工具 (例如 `drawmiat_generate_diagram`)
  * `docxmcp_` 系列工具
  * `bodesign_` 系列工具
