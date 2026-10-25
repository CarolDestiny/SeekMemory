---
name: seekmemory-architecture
description: Use when changing SeekMemory layers, services, repositories, runtime boundaries, write ownership, import/export, or other cross-cutting architecture. Captures the refactor invariants, pitfalls, audit commands, and acceptance workflow learned from the services/repository cleanup.
---

# SeekMemory Architecture Skill

## When to use

Use this skill when a task touches any of:

- layer boundaries
- services or service collection
- repository ports or store composition
- AgentRuntime behavior
- write ownership
- import/export adapters
- host adapters or lifecycle
- architecture tests or refactor plans

Do not use it for a purely local algorithm change inside one pure module unless the change also crosses a layer.

## First question: who owns the semantic?

Before adding code, identify the single owner:

| Semantics | Owner |
|---|---|
| artifact read/write mechanics | ArtifactStore |
| immutable dialogue/Source evidence | RunRecorder for live runs; ImportService for bulk import |
| extraction and artifact generation | IngestService |
| long-term maintenance writes | MaintenanceService |
| recall and delivery state | RecallService |
| user/client permissions | AccessService |
| composition and lifecycle | AstrBotPlugin |
| repository implementation | store |

If two owners appear, stop and resolve ownership before writing code.

## Core invariants

1. Source is immutable truth. Artifact is a derived, versioned interpretation.
2. Every production artifact write uses expected-revision CAS through ArtifactStore.
3. SQL lives only in store.
4. Engine and service layers must not import store, DB, SQLite or adapters.
5. Store must not import app, services, adapters or AstrBot.
6. Only the AstrBot composition root calls open_store.
7. ServiceCollection is typed data only. It is not a registry, locator or DI container.
8. main.py is explicit composition and lifecycle only.
9. One semantic has one write path.
10. Conversion is pure; side effects have an orchestration owner.
11. Recall and permission checks are not duplicated in hooks.
12. Privacy and scope decisions are never bypassed by relationship, memory or UI state.

## The refactor order that worked

1. Establish services and explicit lifecycle.
2. Hide DB behind open_store and repository bundle.
3. Replace aggregate Store dependencies with narrow repository ports.
4. Collapse duplicate semantic write paths.
5. Split pure conversion from write orchestration.
6. Audit dependency direction and enforce with tests.

Do not attempt all six in one unverifiable step. Each step needs its own acceptance record.

## Pitfalls we actually hit

### 1. Renaming is not boundary cleanup

Renaming orchestration to services did not fix hidden dependencies. The real work was repository ports and single write owners.

Rule: a rename PR must not claim architectural cleanup unless dependency direction changed and is tested.

### 2. Aggregate objects create blind dependencies

DB and Store look convenient but make every caller omnipotent.

Ban from engines/services:

    db.artifacts
    store.artifacts
    Store parameters
    open_store imports

Prefer narrow protocols: ArtifactStore, SourceStore, ExtractionStore, MetricsStore, LedgerStore, ArtifactCache.

### 3. Any and getattr hide architecture violations

Examples:

    def Tree(db: Any, cache: Any)
    graph = getattr(...)
    cache.artifacts.history(...)

These patterns make tests pass while hiding the real dependency.

Rule: cross-layer boundaries use explicit protocols and typed parameters.

### 4. Concrete infrastructure leaks into domain engines

Recall/perceive/maintain once imported store.cache.Cache directly. Fix: app.ports.ArtifactCache.

Rule: if an engine needs a capability, add a role protocol; do not import its implementation.

### 5. Duplicate semantic hubs drift

Examples found:

- CapacityService and MaintenanceService both executed merge/forget.
- WebUI and RecallService both called build_block.
- absorb mixed parsing, model calls and persistence.

Rule: one semantic owner. Other layers adapt or delegate.

### 6. Test-only helpers can become second write paths

When splitting absorb, tests initially called a parallel implementation.

Rule: test support may construct the production service, but must not reimplement its write behavior.

### 7. UI constructing application services is a boundary violation

ManagementService originally lived in webui and was built per request with repos.

Rule: application services live in services, are built once by composition, and adapters only call them.

### 8. Lifecycle ordering bugs

Observed:

- start_jobs could run before start and silently no-op.
- Main.initialize only started the plugin, not jobs.
- restart could retain stale Store/cache references after a failed open.

Rule: start/stop must be idempotent, reset volatile state, and hooks must bootstrap safely.

### 9. Relative package imports are fragile

Moving pure code into core exposed the wrong relative level:

    app.runtime.tracing -> ..core  # wrong: resolves to app.core
    app.runtime.tracing -> ...core # correct in package mode

Rule: when moving modules, test both package import and top-level import paths.

### 10. Documentation and test fixtures lag behind real contracts

API contract fixtures and docs referenced the old DB and old trace path after the move.

Rule: update tests, fixtures, package allowlists and docs in the same change.

### 11. Architecture guards must be executable

A prose rule is not a boundary. Add tests that reject the exact regression:

- store importing app/adapters/astrbot
- engines importing store
- aggregate Store or DB parameters
- WebUI constructing services or calling build_block
- importer modules importing storage
- conversion modules performing writes
- only one production consumer of a write orchestration function

### 12. A clean dependency graph is not enough

The second audit found concrete Cache imports and a WebUI-owned ManagementService even after the main refactor.

Rule: run a fresh dependency audit after the planned work, not only at the start.

## Adding a feature

Before coding, answer:

1. What is the user-visible behavior?
2. Which existing service owns this semantic?
3. What is the smallest port or method needed?
4. Does any existing service already do this?
5. Is there a duplicate path that must be removed?
6. What must remain forbidden?
7. What architecture test will prevent regression?
8. What acceptance evidence will be recorded?

## Adding a format importer or external adapter

Importers are read-only adapters:

- importer parses external data into normalized DTOs
- ImportService admits immutable Sources and extraction state
- IngestService remains the only artifact writer
- importers must not import store, services, AstrBot or call models
- community contributors add one format adapter and one fixture test
- stream records, preserve event time and stable external ids
- default to deferred extraction for bulk imports

## Changing AgentRuntime

Runtime owns run decisions, not storage.

Rules:

- timing, attention, relationship and proactive policy belong in runtime
- memory retrieval stays behind a memory-context port
- runtime must not import store
- missing persistence fails open
- decisions must be content-free and testable
- host extras or host events must not leak into core

Relationship/favorability example:

- favorability is evidence-backed, versioned relationship memory
- it affects reply/proactive behavior only
- it must never block recall, scope or memory injection
- updates happen in Dream/Maintenance, not on every message
- long-term state is cached and read by the runtime

## Issue format

Every issue must start with Background and answer:

1. Why does this issue exist?
2. What is the observed user or system problem?
3. Why is the current behavior insufficient?
4. Why is solving it necessary now?
5. What is in scope and out of scope?
6. What are the architecture constraints?
7. What are the acceptance criteria?
8. Which existing issues does it relate to or supersede?

Do not write a solution-only issue with no problem context.

## PR and acceptance format

A PR should include:

- scope
- ownership decision
- forbidden paths preserved
- tests and commands
- architecture guard added or updated
- risk and rollback
- follow-up work

Record acceptance under docs/refactor or docs/issues when the change is architectural.

## Fast audit commands

Run from the repository root:

    grep -RIn --include='*.py' -E 'from (\.\.)?app|from (\.\.)?adapters|import astrbot' store
    grep -RIn --include='*.py' -E 'from (\.\.)?store|import store' app core services recall perceive maintain webui
    grep -RIn --include='*.py' -E '\bDB\b|store\.db|\bStore\b|open_store' app core services recall perceive maintain webui
    grep -RIn --include='*.py' -E 'from (\.\.)?maintain|from maintain' services/capacity_service.py
    grep -RIn --include='*.py' -E 'build_block|recall\.pipeline' webui services/management_service.py
    grep -RIn --include='*.py' -E '\.commit\(|commit_many\(|cache\.put\(' app services webui

Expected properties:

- store has no app/adapters/astrbot imports
- inner layers have no store imports
- only adapters/composition use open_store
- no DB symbol outside store
- no duplicate maintenance or recall entry point
- write calls appear only in their explicit owners

## Definition of done

- [ ] Ownership is explicit.
- [ ] No forbidden dependency was added.
- [ ] No duplicate write path was introduced.
- [ ] Tests cover behavior and boundaries.
- [ ] Acceptance evidence exists.
- [ ] Documentation and fixtures are current.
- [ ] Independent review is complete.
