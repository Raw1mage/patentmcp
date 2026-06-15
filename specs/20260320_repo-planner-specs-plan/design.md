# Design

## Context
- PatentDrafter 現行定位是 PatentWorks：一組 `patentmcp` MCP server 與 `skills/patentworks` skill flows。
- `README.md` 已明確標示舊 8 層多 Agent 架構與 HLS/Grafcet 實驗廢除；舊 spec package 需重構以避免後續 agent 使用過時邊界。
- 現有 `screening.md` 已同時承擔檢索、建表、逐列判讀與新穎性綜述；使用者要求 analysis 可獨立於資料來源。

## Goals / Non-Goals

**Goals:**
- 將 current-state architecture 改為 PatentWorks MCP + skill。
- 定義 `analysis` 為資料來源無關的中介層。
- 保留 `screening` 的 CSV 交付不變式。
- 讓 `drafting` 從 analysis 結構化輸出開始，而不是直接吃檢索工具 schema。

**Non-Goals:**
- 不在本 spec 重構中直接新增 skill flow 檔案。
- 不改 MCP server 行為或欄位。
- 不替代人類專利判斷或法律意見。

## Decisions
- Decision 1: `patentmcp` 是檢索/取文/落地交付層，不是 analysis 的唯一資料來源。
- Decision 2: `screening` 是檢索工作流與 scored spreadsheet 交付；其逐列判讀產物可作為 analysis input。
- Decision 3: `analysis` 應使用標準化 input envelope，至少包含 `sourceType`、`materials`、`analysisGoal` 與可選 metadata。
- Decision 4: `drafting` 應依賴 analysis output：核心特徵、必要要件、最接近前案、差異點、實施例、術語表、疑點清單。
- Decision 5: 大型資料仍以 handle 傳遞；analysis 可讀取必要摘要/節選，但不應把整份 PDF/CSV/docx bytes 放入 context。
- Decision 6: CSV 大檔如何切批、抽樣、索引、分工或迭代讀寫，屬 agent execution strategy；spec 只約束輸入來源、輸出契約、可稽核性與不得捏造證據。

## Data / State / Control Flow
- Retrieval-first path: `patentmcp` search/get/build table → `screening` scored CSV / shortlist / handles → `analysis` structured report → `drafting` claims-first output。
- User-first path: user-provided invention/prior-art/claim text → `analysis` structured report → optional `screening` for prior-art enrichment → `drafting`。
- Mixed path: disclosure + prior-art shortlist + full claims handles → `analysis` claim chart / feature matrix → `drafting`。

## Planned Analysis Contract

### Input Envelope
```ts
type AnalysisInput = {
  sourceType: "retrieval_mcp" | "user_provided" | "file" | "mixed"
  materials: Array<{
    id?: string
    title?: string
    content?: string
    handle?: { token: string; rel: string; download_url?: string }
    metadata?: Record<string, unknown>
  }>
  analysisGoal:
    | "technical_features"
    | "novelty"
    | "claim_mapping"
    | "drafting_basis"
    | "landscape"
    | "fto"
}
```

### Output Envelope
```ts
type AnalysisOutput = {
  normalizedMaterials: Array<{ id: string; title?: string; gist: string }>
  technicalFeatures: Array<{ feature: string; role: "required" | "optional" | "variant"; support: string[] }>
  elementMap?: Array<{ feature: string; references: Array<{ materialId: string; disclosure: string; gap?: string }> }>
  closestPriorArt?: Array<{ materialId: string; reason: string; coveredFeatures: string[]; missingFeatures: string[] }>
  differences: Array<{ point: string; basis: string; draftingUse?: string }>
  draftingBasis?: { problem: string; solution: string; effects: string[]; claimSeeds: string[] }
  reviewFlags: Array<{ issue: string; severity: "low" | "medium" | "high"; humanReviewNeeded: boolean }>
}
```

## Risks / Trade-offs
- Over-separation risk: screening may still need lightweight row judgement for CSV delivery; do not force every row through deep analysis.
- Schema drift risk: MCP handles and CSV columns may evolve; analysis should depend on normalized materials, not raw column names.
- Legal risk: analysis outputs are drafting aids and triage evidence, not attorney conclusions.
- Token risk: user-provided files may be large; analysis must preserve handle-first and excerpt-first discipline.
- Over-specification risk: 如果 spec 規定固定 CSV 讀取策略，會限制 agent 依檔案大小、欄位品質與工具能力自行最佳化；因此只定 contract，不定 algorithm。

## Critical Files
- `/home/pkcs12/projects/PatentDrafter/specs/architecture.md`
- `/home/pkcs12/projects/PatentDrafter/README.md`
- `/home/pkcs12/projects/PatentDrafter/vendor/patents-mcp/src/patent_mcp_server/patents.py`
- `/home/pkcs12/projects/PatentDrafter/skills/patentworks/SKILL.md`
- `/home/pkcs12/projects/PatentDrafter/skills/patentworks/flows/screening.md`
- `/home/pkcs12/projects/PatentDrafter/skills/patentworks/flows/drafting.md`
- `/home/pkcs12/projects/PatentDrafter/skills/patent-practitioner-workflow.md`

## Supporting Docs
- `proposal.md` explains why this refactor is needed.
- `spec.md` defines acceptance requirements.
- `tasks.md` identifies the follow-up implementation sequence.
