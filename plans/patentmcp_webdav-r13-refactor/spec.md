# Spec: patentmcp_webdav-r13-refactor

## Purpose

把 patentmcp 從「單一 container 包辦所有工作」重構為 mcp-integration-standard 的目標形態：
**docker（repoless 網路 compute）+ webdav（token namespace 的 online 工作區）+ skill
with scripts（R13 landing plane，確定性後處理在 host 以使用者 uid 執行）**。保證：
檢索/取文等憑證網路工作留在 container；可確定地在本地完成的轉換不再付 token
往返稅；token 產物可經 WebDAV 掛載直接存取並有顯式 export/close 生命週期。

## Requirements

### Requirement: webdav-working-cache

服務 SHALL 提供 docxmcp 式 WebDAV working cache：subject-anchored provision（idempotent
per (owner, subject)）、class-2 DAV method 表、per-owner credential、跨 owner typed
403、export 一等公民（N:M target）、dirty close gate、class-aware reaper。

#### Scenario: provision 後 rclone 掛載可用

- **WHEN** 認證使用者 provision subject 並以回傳 credential 掛載 DAV 端點
- **THEN** copyto/lsf/cat/mkdir/moveto/deletefile 如一般目錄運作，PROPFIND 回合規 multistatus

#### Scenario: dirty close 拒絕

- **WHEN** cache 自上次 export 後有改動且 close 未帶 force
- **THEN** 回 typed `WORKSPACE_CLOSE_DIRTY` + 未落地清單，cache 不回收

#### Scenario: 跨 owner 存取拒絕

- **WHEN** 其他 identity 對非自己的 cache 發任何 DAV method
- **THEN** typed 403，無任何 identity fallback，不揭露任何 bytes

### Requirement: r13-landing-plane

確定性後處理（建表/去重/Claim1 切割/欄位選擇/CSV 組裝）SHALL 以 skill-attached
local scripts 提供（R13.2/R13.3/R13.6）；container 僅保留網路/憑證 compute，回
records JSON + handle。

#### Scenario: 本地建表

- **WHEN** agent 以 search 結果 records JSON 執行 landing 建表 script
- **THEN** 以使用者 uid 在本地產出去重/切 Claim1/選欄的 CSV，零 container 往返

#### Scenario: 下架 tool 的 typed redirect

- **WHEN** 呼叫已落地下架的 container 建表 tool
- **THEN** 回 typed `TOOL_LANDED` 錯誤，指引對應 landing script 用法，不執行舊邏輯

### Requirement: standard-conformance-sync

mcp.json SHALL 依 R13.5 在 `instructions` 宣告 compute-plane vs landing-plane verb
分工，version bump；既有 R1/R7/R8 面行為不變。

#### Scenario: 宣告完整

- **WHEN** host 讀取 mcp.json
- **THEN** instructions 列出兩平面 verb 清單與 landing script 呼叫形式，無需 per-repo hardcode

## Acceptance Checks

- [ ] AC-1 provision idempotent；同 owner 同 subject 兩次 → 同 token
- [ ] AC-2 無/錯認證 401（帶 WWW-Authenticate）；跨 owner 403；無 identity fallback
- [ ] AC-3 OPTIONS 回 `DAV: 1, 2`；rclone 實掛載全操作過
- [ ] AC-4 export N:M + target 不可達 typed fail-fast；dirty close 409，clean close 回收
- [ ] AC-5 deliverable-cache 免 idle reap（dirty 時）；ephemeral 對照組照常 reap
- [ ] AC-6 landing 建表 script：同一 records JSON 經 script 與舊 container 邏輯產出等價 CSV
- [ ] AC-7 下架 tool 回 typed TOOL_LANDED redirect；保留 tool 行為不變（回歸綠）
- [ ] AC-8 mcp.json instructions 兩平面宣告 + version bump
- [ ] AC-9 既有測試全綠（host venv + container image）
