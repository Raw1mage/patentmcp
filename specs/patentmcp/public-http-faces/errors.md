# Errors: patentmcp_public-http-faces

## Error Catalogue

實際錯誤面全部來自 `src/patent_mcp_server/_http_app.py` 的 `build_app()` route handlers +
gateway 前置代理。下表每筆對應可觀察的真實回應。

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| `404 tool_not_found` | `/tools/{name}` 的 `name` 不在 `mcp.list_tools()`（`tool_page` `match is None`，:476-482） | HTML 404，body `Unknown tool: <code>{name}</code>` + 連回 `{prefix}/tools` | 打開 `/tools` 索引取正確 tool name 後重打分頁 |
| `500 tool_registry_unavailable` | live registry 取用失敗（`tool_page`/`tools_json` 的 `mcp.list_tools()` 拋例外，:470-474 / :524-528） | JSON `{"error":"tool_registry_unavailable","detail":...}`，status 500 | 伺服器內部問題（session-manager/註冊表異常）；重試或查 container log；**不 silent `[]` fallback**（設計即 fail-loud） |
| `landing 靜默降級空表` | landing (`/`) 的 `mcp.list_tools()` 失敗（:552-554 `except → tools=[]`） | HTTP 200，landing 正常渲染但工具表為空 | 與 `/tools.json` 的 500 對照即可辨識 registry 是否真的掛；landing 刻意不 500（頁面仍可讀安裝說明） |
| `401 webdav unauthorized` | `/dav/{subject}` 或 `/webdav/{subject}` 無 / 錯 Basic 憑證（`dav()` `_auth.resolve_identity` 回 `AuthError`，:594-599） | XML `<error><code>unauthorized</code>...`，status 401 + `WWW-Authenticate: Basic realm="patentmcp-webdav"` | client 帶正確 Basic 憑證（cache token 的 owner username + secret）重試 |
| `403 webdav forbidden` | 憑證有效但非該 subject cache 的 owner（cross-owner probe，`dav()` `not _auth.owns`，:602-606） | XML `<error><code>forbidden</code><detail>identity does not own this subject cache</detail>`，status 403 | 只能存取自己 owner 名下的 cache；跨 owner 一律 403，無 fallback |
| `404 file not_found` | `/files/{token}/blob/{rel}` 的 token/rel 解不到 blob（`blob()` `store.blob_path` 拋例外，:509-512） | JSON `{"error":"not_found","detail":...}`，status 404 | 確認 token 有效且 rel 路徑存在於該 cache |
| `404 skill_not_found` | `/skills/patentworks.zip` 但 skills 目錄無 `patentworks/`（`skill_zip`，:541-542） | JSON `{"error":"skill_not_found","skill":"patentworks"}`，status 404 | host 未部署 skill 套件；landing 也會顯示 `skill_unavailable`（`_skills_root()` 判斷） |
| `gateway login wall（webdav 別名）` | 外網經 gateway 打 `/patentmcp/webdav/*`（gateway binary 對此前綴套 login 牆，非本 repo route config） | gateway 回 login page（非 app 401） | 對外公開 WebDAV 一律用 `/dav/{subject}`；`/webdav` 僅供已認證 gateway session（tasks.md e2e 結論 2026-07-15） |
| `gateway UDS 連線失敗` | gateway 的 `/patentmcp` route socket 路徑錯 / socket 不存在 / container down（web_routes.conf `uds .../.run/patentmcp.sock`） | gateway 層 502/503（app 未觸及） | 確認 `.run/patentmcp.sock` 存在（`docker restart patentmcp` 重建）；確認 web_routes.conf socket 路徑指向 repo root 而非舊 `vendor/...` 路徑 |
| `mcp -32600 Missing session ID` | client 未先 `initialize` 就 POST `tools/list`（Streamable-HTTP 握手順序錯，FastMCP session-manager 拒絕） | JSON-RPC error `-32600`，經 SSE data 行回傳 | 先 POST `initialize` 取 `mcp-session-id`，後續請求全帶該 header（landing handshake checklist 已明列，:94/:119） |

## SSDLC 面：無認證公開的暴露風險與緩解

gateway route `auth=0`（DD-6/DD-7），對外任何人無需憑證即可觸及下列面。這是**使用者知情接受**的設計決策；
以下為暴露風險與現有緩解（對應 design.md Threat Model）：

| 暴露面 | 風險（無認證公開後任何人可觸發） | 現有緩解 | 殘餘風險 / 建議 |
| ---- | ---- | ---- | ---- |
| `/mcp` `/sse`（MCP 工具呼叫） | 觸發 BigQuery 計費查詢，成本可被外部累積 | `BIGQUERY_MAX_BYTES_BILLED` 單 query 上限 + `BIGQUERY_MAX_RESULTS` | 可被大量呼叫累積成本；**建議 follow-up rate-limit**（OUT of scope） |
| `/mcp` `/sse`（爬蟲工具） | 觸發對上游（Google Patents 等）爬蟲，可能損及本站 IP 信譽 | 爬蟲尾級需 `allow_scraping=true` 明示才啟用 | 公開後任何人可觸發；使用者接受 |
| `/files/{token}` `/dav` `/webdav`（檔案/快取讀取） | 未授權讀取他人 cache 檔案 | `/files` token 需有效；WebDAV 有 Basic auth（app-level，route auth=0 不影響）+ ownership check（cross-owner 403） | 僅 token 洩漏才可讀；per-cache 授權在 route auth=0 下**仍然生效**（app 自己驗） |
| `/tools` `/tools/{name}` `/tools.json`（schema 全公開） | tool inputSchema 全對外揭露 | — | 設計即公開文件站，非威脅 |
| 全部面（Host header 信任） | DNS rebinding | `enable_dns_rebinding_protection=False`（:292-294）；gateway 為信任邊界，Host 由 proxy 設定 | gateway 前置為信任邊界，無額外殘餘 |

**關鍵不變式**：route auth=0 只解除 gateway 層登入牆，**不解除 app 自身的 WebDAV Basic auth + ownership check**
（`_auth_provider.py`）。故 `/webdav` `/dav` 面即使公開路由，per-cache 授權依舊由 app 把關（401/403 如上表）。

<!-- observability 面詳見 observability.md：每個對外請求經 `_access_log_mw` 落一筆 category='access'，
     可用於偵測異常呼叫量（rate-limit 建議的觀測基礎）。 -->
