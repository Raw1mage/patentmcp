# Proposal: patentmcp_r17-minimum-operational-toolset

## Why

- MCP integration standard 新增最新 ring **R17 = Minimum operational toolset + host
  mediation**（Layer 1+2）。§12 fleet matrix 尚未對 patentmcp 做 R17 評估。
- R17 的核心論點：正確的 lifecycle 操作若只是 prose recipe、而錯誤操作卻是 first-class
  tool，服務會在 action boundary 輸掉——所以 conformant MCP 的常見 lifecycle 必須由一組
  小而可預測的工具族表達，且產物必須經 protocol-native 的 portable floor 取得。
- BR `issues/issue_20260721_r17_minimum_operational_toolset_conformance.md` 完成 recon，
  界定三個實質 gap（其餘 R17 子項已達標）。

## Original Requirement Wording (Baseline)

- "實作 patentmcp 對 MCP integration standard R17（Minimum Operational Toolset + Host
  Mediation）的 conformance。" — 收斂 BR 界定的三個實質 gap，複驗已達標項，勿重做。

## Requirement Revision History

- 2026-07-21: initial draft created via plan-init.ts
- 2026-07-21: 需求收斂到 BR 三 gap（resources/read、結構化 capability summary、
  typed asset preflight + content assertions），並補 R17.6 端到端 eval。

## Effective Requirement Description

1. **R17.1(c) portable result retrieval（最硬性）**：patentmcp 目前每個產出 binary 只能經
   host-private extension（UDS `/files/{token}/blob/{rel}` + WebDAV `/dav`）取得，缺
   protocol-native 的 `resources/read`。SHALL 補 MCP `resources/read` 面，讓每個 token
   store 的產物 binary 都能經 `resources/list` + `resources/read` 這個 portable floor
   取得（R0/R2），不倚賴 host-private extension。
2. **R17.1.1 結構化 capability summary**：`patentmcp_init` 目前只回 `_guide_doctrine()`
   prose。SHALL 讓 init 額外回一份 compact machine-readable capabilities（transport、
   file ingress/egress、WebDAV state、companion skill、conditional tool families），且
   MUST 分辨 service/container endpoint 與 host-visible endpoint，MUST NOT 讓 container
   socket path 看似 host-executable。prose 面維持不變（doctrine 仍 byte-identical）。
3. **R17.2.4/5 typed asset preflight + content assertions**：交付導向操作（cache_export、
   資產交付路徑）SHALL 在落地前拒絕 unresolved 路徑 / 缺媒體 / token 外路徑 / host-only
   絕對路徑，並接受或發出可機檢的 content assertions（expected file 數、non-empty）。
   一個 transport-valid 但空的產物 MUST NOT 被報成 delivery-ready。
4. **R17.1.2 / R17.6 conformance**：init capability summary 至少一個 decision 要被
   conformance test 執行（非只測 guide text 存在）；補 R17.6 端到端 eval（host file →
   ingress → token → stage → transform → assertion-backed QA → resource/blob egress，
   一次 portable floor 無 WebDAV、一次含 WebDAV）。

## Scope

### IN

- 補 FastMCP `resources/list` + `resources/read`（token-store blob 的 protocol-native
  egress 面），resource URI scheme + traversal 防禦 + fail-loud。
- `patentmcp_init` 回傳型別由 `str` 改為結構化 envelope（doctrine prose + structured
  capabilities），維持 prose byte-identical、prompts/get 面相容。
- 交付路徑 typed asset preflight + content assertions（cache_export 空產物 gate、
  assertion 參數）。
- 測試（unit + R17.6 端到端 eval）。
- 收尾：standard §12 matrix R17 列、architecture sync、event log、BR closed。

### OUT

- R17.3 host-file ingress mediation（Layer 2 host 側；對 patentmcp repo 本身 N/A —
  屬 opencode host accelerator 面，非本 repo）。
- R17.4 WebDAV lifecycle（已達標；本 plan 只複驗 dirty-close fail-loud 覆蓋）。
- R17.1(a) init/prompts 雙面同源、R17.1(b) health/tools、R17.5 companion parity
  （已達標；只複驗）。
- 舊 UDS `/files/.../blob` + WebDAV 不移除（host accelerator 保留，R17 允許 host
  richer capability 與 portable floor 並存）。

## Non-Goals

- 不改 patent 檢索 / 取文 / 批次工具的行為。
- 不改 token store 的落地結構（`<root>/<token>/<filename>`）與 docxmcp 相容契約。
- 不新增任何 silent fallback（天條 §11）。

## Constraints

- Python FastMCP 服務（`src/patent_mcp_server/`），`mcp` SDK 提供 `@mcp.resource`。
- 天條：無 silent fallback、fail-loud、scratch 落 XDG 非 /tmp。
- `patentmcp_init` tool 與 `prompts/get patentmcp_init` 面必須維持 doctrine 同源
  （R15.5 no-drift）——結構化 capabilities 若加到 prompts/get 面須兩面一致，或
  capabilities 只加在 tool 面而 prompt 面維持 prose（需明確 DD）。
- `resources/read` 的 URI 必須能唯一定位 token+rel，且 traversal-safe（重用
  `TokenStore._safe_target`）。

## What Changes

- `patents.py`：新增 `@mcp.resource` handlers（list + read）；`patentmcp_init` 回傳
  結構化 envelope + capability summary builder；cache_export 加 preflight + assertions。
- 可能新增 `_resources.py`（resource URI ↔ token/rel 映射 SSOT）。
- `mcp.json` 版本升（0.5.0 → 0.5.1）+ R17 signpost。
- 測試 + skill/README/architecture 文件同步。

## Capabilities

### New Capabilities

- `resources/read` portable egress：任一 token blob 經 `patent://<token>/<rel>`
  （scheme 待 design 定案）resource URI 取得，bare MCP client 無需 host extension。
- 結構化 capability summary：init 回 machine-readable capabilities（含 endpoint
  可見性分類）。
- typed asset preflight + content assertions：交付前機檢，空產物 fail-loud。

### Modified Capabilities

- `patentmcp_init`：prose-only → prose + structured capabilities（doctrine 不變）。
- `cache_export`：加 preflight（unresolved / 缺媒體 / 空）+ optional assertions 參數。

## Impact

- 影響 `patents.py`（init、cache_export、新 resource handlers）、`_http_app.py`
  （複驗 blob 面共存）、`mcp.json`、`skills/patentworks/SKILL.md`（init capability
  首用段可能補），`specs/architecture.md`，opencode standard §12 matrix。
- 對現有 token/blob/WebDAV 消費者無破壞（純新增面）。
