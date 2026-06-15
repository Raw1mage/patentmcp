# Implementation Spec

## Goal
- 盤點 PatentDrafter repo 的真實架構，建立可供後續 AI/人類直接接手的 `/specs/` 規劃契約，明確區分「現況資產」與「目標產品設計」。

## Scope

### IN
- 建立 repo 現況導向的 architecture SSOT。
- 盤點 `source/`、`.claude/agents/`、`docs/`、`sample/`、`bin/`、`hls/` 的角色與邊界。
- 將盤點結果整理成 proposal/spec/design/tasks/handoff 與正式模型 JSON。
- 為後續 build agent 提供明確的 execution phases 與 stop gates。

### OUT
- 不實作 Web UI、API、workflow engine 或任何新 runtime。
- 不修正歷史 docs 內的所有過期描述。
- 不變更 sample 產物、agent prompt 或現有行為。

## Assumptions
- repo 目前最可信的執行現況來自 `source/CLAUDE.md`、`.claude/agents/*.md` 與 `sample/**`，而非 `docs/spec/**` 中較產品化的目標態敘述。
- 後續若要真正 build 成應用，需要先選擇實作標的：延續 prompt-first pipeline，或落地成程式化 runtime。
- 本次使用者要的是架構盤點與 planning artifact，不是直接 coding。

## Stop Gates
- 若使用者要把本 plan 直接轉成 build 任務，必須先決定優先實作標的（prompt pipeline 強化 / Web app / workflow controller / 文檔同步整頓）。
- 若發現 repo 另有隱藏程式碼入口未被納入盤點，需回到 plan mode 擴充範圍。
- 若後續 implementation 要修改模組邊界或引入新 runtime，需先同步更新 `specs/architecture.md`。

## Critical Files
- `/home/pkcs12/projects/PatentDrafter/specs/architecture.md`
- `/home/pkcs12/projects/PatentDrafter/source/CLAUDE.md`
- `/home/pkcs12/projects/PatentDrafter/source/PATENT_SKILL.md`
- `/home/pkcs12/projects/PatentDrafter/.claude/agents/input-parser.md`
- `/home/pkcs12/projects/PatentDrafter/.claude/agents/patent-searcher.md`
- `/home/pkcs12/projects/PatentDrafter/.claude/agents/outline-generator.md`
- `/home/pkcs12/projects/PatentDrafter/.claude/agents/markdown-merger.md`
- `/home/pkcs12/projects/PatentDrafter/docs/A0_system_idef0.md`
- `/home/pkcs12/projects/PatentDrafter/docs/A0_system_grafcet.md`
- `/home/pkcs12/projects/PatentDrafter/docs/spec/PatentDrafter_Spec.md`
- `/home/pkcs12/projects/PatentDrafter/sample/`
- `/home/pkcs12/projects/PatentDrafter/docs/events/event_20260320_repo-architecture-planning.md`

## Structured Execution Phases
- Phase 1 — Inventory Existing Assets: read prompt contracts, sample outputs, design docs, helper scripts, and modeling experiments.
- Phase 2 — Normalize Architectural Truth: distill actual module boundaries, data flow, and mismatches between current repo state and aspirational docs into `specs/architecture.md`.
- Phase 3 — Produce Planner Contract: align proposal/spec/design/tasks/handoff so a future build agent can act from this plan without re-discovering context.
- Phase 4 — Formalize Models: encode the repo architecture inventory as IDEF0, Grafcet, C4, and Sequence artifacts scoped to planning and handoff.
- Phase 5 — Readiness Review: verify artifact consistency, record event evidence, and prepare user-facing next-step recommendations.

## Validation
- Confirm `specs/architecture.md` exists and reflects the repo’s observable structure rather than placeholder text.
- Confirm all files under `specs/20260320_repo-planner-specs-plan/` are non-template, non-empty, and mutually consistent.
- Confirm `tasks.md` tasks map to the execution phases above.
- Confirm `idef0.json` and `grafcet.json` reference actual planning modules and not generic placeholders.
- Confirm `c4.json` and `sequence.json` trace to the same architecture narrative.
- Confirm `docs/events/event_20260320_repo-architecture-planning.md` records scope, evidence, and architecture sync status.

## Handoff
- Build agent must read this spec first.
- Build agent must read `proposal.md`, `spec.md`, `design.md`, `tasks.md`, `handoff.md`, and `specs/architecture.md` before coding.
- Build agent must materialize runtime todo directly from `tasks.md`.
- If the next task is implementation, first ask the user which target slice should be built from this inventory plan.
- Conversation memory is supporting context only; the spec package and `specs/architecture.md` are the execution source of truth.
