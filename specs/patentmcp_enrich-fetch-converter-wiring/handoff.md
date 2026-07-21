# Handoff: patentmcp_enrich-fetch-converter-wiring

## Execution Contract

- 交付：`patents.py` 取文降級鏈每個送查點在呼叫外部源前過 per-target converter；新增取文端 roundtrip 實查測試。
- Done 定義：實測 `patent_get_claim1("US09993161B1")` success + claim1 落地、取文端 roundtrip 測試綠燈且改回原號直送時 fail、既有 pytest 全綠。

## Required Reads

- `issues/closed/BR_20260719_cross_db_pubno_format_converter_layer.md`（R3 復發樣本 + DD-3/DD-4）
- `patentmcp/pubno_convert.py`（per-target converter 全清單，唯讀依賴）
- `patentmcp/patents.py`（取文降級鏈，:1437/:1440 gpatents 送查點）

## Stop Gates In Force

- 無架構級決策待批；純 tool 接線 + 測試，可自主執行到驗證完成。

## Execution-Ready Checklist

- [ ] BR_20260719 已 reopen（R3 已 append）
- [ ] event log 已寫受理決策 + RCA
- [ ] plan designed → planned 已推進
