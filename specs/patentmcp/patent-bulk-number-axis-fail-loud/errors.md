# Errors: patentmcp_patent-bulk-number-axis-fail-loud

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| `NUMBER_AXIS_SYNTAX_UNSUPPORTED` | keyword 帶號碼軸修飾（@PN/@AN 尾綴、外括號）清洗後仍無法解析成合法號碼列（DD-2） | `{success:false, error_code, hint}` | 用 `pub_number` 參數（單值/清單）或純 `no or no` keyword |

## Notes

- **不再靜默 zero_hits**：號碼軸語法問題以 typed 錯或清洗（記 `number_axis_cleaned`）回應；真無此案的 zero_hits 才保留 `success:true`。
- `likely_number_syntax_error`（provenance.reason，非 error_code）：zero_hits 且疑似號碼語法時的分級標記 + 自救 hint，不改 success 語義。
- 同族 BR_20260709（closed）已確立「GPSS 不認的語法會靜默 miss」教訓；本 BR 為 number 軸的同構修復。
