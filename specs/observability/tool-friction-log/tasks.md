# Tasks: observability_tool-friction-log

## 1. friction store 核心

- [x] 1.1 新增 `friction_log.py`:SQLite schema(單表 `friction_events`)+ lazy-init connection(WAL、`CREATE TABLE IF NOT EXISTS`、落點 `PATENTS_DB_ROOT`/friction.sqlite)
- [x] 1.2 實作 `record_friction(kind, tool, source?, reason, detail?, args_summary?)`:fail-open 寫入(整段 try/except 吞掉、絕不 raise)
- [x] 1.3 實作 reason 正規化 helper(exception → `http_error:NNN`/截斷字串,複用 search_dispatcher 模式;args 只存摘要不存憑證)

## 2. 中央 exception 攔截層

- [x] 2.1 實作 `friction_tool()` decorator wrapper(包 `mcp.tool()`,`functools.wraps` 保留 signature/schema,try/except 捕捉 → `record_friction(kind="exception")` → re-raise)
- [x] 2.2 在 `patents.py` 把工具註冊切換成經 wrapper(或 monkeypatch `mcp.tool`),確保全部 45+ 工具覆蓋

## 3. 靜默磨擦顯式埋點

- [x] 3.1 首批高價值熱點加 `record_friction(kind="silent", ...)`:absorb 失敗、source ladder 級 miss/error、EPO throttle、SCRAPING_REQUIRED

## 5. Unified 擴充(access log + 統一 store)

- [x] 5.1 一般化 store:單表 `events` + `category`(friction|access)+ 統一 `record_event()` + `record_friction`/`record_access` 薄包裝(落點改名 observability.sqlite)
- [x] 5.2 新增 ASGI access-log middleware(W3C 語義:method/uri/status/duration/client_ip/user_agent/mcp_client)到 `_http_app.py` build_app 尾端(修 middleware 包裝時機 AttributeError bug)
- [x] 5.3 驗證:access row 落地(mcp_client=opencode 辨識來客)+ friction 仍運作 + schema 內省完好 + restart 健康

## 4. 驗證

- [x] 4.1 `webctl.sh restart` 後服務健康,`patentmcp_init` 正常(攔截層未破壞 doctrine loader)
- [x] 4.2 tools/list 對照:任一工具參數 schema 未因 wrapper 改變(FastMCP 內省完好)
- [x] 4.3 故意觸發一個 error(如非法參數工具呼叫)→ 確認 `friction.sqlite` 有對應 row;讀表驗證欄位正確
- [x] 4.4 觸發一個靜默磨擦(如 source ladder 部分 miss)→ 確認 kind=silent row 落地
- [x] 4.5 fail-open 驗證:DB 路徑不可寫時工具照常運作(no-op 降級)
