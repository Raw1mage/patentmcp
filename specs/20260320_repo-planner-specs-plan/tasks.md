# Tasks

## 1. Specbase Architecture Refactor

- [x] 1.1 Read `README.md`, `specs/architecture.md`, `patentmcp`, and `patentworks` flow files
- [x] 1.2 Replace obsolete eight-stage prompt pipeline architecture with PatentWorks MCP + skill boundaries
- [x] 1.3 Record analysis as a planned source-agnostic boundary between retrieval/screening and drafting

## 2. Analysis Boundary Specification

- [x] 2.1 Define analysis input sources: `retrieval_mcp`, `user_provided`, `file`, and `mixed`
- [x] 2.2 Define analysis responsibilities: normalization, technical features, element mapping, differences, drafting basis, review flags
- [x] 2.3 Preserve screening CSV delivery and drafting jurisdiction knowledge boundaries

## 3. Future Skill Implementation Slice

- [x] 3.1 Add `skills/patentworks/flows/analysis.md` as a standalone flow
- [x] 3.2 Update `skills/patentworks/SKILL.md` to route analysis requests separately from screening and drafting
- [x] 3.3 Update `screening.md` to hand shortlist/deep-read needs to analysis without losing scored CSV delivery
- [x] 3.4 Update `drafting.md` to consume analysis output as the preferred drafting basis

## 4. Optional Schema / Validation Slice

- [x] 4.1 Decide whether `AnalysisInput` / `AnalysisOutput` should be formalized as JSON schema
- [x] 4.2 If formalized, add schema under this spec package or a stable `specs/` subdirectory
- [x] 4.3 Add example test vectors for MCP-derived and user-provided materials

## 5. Closeout

- [x] 5.1 Record event log with scope, decisions, validation, and remaining work
- [x] 5.2 Validate specs remain aligned after any future skill implementation
- [x] 5.3 Sync `specs/architecture.md` whenever flow routing or MCP contracts change
