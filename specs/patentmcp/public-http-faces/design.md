# Design: patentmcp_public-http-faces

## Context

patentmcp 是 FastMCP-based server，跑在 per-user container，透過 `_http_app.py` 的 `build_app()` 在**單一 Starlette app** 上掛所有 HTTP 面（app 基底 = `mcp.streamable_http_app()`，session-manager lifespan 已綁入且只能跑一次）。對外由 opencode gateway 以 `https://cms.thesmart.cc/patentmcp/...` 代理，gateway 走 UDS 連進 container、strip `/patentmcp` 前綴後轉發裸路徑。

現況：landing 只列 tool name+desc 首行；`/mcp` 已掛（FastMCP 內建）；WebDAV 面掛在 `/dav`；無 `/sse`；gateway route `/patentmcp` 指向不存在的 socket 路徑且 auth=1。使用者要對外公開（無認證）、加 schema 分頁站、加 `/webdav` 別名、（實測後）加 `/sse`。

## IDEF0 Skeleton（architecture hung on this）

本設計掛在 idef0.json 的三個頂層 activity 上：

- **A1 渲染文件站** — landing + tools schema 分頁（DD-2/DD-3）：從 live registry 動態產出安裝說明、傳輸面總覽、`/uds` 段落、tool 索引與每工具 schema。
- **A2 多傳輸面請求分派** — 單一 Starlette app / 單一 streamable lifespan 上分派 `/mcp` `/sse` `/webdav` `/files`（DD-1/DD-4/DD-5）；SSE 用自建 `SseServerTransport` 避開第二 lifespan。
- **A3 gateway 對外代理與公開暴露** — gateway strip `/patentmcp` 前綴走 UDS 轉發；route 導正 socket + auth=0（DD-6/DD-7）。

下方 Decisions 全部對應這三個 activity：A1←DD-2/DD-3；A2←DD-1/DD-4/DD-5；A3←DD-6/DD-7。

## Goals / Non-Goals

**Goals**

- `https://cms.thesmart.cc/patentmcp/` 對外公開可達，landing 提供安裝說明 + 傳輸面總覽 + `/uds` 本機連法段落 + tool 索引。
- `/tools/{name}` 每工具完整 inputSchema 分頁，動態取自 live registry。
- `/webdav` 別名與 `/dav` 並存；條件性 `/sse`。
- gateway route 導正 + 公開；從外網 e2e 通過。

**Non-Goals**

- 不改工具邏輯 / schema 定義；不破壞 `/dav` rclone 相容；不加認證。

## Decisions

- **DD-1: 單一改動檔 `_http_app.py`，全部 route 追加在 `build_app()` 的 `app.router.routes.extend([...])`（:396-411）。** 理由：現有結構已是「一個 app、一個 lifespan、N 個 route」的正確形態；沿用即可，避免第二個 ASGI app / 第二個 lifespan。

- **DD-2: `/uds` 不是對外 endpoint，是 landing 上的說明段落。** 理由：UDS 只存在於 gateway↔container 內部，外網不可能「透過 UDS」連入。landing 提供同主機使用者 `curl --unix-socket .run/patentmcp.sock` 與 stdio `.mcp.json` 的連法。

- **DD-3: tools schema 分頁複用 `mcp.list_tools()` + `t.inputSchema`（與 `/tools` JSON、landing 同源零漂移）。** 新增 `async def tool_page(request)` handler 取 `request.path_params["name"]`，找到對應 tool 渲染其完整 inputSchema（遞迴渲染 properties/type/required/enum/default/description）。找不到 → 404。landing 的 tool rows 改成 `<a href="{prefix}/tools/{name}">`。新增 `Route("/tools/{name}", tool_page, methods=["GET"])`。

- **DD-4: `/webdav` 與 `/dav` 並存（別名）。** 保留 `/dav`（rclone/現有 client 不斷），額外加一組 `/webdav/{subject}` + `/webdav/{subject}/{rel:path}` route 指向同一 `dav()` handler。**關鍵：`dav()` 的 `base_href` 由 request-path 反推（:377-385），故同一 handler 在兩個 mount prefix 下都正確**——不需改 handler，只加 route。`mount_prefix` 參數傳實際命中的 prefix（`/dav` 或 `/webdav`），使 `_dest_rel` 的 MOVE/COPY Destination 比對正確。

- **DD-5【實測定案】: `/sse` 用「自建 `SseServerTransport` + 加兩條裸 route」，不 mount `sse_app()`。** 實測結論（container `/app/server/.venv/bin/python`，mcp SDK python3.13）：`mcp.sse_app()` 回傳的 Starlette **自帶獨立 `lifespan_context`**，且用**獨立 `SseServerTransport`**（非 streamable 的 session-manager）。→ 直接 `Mount("/sse", mcp.sse_app())` 會把第二個 lifespan 帶進主 app，double-enter → crash（正是 serve() docstring :427-434 的場景）。**安全接法**：`sse_app()` 的 `handle_sse` 每次連線各自 `sse.connect_sse()` + `self._mcp_server.run(...)`，transport 本身**不需要 app-lifespan 啟動**。故自建 `sse = SseServerTransport(message_path)`，把「SSE GET endpoint」(`handle_sse`) + 「message POST endpoint」(`sse.handle_post_message`) 兩條 route 直接加進主 app 的 `.extend([...])`，繞開帶 lifespan 的 Starlette 包裝。主 app 維持單一 streamable lifespan 不變。message_path 需 prefix-aware（見 DD-4 base_href 反推同理，避免 gateway prefix 破壞回傳的 endpoint URL）。

- **DD-6: gateway route 導正 + 公開。** `/etc/opencode/web_routes.conf` 的 `/patentmcp` 條目：socket 路徑 `.../vendor/patents-mcp/.run/patentmcp.sock` → `/home/pkcs12/projects/patentmcp/.run/patentmcp.sock`；`auth=1` → `auth=0`。這是使用者明示的公開決策。

- **DD-7: 公開無認證的資安風險為使用者知情接受。** 對外任何人可觸發 BigQuery 計費查詢（有 `BIGQUERY_MAX_BYTES_BILLED` 上限保護）、爬蟲、token 檔案下載（需有效 token）。WebDAV 面仍保留 token-store Basic auth（`_auth_provider.py`），故 `/webdav` 不因 route auth=0 而失去 per-cache 授權。threat model 見下。

## Threat Model (ssdlc)

| 威脅 | 對外面 | 現有緩解 | 殘餘風險 |
|---|---|---|---|
| 未授權呼叫計費工具（BigQuery） | `/mcp` `/sse` | `BIGQUERY_MAX_BYTES_BILLED` 單query上限 + `BIGQUERY_MAX_RESULTS` | 可被大量呼叫累積成本；使用者接受，建議後續加 rate-limit |
| 爬蟲濫用 / 對上游 IP 信譽 | `/mcp` `/sse` | 爬蟲尾級需 `allow_scraping=true` 明示 | 公開後任何人可觸發；使用者接受 |
| 未授權檔案讀取 | `/files/{token}` `/webdav` | token 需有效；WebDAV 有 Basic auth + ownership check（cross-owner 403） | token 洩漏才可讀；per-cache 授權仍在 |
| DNS rebinding | 全部 | `enable_dns_rebinding_protection=False`（gateway 為信任邊界，:255-257） | gateway 前置為信任邊界，無額外殘餘 |
| 資訊揭露（tool schema 全公開） | `/tools` `/tools/{name}` | — | 設計即公開，非威脅 |

## Risks / Trade-offs

- **SSE lifespan 衝突** — mitigation: DD-5 先實測，不安全不接。
- **`/webdav` mount_prefix 傳錯導致 MOVE/COPY 誤判** — mitigation: 傳實際命中 prefix，沿用 base_href request-path 反推。
- **公開無認證成本濫用** — mitigation: BigQuery bytes-billed 上限已在；threat model 記錄；建議 follow-up rate-limit（OUT of scope）。
- **gateway route 改壞導致全斷** — mitigation: 改前備份 web_routes.conf；改後先本機經 gateway 驗證再從外網測。

## Critical Files

- `src/patent_mcp_server/_http_app.py` — 唯一 code 改動檔。`build_app()`（:232-412）掛全部 HTTP 面；`_landing_html()`（:159-229）landing 渲染；`tools_json()`（:277-296）schema 來源；`dav()`（:335-394）WebDAV handler（base_href request-path 反推）。
- `src/patent_mcp_server/_dav.py` — `DAV_METHODS`（:38-41）；`/webdav` 別名沿用同 handler。
- `/etc/opencode/web_routes.conf` — gateway `/patentmcp` route（socket 導正 + auth）。
- `docker-compose.yml` — `PATENTS_GATEWAY_PREFIX=/patentmcp`（:86）；`src/` bind-mount 支援 R15 live-reload（改 code 後 restart 生效）。
