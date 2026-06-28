# Errors: gpss-session-reuse-batch

## Error Catalogue

每個錯誤碼皆為**顯式結構化訊號**,非靜默 fallback(天條 11)。

| Code / reason | Tool | Message / 條件 | Recovery 策略 | 責任層 |
|---|---|---|---|---|
| `failed` (skip record) | patentmcp_batch_download_figures | 單筆抓圖回 success=false 且非 503 類 | 記入 `skipped[pub]` 帶原始 error;不中斷 batch,續下一筆 | batch 層 |
| `503_detected_added_to_cooldown` | patentmcp_batch_download_figures | 單筆 error 含 503/quota/unavailable/limit | 加入 cooldown skip list(600s),續下一筆 | batch 層 |
| `503_exception_added_to_cooldown` | patentmcp_batch_download_figures | 單筆拋例外且訊息含 503/unavailable | 同上;session 不中斷 | batch 層 |
| `503_cooldown` (skip) | patentmcp_batch_download_figures | pub 仍在 cooldown 視窗內 | 回 `remaining_seconds`,跳過該筆 | batch 層 |
| `exception` (skip record) | patentmcp_batch_download_figures | 單筆拋非 503 例外 | 記 error,續下一筆 | batch 層 |

## 沿用的下游錯誤碼(不改)

| Code | 來源 | 說明 |
|---|---|---|
| `NO_FIGURE_PAGE` / `NO_PDF` / `RENDER_FAILED` | extract_representative_figure | 非 TW 分支下游(PDF pipeline)既有錯誤碼,原樣冒泡進 skip record |
| `Failed to retrieve INFO token from GPSS session` | GPSS scrape impl | GPSS 搜尋頁 INFO token 抓取失敗 |
| `No representative figure found for this patent` | GPSS figure impl | 詳情頁無 TWG1 / 無任何圖 |

## SoftScrapePolicy 行為(非錯誤碼,但屬契約)

- `park_cooldown(s)` / `note_block()` 後,下一次 `guard()` 進入會先 `asyncio.sleep(remaining)` 等過冷卻 —— 這是**顯式延遲**,非錯誤,不丟棄請求。
- `guard()` 為非可重入(`asyncio.Lock`);同一 policy 巢狀 `guard()` 會死鎖 —— 設計上 batch 迴圈不持鎖、per-burst 取鎖避免此情形。

## 反模式(禁止)

- 不得在 batch 非 TW 分支退回 `get_patent()` 取 `representative_figure_url`(該欄位不存在於 get_patent 回傳,且縮圖被禁)。
- 不得在 cooldown 期間靜默繞過 policy 直接打 host。
- 不得把 503 skip 當成 batch 整體失敗(batch 仍回 success=true,逐筆狀態在 downloaded/skipped)。
