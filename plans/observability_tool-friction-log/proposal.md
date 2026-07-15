# Proposal: observability_tool-friction-log

## Why

- patentmcp 對外常駐服務中,但工具層的 error 與「靜默磨擦」目前無可持久、可事後查詢的觀測機制。
- 錯誤現散落三路且互不相通:(1) stderr 純文字 log(docker logs,重啟即失、無法機器解析)、(2) 回傳 envelope 的 `error_code`/`provenance`(只回呼叫端不落地)、(3) `logger.warning(...) + continue` 靜默吞掉(約 25+ 處,飄 stderr 即失)。
- 沒有一個地方能事後回答「這個 tool call 為什麼失敗」「哪個來源最常磨擦」「哪個工具最常吞錯」。

## Original Requirement Wording (Baseline)

- "patentmcp目前對外服務中。有沒有辦法建立一個log機制來觀察服務中是否內部工具遇到什麼error或磨擦?"

## Requirement Revision History

- 2026-07-15: initial draft created via plan-init.ts
- 2026-07-15: 使用者拍板三決策 — (1) SQLite 儲存 (2) 只記 Error + 靜默磨擦 (3) 無 MCP 查詢工具/報告,開發時直接叫 agent 讀 sqlite。
- 2026-07-15(unified 擴充): 使用者要求「至少要能記錄 HTTP W3C access log」+「既然要 log 就做一個 unified log mechanism」→ friction-only 一般化為 unified observability log(單一 store,friction + access 同表,category 區分);新增 ASGI access-log middleware(全部 HTTP 請求,W3C 語義,SQLite)。

## Effective Requirement Description

1. 在 FastMCP 工具註冊 choke point 包一層薄 wrapper,攔截**所有** `@mcp.tool()` 工具的未捕捉 exception,結構化記一筆 friction 事件。
2. 提供一個 helper,讓現有「`logger.warning(...) + continue`」的靜默磨擦點主動記一筆(source ladder miss、absorb 失敗、throttle、SCRAPING_REQUIRED 等)。
3. 事件落地 SQLite,寄生於現有 `./patentdb` bind-mount(rebuild 存活,不需新 volume)。
4. 無 MCP 查詢工具、無 cron 報告 — 觀測方式為開發時由 agent 直接讀 sqlite。

## Scope

### IN
- 工具層 exception 中央攔截(wrap `@mcp.tool()`)。
- 靜默磨擦顯式埋點 helper + 在既有 warning+continue 熱點呼叫。
- SQLite friction store(schema + 寫入函式,寄生 `/patentdb/friction.sqlite`)。
- 寫入永不影響工具主流程(fail-open:log 自身出錯只吞掉,不 raise)。

### OUT
- 新增 MCP 查詢工具 / 儀表板 / cron 報告(使用者明確不要)。
- 全部 tool call 成功事件(只記 error + 磨擦,訊噪比優先)。
- 改動現有 error envelope / provenance 契約(只旁路記錄,不改回傳)。
- httpx transport 層 request/response log(已有 LoggingTransport,非本案)。

## Non-Goals

- 不做 metrics/telemetry 匯出(Prometheus 等)。
- 不改 stderr logging 行為(維持現狀,friction store 是旁路增量)。

## Constraints

- 攔截層不得破壞 FastMCP 對工具 signature/schema 的內省(參數名、type hints、docstring 必須透傳)。
- 寫入必須 fail-open:friction store 掛掉時工具照常運作。
- SQLite 落點 `/patentdb/friction.sqlite` 對齊現有 `PATENTS_DB_ROOT` env 與 bind-mount。
- 純 Python、live bind-mount,改完 `webctl.sh restart` 即生效,無需 image rebuild。

## What Changes

- 新增 `src/patent_mcp_server/friction_log.py`:SQLite store + `record_friction()` + `friction_tool()` decorator wrapper。
- `patents.py`:`@mcp.tool()` 改為經 wrapper 註冊(或 monkeypatch mcp.tool),既有靜默磨擦熱點插入 `record_friction(...)`。

## Capabilities

### New Capabilities
- friction-log:工具層 error 與靜默磨擦的結構化、可持久、可 SQL 查詢的觀測記錄。

### Modified Capabilities
- 既有靜默磨擦點:除了 `logger.warning` 外,額外落一筆結構化 friction 事件(行為不變,只增記錄)。

## Impact

- 影響 `src/patent_mcp_server/patents.py`(工具註冊 + 熱點埋點)、新增 `friction_log.py`。
- 落地檔 `/patentdb/friction.sqlite`(既有 bind-mount)。
- 對呼叫端 API 契約零影響(旁路記錄)。
