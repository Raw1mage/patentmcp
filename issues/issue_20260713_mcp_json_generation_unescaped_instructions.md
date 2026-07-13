# issue: mcp.json 生成流程把多行 instructions 直接內嵌造成 invalid JSON，gateway 拒連

- **狀態**: open
- **日期**: 2026-07-13
- **範疇**: patentmcp / MCP manifest
- **嚴重度**: high（整個 MCP app 對 opencode 不可用，症狀卻偽裝成「服務沒啟用」）

## 症狀

Agent 連不到 patentmcp，`patentmcp_*` 工具完全不 surface。容器本身 `Up (healthy)`、TCP+UDS `/health` 正常、`/tools` 回 48 工具 —— 服務端毫無問題，故障全在 opencode gateway 側。

## 根因

gateway 在連任何 MCP app 前有一道 **manifest 前置閘**：先 parse 該 repo 的 `mcp.json`。patentmcp 的 `mcp.json` 是**非法 JSON**：

```
WARN mcp prerequisite unmet id=patentmcp
  missing: mcp.json ... JSON Parse error: Unterminated string
WARN mcp-apps.json app prerequisite unmet — skipping connect id=patentmcp
```

`instructions` 欄位的值（~6954 chars）含**實體換行 (raw U+000A)**，而 JSON 規範要求字串內控制字元必須轉義成 `\n`。`jq` / `python3 json` 皆在 line 17 col 6736 parse 失敗。

git 確認：**此損壞在 commit `9050d9d`（feat(r16): patentmcp_kb_query/kb_get …）就已引入**，非後續編輯造成。這也是 `refresh_capability_layer` / gateway restart 都救不回來的原因 —— 前置閘在握手之前就 skip 掉了。

次要問題（被前置閘擋在後面、修好第一層才會浮現）：註冊 URL 尾斜線 `/mcp/` 會被 FastMCP 以 `307` 轉址到 `/mcp`，MCP client 對 POST 握手不跟隨 307。

## 已套用的即時修復

`mcp.json` 手動修正兩處並通過 `jq`：
1. `instructions` 內 raw 控制字元轉義為 `\n`
2. url 尾斜線移除 `/mcp/` → `/mcp`

（同步修了 live 的 `~/.config/opencode/mcp-apps.json` url。修復後 `patentmcp=connected(48 tools)`。）

## 待辦（根治，避免復發）

即時修復只是把手拼字串補對；**產生 `mcp.json` 的流程本身仍會再次踩坑**。需修上游生成器：

- [ ] 定位產生 / 更新 `mcp.json` 的腳本或 build step（`9050d9d` 附近）
- [ ] `instructions` 這種多行文字**一律經 JSON serializer 輸出**（`json.dumps` / `JSON.stringify`），禁止手拼字串直接內嵌換行
- [ ] 加一道 CI / pre-commit 閘：對 repo 內所有 `mcp.json` 跑 `jq empty` 驗證，非法 JSON 直接 fail
- [ ] 生成器輸出的 url 統一為無尾斜線 `/mcp`（與 FastMCP 端點對齊）

## 參考

- event log: `patentmcp/event_2026-07-13_patentmcp-repo-mcp-json-...`（RCA 全文）
- 備份：`$XDG_RUNTIME_DIR/mcpjson.bak`（修復前的壞檔）
