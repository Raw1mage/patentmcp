# Spec

## Purpose
- 定義 PatentWorks 架構重構後的 specbase 契約，尤其是讓 `analysis` 成為資料來源無關、可被 `screening` 與 `drafting` 共用的中介能力。

## Requirements

### Requirement: Architecture inventory must reflect current PatentWorks repo state
The system SHALL describe the repository as a PatentWorks MCP + skill package, not as the retired eight-stage prompt-agent pipeline.

#### Scenario: future agent reads architecture first
- **GIVEN** a future implementation task starts from `specs/architecture.md`
- **WHEN** the agent identifies current module boundaries
- **THEN** it must see `patentmcp`, `patentworks`, `screening`, `analysis`, and `drafting` as the relevant boundaries

### Requirement: Analysis must be source-agnostic
The system SHALL define analysis as a separate capability that accepts materials from retrieval MCP outputs, user-provided content, files, or mixed sources.

#### Scenario: materials come from patentmcp screening
- **GIVEN** `build_screening_table` or `gpatents_get` produces patent materials or handles
- **WHEN** analysis is invoked
- **THEN** it must normalize the materials into technical features, element mapping, differences, and drafting basis without assuming the caller is drafting directly from MCP schema

#### Scenario: materials come directly from the user
- **GIVEN** the user provides invention text, prior-art excerpts, claim text, or a technical disclosure
- **WHEN** analysis is invoked
- **THEN** it must perform the same structured analysis without requiring a prior screening run

### Requirement: Screening must keep its spreadsheet delivery invariant
The system SHALL keep screening responsible for retrieval, candidate table creation, row-level judgement, and agent-friendly human-readable scored CSV delivery.

#### Scenario: spreadsheet is large or irregular
- **GIVEN** screening produces or receives a large spreadsheet
- **WHEN** an agent needs to analyze it
- **THEN** the spec must not prescribe a fixed batching, sampling, indexing, or delegation algorithm; the agent may choose the execution strategy as long as outputs remain auditable and evidence-grounded

#### Scenario: screening results need deeper interpretation
- **GIVEN** a scored spreadsheet or shortlist exists
- **WHEN** deeper novelty, claim chart, or drafting-basis work is needed
- **THEN** screening should hand selected materials to analysis rather than expanding retrieval flow into a monolithic drafting pipeline

### Requirement: Drafting must consume analysis outputs
The system SHALL make drafting depend on structured analysis outputs such as core features, closest prior art, distinguishing features, embodiments, and terminology.

#### Scenario: drafting begins after analysis
- **GIVEN** analysis has produced a drafting basis
- **WHEN** drafting starts for TW/CN/US/EP or common mode
- **THEN** drafting must combine the analysis basis with jurisdiction-specific drafting knowledge rather than re-parsing raw retrieval results

### Requirement: Specbase documents must stay mutually aligned
The system SHALL keep `architecture.md`, `proposal.md`, `spec.md`, `design.md`, `tasks.md`, `handoff.md`, and `implementation-spec.md` aligned around the same module boundary.

#### Scenario: plan package is used for implementation
- **GIVEN** a future agent reads this package
- **WHEN** it materializes todos
- **THEN** it must be able to implement the analysis boundary without re-discovering the architecture from README and flow files

## Acceptance Checks
- `specs/architecture.md` identifies PatentWorks MCP + skill as current state.
- Spec artifacts explicitly define `analysis` as source-agnostic.
- Screening remains responsible for scored CSV delivery.
- Drafting consumes analysis output rather than raw MCP output.
- Tasks identify implementation steps for adding/refactoring an analysis flow.
