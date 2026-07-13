# issue: mcp.json 生成流程把多行 instructions 直接內嵌造成 invalid JSON，gateway 拒連

- **狀態**: closed（即時修復 + 根治驗證閘皆已 commit）
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

**調查結論：沒有生成器。** 搜過全 repo（`*.py`/`*.sh`/`*.ts`），`mcp.json` 不是程式產生的 —— `patents.py`/`patentdb_store.py` 只是讀 `.mcp.json` 找 repo root，`_http_app.py` 只是 landing page 文案。`mcp.json` 是**手寫維護的 manifest**，含那段 instructions 的來源只有它自己。

因此根治不是「修生成器」，而是「加驗證閘」防止手寫再次弄壞它：

- [x] 確認無生成器（手寫 manifest）→ 「改用 JSON serializer」不適用
- [x] 新增 `scripts/validate-manifests.sh`：對 `mcp.json`/`.mcp.json` 跑 `jq empty`，非法 JSON 直接 fail；並斷言 `mcp.json` 的 url 無尾斜線
- [x] 裝 `.git/hooks/pre-commit` 呼叫該腳本 → 非法 manifest 無法被 commit
- [x] 兩個失敗模式（instructions 內 raw newline、url 尾斜線）皆已實測被擋下

commit: `0d54b06`（即時修復）、`143e330`（驗證閘 + hook）。

> 註：`.git/hooks/` 不隨 repo 版控。若要跨 clone 生效，未來可考慮改用 `core.hooksPath` 指向版控目錄，或接 pre-commit framework / CI。目前 repo 無 CI，先落地本機 hook。

## 參考

- event log: `patentmcp/event_2026-07-13_patentmcp-repo-mcp-json-...`（RCA 全文）
- 備份：`$XDG_RUNTIME_DIR/mcpjson.bak`（修復前的壞檔）
