# Spec: patentmcp_patent-bulk-number-axis-fail-loud

## Purpose

`patent_bulk` 與 `patent_search` SHALL 提供一等 `pub_number` 清單能力顯化 number-list 匯出入口；SHALL 偵測 keyword 內號碼軸語法（`@PN`/`@AN` 尾綴、整包外括號）並清洗或以 typed 錯回應，**絕不靜默 zero_hits**；number/PN 軸 zero_hits 時若疑似號碼語法 SHALL 標 `likely_number_syntax_error`。修復 BR_20260718，恢復 GPSS number 軸的 fail-loud 契約（同族 BR_20260709 教訓）。

## Requirements

### Requirement: 顯化號碼清單入口

`patent_bulk` SHALL 新增一等 `pub_number` 參數；`patent_search` 既有 `pub_number` SHALL 接受單值或清單。清單內部組成 `no or no or ...` + PN 欄位。

#### Scenario: patent_bulk 用 pub_number 清單批量補書目

- **WHEN** `patent_bulk(source="gpss", pub_number=["CN117338286","CN117338290"])`
- **THEN** 組成 `GPSSCondition("PN", "CN117338286 or CN117338290")`，命中並回全書目，不需呼叫者知道 keyword 隱式用法

#### Scenario: patent_search 單值 pub_number 向後相容

- **WHEN** `patent_search(pub_number="CN117338286")`（str）
- **THEN** 行為與改動前完全一致

### Requirement: 號碼軸語法 fail-loud

系統 SHALL 偵測 keyword 含 `@PN`/`@AN`/`@PD` 尾綴或整包外括號的號碼軸語法；預設清洗（strip 尾綴 + 拆外括號）並記 provenance `number_axis_cleaned`；清洗後仍非合法號碼列 SHALL 回 typed `NUMBER_AXIS_SYNTAX_UNSUPPORTED`，不靜默 zero_hits。

#### Scenario: @PN 尾綴自動清洗

- **WHEN** `keyword="(CN117338286 or CN117338290)@PN"`
- **THEN** 清洗成 `CN117338286 or CN117338290` + PN 欄位，命中並記 `number_axis_cleaned`

#### Scenario: 清洗後仍非法 → typed 錯

- **WHEN** keyword 帶號碼軸修飾但清洗後無法解析成號碼列
- **THEN** 回 `{success:false, error_code:"NUMBER_AXIS_SYNTAX_UNSUPPORTED", hint:...}`，不回 success:true zero_hits

### Requirement: zero_hits 分級

number/PN 軸 zero_hits 時，若 keyword 疑似號碼語法，provenance.reason SHALL 為 `likely_number_syntax_error` 並帶自救 hint，而非籠統 `zero_hits`。

#### Scenario: 疑似號碼語法 zero_hits 分級

- **WHEN** number 軸查詢 zero_hits 且 keyword 疑似號碼語法
- **THEN** provenance.reason = `likely_number_syntax_error` + hint「keyword 軸不吃 @PN 尾綴，請用 pub_number 參數」

## Acceptance Checks

- [ ] patent_bulk 新增 pub_number 參數（單值/清單）→ PN 條件
- [ ] patent_search pub_number 清單化，單值向後相容
- [ ] @PN 尾綴/外括號偵測 + 清洗 + provenance number_axis_cleaned
- [ ] 清洗後非法 → NUMBER_AXIS_SYNTAX_UNSUPPORTED typed 錯
- [ ] zero_hits 疑似號碼語法 → likely_number_syntax_error 分級
- [ ] 一般全文 keyword 不被誤判清洗
- [ ] 全套既有測試不回歸
