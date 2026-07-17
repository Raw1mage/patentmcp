# Handoff: patentmcp_patent-bulk-number-axis-fail-loud

## Execution Contract

- 交付：修 BR_20260718——patent_bulk/patent_search 顯化 number-list 入口（一等 pub_number 單值/清單）+ GPSS 號碼軸語法 fail-loud（@PN 尾綴偵測/清洗/typed 錯）+ zero_hits 分級。**Done 定義**：tasks.md 全 5 phase 勾完、`tests/test_number_axis_failloud.py` 通過、全套既有測試不回歸、docstring 明列範例、BR_20260718 補 Resolution 移 closed。

## Required Reads

- `src/patent_mcp_server/search_dispatcher.py`（normalize_query:100、QuerySpec:85、_run_gpss PN 組裝:183）
- `src/patent_mcp_server/patents.py`（patent_bulk:3722、patent_search:3580）
- `plans/patentmcp_patent-bulk-number-axis-fail-loud/design.md`（DD-1..DD-4）
- `issues/BR_20260718*`、`issues/closed/BR_20260709*`（同族 fail-loud 教訓）

## Stop Gates In Force

- 無外部 approval 閘；DD-4（清洗優先於拒絕）與 DD-2（偵測收斂於 normalize_query 單一點）為關鍵正確性；一般全文 keyword 不誤判須測試釘死。
- GPSS 真實命中驗證受 TIPO 配額影響（同 BR_20260709 教訓）；清洗/組裝/分級邏輯以單元測試釘死，不依賴 live GPSS。

## Execution-Ready Checklist

- [x] 根因已坐實（patent_bulk 無 pub_number；keyword 直送 GPSS keyword 引擎 @PN 當全文）
- [x] 既有 anchor 已定位（patent_search pub_number、normalize_query PN 組裝）
- [x] 同族 BR_20260709 fail-loud 教訓已回顧
