# Spec: Anomaly Detection Workflow Lessons Remediation Spec

## Purpose
建立 `patentmcp` 關鍵工具的穩定性規範與降級流程，確保在大批量前案檢索與 Word 報告組裝流程中，系統能穩定處理異常、進行分頁與防範爬蟲限流。

## Requirements

### Requirement: GPSS Response Resilience & Pagination
`build_screening_table` 在向 GPSS 請求時，必須能應對非 JSON 回應並具備自動分頁能力。

#### Scenario: Non-JSON GPSS Response
- **Given**: GPSS 服務因負載過大返回 HTML 錯誤頁面。
- **When**: `build_screening_table` 嘗試解碼回應。
- **Then**: 系統捕獲 `JSONDecodeError`，不拋出 Python Traceback，而是返回包含 `success=false` 與詳細原因的結構化 Tool Error。

#### Scenario: Large Result Set Pagination
- **Given**: 檢索命中數大於 50 件。
- **When**: 呼叫 `build_screening_table`。
- **Then**: 工具內部以 50 件為一頁進行自動分頁拉取，且每頁抓取間隔設有 1 秒的 Cool-down 時間，最後將結果合併至 Token Store CSV 中。

### Requirement: Claim 1 Fallback Chain
`patent_get_claim1` 必須在官方 PPUBS 查詢失敗時，降級至 Google Patents 提取 Claims。

#### Scenario: PPUBS Lookup Failed
- **Given**: 查詢 US 專利號。
- **When**: PPUBS 回報 `Granted patent document not found`。
- **Then**: 自動轉而呼叫 `gpatents_get` 獲取 Claims HTML/JSON，從中匹配並抽取第一項獨立項 (Claim 1)，將結果返回。

### Requirement: gpatents Fail-Fast Guard
`gpatents_*` 工具群必須防範嚴重的 Google 爬蟲限流。

#### Scenario: Scraper Blocked (403/503)
- **Given**: 連續對 Google Patents 發送請求導致觸發限流。
- **When**: API 回傳 `403`（Forbidden）或 `503`（Service Unavailable）。
- **Then**: 工具立即拋出熔斷例外，不進行本地 `time.sleep` 等重試，直接回報 `Throttled/Blocked` 狀態。

### Requirement: Workflow SOP Formalization
Companion Skill 必須固化防範腳本越權的規範。

#### Scenario: Verification of SOP Guidelines
- **Given**: 開發人員查看 Companion Skill。
- **Then**: 內容必須包含 CPC 矩陣檢索日誌、Python 合併 CSV 與使用 `docxmcp` 組裝 Word 的標準流程。

## Acceptance Checks
- [ ] `build_screening_table` 不會因 GPSS 返回非 JSON 而崩潰。
- [ ] 檢索量大於 50 件時，GPSS 請求會進行分頁，且不觸發超時。
- [ ] 對 US 專利調用 `patent_get_claim1` 時，即使 PPUBS 失效也能經由 Google Patents 成功取得第一項獨立項。
- [ ] `gpatents` 遭遇 403 或 503 時立即 Fail-fast 退出，無滯留 retry。
- [ ] `skills/patent-practitioner-workflow.md` 文件已同步最新的五步檢索 SOP。
