# Spec: patentmcp_enrich-fetch-converter-wiring

## Purpose

保證 enrich 取文降級鏈（`patent_get_claim1` / `patent_enrich_backfill`）在把公開號送給任一取文源之前，都先過該源的 per-target pubno converter，使前導零等格式歧異在 tool 內自癒，不再把原號裸送導致假 miss。

## Requirements

### Requirement: 取文送查前 per-target 正規化

取文降級鏈的每個送查點，SHALL 在呼叫外部源前，用該源對應的 per-target converter 正規化公開號（送 gpatents/google_patents → strip-0 canonical、送 GPSS REST → `to_gpss_rest`、送 EPO → `to_epo_variants`）。禁止把呼叫端原號直接送外部源。

#### Scenario: US grant 前導零號取文自癒

- **WHEN** `patent_get_claim1("US09993161B1")` 被呼叫（前導零形態）
- **THEN** 送 gpatents/google 前經正規化為 `US9993161`，取文 `success: true` 回完整 claim1，不再回 `Failed to fetch from gpatents`

#### Scenario: converter 識別不出格式時 fail-fast

- **WHEN** 送查號碼無法被任一 per-target converter 正規化
- **THEN** fail-fast 回明確錯誤，不 silent 預設原號直送

### Requirement: L3 實查閘覆蓋取文降級鏈

測試套件 SHALL 含一個取文端 roundtrip 實查向量：拿一個已知前導零錯號跑取文路徑，斷言 converter 被呼叫且取文成功；converter 在取文消費點漏接時，該測試 MUST 當場 fail。

#### Scenario: 取文端 roundtrip 防回歸

- **WHEN** 取文降級鏈某送查點被改回原號直送
- **THEN** 取文端 roundtrip 實查測試 fail，阻擋回歸

## Acceptance Checks

- [ ] `patent_get_claim1` 對前導零 US grant 號取文成功（實測 `US09993161B1` → claim1 落地）
- [ ] 取文降級鏈各送查點（gpatents/google/GPSS/EPO）grep 得到 per-target converter 呼叫
- [ ] 取文端 roundtrip 實查測試存在且綠燈，改回原號直送時 fail
- [ ] 未新造格式邏輯（復用既有 `to_*` 函式）
