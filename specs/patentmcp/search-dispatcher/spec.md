# Spec: patentmcp_search-dispatcher

## Purpose

保證 patentmcp 的專利「檢索」只有一個 MCP 入口 `patent_search`,來源選擇
(GPSS→EPO→PPUBS→gated gpatents)由 server 端 dispatcher 依 configured()
與查詢軸能力決定;AI/agent 無從自選來源、無從未經授權觸發爬蟲。每次檢索的
路由決策以 provenance 完整可稽核,全 miss 時 fail-fast 回結構化錯誤,絕不
靜默降級。

## Requirements

### Requirement: 單一檢索入口

系統 SHALL 只暴露 `patent_search` 一個檢索類 MCP tool;`gpss_search`、
`epo_search`、`gpatents_search` SHALL 不再註冊為 MCP tool,`uspto_patents`
SHALL 不再接受 search 類 method(`ppubs_search_patents` /
`ppubs_search_applications`)。

#### Scenario: 舊檢索工具不可見

- **WHEN** 客戶端 `GET /tools`(live registry)
- **THEN** 回應包含 `patent_search`,且不包含 `gpss_search` / `epo_search` / `gpatents_search`
- **AND** `uspto_patents` schema 的 method 說明不含 search 類 method

#### Scenario: 舊 search method 被拒

- **WHEN** 呼叫 `uspto_patents(method="ppubs_search_patents", query=...)`
- **THEN** 回傳結構化錯誤,指引改用 `patent_search`

### Requirement: 來源梯路由(官方優先)

`patent_search` SHALL 依序嘗試 ①GPSS(configured 且軸支援)②EPO OPS
(configured)③USPTO PPUBS;SHALL 依查詢軸能力跳級(如 USPC `CCL/` 軸
直達 PPUBS);每級嘗試結果 SHALL 記入 `provenance`。

#### Scenario: GPSS 首選命中

- **WHEN** `GPSS_USER_CODE` 已設且以 `cpc`+`keyword` 呼叫 `patent_search`
- **THEN** 回傳 `source="gpss"`,records 為統一 schema
- **AND** `provenance` 含 GPSS 一筆 `status="hit"`,EPO/PPUBS 為 `skipped`

#### Scenario: GPSS 未設定時降級 EPO

- **WHEN** GPSS 未 configured 而 EPO 已 configured
- **THEN** dispatcher 跳過 GPSS(provenance 記 `skipped`, reason=`not_configured`)並走 EPO search→biblio 二段
- **AND** 回傳 `source="epo"`

#### Scenario: USPC 軸直達 PPUBS

- **WHEN** 呼叫帶 USPC(`CCL/705/300`)軸
- **THEN** dispatcher 直接路由 PPUBS(GPSS/EPO 記 `skipped`, reason=`axis_unsupported`)

### Requirement: 爬蟲授權閘(fail-fast)

官方梯(GPSS/EPO/PPUBS)全 miss 時,`allow_scraping=False`(預設)SHALL
回 `{success: false, error_code: "SCRAPING_REQUIRED", provenance: [...]}`,
不得靜默走 gpatents;`allow_scraping=True` 時 SHALL 走 gpatents 尾級並在
provenance 標 `scraping: true`。

#### Scenario: 未授權時擋下爬蟲

- **WHEN** 官方三級全 miss 且未傳 `allow_scraping`
- **THEN** 回 `SCRAPING_REQUIRED` 結構化錯誤,provenance 含三級 miss 明細
- **AND** 不發出任何 patents.google.com 請求

#### Scenario: 授權後尾級放行

- **WHEN** 官方三級全 miss 且 `allow_scraping=True`
- **THEN** gpatents 檢索執行,回傳 `source="gpatents"`、`provenance` 標 `scraping: true`

### Requirement: 統一回傳 envelope 與誠實缺口

`patent_search` SHALL 回傳 `{success, records[], source, provenance[],
gaps[], total}`;records SHALL 使用 screening_table.py 的統一 record
schema,來源填不了的欄位 SHALL 誠實留白並列入 `gaps`,不得造假。

#### Scenario: 缺口誠實標示

- **WHEN** 結果來自 GPSS(無 family_id)
- **THEN** records 的 `family_id` 為空、`gaps` 含 `family_id` 說明

### Requirement: 內部消費者改接 dispatcher

`build_screening_table` SHALL 改經 dispatcher 檢索路徑,獲得同一來源梯與
同一爬蟲閘語義;其對外回傳格式(handle/count/deduped/source/columns/gaps)
SHALL 維持不變。

#### Scenario: screening 走官方梯

- **WHEN** GPSS 未 configured 而呼叫 `build_screening_table`
- **THEN** 檢索按 EPO→PPUBS 官方梯進行,不觸發爬蟲(除非 allow_scraping)

### Requirement: 標準面同步(MCP integration standard)

`mcp.json` SHALL bump version 至 0.3.0 並重寫 `instructions` 宣告單一檢索
入口(R3/R5.1/R13.5);`/tools` SHALL 由 live registry 自動反映新表面
(R8.1,既有機制);所有工具 SHALL 維持 `patentmcp_` 前綴身分(R4.1)。

#### Scenario: manifest 與 registry 一致

- **WHEN** 比對 `mcp.json.instructions` 與 `GET /tools`
- **THEN** instructions 描述的檢索入口(patent_search)與 registry 一致,無殘留舊工具敘述

## Acceptance Checks

- [ ] `GET /tools` 只含 `patent_search` 一個檢索工具;舊 3 工具消失、`uspto_patents` search method 被拒
- [ ] 單元測試覆蓋:GPSS 首選、GPSS 未設降級 EPO、USPC 直達 PPUBS、SCRAPING_REQUIRED、授權尾級、provenance 完整性(monkeypatch clients,不打真網路)
- [ ] `build_screening_table` 走 dispatcher 且對外格式不變(既有測試綠)
- [ ] 全測試套件通過(`pytest tests/`)
- [ ] `mcp.json` version=0.3.0、instructions 重寫;README 遷移對照表
- [ ] skill 文件(SKILL.md §5、screening.md、priorsearch.md、patent-practitioner-workflow.md)無舊檢索工具名殘留
