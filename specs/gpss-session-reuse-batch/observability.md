# Observability: gpss-session-reuse-batch

## Events

| 訊號 | 來源 | log level | 用途 |
|---|---|---|---|
| `[TIPO-GPSS] scrape pacing {d:.2f}s` | SoftScrapePolicy.delay (GPSS) | DEBUG | 確認 GPSS 序列化+節流實際生效 |
| `[USPTO-ppubs] scrape pacing {d:.2f}s` | SoftScrapePolicy.delay (ppubs) | DEBUG | 確認 ppubs 主動節流生效 |
| `[{name}] waiting out {r:.1f}s cooldown before request` | SoftScrapePolicy.guard | INFO | cooldown 等待中(被擋後降速) |
| `[{name}] cooldown parked for {s:.0f}s` | SoftScrapePolicy.park_cooldown | WARNING | host block 後停park |
| `[{name}] host block observed ({detail})` | SoftScrapePolicy.note_block | ERROR | 觀測到 429/403/challenge |
| `GPSS scrape session close failed: {e}` | _GpssScrapeSession.close | WARNING | session 關閉異常(不影響結果) |

## Metrics

（建議追蹤，非強制）

- `scrape_pace_seconds{host}`：每筆 pace 延遲(觀測節流強度)。
- `scrape_cooldown_parked_total{host}`：cooldown 停park 次數(觀測被擋頻率)。
- `batch_session_reuse_items`：單一 session 內處理的筆數(觀測 cookie 復用效益)。
- `batch_skipped_total{reason}`：各 skip 原因計數。

## Invariants（可觀測保證）

- **INV-1**：任一時刻對單一 host(tipo.gov.tw / ppubs.uspto.gov)的爬蟲 HTTP 請求數 ≤ 1。違反訊號:同一 policy 出現重疊 guard 進入而無對應釋放。
- **INV-2**：一個 batch 全程只建立一個 `_GpssScrapeSession`(一個 httpx client)。違反訊號:`_GpssScrapeSession.__init__` 在單次 batch 內被呼叫 > 1 次。
- **INV-3**：cooldown park 後,下一次 guard 進入必先等過剩餘冷卻才送請求(無「park 後立即再 burst」)。
- **INV-4**：batch 非 TW 分支永不呼叫 `get_patent()` 取 `representative_figure_url`,永不落地 60x80 縮圖。
- **INV-5**：`guard()` 不丟棄請求 —— 每次進入的 body 都會執行(序列化非 rate-drop)。

## Debug Map

- 節流邊界:`util/soft_scrape.py` `SoftScrapePolicy.guard` 的 lock acquire / cooldown wait / pace log。
- session 復用邊界:`_GpssScrapeSession` 建立計數 + 單一 client id。
- batch 路由邊界:`patentmcp_batch_download_figures` 的 TW/非TW 分支 + downloaded/skipped 分類。
- ppubs 節流邊界:`PpubsClient.make_request` 的 guard + 429/403 park log。
- 既有限流參考(不動):`gpatents/client.py` `_get` 的 cooldown log(模範生)。
