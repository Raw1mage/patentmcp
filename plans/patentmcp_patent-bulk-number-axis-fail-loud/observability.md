# Observability: patentmcp_patent-bulk-number-axis-fail-loud

## Events

- `logger.info("number-axis syntax cleaned: %s -> %s", original, cleaned)` — normalize_query 偵測並清洗號碼軸語法時。
- provenance `number_axis_cleaned` 欄位 — 回應內透明記錄清洗前後（呼叫者可辨識工具改寫了查詢）。
- provenance.reason `likely_number_syntax_error` — zero_hits 分級標記，供呼叫者自救。

## Metrics

- 號碼軸清洗次數（由 info log 計數）— 反映呼叫者誤帶 @PN 尾綴的頻率，高則代表入口顯化不足需再強化 docstring。
- `NUMBER_AXIS_SYNTAX_UNSUPPORTED` 發生率 — 清洗仍無法解析的硬失敗頻率。
