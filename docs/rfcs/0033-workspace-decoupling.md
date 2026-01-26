# RFC-0033: Velo Workspace Decoupling & Modular Architecture

**Status**: ✅ IMPLEMENTED (v1.0)
**Author**: Velo Architect
**Date**: 2026-01-19
**Implemented**: 2026-01-27
**Scope**: Project Structure, Dependency Governance, Iteration Speed

---

## 1. Executive Summary

Velo is evolving from a single CLI tool into a multi-service runtime platform. Currently, all services (`run`, `serve`, `test`, `analyze`) reside in a single Rust crate with high dependency crosstalk. This RFC proposes the transition to a **Cargo Workspace** and a **Service-Engine Split** to ensure TITANIUM-grade iteration quality and mechanical sympathy.

## 2. The Problem: "Monolithic Inertia"

1.  **Dependency Bloat**: Adding `hyper` for `serve` affects the compilation time and binary risk for `test`, even if they are logically separate.
2.  **Logic Leakage**: 20KB+ of business logic is currently trapped inside the CLI command handlers (`src/cmd/*.rs`), making them un-testable in isolation.
3.  **Compilation Bottleneck**: Parallel execution is limited by the single-crate compilation unit.

## 3. Proposed Architecture: The Velo Workspace

We will transition to a tiered Workspace structure:

```
┌─────────────────────────────────────────────────────────────┐
│                    Velo Workspace                            │
├─────────────────────────────────────────────────────────────┤
│  Tier 1: velo-core (Shared Primitives)                       │
│  ├── Zygote Lifecycle, COW Fork                             │
│  ├── IPC Protocol, SHM Registry                             │
│  └── 0 Dependencies on L7 protocols                         │
├─────────────────────────────────────────────────────────────┤
│  Tier 2: Domain Engines (Independent Compile, Deploy)       │
│  ├── velo-vtest-engine  (Test orchestration, pytest)        │
│  ├── velo-serve-engine  (HTTP proxy, Granian)               │
│  └── velo-live-engine   (Hot-reload, file watch)            │
├─────────────────────────────────────────────────────────────┤
│  Tier 3: velo-cli (Thin Dispatch Layer)                      │
│  └── < 50 lines/command, pure flag -> Engine call           │
└─────────────────────────────────────────────────────────────┘
```

### 3.1. Tier 1: The Sovereign Foundation (`velo-core`)
- **Responsibility**: Zygote lifecycle, COW IPC protocol, SHM Management, Governance/SOP Enforcement.
- **Invariants**: 0 Dependencies on L7 protocols (HTTP/RSGI). Pure system-level logic.

### 3.2. Tier 2: Domain Engines
- **`velo-serve-engine`**: High-perf proxy, HTTP/2+3 stack, protocol translation.
- **`velo-vtest-engine`**: Test discovery, orchestration, result aggregation (MARKER: vtest).
- **`velo-bundle-engine`**: Packaging and static analysis logic.

### 3.3. Tier 3: Command Sovereignty (`velo-cli`)
- **Responsibility**: Thin dispatch layer.
- **Logic**: < 50 lines per command. Simply maps CLI flags to Engine calls.

## 4. Implementation Strategy (The Phased Rollout)

### Phase 1: Engine Extraction (Non-Breaking)
Move logic from `src/cmd/vtest.rs` and `src/cmd/serve.rs` into `src/vtest/` and `src/serve/` as clean Rust modules, removing all CLI-specific dependencies from these sub-engines.

### Phase 2: Workspace Skeleton
- Create `crates/core`, `crates/vtest`, `crates/serve`.
- Convert the root `Cargo.toml` into a `[workspace]`.

### Phase 3: Dependency Pruning
- Strip unnecessary crates from each sub-service.
- Example: `velo-vtest` will no longer compile `hyper-util` or `tower`.

## 5. Governance & Invariants

1.  **INV-WORKSPACE-001**: Domain engines MUST NOT depend on each other. They must only talk via `velo-core` or shared traits.
2.  **INV-WORKSPACE-002**: No business logic in `main.rs` or `cli.rs`.
3.  **INV-WORKSPACE-003**: All engine crates MUST achieve >80% coverage in isolation.

---
**Custodian**: Velo Architect
**Last Updated**: 2026-01-19
