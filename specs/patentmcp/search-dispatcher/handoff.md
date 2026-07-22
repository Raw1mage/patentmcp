# Handoff: patentmcp_search-dispatcher

## Execution Contract

- 交付:單一 `patent_search` dispatcher 上線、4 個分散檢索工具下架、`build_screening_table` 改接 dispatcher、mcp.json 0.3.0 + instructions 重寫、skill 文件同步、單元測試綠。
- Done 定義:tasks.md 全勾 + `pytest tests/` 全綠 + `webctl.sh refresh` 後 `GET /tools` live 驗證通過。

## Required Reads

- `plans/patentmcp_search-dispatcher/design.md`(DD-1~DD-8)與 `data-schema.json`(QuerySpec/AXIS_CAPABILITY/ProvenanceEntry/Envelope)
- `src/patent_mcp_server/patents.py`:233(uspto_patents)、828(gpatents_search)、1032(build_screening_table)、2546-2732(fetch_patent_pdf 的 gate 模式)、2742(gpss_search)、2861(epo_search)
- `src/patent_mcp_server/screening_table.py`(record schema + 既有 adapters)
- `tests/test_br20260628_tooling_gaps.py`(monkeypatch-client 測試模式)
- `opencode/specs/mcp-integration-standard/standard.md` R3/R4/R5/R8/R13.5

## Stop Gates In Force

- 下架屬 breaking change,已獲使用者 question() 裁決——無需再批。
- `webctl.sh refresh` 重啟服務前向使用者知會(live 服務)。
- 發現 scope 外的既有 bug → event_record 記錄,不順手修。

## Execution-Ready Checklist

- [x] proposal / design / spec / data-schema / sequence / idef0 / grafcet 完成且過 designed gate
- [x] 偵查完成:查詢軸對照、configured() 機制、註冊機制、adapter 現況(見 event log)
- [x] 使用者裁決:全部下架 + gpatents 留 allow_scraping 尾級
