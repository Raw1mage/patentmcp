# Proposal

## Why
- 目前 repo 已重定位為 PatentWorks：`patentmcp` MCP server + `patentworks` skill，而舊 spec package 仍描述已廢除的八階段 prompt pipeline。
- 使用者指出「分析技能」應更獨立：資料來源可以是檢索 MCP 產出，也可以是使用者提供內容。
- 若不先重構 specbase 文件，後續實作容易把 analysis 綁死在 screening CSV 或 MCP schema 上，導致 drafting 無法吃非檢索來源材料。

## Original Requirement Wording (Baseline)
- 「在分析技能上我覺得可以再獨立一點。資料來源可以是檢索mcp的產出，也可以是使用者提供的內容」
- 「先分析一下架構，用specbase重構spec文件」

## Requirement Revision History
- 2026-06-15: 盤點 README、`patentmcp`、`patentworks` flows 與既有 specs，確認舊架構文件與現行 repo 定位不一致。
- 2026-06-15: 決定先重構 specbase/plan package，不直接修改 skill 行為；analysis skill 實作留為後續可執行 slice。

## Effective Requirement Description
1. 將 spec 文件從舊八階段 prompt pipeline 重構為現行 PatentWorks MCP + skill 架構。
2. 明確切分 `檢索`、`分析`、`撰寫` 三層能力。
3. 把 `analysis` 定義為資料來源無關的中介層，可接受 `retrieval_mcp`、`user_provided`、`file`、`mixed` 等來源。
4. 為後續新增或重構 `skills/patentworks/flows/analysis.md`、`SKILL.md` routing、screening/drafting handoff 建立 spec contract。

## Scope

### IN
- 更新 `specs/architecture.md`，反映 PatentWorks 現況。
- 重構 plan package 的 proposal/spec/design/tasks/handoff/implementation-spec。
- 定義 analysis skill 的輸入來源、輸出角色、與 screening/drafting 邊界。

### OUT
- 不直接實作 `flows/analysis.md`。
- 不修改 `patentmcp` tool schema。
- 不修改 CSV 產物讀寫邏輯。
- 不建立或變更遠端 issue。

## Non-Goals
- 不把 AI analysis 結論視為法律最終裁決。
- 不取消 screening 的 scored CSV 交付物不變式。
- 不要求所有使用者內容都先轉成檢索表格。

## Constraints
- 大型檔案、PDF、CSV、docx 交付物仍走 token/blob handle，不進模型 context。
- Screening 的最終交付仍是一張人類可讀、可稽核的 spreadsheet。
- Drafting 應依賴 analysis 的結構化中間產物，而不是直接依賴 patentmcp 回傳格式。
- AGPL 來源只能研讀，不得把其程式碼複製進產品。

## What Changes
- `specs/architecture.md` 改為 PatentWorks current-state SSOT。
- 本 plan package 改為「analysis boundary refactor」規格，而非舊 repo skeleton inventory。
- 新增 analysis 作為 planned module boundary：資料正規化、技術特徵抽取、要件對照、差異點歸納、drafting basis。

## Capabilities

### New Capabilities Planned
- Source-agnostic analysis contract：同一分析能力可處理 MCP 檢索產物、使用者貼文、文件摘要或混合材料。
- Drafting handoff contract：analysis 產出明確可供 claims-first drafting 使用。
- Screening/analysis separation：檢索負責候選與可稽核表格，分析負責理解與結構化判讀。

### Modified Capabilities
- Repo knowledge grounding：後續 agent 從 `specs/architecture.md` 與本 package 建模 PatentWorks，而不是舊 prompt pipeline。
- Skill workflow design：`disclosure → screening → drafting` 被擴充為可插拔的 `disclosure/search/user materials → analysis → drafting`。

## Impact
- 降低 analysis 與 retrieval MCP 的耦合。
- 讓使用者直接提供內容時，也能走同一分析/撰寫管線。
- 為後續實作獨立 analysis flow 提供驗收基準。
