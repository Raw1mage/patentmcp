# Spec: patentmcp_bulk-entry-unification

## Purpose

窮盡批次(bulk)檢索只有一個 MCP 入口 `patent_bulk`:呼叫者顯式選源(gpss/epo),得到統一 envelope(含跨源一致的 `next_skip`/`exhausted` 續撈語義);EPO 分支的布林 keyword 轉譯與 per-page 落地行為由測試鎖定,任何一頁完成即持久化、客戶端逾時不丟已落地資料。

## Requirements

### Requirement: 單一 bulk 入口依 source 顯式路由

The system SHALL expose exactly one bulk MCP tool `patent_bulk(source, ...)`;`source` 無預設值,缺失或非 `gpss`/`epo` 時 SHALL 回 `INVALID_PARAMS`,不得隱式選源或跨源 fallback。

#### Scenario: GPSS 分類軸全拉

- **WHEN** `patent_bulk(source="gpss", cpc="G08B21/04")`(無 keyword)
- **THEN** 走分類軸 export 路徑(強制全欄 expFld),envelope `source="gpss"` 且含 `next_skip`/`exhausted`

#### Scenario: EPO keyword 收割

- **WHEN** `patent_bulk(source="epo", keyword="radar AND fall", num=100)`
- **THEN** keyword 經 `_keyword_to_cql` 轉譯為布林 CQL;每頁 biblio 完成即 absorb 進 patentdb;envelope 帶 `next_skip` 供續撈

#### Scenario: 無效 source fail-fast

- **WHEN** `patent_bulk(source="uspto", cpc="...")` 或省略 source
- **THEN** 回 `{success: false, error_code: "INVALID_PARAMS"}`,不打任何後端

### Requirement: 舊 bulk 工具 typed 轉址

`patent_bulk_export`、`patent_bulk_harvest`、`epo_bulk_harvest` SHALL 回 `TOOL_RENAMED` envelope(`use: "patent_bulk"`),不執行檢索。

#### Scenario: 舊工具呼叫

- **WHEN** 任一舊 bulk 工具被呼叫
- **THEN** 回 `{success: false, error_code: "TOOL_RENAMED", use: "patent_bulk", note: <參數搬遷指引>}`,零後端呼叫

### Requirement: EPO 布林 keyword CQL 轉譯

`_keyword_to_cql` SHALL 把 GPSS 風格布林 keyword 轉為逐 term 帶欄位前綴的 CQL;引號片語保留為單一 phrase term。

#### Scenario: 四類轉譯

- **WHEN** 輸入 `radar AND fall` / `"millimeter wave" OR radar` / `(radar OR lidar) AND fall` / `radar NOT vehicle`
- **THEN** 輸出 `txt=radar and txt=fall` / `txt="millimeter wave" or txt=radar` / `(txt=radar or txt=lidar) and txt=fall` / `txt=radar not txt=vehicle`

### Requirement: per-page 落地與斷點續撈

EPO 分支 SHALL 每完成一頁 biblio fan-out 即呼叫 absorb callback 落地;absorb 失敗不中斷收割;envelope 的 `next_skip` SHALL 可作下次呼叫的 `skip` 續撈,COALESCE upsert 重跑不覆寫既有非空欄位。

#### Scenario: 中途逾時不丟頁

- **WHEN** 收割在第 N 頁後中斷(模擬 client timeout)
- **THEN** 前 N 頁 records 已透過 absorb callback 落地;以 `next_skip` 重呼叫可續撈且不產生覆寫

### Requirement: EPO 自動 date 切片(母數 > skip wall)

`patent_bulk(source="epo", slice_plan=true)` SHALL 以 count-probe(零 biblio fan-out)探母數並回切片計畫:total ≤ 2000 → 單片;total > 2000 且有 date 範圍 → 遞迴二分至每片 total < 2000。各片 total 總和與母數差 > 5% SHALL 回 `SLICE_INEFFECTIVE`;無 date 範圍且 total > 2000 SHALL 回 `DATE_RANGE_REQUIRED`。遞迴深度 cap 6、probe 呼叫 cap 32,觸頂片標 `truncated:true`。

#### Scenario: 大母數自動切片

- **WHEN** `patent_bulk(source="epo", keyword=..., date_from="20150101", date_to="20241231", slice_plan=true)` 且母數 22622
- **THEN** 回 `{slice_plan: {total, slices: [{date_from, date_to, total}...], sum_check}}`,每片 total < 2000,零 records 拉取;呼叫者逐片呼叫 `patent_bulk` 完成收割

#### Scenario: 無 date 範圍 fail-fast

- **WHEN** slice_plan=true、total > 2000、date_from/date_to 皆缺
- **THEN** 回 `{success: false, error_code: "DATE_RANGE_REQUIRED"}`,不自行猜測全史範圍

#### Scenario: 假切自證

- **WHEN** 各片 total 總和與母數差超過 5%(date 條件在該 query 未生效)
- **THEN** 回 `SLICE_INEFFECTIVE` fail-fast,不靜默交殘缺切片計畫

## Acceptance Checks

- [ ] `patent_bulk` 路由測試:gpss 無 keyword→export 路徑、gpss 有 keyword→harvest 路徑、epo→收割路徑、無效 source→INVALID_PARAMS
- [ ] 三舊工具 stub 測試(比照 test_tool_renamed_stubs.py)
- [ ] `_keyword_to_cql` 四類 case 測試全綠
- [ ] per-page absorb 冪等 + next_skip 續撈測試全綠
- [ ] SKILL.md §5 已收錄 `patent_bulk` 契約與 EPO 布林能力
- [ ] 全測試套件無回歸
- [ ] slice_plan 測試:單片/遞迴二分/DATE_RANGE_REQUIRED/SLICE_INEFFECTIVE/深度觸頂 truncated 全覆蓋
