# Spec

## Purpose
- 定義本次「repo 架構盤點與 plan 建立」工作的可驗證需求，確保產出的規劃文件能準確反映現況並支援後續執行。

## Requirements

### Requirement: Architecture inventory must reflect observable repo state
The system SHALL build planning artifacts from observable repository assets rather than from aspirational product descriptions alone.

#### Scenario: repo contains prompt assets, sample outputs, and design docs
- **GIVEN** the repository contains `source/`, `.claude/agents/`, `docs/`, `sample/`, `bin/`, and `hls/`
- **WHEN** the planner prepares the architecture inventory
- **THEN** it must describe each area’s current role and distinguish real assets from future-state design narratives

### Requirement: Global architecture SSOT must exist in specs
The system SHALL provide a `specs/architecture.md` file that captures current architectural truth for later sessions.

#### Scenario: a future agent starts work from specs
- **GIVEN** a future implementation or debug task begins
- **WHEN** the agent reads architecture context
- **THEN** it must be able to use `specs/architecture.md` as the first source of truth for repo structure and boundaries

### Requirement: Planner package must be execution-ready
The system SHALL replace template placeholders in the active plan package with taskable, repo-specific content.

#### Scenario: plan root was auto-created from a template
- **GIVEN** the active plan root contains placeholder markdown and generic JSON models
- **WHEN** planning completes
- **THEN** each companion artifact must contain repo-specific scope, decisions, tasks, and validation criteria

### Requirement: Event evidence must be recorded
The system SHALL record planning evidence, scope, and architecture-sync conclusions in an event file.

#### Scenario: non-trivial planning task is performed
- **GIVEN** a non-trivial architecture-planning request
- **WHEN** the planning work is executed
- **THEN** `docs/events/event_20260320_repo-architecture-planning.md` must document the requirement, scope, evidence, and validation status

## Acceptance Checks
- `specs/architecture.md` exists and contains repo-specific structure notes.
- No placeholder tokens remain in the active plan package.
- `tasks.md` can seed a future runtime todo without reinterpretation.
- Event log records architecture sync and validation evidence.
