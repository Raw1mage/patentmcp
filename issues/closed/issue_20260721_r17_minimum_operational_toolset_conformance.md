# BR: R17 (Minimum Operational Toolset + Host Mediation) conformance — patentmcp

- **Date**: 2026-07-21
- **Repo**: patentmcp (v0.5.0)
- **Standard**: `opencode/specs/mcp-integration-standard/standard.md` R17 (lines 1090-1190, landed 2026-07-21 — newest ring)
- **Type**: conformance gap / standard adoption
- **Status**: open

## 背景

MCP integration standard 新增最新 ring **R17 = Minimum operational toolset + host mediation**（Layer 1+2）。§12 fleet matrix 尚未對 patentmcp 做 R17 評估。本 BR 記錄 recon 結論並界定收斂範圍。

R17 六節：

- **R17.1** baseline tools（`<id>_init` + `prompts/get` 帶**結構化** capability summary、health/introspection、`resources/read` portable retrieval）
- **R17.2** file toolset（stage/ingress、blob/resource egress、workspace inspection、typed asset preflight、content assertions）
- **R17.3** host-file ingress mediation（Layer 2 host 側 — 對 patentmcp repo 本身 N/A）
- **R17.4** WebDAV lifecycle toolset（provision→transfer→export→close，dirty-close fail loud）
- **R17.5** companion-skill parity（skillPaths / GET /skills / init / skill 同源、guide 首用段點名具體工具）
- **R17.6** conformance scenarios（任一 silent-success 即 non-conformant）

## Recon 結論（gap 評估）

> 證據來源：patentmcp v0.5.0 原始碼 inline 偵查（recon subagent worker_dead 於合成步驟，主體證據由 orchestrator inline 坐實）。

| R17 子項                          | 狀態 | 證據                                                                                                                                                                                                   | 收斂動作                                                                                                                                                                     |
| --------------------------------- | ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R17.1(a) init/guide**           | ✅   | `patentmcp_init` tool `src/patent_mcp_server/patents.py:4511` + prompts/get face `:4529`，兩面 byte-identical 投影 `_guide_doctrine()`（R15.5 單源）                                                   | 已達                                                                                                                                                                         |
| **R17.1(a) capability summary**   | ⚠️   | `patents.py:4526` init 回 `_guide_doctrine()` = **prose-only**；無結構化 machine-readable capabilities（transport / file ingress-egress / WebDAV state / companion / conditional families）            | **補結構化 capability summary**：init SHOULD 附結構化 capabilities（R17.1.1 需分辨 container vs host-visible endpoint，且不得讓 container socket path 看似 host-executable） |
| **R17.1(b) health/introspection** | ✅   | `GET /healthz`（`_http_app.py:8,516`）+ `GET /tools`（`:518` tools_json，live FastMCP registry）                                                                                                       | 已達                                                                                                                                                                         |
| **R17.1(c) resources/read**       | ❌   | 全 `src/` 無 `@mcp.resource` / `list_resources` / `read_resource`（grep 0 命中）；egress 靠 UDS `/files/{token}/blob` + WebDAV = **host-private extension**，非 protocol-native portable floor         | **補 MCP `resources/read`**：每個產出 binary 需可經 protocol-native resources/read 取得（R17.1(c) / R0 / R2 portable floor），不倚賴 host-private UDS 擴充                   |
| **R17.2 file toolset**            | ⚠️   | `stage_file`（`patents.py:1183`）已標 **retired → WebDAV working cache**（R13）；stage/egress 走 WebDAV。typed asset preflight + content assertions（R17.2.4/5）未見機檢斷言                           | 確認 WebDAV 路徑涵蓋 R17.2 五項；補 typed asset preflight（拒未解析路徑/缺媒體/token 外路徑）+ content assertions（空產物 ≠ delivery-ready）                                 |
| **R17.4 WebDAV lifecycle**        | ✅   | `cache_provision/list/export/close`（`patents.py:5109-5273`），dirty-close guard `:5264`；provision 報 host_provision + opt-in credential（commit `109d2c1`）                                          | 已達（複驗 dirty-close fail loud 覆蓋所有 unexported 情境）                                                                                                                  |
| **R17.5 companion parity**        | ✅   | mcp.json `skillPaths:["skills"]`（`mcp.json:14`）+ `GET /skills/patentworks.zip`（`_http_app.py:669`）+ init doctrine + patentworks skill（skill 已含 R17 backend-routing 紀律 `SKILL.md:30`）同名同源 | 已達（複驗 guide 首用段點名具體 baseline/conditional 工具，非僅「load the skill」）                                                                                          |
| **R17.6 conformance scenarios**   | ⚠️   | 需針對五情境做端到端 eval：FUSE 檔當未驗證 container path、init 只給 container socket path、render unresolved media、QA ready=true 空產物、companion/guide/manifest 三處 rail 不一致                   | 補 R17.6 端到端 eval（host file → UDS/HTTP ingress → token → stage → transform → assertion-backed QA → resource/blob egress，一次無 WebDAV floor + 一次含 WebDAV）           |

## Net R17 verdict — patentmcp

**大致達標，三個實質 gap**：

1. **R17.1(c) `resources/read`** — 完全缺（最硬性，關乎 R0/R2 portable floor）。
2. **R17.1.1 結構化 capability summary** — init 目前 prose-only，需附 machine-readable capabilities（含 container vs host-visible endpoint 區分）。
3. **R17.2.4/5 typed asset preflight + content assertions** — WebDAV 產物路徑需補機檢斷言（空產物不得報 delivery-ready）+ R17.6 端到端 eval。

R17.1(a) init/prompts、R17.1(b) health/tools、R17.4 WebDAV lifecycle、R17.5 companion parity **已達標**。

## 執行

由 dedicated new session（root@patentmcp）依此 BR 執行：讀 standard R17 全文 → 逐條坐實 → 補三個 gap（優先 resources/read）→ 測試 → 更新 §12 matrix 的 patentmcp R17 列 → event log 收尾。**先走 plan-builder 建 plan 再實作。**
