# Event: GCP Billing Kill-Switch & Budget Setup

## 需求
- 設定 `<account-redacted>` 的專案計費預算上限為 600 台幣 (TWD)。
- 建立自動熔斷機制 (Kill-Switch)：當預算超支時，觸發 Cloud Functions 自動解除專利專案 `gen-lang-client-0857568615` 的計費綁定，避免產生額外費用。

## 範圍

### IN
- 在工作區建立 `billing-kill-switch` 目錄。
- 建立自動熔斷 Python 程式碼 `main.py` 與依賴 `requirements.txt`。
- 建立全自動部署腳本 `deploy.sh`：
  - 自動偵測目前的計費帳戶 (Billing Account)。
  - 建立 Pub/Sub 主題 `budget-kill-switch-topic`。
  - 部署 Cloud Functions `stop-billing-fn`。
  - 建立 600 TWD 的 Billing Budget 並關聯至 Pub/Sub 主題。
- 提供 IAM 權限配置指南，以防運行時權限不足。

### OUT
- 直接在 Agent 沙盒中執行 `gcloud` 指令（因 sandbox 限制，無法直接調用 CLI 命令）。

## 任務清單
- [x] 1. 建立 `billing-kill-switch` 目錄與核心檔案 (`main.py`, `requirements.txt`)。
- [x] 2. 建立自動部署腳本 `deploy.sh`（包含自動獲取計費帳戶與 Budget 綁定）。
- [x] 3. 更新架構與完成度驗證。

## Debug Checkpoints

### Baseline
- 專案 `gen-lang-client-0857568615` 目前尚未建立預算警示與自動熔斷功能。

### Execution
- 本次任務已成功產生以下實體檔案：
  - [main.py](file:///home/pkcs12/projects/patentmcp/billing-kill-switch/main.py)
  - [requirements.txt](file:///home/pkcs12/projects/patentmcp/billing-kill-switch/requirements.txt)
  - [deploy.sh](file:///home/pkcs12/projects/patentmcp/billing-kill-switch/deploy.sh)

### Validation
- **程式碼審計**：[main.py](file:///home/pkcs12/projects/patentmcp/billing-kill-switch/main.py) 中具備例外捕捉結構（Exception handling），並使用 `logging` 模組記錄當前支出與閾值，確保出錯時在 Cloud Logging 中可見。
- **一鍵部署驗證與 RCA 修復**：
  * *問題*：初次執行 `deploy.sh` 時，在 Step 3 遭遇 `INVALID_ARGUMENT: Service account ...appspot.gserviceaccount.com does not exist` 錯誤而中斷。
  * *RCA*：App Engine 預設服務帳戶是在首次部署 Function 或開啟 App Engine 時 Lazy 建立，此時該帳戶在 IAM 系統中尚不存在，導致提前賦權失敗。
  * *處置*：與使用者討論後採用 **方案 B**，改用專案建立即存在的 **Compute Engine 預設服務帳戶** (`{PROJECT_NUMBER}-compute@developer.gserviceaccount.com`)，並在部署命令中使用 `--service-account` 指定。目前腳本已完成此項重寫與更新。


