# SPEC-0006: Velo Polyglot Service Taxonomy & Observability Standard

**Status**: DRAFT (Proposed for Phase 7.2)
**Author**: Architect
**Date**: 2026-01-14

## 1. Introduction
Velo is a complex, polyglot system comprising Rust-native supervision and Python-native execution. To eliminate technical debt at the "Service Mesh" level, this standard defines the mandatory taxonomy for cross-service communication, log attribution, and code organization.

## 2. Nominal Sovereignty (Intention-Based Naming)
To minimize ambiguity and prevent "Semantic Hijacking," Velo enforces strict naming conventions across all layers.

### 2.1 Prefix-Directed Intent
Every internal identifier OR file MUST follow a naming prefix that signals its sovereignty:

| Prefix | Domain | Intent | Example |
|:---|:---|:---|:---|
| `core_` | Rust Core | Critical system logic (Unsafe/Kernel-adjacent) | `core_executor.rs` |
| `bridge_` | RSGI Bridge | Cross-language protocol translation | `bridge_payload.rs` |
| `util_` | Shared Utils | Side-effect free helper functions | `util_hash.rs` |
| `v_` | Velo Runtime | Python-side internal runtime logic | `v_shield.py` |
| `compat_` | Compatibility | Framework-specific polyfills/hacks | `compat_starlette.py` |

### 2.2 Variable Sovereignty (Namespacing)
As per **SPEC-0005**, environment variables are tiered. This logic extends to internal Python objects:
- `_v_` (Global/Single Underscore): Protected Velo internal state.
- `__v_` (Double Underscore): Private, un-spoofable engine state (Dunder-Style).
- `app_` (User Space): Reserved for user-provided context.

## 3. Service Identity (SID) Protocol

## 3. Log Origin Protocol (LOP)
All logs emitted by Velo (Host or Zygote) MUST follow the unified LOP format to facilitate forensic filtering.

**Format**: `[TIMESTAMP] [SID] [LEVEL] [EVENT_CODE] Message...`

- **[SID]**: As defined in Section 2.
- **[EVENT_CODE]**: Forensic markers (e.g., `VELO-COMPAT-001`, `VELO-SEC-002`).

**Example**:
`2026-01-14T03:30:00 [WRK:1234] WARN [VELO-COMPAT-031] Un-buffered body access detected in Starlette.`

## 5. Polyglot Code Orthogonality
To maintain "Nominal Sovereignty" and prevent import-path collisions:

- **`/src`**: Rust Core.
- **`/velo_proxy`**: (Proposed) Unified Python sovereignty layer.
    - `velo_proxy/core/`: Engine-facing Python logic.
    - `velo_proxy/compat/`: Framework parity layer.
- **`/vendor`**: Strictly isolated 3rd party code (no direct user modification).
- **`/app`**: User land.

## 5. Observability Hierarchy
Velo provides three layers of truth for every request lifecycle:
1. **Rust-Host Metrics**: L4/L5 metrics (TCP latency, packet size, SHM pressure).
2. **RSGI-Bridge Events**: L7 protocol transitions (Handshake, Body Draining).
3. **Python-Worker Traces**: Application-level traces (DB queries, middleware timing).

## 6. Industrial Invariants
1. **INV-POLY-001**: No Python worker shall log directly to stdout; all logs must be intercepted and tagged with the SID by the Rust Supervisor.
2. **INV-POLY-002**: Every crash MUST result in a `[CRASH:SID]` forensic report file in `.velo/logs/`.
3. **INV-POLY-003**: Cross-language traces MUST propagate the same TraceID.
