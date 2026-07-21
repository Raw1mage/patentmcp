# Proposal: patentmcp_enrich-fetch-converter-wiring

## Why

`patent_get_claim1` / `patent_enrich_backfill` 的取文降級鏈（送 gpatents / google_patents / GPSS / EPO 前）**整條沒呼叫任何 per-target pubno converter**，把呼叫端原號直送。US grant 前導零號（如 `US09993161B1`）直送 gpatents 必 miss，下游誤判成「451 筆真缺口 / gpatents 未上架」。

這是 `BR_20260719`（跨 DB pubno converter layer，已 resolved）的**第三度同族復發**：converter 有能力、docstring 有 mapping（L1/L2 到位），但取文降級鏈這個消費點漏接線（L3 實查閘未覆蓋 → 漏網）。前兩個漏網消費點：US A1 pre-grant 10↔11 位、US grant/old-A strip-0。

## Original Requirement Wording (Baseline)

- "有沒有辦法直接在 tool 裏融入錯號自癒"
- "每個 patent service provider 可以吃的號碼格式也不一樣。converter 要能識別不同對象，給予不同的格式自癒"
- "今天犯的錯誤證明昨天努力半天對今天零幫助，完全沒避免同樣錯誤再犯"

## Requirement Revision History

- 2026-07-21: initial draft; 根因升級為 tool 層取文端接線（非只對帳端）

## Effective Requirement Description

1. enrich 取文降級鏈每個送查點，送查前先過該源的 per-target pubno converter（送 gpatents/google→strip-0 canonical、送 GPSS→to_gpss_rest、送 EPO→to_epo_variants），禁原號直送。
2. L3 roundtrip 實查閘擴充覆蓋取文降級鏈——拿一個已知前導零錯號跑 `patent_get_claim1`，斷言 converter 被呼叫且取文成功；converter 漏任一消費點時該測試當場 fail。

## Scope

### IN
- `patents.py` 取文降級鏈（`patent_get_claim1` / `patent_enrich_backfill` 送查點，含 gpatents / google_patents / GPSS / EPO 各跳）接 per-target converter。
- 取文端 roundtrip 實查測試（L3 閘的取文端實例）。

### OUT
- converter layer 本體（`pubno_convert.py` 各 `to_*` 函式已正確，不動）。
- 對帳/落地 key 消費點（`_get_patent_country_and_normalized_no`、`patentdb_store`，前輪已收斂）。
- US claim1 母池重撈（converter 修好後的下游回收，屬前案檢索案主線）。

## Non-Goals

- 不改 converter 的 mapping 規則（strip-0 / variants 已對）。
- 不新增背景 job / 輪詢機制（subagent 誤診的 transport 方案，非本 bug 根因）。

## Constraints

- 禁重複造輪子：復用既有 `to_gpss_rest` / `to_gpss4_web(lstrip 0)` / `to_epo_variants` / `to_docdb`，不新造格式邏輯。
- 禁 silent fallback：converter 識別不出對象格式時 fail-fast，不預設。

## What Changes

- 取文降級鏈每個送查點插入 per-target 正規化呼叫。
- 新增取文端 roundtrip 實查測試向量。

## Capabilities

### Modified Capabilities
- `patent_get_claim1` / `patent_enrich_backfill`：送查前正規化號碼，前導零錯號自癒；US grant/old-A 不再假 miss。

## Impact

- `patents.py`（取文降級鏈送查點）
- `tests/`（新增取文端 roundtrip 實查）
- 下游回收：本案 US claim1 補撈的「451 筆真缺口」大部分可用正確號重撈。
