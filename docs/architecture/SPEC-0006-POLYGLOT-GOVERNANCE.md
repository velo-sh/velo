# SPEC-0006: Velo Polyglot Service Taxonomy & Observability Standard

**Status**: APPROVED (Phase 7.3 Stabilization)
**Author**: Architect
**Date**: 2026-01-15

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
- `__v_` (Double Underscore): Private, un-spoofable engine state (utilizing Python's name-mangling).
- `app_` (User Space): Reserved for user-provided context.

### 2.3 Naming Best Practices (Good vs. Bad)
| Aspect | ✅ Good (Sovereign) | ❌ Bad (Ambiguous) |
|:---|:---|:---|
| **Python Core** | `v_shield_manager.py` | `security.py` |
| **Rust IPC** | `bridge_payload_decoder.rs` | `message.rs` |
| **Env Var** | `VELO_SYS_SOCK_FD` | `VELO_FD` |
| **Worker Log** | `log.info("Request processed")` | `log.info("[WRK:123] Processed")` |

> [!CAUTION]
> Manually injecting `[SUP]` or `[SID]` tags into log strings is a violation of **INV-POLY-004** and will be flagged as an intrusion attempt.

## 3. Service Identity (SID) Protocol

## 3. Log Origin Protocol (LOP)
All logs emitted by Velo (Host or Zygote) MUST follow the unified LOP format to facilitate forensic filtering.

**Format**: `[TIMESTAMP] [SID] [LEVEL] [EVENT_CODE] Message...`

- **[SID]**: As defined in Section 2.
- **[EVENT_CODE]**: Forensic markers (e.g., `VELO-COMPAT-001`, `VELO-SEC-002`).

**Example**:
`2026-01-14T03:30:00 [WRK:1234] WARN [VELO-COMPAT-031] Un-buffered body access detected in Starlette.`

## 4. Log Sovereignty & Safety (Anti-Spoofing)
In a multi-process environment, log integrity is paramount. Velo enforces **Supervisor-Attributed Logging**.

### 4.1 The "Sovereign Tagging" Protocol
- **Constraint**: Workers are FORBIDDEN from tagging their own logs with an SID. 
- **Mechanism (Rust Host)**: The Supervisor captures the `stdout`/`stderr` of each worker via a dedicated pipe. The Supervisor then wraps the raw payload with the authoritative `[SID]` and `[TIMESTAMP]` before writing to the final log sink.
- **Security**: This prevents a compromised Worker from spoofing a different `WRK:PID` or, more crucially, impersonating the `SUP` (Supervisor) to inject false instructions or deceptive metadata.

### 4.2 Sink-Side Scrubbing (Redaction)
To prevent the "Sin of Leakage," the Rust Supervisor implements a high-performance **Redaction Filter** on all outgoing log streams:
1. **Secret Masking**: Matches patterns like `VELO_APP_SECRET=*` and replaces with `[REDACTED]`.
2. **Path Sanitization**: Replaces absolute user paths (e.g., `/Users/gjwang/`) with relative project anchors.
3. **Forensic Code Injection**: Automatically attaches the relevant `[EVENT_CODE]` based on the stream origin (e.g., `stderr` triggers a default `VELO-ERR` code).

### 4.3 Serialization & Atomicity (Concurrency Safety)
To prevent log corruption/interleaving when multiple workers emit data simultaneously:
- **Single-Writer Pattern**: The Rust Supervisor acts as the **Sole Sequencer** for the log sink. Workers pipe data to the Supervisor; they NEVER open the log file directly.
- **Line-Atomic Buffering**: The Supervisor uses line-buffered reading from child pipes. A log entry is only committed to the sink once a newline (`\n`) is reached, ensuring that lines from `WRK:A` and `WRK:B` are never interleaved.
- **Async Queueing**: Internally, the Supervisor utilizes a non-blocking MPMC or MPSC channel (e.g., `tokio::sync::mpsc`) to queue log events, ensuring that the critical path of worker execution is not blocked by log I/O.

### 4.4 Performance Invariants (Mechanical Sympathy)
Centralizing logs in the Rust Supervisor provides significant throughput gains over traditional Python logging:
- **Offloading I/O**: Workers perform **zero** blocking Disk I/O. Writing to a Pipe is an in-memory kernel operation (O(1) from the user-space perspective), effectively offloading the expensive syscalls to the Supervisor.
- **Zero-Formatter Overhead**: Python workers emit raw strings/bytes. Complex formatting, SID tagging, and TIMESTAMP generation are performed in Rust, which is orders of magnitude faster at string manipulation.
- **Batched Sinks**: The Supervisor can batch multiple log entries into a single `write()` call to the file system or network sink, drastically reducing the total number of system calls.
- **Cache Locality**: By centralizing the writing logic in a single Rust thread, we minimize cache misses and lock contention on the global file system table.

## 5. Polyglot Code Orthogonality
To maintain "Nominal Sovereignty" and prevent import-path collisions:

- **`/src`**: Rust Core.
- **`/velo_proxy`**: (Proposed) Unified Python sovereignty layer.
    - `velo_proxy/core/`: Engine-facing Python logic.
    - `velo_proxy/compat/`: Framework parity layer.
- **`/vendor`**: Strictly isolated 3rd party code (no direct user modification).
- **`/app`**: User land.

## 6. Observability Hierarchy
Velo provides three layers of truth for every request lifecycle:
1. **Rust-Host Metrics**: L4/L5 metrics (TCP latency, packet size, SHM pressure).
2. **RSGI-Bridge Events**: L7 protocol transitions (Handshake, Body Draining).
3. **Python-Worker Traces**: Application-level traces (DB queries, middleware timing).
    - **TraceID Propagation**: Mandated via **X-Velo-Trace-ID** internal RSGI headers for cross-language continuity.

## 7. Industrial Invariants
1. **INV-POLY-001**: No Python worker shall log directly to a file; all output MUST flow through the Supervisor-managed pipe.
2. **INV-POLY-002**: Every crash MUST result in a `[CRASH:SID]` forensic report file in `.velo/logs/`.
3. **INV-POLY-003**: Cross-language traces MUST propagate the same TraceID.
4. **INV-POLY-004 (Anti-Spoofing)**: Any log line attempting to manually inject a `[SUP]` or `[SID]` tag from user-space shall be flagged as a `VELO-SEC-004` (Log Poisoning Attempt).
