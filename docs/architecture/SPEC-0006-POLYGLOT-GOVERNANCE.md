# SPEC-0006: Velo Polyglot Service Taxonomy & Observability Standard

**Status**: DRAFT (Proposed for Phase 7.2)
**Author**: Architect
**Date**: 2026-01-14

## 1. Introduction
Velo is a complex, polyglot system comprising Rust-native supervision and Python-native execution. To eliminate technical debt at the "Service Mesh" level, this standard defines the mandatory taxonomy for cross-service communication, log attribution, and code organization.

## 2. Service Identity (SID) Protocol
Every active process in the Velo ecosystem MUST have a unique **Service Identity (SID)**.

| Service Role | SID Template | Example |
|:---|:---|:---|
| **Supervisor** | `SUP` | `SUP` |
| **Zygote** | `ZYG:{N}` | `ZYG:0` |
| **Worker** | `WRK:{PID}` | `WRK:1024` |
| **Log Forwarder** | `LOG` | `LOG` |
| **Probe/Health** | `PRB` | `PRB` |

## 3. Log Origin Protocol (LOP)
All logs emitted by Velo (Host or Zygote) MUST follow the unified LOP format to facilitate forensic filtering.

**Format**: `[TIMESTAMP] [SID] [LEVEL] [EVENT_CODE] Message...`

- **[SID]**: As defined in Section 2.
- **[EVENT_CODE]**: Forensic markers (e.g., `VELO-COMPAT-001`, `VELO-SEC-002`).

**Example**:
`2026-01-14T03:30:00 [WRK:1234] WARN [VELO-COMPAT-031] Un-buffered body access detected in Starlette.`

## 4. Polyglot Code Orthogonality
To maintain a clean boundary, the repository follows a strict ownership model:

- **`/src`**: Rust Core (Supervisor, Zygote-Proxy, RSGI-Bridge).
- **`/velo_proxy`** (proposed rename of current Python bits): Velo-owned Python logic (Zygote bootstrap, Environment Shield).
- **`/vendor`**: Vendored Python dependencies (Section 5 of RFC-0024).
- **`/app`**: (User-provided) User application logic.

## 5. Observability Hierarchy
Velo provides three layers of truth for every request lifecycle:
1. **Rust-Host Metrics**: L4/L5 metrics (TCP latency, packet size, SHM pressure).
2. **RSGI-Bridge Events**: L7 protocol transitions (Handshake, Body Draining).
3. **Python-Worker Traces**: Application-level traces (DB queries, middleware timing).

## 6. Industrial Invariants
1. **INV-POLY-001**: No Python worker shall log directly to stdout; all logs must be intercepted and tagged with the SID by the Rust Supervisor.
2. **INV-POLY-002**: Every crash MUST result in a `[CRASH:SID]` forensic report file in `.velo/logs/`.
3. **INV-POLY-003**: Cross-language traces MUST propagate the same TraceID.
