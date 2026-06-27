# Handoff: Anomaly Detection Workflow Lessons Remediation

## Execution Contract
本實作旨在加固 `patentmcp` 前案檢索相關工具。主要著眼於提升 API 的穩定度與健壯性（GPSS 分頁與異常解碼、PPUBS 降級備援、Google 限流熔斷），並同步更新 Companion Skill 文件以確立開發邊界。

## Required Reads
- `vendor/patents-mcp/src/patent_mcp_server/patents.py`：檢視 `build_screening_table` 與 `patent_get_claim1` 實作。
- `vendor/patents-mcp/src/patent_mcp_server/screening_table.py`：檢視 CSV/去重處理逻辑。
- `skills/patent-practitioner-workflow.md`：檢視目前專利檢索的工作流程指引。

## Stop Gates In Force
- **Stop** 如果分頁拉取導致連接 GPSS 連續超時。
- **Stop** 如果 Google Patents 阻斷頻率過高，導致單件 Fallback 呼叫也頻繁失敗。
- **Stop** 如果實作中涉及任何對 DOCX 的底層 XML 讀寫修改。

## Execution-Ready Checklist
- [ ] Python 環境中已安裝 `BeautifulSoup4` 用於網頁解析。
- [ ] 擁有有效的 GPSS 檢索測試環境以驗證大池檢索。
- [ ] 確認 `token-store` 可正常寫入與讀取 CSV 檔案。

## Downstream Consumer
後續在進行任何多模態或異常偵測專利檢索的 AI Agent，其檢索與 CSV 合併流程將直接受惠於此加固工具與 SOP 規範。
