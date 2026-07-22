# Spec: mcp_r15-self-describing-guide

## Purpose

patentmcp 作為 fleet MCP 標準 `mcp-integration-standard` 的 conformant adopter,採納 R15（self-describing organism / in-band usage guidance）。本 spec 保證 patentmcp 的完整 usage doctrine 以 MCP public primitives（`tools/call` + `prompts/get`）在 action boundary 就地遞送為 delivered context,而非仰賴 host-side prose 被模型主動記憶。doctrine 單一來源投影,杜絕三份漂移。

## Requirements

### Requirement: R15.1 dual-protocol usage guide（雙寫同源）

系統 SHALL 提供 `patentmcp_init` MCP tool（`tools/call`）與 `prompts/get patentmcp_init` prompt entry,兩者回傳 byte-identical 的同一份 patentmcp usage doctrine。doctrine SHALL 涵蓋 R15.2 四類:cross-tool tradeoffs（多資料源 flow 選用 / 來源梯）、pre-call disciplines（工作池資料樹規範、scratch→/tmp、爬蟲授權）、organ coordination（container + UDS transport + patentworks skill + 本地腳本 + WebDAV working cache）、counter-intuitive gotchas。

#### Scenario: guide tool 回傳完整 doctrine

- **WHEN** client 呼叫 `patentmcp_init` tool（無參數）
- **THEN** 回傳 patentmcp 完整 usage doctrine 的 TextContent,涵蓋 R15.2 四類內容

#### Scenario: prompts entry 同源

- **WHEN** client 呼叫 `prompts/get patentmcp_init`
- **THEN** 回傳與 `patentmcp_init` tool body byte-identical 的同源 doctrine

### Requirement: R15.3 signpost（service-authored manifest 宣告）

系統 SHALL 在 `mcp.json.instructions` 與 server 內建 instructions 常數各宣告一句 guide surface 存在的 signpost,指示模型在 first use 前呼叫 guide。此為 service 自身 manifest 宣告,走既有 instructions rail,SHALL NOT 注入對話流（無 conversational nudge / `<system-reminder>`）。

#### Scenario: signpost 可被 client 讀取

- **WHEN** client 讀取 server InitializeResult 的 instructions 或 mcp.json.instructions
- **THEN** instructions 含指向 `patentmcp_init`（或 `prompts/get patentmcp_init`）的 signpost 句

### Requirement: R15.5 one-source projection（單一來源投影）

guide tool body、`prompts/get` body、companion skill `skills/patentworks/SKILL.md` 三者 doctrine SHALL 來自單一 source（投影,不手維護三份）。source 缺失/空 SHALL fail fast,不靜默回退空 doctrine（天條 11）。

#### Scenario: source 缺失 fail fast

- **WHEN** server 啟動時 doctrine source 檔缺失或為空
- **THEN** server 啟動 fail fast,不以空 doctrine 靜默續行

#### Scenario: drift 一致性

- **WHEN** 改動 doctrine source（SKILL.md）後重啟 server
- **THEN** `patentmcp_init` tool 與 `prompts/get` 回傳的內容隨之變更（三者同源）

## Acceptance Checks

- [ ] `patentmcp_init` tool 可呼叫,回傳含 R15.2 四類的 doctrine
- [ ] `prompts/list` 列出 `patentmcp_init` entry;`prompts/get patentmcp_init` 回同源 doctrine
- [ ] guide tool body 與 prompts body byte-identical（同源投影驗證）
- [ ] `mcp.json.instructions` 與 server instructions 各含 R15.3 signpost 句
- [ ] doctrine source 缺失時 server 啟動 fail fast（無空 doctrine 靜默回退）
- [ ] guide tool annotations = `{readOnlyHint:true, destructiveHint:false, idempotentHint:true, openWorldHint:false}`
- [ ] 對照 `specs/mcp-integration-standard` §13 checklist R15.1/R15.2/R15.3/R15.5 逐項通過
