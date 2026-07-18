# Feature Request: 擴充批次專利獨立請求項 (Claim 1) 匯出工具

## 描述
在進行多模態異常偵測等大規模專利前案技術洞察報告時，Agent 經常需要批次獲取多篇代表專利的獨立請求項（Claim 1）原文以進行白話技術分析。目前 `patentmcp` 雖有單一查詢功能，但缺乏批次匯出 Claim 1 至 JSON 或指定格式的專屬高階 API 或 CLI 工具。這導致 Agent 在需要批次 Claims 時容易採取自行編寫臨時爬蟲或抓取腳本的繞道手段，違反了 repo 的開發精神與安全規範。

## 建議方案
- 於 `patent_mcp_server.patents` 中新增 `ppubs_batch_get_claims(patent_numbers: List[str])` 的批次獲取工具。
- 整合 `uspto_patents` 轉發機制，允許一次性查詢多個專利號並回傳對應的 Claim 1。
- 提供 CLI 進入點以供腳本直接執行匯出，與 `docxmcp` 的中間產物結構調和。

---
## 結案（2026-07-19）
`ppubs_batch_get_claims` 已存在於 `src/patent_mcp_server/patents.py` / `search_dispatcher.py`（MCP tool 註冊）；host 側另有 `skills/patentworks/scripts/claims_tools.py`（clean-html / extract-claim1 / claim1-empty CLI）。需求已實質滿足 → closed。
