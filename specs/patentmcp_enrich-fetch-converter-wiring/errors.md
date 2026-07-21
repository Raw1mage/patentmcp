# Errors: patentmcp_enrich-fetch-converter-wiring

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| PUBNO_NORMALIZE_UNRESOLVED | 送查號無法被任一 per-target converter 正規化 | fail-fast 明確錯誤（不 silent 原號直送） | 補齊 converter mapping 或修正呼叫端號碼；禁 silent fallback 天條 |
| FETCH_MISS_AFTER_NORMALIZE | converter 正規化後外部源仍 miss | 降級到下一取文源，重走正規化+送查 | 正常降級行為，非錯誤 |
| FETCH_TRUE_GAP | 全部取文源皆 miss（正規化後仍缺） | 回 `Failed to fetch`，記入殘餘清單供日後重跑 | 區分真缺口 vs 錯號假 miss；正規化後仍 miss 才算真缺 |

## 反模式（本 bug 製造機制）

- 原號直送外部源（跳過 converter）→ 前導零號假 miss → 誤判「真缺口 / 源未上架」。修復後禁止再現；由 L3 取文端 roundtrip 實查閘釘死。
