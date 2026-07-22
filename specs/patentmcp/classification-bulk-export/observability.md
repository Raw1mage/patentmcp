# Observability: patentmcp_classification-bulk-export

分類軸批次匯出的可觀測性以 **結構化 envelope 的 `provenance[]`**(逐頁 attempted/hit/miss + reason + elapsed_ms)為主軸,輔以 `logger.warning` 日誌與 `patentdb_absorb` 落地統計。實作見 `search_dispatcher.py::_bulk_pull_gpss` / `bulk_export`,前端 `patents.py::patent_bulk`。

## Events

- **逐頁進度(hit)** — `_bulk_pull_gpss` 每成功一頁 append `_entry("gpss","hit","page skip=<skip> n=<len>", elapsed_ms=<ms>)` 至 provenance。分頁進度 = 數 provenance 中 `status=="hit"` 的筆數;`skip` 游標記錄拉取位置。
- **真 0 訊號(miss/zero_hits)** — GPSS 回 `status=success` + "no record found" boilerplate → append `_entry("gpss","miss","zero_hits", elapsed_ms=<ms>)`;第一頁即空則 envelope `success=True` + `records=[]` + **無 error_code**。這是判別「真 0」vs「錯誤」的關鍵訊號(DD-5)。
- **軸窮盡(axis_exhausted)** — 分頁途中某頁回空(非首頁)→ append `_entry("gpss", "miss"|"hit", "axis_exhausted", elapsed_ms=<ms>)`,迴圈停止;表示該軸已拉完。
- **分頁錯誤(error)** — 非首頁 transient 失敗 → append `_entry("gpss","error","http_error:<code>"|<msg>, elapsed_ms=<ms>)` + `logger.warning("bulk_export pagination failed at skip=%d: %s", ...)`;保留已累積 partial。
- **落地統計(patentdb_absorb)** — `patent_bulk` collect-then-absorb 後,envelope 帶 `patentdb_absorb={imported, updated, skipped}`;absorb 失敗以 `logger.warning("patentdb absorb failed for patent_bulk: ...")` + `patentdb_absorb={error:"absorb_failed", detail:...}` 回報(absorb 永不中斷 harvest)。

## Metrics

- **匯出筆數** — `len(envelope["records"])`(跨頁累積);對 `envelope["total"]`(GPSS 回報總數)可判斷是否窮盡(`skip >= total`)或截於 num 上限。
- **分頁頁數 / 呼叫數** — provenance 中 `status in {hit,miss,error}` 的 entry 數 = 實際 GPSS `search()` 呼叫次數;測試以 `gpss.calls` 斷言(如 450 筆 / 200 頁 → ≥3 次)。
- **單頁延遲** — 每 entry 的 `elapsed_ms`(`time.monotonic()` 差);用於偵測 GPSS 端節流/慢頁。
- **落地成效** — `patentdb_absorb.{imported, updated, skipped}`:imported=新 row、updated=COALESCE 回補既有(如 title_en 空白件補齊)、skipped=重複無變更。
- **配額防護常數** — `BULK_EXPORT_MAX=5000`(num 硬上限)、`_BULK_PAGE=200`(單頁 expQty)、`_BULK_PAGE_RETRIES=3` + exp-backoff(2s/4s/8s)、頁間 `asyncio.sleep(1.0)`;皆為 TIPO 每日配額/節流的可觀測約束點。
