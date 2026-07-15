# Tasks: patentmcp_public-http-faces

## 1. SSE 面可行性實測（先於任何 SSE 實作）

- [x] 1.1 container 內實測 `mcp.sse_app()`：確認自帶獨立 lifespan + 獨立 SseServerTransport → 定案「自建 SseServerTransport + 裸 route」為安全路徑（DD-5）

## 2. `_http_app.py` 實作（唯一 code 改動檔）

- [x] 2.1 新增 `tool_page(request)` handler：取 `path_params["name"]`，從 `mcp.list_tools()` 找對應 tool，遞迴渲染完整 inputSchema（properties/type/required/enum/default/description），找不到 404（DD-3）
- [x] 2.2 擴充 landing：tool rows 改 `<a href="{prefix}/tools/{name}">`；`/tools` 改為 HTML 索引頁、JSON 移至 `/tools.json`（DD-2/DD-3）
- [x] 2.3 新增 `/webdav/{subject}` + `/webdav/{subject}/{rel:path}` route 指向同一 `dav()` handler（DD-4）
- [x] 2.4 接 `/sse`：自建 `SseServerTransport(f"{prefix}/sse/messages")`，`/sse` 用 Route（避 Mount 307）、`/sse/messages` 用 Mount（DD-5）
- [x] 2.5 tool schema 分頁 CSS + 索引（沿用 `_LANDING_CSS`，schema 用表格 + 原始 JSON `<pre>`）

## 3. gateway route 導正 + 公開

- [x] 3.1 經 ctl.sock（`/run/opencode-gateway/ctl.sock`）remove + publish：socket 路徑 → `.run/patentmcp.sock`、auth=0（publish 天生 auth=0）（DD-6）
- [x] 3.2 publish 即時觸發 `flush_web_routes()`，web_routes.conf 生效：`/patentmcp uds .../.run/patentmcp.sock 0 1000 0`

## 4. 套用與本機驗證

- [x] 4.1 `docker restart patentmcp` 套用 code（R15 bind-mount，無需 rebuild），container healthy 無 lifespan crash
- [x] 4.2 經 UDS 驗證各面：landing 連結化、`/tools` 索引、`/tools/{name}` schema 分頁、未知 404、`/webdav` 401（路由到位）、`/sse` 200 event-stream
- [x] 4.3 經 gateway 127.0.0.1:1080 驗證 strip-prefix 轉發：所有面 200、webdav 別名 200（auth=0 生效）

## 5. 外網 e2e 實測

- [x] 5.1 從外網打 `https://cms.thesmart.cc/patentmcp/`：landing（48 tools）、`/tools`、`/tools/{name}`（完整 schema 分頁）、`/tools.json`、`/sse`（endpoint 帶前綴）全部正常
- [x] 5.2 確認公開無認證可達（webfetch 無憑證即取得內容）

## 6. 收尾

- [x] 6.1 event_record 收尾
- [x] 6.2 architecture.md 同步檢查
- [x] 6.3 threat model 殘餘風險告知使用者

## e2e 驗證結論（2026-07-15）

經 `https://cms.thesmart.cc/patentmcp/` 外網實測：landing / tools.json / tools/{name} / sse / mcp 全部公開直通；`/dav/{subject}` 公開直通 app（app-level 401 Basic auth 正確）。**`/webdav/{subject}` 別名經 gateway 穩定回 login page**（gateway 對 `/patentmcp/webdav/*` 前綴套 login 牆，binary 層行為、非本 repo route config 可改）→ 對外公開 WebDAV 一律用 `/dav/{subject}`，`/webdav` 僅供已認證 gateway session。
