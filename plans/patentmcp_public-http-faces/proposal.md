# Proposal: patentmcp_public-http-faces

## Why

- 使用者要讓 `https://cms.thesmart.cc/patentmcp/` 對外開放：根路徑提供 MCP 安裝/使用說明 + 全部 tools schema 的分頁 HTML，並用子路徑分別提供不同 MCP 傳輸面（`/mcp` streamable-http、`/sse` HTTP+SSE、`/webdav` 檔案面），`/uds` 以說明段落呈現同主機 Unix socket 連法。
- 現況阻塞：(1) gateway 對外 web route `/patentmcp`（`/etc/opencode/web_routes.conf`）指向**不存在**的 socket 路徑 `.../vendor/patents-mcp/.run/patentmcp.sock`，實際 socket 在 repo root `.run/patentmcp.sock` → 對外現在連不上；(2) 該 route `auth=1`（需登入），與「對外公開」目標不符；(3) landing page 只列 tool name + 描述首行，無 schema 分頁；(4) 無 `/sse` 面；(5) WebDAV 面掛在 `/dav` 而非 `/webdav`。

## Original Requirement Wording (Baseline)

- "我希望 https://cms.thesmart.cc/patentmcp/ 可以對外開放，頁面提供 mcp 安裝使用說明，以及所有 tools schema（可以編寫成分頁架構），然後用子目錄 /uds, /mcp, /sse, /webdav 等方式去分別提供真正的 mcp 服務。幫我設計/設定。我要從外網打進來試試"

## Requirement Revision History

- 2026-07-15: initial draft created via plan-init.ts
- 2026-07-15: 澄清 3 項決策 — (a) `/uds` 為說明頁段落非對外 endpoint；(b) 認證策略=**全部公開無認證**（使用者明示接受風險，要從外網實測）；(c) tools schema=每個 tool 一個分頁，從 live FastMCP registry 動態生成。SSE 面先實測 `sse_app()` lifespan 行為再決定接法；`/dav` 與 `/webdav` 並存。

## Effective Requirement Description

1. `https://cms.thesmart.cc/patentmcp/` 對外可達且**無認證**（gateway route auth=0）。
2. 修正 gateway route 指向實際 socket `.run/patentmcp.sock`。
3. 根路徑 landing：MCP 安裝/使用說明 + 傳輸面總覽 + `/uds` 本機 socket 連法段落 + tools 索引（連到分頁）。
4. `/patentmcp/tools/{name}`：每個 tool 一個分頁，完整 inputSchema（參數/型別/必填）+ 描述，動態取自 `mcp.list_tools()`。
5. `/patentmcp/mcp`：streamable-http（已存在，維持）。
6. `/patentmcp/sse`：SSE transport（先實測 `sse_app()` 是否可安全 mount；不安全則回報改法，不硬接冒 crash 風險）。
7. `/patentmcp/webdav`：WebDAV 面別名，與現有 `/dav` 並存。
8. 從外網實測全部子路徑。

## Scope

### IN
- `src/patent_mcp_server/_http_app.py` 的 `build_app()`：新增 tool 分頁 handler、landing 擴充、`/webdav` 別名 route、（實測後）`/sse` mount。
- gateway `/etc/opencode/web_routes.conf` 的 `/patentmcp` 條目：socket 路徑導正 + `auth=1`→`auth=0`。
- 從外網 e2e 驗證。

### OUT
- 不改 MCP 工具本身的邏輯 / schema 定義。
- 不動 container compose 傳輸拓樸的既有 UDS+TCP 綁定機制（除非 TCP posture 收斂決策要求）。
- 不新增認證機制（使用者明示要無認證公開）。

## Non-Goals

- 不做細粒度 per-tool 授權（全公開）。
- 不改 `/dav` 現有行為（rclone 相容不可破壞）。

## Constraints

- **單一 app / 單一 lifespan**：`streamable_http_app()` 已把 session-manager lifespan 綁進 app 且只能跑一次；任何新 mount（尤其 `sse_app()`）不得引入第二個 lifespan（會 crash，見 `_http_app.py:427-434` serve() docstring）。
- **DAV href 由 request-path 反推**，不得把 `PATENTS_GATEWAY_PREFIX` 烤進 href（rclone bug 5.5 教訓，`_http_app.py:370-385`）。
- **route 用裸路徑**，gateway strip `/patentmcp` 前綴後轉發；`prefix` 只用於 landing 顯示連結。
- **R15 live-reload**：`src/` 是 bind-mount，改 code 後 `restart` process 即生效，無需 rebuild image。
- **資安**：公開無認證 = 任何人可觸發 BigQuery 計費查詢、爬蟲、檔案下載。plan 需在 threat model 明列並確認為使用者知情接受的風險。

## What Changes

- 對外多一組公開、分子路徑的 HTTP MCP 服務面 + 完整 schema 文件站。
- gateway route 從「壞路徑 + 需登入」變成「正確 socket + 公開」。

## Capabilities

### New Capabilities
- Tools schema 分頁站：`/tools` 索引 + `/tools/{name}` 每工具完整 inputSchema。
- `/webdav` 別名面。
- （條件性）`/sse` transport 面。

### Modified Capabilities
- Landing page：加傳輸面總覽 + `/uds` 本機連法段落 + tool 連結化。
- gateway `/patentmcp` route：socket 導正 + 公開。

## Impact

- 對外資安 posture（公開無認證）— 已在 threat model 記錄、使用者知情。
- `_http_app.py`（唯一 code 改動檔）。
- `/etc/opencode/web_routes.conf`（gateway 設定）。
- 影響對外使用者：新增可用的公開 MCP endpoint + 文件站。
