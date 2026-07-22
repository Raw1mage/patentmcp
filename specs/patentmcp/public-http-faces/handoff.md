# Handoff: patentmcp_public-http-faces

## Execution Contract

- **Deliverable**：patentmcp 對外 HTTP 面重構已完成並 verified —— 對外 `https://cms.thesmart.cc/patentmcp/` 公開（gateway auth=0）可達，landing + `/tools/{name}` schema 分頁（動態取自 live registry）、`/webdav` 別名與 `/dav` 並存、條件性 `/sse`、gateway strip `/patentmcp` 前綴走 UDS。
- **Done 定義**：唯一 code 改動檔 `src/patent_mcp_server/_http_app.py` 的 `build_app()` 掛齊所有 route；gateway `/patentmcp` route 導正 socket + auth=0；外網 e2e 全部子路徑實測通過（tasks.md §5 已 [x]）。本 plan 已 verified，此 handoff 作為 living 後任何 amend/sync 的執行契約基準。
- **不做**（Non-Goals）：不改工具邏輯 / schema 定義；不破壞 `/dav` rclone 相容；不加認證（公開無認證為使用者明示決策）。

## Required Reads

執行任何 `_http_app.py` HTTP 面相關的 amend / debug 前，MUST 先讀：

- `plans/patentmcp_public-http-faces/design.md` —— DD-1..DD-7 決策 + Threat Model（單一 app/單一 lifespan 約束、DAV base_href request-path 反推、SSE 自建 transport 而非 mount sse_app()）。
- `plans/patentmcp_public-http-faces/proposal.md` —— Effective Requirement + Constraints（尤其「單一 lifespan」「DAV href 不烤 prefix」「R15 live-reload」三條硬約束）。
- `src/patent_mcp_server/_http_app.py` —— `build_app()`（:269-676）掛全部面；`_landing_html()`（:190-266）；`dav()`（:576-635）；access-log middleware `_access_log_mw`（:308-350）。
- `src/patent_mcp_server/_dav.py` —— `DAV_METHODS`、`DavHandler`；`/webdav` 別名沿用同 handler。
- `src/patent_mcp_server/_auth_provider.py` —— WebDAV Basic auth + ownership check（route auth=0 下仍生效）。
- `errors.md` / `observability.md`（本 package）—— 錯誤面 + 每請求 access-log 觀測契約。

## Stop Gates In Force

- **gateway route 改動（`/etc/opencode/web_routes.conf` / ctl.sock publish）為 destructive** —— 改壞會讓對外全斷。改前備份、改後先本機經 gateway（127.0.0.1:1080）驗證再從外網測。需使用者知情。
- **公開無認證 posture 變更** —— 加認證 / 收緊 auth 屬 architecture_change，需使用者確認（現況為使用者明示接受的公開決策）。
- **SSE mount 方式變更** —— 若改回 `Mount("/sse", sse_app())` 會 double-enter lifespan → crash（DD-5）。任何 SSE 接法變更 MUST 先實測 lifespan 行為，不安全不接。
- **DAV href 生成方式變更** —— 不得把 `PATENTS_GATEWAY_PREFIX` 烤進 href（rclone bug 5.5 教訓）；base_href 必須由 request-path 反推。

## Execution-Ready Checklist

- [x] `src/` bind-mount（R15 live-reload）確認可用：改 code 後 `docker restart patentmcp` 即生效，無需 rebuild image。
- [x] gateway `/patentmcp` route socket 指向 repo root `.run/patentmcp.sock`（非舊 `vendor/...` 路徑）、auth=0。
- [x] `.run/patentmcp.sock` 存在且 container healthy（無 lifespan crash）。
- [x] 單一 Starlette app / 單一 streamable lifespan 不變（新 route 全掛在 `app.router.routes.extend([...])`，無第二 lifespan）。
- [x] 外網 e2e 可達性可測（webfetch 無憑證即取 landing 內容 = 公開生效）。
