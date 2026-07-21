# Observability: patentmcp_enrich-fetch-converter-wiring

## Events

- 取文送查前正規化日誌：每個送查點記 `raw_pubno → target_source → normalized`，可事後稽核 converter 是否被呼叫、正規化結果是否符合該源格式。
- `Failed to fetch` 事件記「送查號是否已正規化」——已正規化仍 miss 才計真缺口；未正規化的 miss 是接線漏洞（不該再出現）。

## Metrics

- 取文成功率（claim1 length>0 / 送查數）：接線前 vs 後，US grant 前導零號段應顯著提升。
- L3 roundtrip 測試綠燈狀態：fail = 某送查點被改回原號直送，立即阻擋 merge。
