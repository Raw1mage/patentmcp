# Observability: patentmcp_bulk-entry-unification

## Events

- `logger.warning("EPO bulk_harvest per-page absorb failed: ...")` — absorb callback 例外(不中斷收割,稽核靠此行)
- `logger.warning("patentdb absorb failed for patent_bulk: ...")` — GPSS 收尾 absorb 失敗

## Metrics

- envelope `patentdb_absorb {imported, updated, skipped}` — 每次呼叫的落地計數(EPO 為跨頁累計)
- envelope `provenance[]` — 每級後端嘗試與結果
- envelope `next_skip` / `exhausted` — 續撈進度與窮盡判定(EPO 另受 skip wall 2000)
