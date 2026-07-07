# Proposal: mcp_r15-self-describing-guide

## Why

- opencode 的 fleet MCP 標準 `mcp-integration-standard` 於 2026-07-07 extend 增訂
  **R15（self-describing organism / in-band usage guidance）** 為 MUST 條文。patentmcp
  是 fleet conformant service，須採納 R15，複製 docxmcp reference pattern。
- 病根（R15 要治的 L3）：patentmcp 的 usage doctrine（USPTO/Google Patents/TIPO/EPO
  多源檢索管線、flow 選用、專利工作池資料樹規範、organ coordination）目前只活在
  host-side prose —— companion skill `skills/patentworks/SKILL.md` + AGENTS.md 路由。
  模型必須主動載入且不能反射略過；經驗上會反射略過（confident-but-wrong prior 壓過
  loaded prose）。R15 把 doctrine 放上 portable MCP surface，以 tool result 形式在
  action boundary 就地遞送 —— delivered context，非 remembered context。

## Original Requirement Wording (Baseline)

- "為每一個 mcp repo 開一個 plan。優先處理 docxmcp、bodesign、patentmcp、specbase。"
- "把這個樣板 plan 複製到每個 mcp repo。"（docxmcp reference pattern，本 repo 採納）

## Requirement Revision History

- 2026-07-07: initial draft created via plan-init.ts
- 2026-07-07: copied from docxmcp reference plan, patentmcp-specific substitution

## Effective Requirement Description

1. **R15.1 dual-protocol guide（雙寫）**：新增 `patentmcp_guide` MCP **tool**
   (`tools/call`)，回傳 patentmcp 的完整 usage doctrine（單次呼叫拿到 organ
   coordination + cross-tool tradeoffs + pre-call disciplines + gotchas）。同時
   新增 `prompts/get` 的 **R15 usage-guide prompt entry**（名 `patentmcp_guide`
   或 `usage`），回傳**同一份** doctrine。（patentmcp 現無 prompts handler，需新建。）
2. **R15.3 signpost**：在 `mcp.json.instructions`（且/或 server 內建 instructions
   常數）新增一句宣告 guide surface 存在（"call `patentmcp_guide`
   (or `prompts/get patentmcp_guide`) for the full usage doctrine before first
   use"）。此為 service-authored manifest 宣告，非 host 注入 nudge。
3. **R15.5 one-source**：guide tool body、`prompts/get` body、companion skill
   `patentworks/SKILL.md` 三者 doctrine 必須來自**單一 source**（投影，不手維護三份）。
4. **R15.2 內容涵蓋**：guide 必須承載 per-tool `description` 結構上無法承載的內容 ——
   cross-tool tradeoffs（多資料源 flow 選用）、pre-call disciplines（工作池資料樹規範、
   scratch→`/tmp`）、organ coordination（container + UDS + patentworks skill + scripts
   - webdav working-cache）、counter-intuitive gotchas。

## Scope

### IN

- 在 patentmcp repo 內實作 `patentmcp_guide` tool + `prompts/get` guide handler +
  instructions signpost + one-source 投影機制。
- 驗證：guide tool 可呼叫並回傳 doctrine；prompts/get 同 doctrine；instructions 含
  signpost；doctrine 與 SKILL.md 同源（drift 檢查）。
- 對照 `specs/mcp-integration-standard` R15.1–R15.5 checklist 逐項自檢。

### OUT

- 其餘 MCP（docxmcp/bodesign/specbase/…）的 R15 實作 —— 各自 repo 的 plan。
- 對 standard 本身的再修改（R15 條文已 living）。
- patentworks SKILL.md 的內容重寫（僅在需要建立 one-source 投影時做最小調整）。

## Non-Goals

- 不改 patentmcp 既有 tools 的行為。
- 不引入 host-side「先載 skill 才能呼叫 tool」的 load-gate（R15.4 明禁，違 R0.3）。
- 不新增任何 conversational nudge / `<system-reminder>` 注入（天條 2）。

## Constraints

- **協議純正**：guide 走 MCP public primitives（`tools/call` + `prompts/get`），不
  發明私有 wire schema（R0 portability floor / 天條 no-MCP-dialect）。
- **no fallback**：投影機制若 source 缺失，fail fast，不靜默回退空 doctrine（天條 11
  —— 無 doctrine 的 guide byte-identical to no contract）。
- guide tool 必須 `readOnlyHint:true`、`openWorldHint:false`。

## What Changes

- `src/patent_mcp_server/patents.py`（+ `_http_app.py` 若 prompts 掛 HTTP 層）：註冊
  `patentmcp_guide` tool；**新建** `prompts/list`+`prompts/get` handler 加入 usage-guide
  entry；server instructions 常數補 signpost。
- `mcp.json`：`instructions` 補 signpost 句。
- 新增 one-source doctrine 投影（機制待 design 定：讀 SKILL.md vs 抽共享檔）。

## Capabilities

### New Capabilities

- `patentmcp_guide` tool：單呼叫取得 patentmcp 完整 usage doctrine（in-band, portable）。
- `prompts/get patentmcp_guide`：bare-client 可達的同源 doctrine 投影（新建 handler）。

### Modified Capabilities

- `mcp.json.instructions` / server instructions：新增 R15.3 guide signpost。

## Impact

- 影響檔：`src/patent_mcp_server/patents.py`、`_http_app.py`、`mcp.json`、
  `skills/patentworks/SKILL.md`（若作為投影 source）、`Dockerfile`（確認 skills/ COPY）。
- 影響 operator：需 rebuild patentmcp container 使新 tool/prompts 生效。
- 對照標準：`/home/pkcs12/projects/opencode/specs/mcp-integration-standard/standard.md`
  R15.1–R15.5 + §13 checklist。
