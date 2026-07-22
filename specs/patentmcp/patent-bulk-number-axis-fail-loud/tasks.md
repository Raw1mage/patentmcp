# Tasks: patentmcp_patent-bulk-number-axis-fail-loud

## 1. pub_number 清單化（DD-1，顯化入口）

- [x] 1.1 `QuerySpec.pub_number` 型別放寬 `Optional[Union[str, List[str]]]`（search_dispatcher.py:88）
- [x] 1.2 `normalize_query` / `_run_gpss` PN 組裝：清單 → `no or no or ...`（search_dispatcher.py:183）；單值路徑不變
- [x] 1.3 `patent_search` `pub_number` 參數型別放寬 + docstring（patents.py:3588）
- [x] 1.4 `patent_bulk` 新增 `pub_number` 參數 + docstring number-list 範例（patents.py:3722）

## 2. 號碼軸 fail-loud（DD-2/DD-4）

- [x] 2.1 `normalize_query` 加號碼軸語法偵測：`@PN`/`@AN`/`@PD` 尾綴 + 整包外括號
- [x] 2.2 預設清洗（strip 尾綴 + 拆外括號）+ provenance `number_axis_cleaned`
- [x] 2.3 清洗後仍非合法號碼列 → typed `NUMBER_AXIS_SYNTAX_UNSUPPORTED`
- [x] 2.4 偵測條件收窄，一般全文 keyword 不誤傷

## 3. zero_hits 分級（DD-3）

- [x] 3.1 `_run_gpss` zero_hits 時：清洗旗標 or 疑似號碼語法 → reason `likely_number_syntax_error` + hint

## 4. 驗證

- [x] 4.1 `tests/test_number_axis_failloud.py`：清單組成 PN / 單值相容 / @PN 清洗 / 清洗後非法 typed 錯 / zero_hits 分級 / 全文不誤判
- [x] 4.2 全套既有測試不回歸（重點 test_patent_bulk / test_search_dispatcher）
- [x] 4.3 docstring 明列 number-list 匯出範例

## 5. 收尾

- [x] 5.1 tick tasks + event log 收尾 + architecture sync
- [x] 5.2 BR_20260718 補 Resolution → 移 issues/closed/
- [x] 5.3 verified + 重建容器（./src bind-mount 熱掛，restart 重掃工具）
