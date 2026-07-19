# Observability: patentmcp_cross-db-pubno-converter

## Events

- converter 是純函式，**無自身 log / event**（無副作用）。
- 觀測落在**呼叫端**：EPO/GPSS 查詢點在逐個 variant fallback 時，於 `provenance[]` 記錄實際命中的 variant 形式，
  供稽核「哪個格式對哪個 DB 命中」——這也是 mapping 知識表實測依據的持續來源。

## Metrics

- **vendor-drift guard**（pytest）：src 與 patentdb_local 的 canonical 函式體逐字相同 → 綠；drift → 紅（機檢閘）。
- **canonical_pubno 向後相容**（pytest）：既有 patentdb 實 key 抽樣輸出逐字不變 → 綠。
- **mapping 向量覆蓋**（pytest）：test-vectors.json 的 TV-1..8 全過 → 綠。
