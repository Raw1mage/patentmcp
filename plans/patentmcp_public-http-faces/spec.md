# Spec: patentmcp_public-http-faces

## Purpose

patentmcp 對外以 `https://cms.thesmart.cc/patentmcp/` 提供公開（無認證）的多傳輸面 MCP 服務：根路徑是安裝/使用說明 + 全部 tools schema 分頁文件站，子路徑 `/mcp`（streamable-http）、`/sse`（HTTP+SSE）、`/webdav`（檔案面，與 `/dav` 並存）分別提供真正的傳輸面，`/uds` 以說明段落呈現同主機 Unix socket 連法。全部面共用單一 Starlette app 與單一 streamable session-manager lifespan。

## Requirements

### Requirement: 對外公開多傳輸面

系統 SHALL 在 gateway `/patentmcp` 前綴下對外公開（auth=0）提供 landing、tools schema 分頁、`/mcp`、`/webdav` 與（可安全接上的）`/sse`，且不得引入第二個 app lifespan。

#### Scenario: 外網取用 tool schema 分頁

- **WHEN** 外部使用者 GET `https://cms.thesmart.cc/patentmcp/tools/{name}`
- **THEN** 回傳該 tool 的完整 inputSchema（參數/型別/必填/描述）HTML 分頁，資料源為 live FastMCP registry；未知 name 回 404

#### Scenario: 外網連 MCP streamable-http

- **WHEN** MCP client 連 `https://cms.thesmart.cc/patentmcp/mcp`
- **THEN** 完成 MCP 握手並可列出/呼叫工具，無需認證

#### Scenario: WebDAV 別名與現有 /dav 並存

- **WHEN** WebDAV client 對 `/patentmcp/webdav/{subject}` 發 PROPFIND
- **THEN** 回應與 `/dav/{subject}` 等價（同 handler、base_href 由 request-path 反推），且 `/dav` 舊路徑仍可用

## Acceptance Checks

- [ ] gateway route `/patentmcp` 指向實際 socket `.run/patentmcp.sock` 且 auth=0
- [ ] `GET /patentmcp/` landing 含傳輸面總覽 + `/uds` 段落 + tool 連結
- [ ] `GET /patentmcp/tools/{name}` 回正確 inputSchema 分頁；未知 name 404
- [ ] `/patentmcp/mcp` MCP client 可連
- [ ] `/patentmcp/webdav/{subject}` PROPFIND 與 `/dav` 等價；`/dav` 未壞
- [ ] `/patentmcp/sse` 依實測結論接上或明確標註不提供（不得 crash）
- [ ] container process 單一 lifespan 正常啟動（無 double-enter session_manager）
- [ ] 從外網實測全部子路徑公開可達
