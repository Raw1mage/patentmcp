# Design: patentmcp_gpss-web-boolean-search

## Context

現有 `patents.py` 的 gpss3 網頁爬蟲基礎設施 (`_gpss_client` + `_GPSS_POLICY` + `_gpss_extract_info` + `_gpss_extract_action` + `_gpss_iter_result_rows` + `_gpss_select_detail_link`) 只實作到「單號 → 詳目 → 抓圖」(`gpss_download_representative_figure`)。沙盤推演 (2026-07-16, event `patentworks/event_2026-07-16_gpss-us-gpss-epo`) 證實：同一套 handshake 可承載**單一欄位化括號布林檢索式**，GPSS 布林表達力不弱，且網頁路徑檢索不燒 API quota。本 spec 在既有基礎設施上加一條「布林檢索計數 / 書目」能力。

## Goals / Non-Goals

**Goals**

- 新增 `gpss_web_search` MCP 工具：gpss3 人類路徑、單一欄位化括號布林式、回各資料庫精確命中數 + 結果列書目、零 API 額度。
- 內建限縮：日期範圍、國別 / 資料庫。
- 大母數 (>30萬) fail-fast + 限縮提示，不救。
- 最大化複用既有 handshake / policy / 結果列解析，不重造。

**Non-Goals**

- 不下載 PDF / 圖式 (既有工具職責)。
- 不改 `gpss_api` REST 路徑與 `patent_search` 來源梯。
- 不改 US→EPO 路由決策 (本工具僅提供能力證據)。
- 不做需登入帳號的加值功能 (統計 / 圖表 / 專案資料夾)。

## Decisions

- **DD-1: 走網頁人類路徑，不走 `gpss_api` REST**。動機是省 API 額度 + 繞 condition-length 硬閘 (該閘只掐 API 端)。代價是依賴 gpss3 HTML 結構 (脆於 API)，用既有 `_gpss_extract_*` 正則模式吸收。**已拒方案**：擴 `gpss_api` 支援布林——會燒 quota 且撞 condition-length 牆 (本身就是 BR_20260715 的根因)。

- **DD-2: 單一檢索式字串承載一切 (欄位 / 布林 / 日期 / 國別)**。推演證實 `_21_1_T` 是通用文字檢索欄位 (T_XX 型，size=100)，欄位限定靠字串內 `@TI`/`@AB` 語法、日期靠 `ID=YYYYMMDD:YYYYMMDD`、跨欄位布林靠 `(A)@TI not (B)@AB`。**不重構表單分欄**——這正是使用者洞察「只要能產生單一檢索式就能解決」。資料庫別 (patDB) 是唯一走獨立 POST 參數的限縮 (與 `_gpss_download` 現況一致)。

- **DD-3: 精確筆數走 `ttsserv_watch` AJAX 輪詢**。第一發搜尋 POST 只回結果頁框架 (title=「全部結果超過30萬筆」模糊上限)，各資料庫精確命中數由結果頁 JS 非同步呼叫 `/gpss3/gpsskmc/ttsserv_watch?` 載入 (對應官方文件「非同步顯示，未顯示筆數代表該庫仍在檢索中」)。工具須輪詢此端點至各庫筆數就緒。**t7 探偵已解除 (2026-07-16)**：端點組法 `/gpss3/gpsskmc/ttsserv_watch?<kmtmp>/km.swp:102:1:<URL編碼"全部">:`；`kmtmp = ptmp.substr(0, ptmp.indexOf("/"))`(ptmp 為結果頁檢索暫存 key)；回應由 `transferULLI(d)` 逐子資料庫解析 `subdbname(rec)` 格式(subdbname=庫名、rec=括號內命中數、subdb_no=`href.split("^")[1]`-2)。實作 A4 依此輪詢至各庫 rec 就緒。

- **DD-4: 大母數 >30萬 fail-fast，不救**。命中觸及 GPSS 模糊上限時回結構化錯誤 `{error_code: "GPSS_WEB_RESULT_TOO_BROAD", hint: "加日期/國別/收窄布林"}`，不嘗試分頁窮舉、不回巨量無意義結果。對齊使用者原則「只關心有意義的檢索結果」。無 fallback (使用者天條)。

- **DD-5: 檢索式語法驗證前置**。POST 前先驗欄位代碼白名單 (TI/AB/CL/AX/IV/ID/IPC/CPC…)、`@欄位` 後綴合法性、括號配對。非法 → `INVALID_PARAMS` 零網路呼叫 (省一次 handshake + 節流)。

- **DD-6: Cloudflare 節流沿用 `_GPSS_POLICY`**。所有請求 (handshake + 搜尋 POST + ttsserv_watch 輪詢) 序列化走既有 SoftScrapePolicy，不並行。輪詢加最大次數 + 逾時上限，避免無限輪詢燒節流預算。

## Risks / Trade-offs

- **gpss3 HTML 結構變動** — mitigation: 複用既有 `_gpss_extract_*` 正則集中處理，變動時單點修；加結構性斷言 (INFO token 抽不到 → fail-fast 非靜默空結果)。
- **`ttsserv_watch` 回應格式未知** — mitigation: t7 探偵先釘死真實 payload/回應再實作，不憑猜建工具。
- **輪詢逾時 / 部分資料庫慢** — mitigation: 最大輪詢次數 + 逾時，回「部分庫就緒」時明示哪些庫仍在檢索 (對齊官方非同步語義)，不假裝完整。
- **Cloudflare Managed Challenge** — mitigation: 沿用 `_GPSS_POLICY` Concurrency=1 + pacing + cooldown，與既有抓圖工具共用 cf_clearance 續連指紋。

## Architecture (derived from IDEF0 skeleton)

本工具的執行架構挂在 idef0.json 的 A0 分解 (A1-A5) 上，每個活動對應一個實作關卡：

- **A1 驗證檢索式語法** → `gpss/` 新增語法驗證 helper (DD-5)；欄位代碼白名單 + `@欄位` 後綴 + 括號配對 + 日期語法；非法即 `INVALID_PARAMS` 零網路呼叫。
- **A2 建立 handshake** → 複用 `_gpss_client` + `_GPSS_POLICY` + `_gpss_extract_info` + `_gpss_extract_action` (DD-1/DD-6)；Cloudflare cf_clearance 續連、序列化節流。
- **A3 提交單一檢索式 POST** → 單一字串塞 `_21_1_T`、國別經 `patDB` (DD-2)；payload 形狀參照 `_gpss_download_representative_figure_impl` Step 4。
- **A4 輪詢 AJAX 筆數** → `ttsserv_watch` 端點輪詢至各庫就緒 (DD-3)；最大輪詢次數 + 逾時保護。
- **A5 判母數 + 解析書目 / fail-fast** → >30萬 → `GPSS_WEB_RESULT_TOO_BROAD` (DD-4)；否則複用 `_gpss_iter_result_rows` 解析結果列書目。

GRAFCET (grafcet.json) 把上述 A1-A5 展開成執行態機：語法分岔 (step 2←90)、handshake 分岔 (4↑91)、AJAX 輪詢迴圈 (6↔7)、母數分岔 (8↑92/9)。

## Critical Files

- `src/patent_mcp_server/patents.py` — 新增 `gpss_web_search` 工具 + 內部實作；複用 `_gpss_client` (line ~209)、`_GPSS_POLICY` (line ~179)、`_gpss_extract_info` (line ~1747)、`_gpss_extract_action` (line ~1757)、`_gpss_iter_result_rows` (line ~1766)、`_gpss_select_detail_link` (line ~1786)。搜尋 POST payload 形狀參照 `_gpss_download_representative_figure_impl` Step 1-5 (line ~2033)。
- `src/patent_mcp_server/gpss/` — 新增檢索式語法驗證 helper (欄位代碼白名單 + `@欄位` 語法檢查)。
- MCP 工具註冊點 — 暴露 `gpss_web_search`。
- `skills/patentworks/SKILL.md` — 來源梯 GPSS 條目補網頁路徑檢索工具使用紀律。
- `specs/architecture.md` — 補 gpss3 網頁檢索路徑 (compute plane) 說明。

## Code Anchors (探偵已證實事實)

- 搜尋 POST 入口欄位：`_21_1_T` (通用文字，塞完整檢索式)；`@_21_1_T=T_XX` 隨附。
- AJAX 筆數端點：`/gpss3/gpsskmc/ttsserv_watch?`。
- 結果視圖：`gpssbkm?<state>^L^` (List) / `^P^` (Print) / `^S^` (Statistics)。
- mode-switch：`gpssbkm?.<40hex>` 切號碼/布林/進階/表格 (本工具塞 `_21_1_T` 即可，不需切布林頁)。
- 大母數上限標記：結果頁 `title="全部結果超過30萬筆"`。
