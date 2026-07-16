# Handoff: patentmcp_gpss-web-boolean-search

## Execution Contract

實作 `gpss_web_search` MCP 工具：走 gpss3 人類登入路徑、接受單一欄位化括號布林檢索式、回各資料庫精確命中數 + 結果列書目、零 API 額度。**Done 定義**：tasks.md 全 6 phase 勾完、測試 5.1-5.6 通過、SKILL/architecture 同步、plan-validate PASS。

## Required Reads

- `design.md` — DD-1~6 (網頁路徑決策、單一檢索式承載、ttsserv_watch AJAX、30萬 fail-fast、語法驗證前置、節流複用)
- `data-schema.json` — envelope 結構、錯誤碼、gpss3 表單欄位事實 (`_21_1_T` / `patDB` / `ttsserv_watch`)
- `knowledge-base/gpss-search-syntax/gpss-query-syntax.md` — 完整 GPSS 查詢語法 (欄位代碼、`@欄位`模糊 vs `欄位=`完全、跨欄位布林)
- `src/patent_mcp_server/patents.py` — 既有 gpss3 爬蟲基礎設施 (line ~179 `_GPSS_POLICY`、~209 `_gpss_client`、~1747 `_gpss_extract_info`、~1757 `_gpss_extract_action`、~1766 `_gpss_iter_result_rows`、~2033 `_gpss_download_representative_figure_impl` Step 1-5)

## Stop Gates In Force

- **t7 (探偵 ttsserv_watch) 是實作前置硬閘**：`ttsserv_watch` 真實 payload/回應格式未探明前，不得動 A4 輪詢實作 (避免建在猜測上)。
- **語法驗證白名單需人工複核**：欄位代碼白名單直接影響誤拒/誤放，定稿前對照 KB §8 欄位代碼表。
- **不新增 fallback (使用者天條)**：任何 fail-fast 路徑不得靜默降級或誤呼叫 `gpss_api` REST。

## Execution-Ready Checklist

- [ ] design.md DD-1~6 已讀且理解網頁路徑 vs API 平面差異
- [ ] gpss-query-syntax KB 已讀 (欄位代碼 + 兩種欄位限定語義)
- [ ] 既有 `_gpss_*` 基礎設施已讀 (複用而非重造)
- [ ] `ttsserv_watch` AJAX 真實 payload 已探明 (t7 完成)
- [ ] XDG scratch 就緒 (探偵/中間 HTML 落 `$XDG_RUNTIME_DIR`，非 /tmp)
