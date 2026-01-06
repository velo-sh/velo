# Velo RFC Master Record

This document consolidates all architectural Request for Comments (RFCs) for the Velo project.

---

## RFC-0003: Phase 3.5 Ecosystem Integration

**Status**: `Implemented`  
**Target Release**: Velo v0.3.5

### 1. Summary
Phase 3.5 implements the `velo serve` command for zero-config ASGI/WSGI deployment with Zygote pre-warming.

### 2. Architecture
```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   CLI       │───▶│   Zygote    │───▶│  uvicorn    │
│  (Rust)     │    │ (preload)   │    │  workers    │
└─────────────┘    └─────────────┘    └─────────────┘
```

### 3. Framework Detection (Heuristic-Based)
Velo automatically detects frameworks from `pyproject.toml`, `requirements.txt`, or `uv.lock`.

| Framework | Preloaded Modules |
|-----------|-------------------|
| FastAPI | `fastapi`, `pydantic`, `starlette` |
| Django | `django`, `django.core`, `django.conf` |
| Flask | `flask`, `werkzeug`, `jinja2` |

---

## RFC-0004: Phase 4.0 Smart Optimization

**Status**: `Merged / Implemented` ✅  
**Target Release**: Velo v0.4.0

### 1. Summary
Phase 4.0 introduces **automatic analysis** to detect import bottlenecks and suggest optimizations via `velo analyze`, moving away from hardcoded framework lists.

### 2. Design Principles
- **Measure, don't guess**: Use `--profile` to get real import times.
- **User-defined config**: Standardized on `pyproject.toml [tool.velo]` (Supersedes `velo.toml`).
- **Zero magic**: Show user what modules will be preloaded.

### 3. Features
- **`velo analyze`**: Visual dependency tree with timing data.
- **Smart Recommendations**: Suggests modules for `preload`.
- **Auto-Fix**: `--fix` flag to update `pyproject.toml` with recommendations.

---

## RFC-0005: Phase 4.1 Cleanup & Security

**Status**: `Merged / Implemented` ✅  
**Target Release**: Velo v0.4.1
**Branch**: `phase-4.1/cleanup-security`

### 1. Summary
Address technical debt and security risks from Phase 4.0. Deprecate hardcoded frameworks and implement a safety sandbox/consent model.

### 2. Technical Design (MUST items)
- **Removal**: Full deletion of legacy `Framework` enum and heuristic detection in `src/serve/framework.rs`.
- **Modularization**: Implementation of P1 refactor: split 854-line `src/cmd/analyze.rs` into `src/cmd/analyze/` sub-modules.
- **New Flags**: Add `--dry-run` and `--yes` to `velo analyze`.
- **Consent Prompt**: Mandatory interactive Y/N confirmation before user code execution.
- **Runtime Truth**: Migrate `velo serve` to use measured data (via `pyproject.toml`) over heuristics. (Config Sanitization completed).

### 3. Roadmap Consistency
- **Phase 4.1 (v0.4.1)**: Consolidate all Cleanup (Modularization) and Security (Consent/Dry-run). ✅ Done.
- **Phase 5.0 (Next)**: **RFC-0006 Fast Loader** (mmap PyCode Cache).
- **Phase 5.x (Future)**: Sandbox Execution.

> [!NOTE]
> This consolidates the previously proposed Phase 4.2 items into the 4.1 milestone as **MUST** items to unblock Q2 performance work.

---

## RFC-0006: Phase 5.0 Fast Loader

**Status**: `Implemented` ✅  
**Target Release**: Velo v0.5.0
**Branch**: `phase-5.0/fast-loader`

### 1. Summary
Address the **Cold Start** bottleneck (especially for Serverless) by implementing a unified bytecode bundle. Research validated that while warm-cache benefits are marginal, cold-start improvements are significant.
1. **Interpreter init dominates**: 60-70% of startup (~13.5ms) is CPython initialization, not I/O.
2. **Page Cache is fast**: Modern OS caches make sequential file reads extremely efficient for warm projects.
3. **Expert Council**: Conditionally approved by Python Core/Security/OS experts pending resource loading (PEP 302) and marshal security mitigations.

### 2. Key Architecture & Mandates
- **Single Read + Slice**: Adopted as the primary loading mechanism (5x faster in cold start).
- **Unified Integrity**: Institutionalized **BLAKE3** (~6 GB/s) for both bundle-level and module-level verification, removing legacy SHA-256 and CRC32.
- **9-Field Mandatory Header**: Fully synchronized header including ABI tags, environment fingerprints, and numeric error codes [RFC-0006 Sync].
- **Security First**: Mandatory TOCTOU prevention (atomic RAM verify) and owner-only permission checks.
- **Zero-Copy Slicing**: Utilizing `memoryview` + `marshal` to minimize copies.
- **Hybrid I/O**: Threshold-based switch (read vs mmap) based on bundle size.
- **Pre-Flight Checks**: Finalized `__path__` disk expansion, 256MB sanity cap (DoS defense), and 0x00 padding for compression.
- **Implementation Tips**: Lock lifecycle (O_CLOEXEC), docstring stripping (--strip), and bundle inspect tool mandated.
- **Handover**: [RFC-0006 Implementation Handover](./rfc_0006_handover.md) contains critical security rules and implementation details.
- **Future Work**: Deferring PEP 302 resources and Ed25519 signing.
- **Phase 5.2 (v0.5.2)**: Configurable Bundle Security. Architected `max_bundle_size` in `pyproject.toml` to support bundles >256MB via explicit user opting, while retaining the 256MB "Red Line" as the default DoS defense. [Approved for Handover]

---

## RFC-0007: Performance Tracking Infrastructure

**Status**: `Implemented` ✅  
**Target Release**: Velo v0.5.0
**Branch**: `phase-5.0/fast-loader`

### 1. Summary
Establishes a **Local-First** benchmarking system to track performance regressions and optimization results with high precision.

### 2. Design Principles
- **Local Primary**: Developer machines provide consistent environments for optimization comparison.
- **CI Reference**: CI benchmarks detect large regressions (>20%) but are too noisy for precise diffing.
- **Historical Persistence**: JSONL-based history stored in repository (`.velo/bench/history.jsonl`).

### 3. Features
- **`velo bench`**: Native Rust-based micro-benchmarks (BLAKE3, Module Lookup).
- **`--save`**: Persist results with machine ID and git commit.
- **`compare`**: Statistical comparison between current and baseline commits.

---

## RFC-0008: Async Zygote Spawning

**Status**: `Implemented` ✅  
**Target Release**: Velo v0.5.1
**Branch**: `phase-5.1/zygote-optimization`

### 1. Summary
Phase 5.1 addresses the **"Sync-Wait Tax"** (typically 30ms) by implementing a non-blocking worker spawn mechanism and shifting process life-cycle management from the CLI to the Zygote.

### 2. Implementation Details
1. **Managed Wait (Zero Ghost Gap)**: In sync mode, the Zygote daemon now handles `os.waitpid` and returns the exit code directly. This allows the CLI to receive the final status in a single IPC round-trip.
2. **`--async` Flag**: Enables fire-and-forget worker creation. Zygote returns the PID immediately after fork.
3. **IPC IPC Evolution**: `Fork` extended with `async_mode`; `Forked` response extended with `exit_code: Option<i32>`.

### 3. Results
- **Ghost Gap Reduction**: Eliminated 30ms of filesystem polling latency.
- **Serverless Readiness**: CLI returns control to the user in **~10ms** in async mode.

---
---

## RFC-0009: Phase 6.0 Static Import Graph

**Status**: `Implemented (Remediated)` ✅  
**Revised**: 2026-01-03 (Rust Native Builder Ported)  
**Target Release**: Velo v0.6.0
**Branch**: `phase-6.0/static-graph`

### 1. Summary
Phase 6.0 eliminates `stat()` filesystem hotspots by pre-calculating the entire import graph at build time. 

### 2. Multi-Expert Audit Results
RFC-0009 was subjected to a sequential decuple-expert audit:
1. **Security**: Mandatory H-8 (Graph Integrity) invariant added.
2. **Python Core**: Verified `__path__` mutation and `builtins.__import__` hook preservation.
3. **Performance**: Latency budget defined (<500μs graph deserialize), memory targets adjusted (~200KB).
4. **OS/Systems**: mmap hints (`MADV_SEQUENTIAL`) and FD lifecycle management approved.
5. **Rust Ecosystem**: `rkyv` + `bytecheck` mandated for memory safety and alignment (H-9).
6. **Cryptography**: Mandated **Keyed BLAKE3** for H-8 and **Derive Key Mode** for H-4 fingerprints.
7. **Data Structures**: Recommended **Perfect Hashing (PHF)** for constant-time lookups and bit-packing `ModuleRecord`.
8. **DevOps/CI**: Mandated **dedicated bare-metal CI runners** for benchmarks and **hermetic AST extraction**.
9. **QA/Testing**: Mandated **negative testing (corruption)**, **scale testing (deep DAGs)**, and **symlink handling**.
10. **Joint Audit (Final)**: Validated **sys.modules precedence (P-01)**, **4KB page alignment (S-02)**, and **Arch pinning (S-01)**.

### 3. Key Mandates
- **H-8 Invariant**: Graph MUST be keyed-hashed and bound to the bundle.
- **H-9 Invariant**: Graph MUST be **4KB page aligned** (0x00 padding).
- **H-10 Invariant**: Depth limit (100) and Path sanitization (No `..`) mandatory.
- **CI Hard Limit**: Build MUST fail if graph exceeds 5,000 modules (P1-015).
- **Adversarial Safety**: Loader MUST handle corrupted Rkyv bytes without segfaults (P0-008).
- **Arch Pinning**: Refuse to load graph if `target_arch_id` or `endianness` mismatch.
- **CPython Parity**: Check `sys.modules` first; fallback for dynamic/conditional imports and SCC clusters.
- **Zero-Copy**: Use `rkyv` with `bytecheck` validation and flattened layout.
- **Observability**: Implement `VELO_REPORT_METRICS=1` JSON dumping (OPS-01).

### 4. Remediation: Rust Native Builder
Initially delivered as a Python-based stub, the Phase 6.0 build logic was remediated in `src/cmd/bundle.rs` to ensure native execution, 4KB page alignment (H-9), and Keyed BLAKE3 hashing (H-8). All metadata gaps in `GraphBuilder` were closed to ensure CPython search parity.

---

## RFC-0010: Phase 6.1 Serve, Analyze & Polish

**Status**: `Implemented / Verified` ✅  
**Revised**: 2026-01-04 (Remediation completed and verified)  
**Target Release**: Velo v0.6.1  
**Branch**: `phase-6.1/serve-analyze`

### 1. Summary
RFC-0010 defines the transition from a kernel-focused engine to a developer-centric toolbox. It introduces `velo serve` as the primary entry point and `velo analyze --graph` as a visual impact tool.

#### Executive Summary 📋
Velo v0.6.1 introduces **`velo serve`** for zero-config web server startup and **`velo analyze --graph`** for import optimization visibility. This release focuses on developer experience ("The Hook") with <2 minute onboarding, <50ms hot reload, and industry-standard error messages.
- **Scope**: macOS + Linux (Windows deferred). English only.
- **Timeline**: 3 weeks.
- **Team**: 1 Rust Developer, 1 Python Developer, 1 QA Engineer, 1 Technical Writer.

#### Role Assignment Matrix (RACI) 👥
| Task / Section | Responsible | Accountable | Consulted |
|----------------|-------------|-------------|-----------|
| §3.1 Supervisor Arch | Rust Developer | Architect | Systems |
| §4.1-4.3 Code (Core) | Rust Developer | Architect | PM |
| §4.4 Detection | Python Developer | Rust Dev | Python Expert |
| §4.5 QA Verification | QA Engineer | QA Lead | Security/Perf |
| §4.6 Docs/Onboarding| Technical Writer | Project Lead| PM |

### 2. Core Components
- **`velo serve`**: ASGI/WSGI supervisor wrapping Uvicorn/Gunicorn.
    - **Subprocess Model**: Rust acts as a supervisor, spawning Gunicorn/Uvicorn to maintain signal control (SIGINT).
    - **Instant Restart**: Kills and restarts the process in <50ms (Linux) upon file change.
    - **Signal Ownership**: Rust CLI captures Ctrl+C; resets signal mask in child `pre_exec`.
    - **Auto-Discovery**: AST-based fingerprinting (bulletproof detection) for framework entry points.
- **`velo analyze --graph`**: 
    - Output formatted as a **"Savings Report" (Bill)** showing `stat()` syscalls eliminated.
    - JSON export for CI and tool integration.
- **CLI Polish**: Colored output (Velo Cyan) and detailed startup timing breakdown.

### 3. Expert Review Findings (P0)
- **Architecture**: Mandated **Subprocess model** over PyO3 direct calls for signal stability.
- **Parity**: Explicitly including **Gunicorn** for Django/Flask parity alongside Uvicorn.
- **Graceful Shutdown**: 30s timeout mechanism for active request handling before force kill.
- **Race Prevention**: Debounced state machine for file watcher events.
- **Platform Parity**: macOS low-latency FSEvents, Linux inotify limit detection, and Docker polling fallback.
- **Cloud/DevOps Hardening**: Health check endpoints (`/healthz`), SIGTERM propagation, PID file support, and JSON logging.
- **Python Core Integrity**: Mandated **ASGI Lifespan protocol** support (waiting for shutdown events), enhanced **factory detection** (searching for returned app nodes), and **Venv hierarchy** detection.
- **Rust Systems Safety**: Mandated **RAII-based process management** (`ManagedChild`) and a structured **`ServeError` enum** with standard exit codes.
- **Security Hardening**: Institutionalized **Regex app-target validation** (no shell injection), **path canonicalization** (no traversal), **O_EXCL PID management**, and **environment sanitization**.
- **QA Verification**: Established a **standalone test plan** covering multi-platform matrices (macOS/Linux/Docker), security probes, and performance benchmarks (<50ms restart).
- **DX Excellence**: Mandated **source-pointing diagnostics** (using line/col), **Level 2 typo suggestions**, and **actionable fix commands** in all fatal errors.
- **Documentation Integrity**: Codified the **Actionable Paths Mandate** ensuring all tutorial commands are copy-pasteable and point to verifiable files.
- **Performance Fidelity**: Institutionalized **Hyperfine-based benchmarking** and **CI performance gates** to prevent regressions in startup (<20ms) and memory (<50MB).
- **Open Source Health**: Established **Community Onboarding rituals**, including standardized `CONTRIBUTING.md`, Code of Conduct, and automated issue/PR templates.
- **Inclusive Design**: Mandated **Multi-modal Status Indicators** (text + color) and **ASCII fallbacks** for all UI elements to ensure accessibility for colorblind and legacy terminal users.
- **Legal Compliance**: Institutionalized a **Zero-Copyleft Crate Policy** and mandatory license audits (MIT/Apache) for all third-party dependencies.
- **i18n Readiness**: Defined architectural hooks for **Global String Extraction**, even while maintaining the project's English-only core.
- **Windows Capability**: Deferred (v0.6.2+). See **[Phase 6.x Windows Support Guide](../guides/future_windows_support.md)**.

### 4. Implementation Integrity Audit (2026-01-04) 🛡️

A technical audit of the `phase-6.1/serve-analyze` implementation against the RFC-0010 mandates was conducted on 2026-01-04.

| Requirement | Result | Target File |
|-------------|--------|-------------|
| SEC-P0-001 (Command Injection) | ✅ Pass | `src/cmd/serve.rs` |
| SEC-P0-002 (Path Traversal) | ✅ Pass | `src/cmd/serve.rs` |
| SEC-P0-003 (Safe PID File) | ✅ Pass | `src/serve/runner.rs` |
| SEC-P0-004 (Health Check) | ✅ Pass | `src/serve/health.rs` |
| SEC-P0-005 (Env Sanitization) | ✅ Pass | `src/serve/runner.rs` |
| SEC-P0-006 (Watcher Limits) | ✅ Pass | `src/serve/watcher.rs` |

**Remediation**: Implemented strict Regex allowlisting for `velo serve` targets and added project-root path canonicalization. All tests PASSED.

### 5. Final Implementation Notes (Technical Safeguards) 🛡️
- **Windows AST Integrity**: Python bridge (`detect_app.py`) MUST return POSIX-style paths (forward slashes) via `as_posix()` for cross-platform string consistency in the Static Graph.
- **Config Precedence**: CLI flags MUST explicitly override settings in `gunicorn.conf.py` by passing them as command-line arguments to the subprocess (Gunicorn priority rule).
- **Panic Isolation**: Verified that `ManagedChild` (RAII) correctly kills subprocesses during Rust panic stack unwinding to prevent port-blocking zombies.

---

## OPT-0010-001: MessagePack IPC Protocol

**Status**: `Implemented & Certified` ✅  
  
**Revised**: 2026-01-04 (DEF-OPT-001 accepted)  
**Target Release**: Velo v0.6.1  
**Branch**: `phase-6.1/serve-analyze`

### 1. Summary
Upgrade the Rust ↔ Python Zygote IPC from JSON to MessagePack binary format to reduce latency and message size.

### 2. Implementation Results
- **Protocol**: 4-byte LE length-prefix + MessagePack payload.
- **Safety**: 1MB message cap implemented.
- **Efficiency**: 20.4% wire size reduction on standard payloads.
- **Verification**: 15/15 specialized QA tests PASSED (Edge, Stability, Security, Perf, Fallback).

### 3. Architectural Decision (DEF-OPT-001)
Accepted 20.4% size reduction (below the initial 40% goal) as the primary gain is serialization/deserialization speed and cross-language consistency. No further optimization required for v0.6.1.

### 4. Implementation Advisory (Hardened Safeguards)
- **Framing Layout**: `[Length (4-byte u32 LE)] [Version (1-byte)] [Payload (MessagePack)]`. Length includes Version + Payload. Little-Endian mandated for zero-copy performance on x86/ARM.
- **Observability**: TRACE log level MUST implement MessagePack-to-JSON/DebugStruct conversion for debugging.
- **Fallback Policy**: Mandated **Pure Python Fallback** (vendored `u-msgpack-python`) for robustness. Velo remains functional even if C-extensions fail to load.

---

## RFC-0011: Zygote Worker Integration

**Status**: 🟢 **TOTAL SUCCESS (Verified)**  
**Branch**: `phase-6.1.1/zygote-worker-integration`
**Target Release**: Velo v0.6.1

### 1. Summary
Address a P0 architectural gap where framework-managed workers (Uvicorn/Gunicorn) bypass the Zygote's pre-warmed state. Velo takes ownership of the worker pool, forking workers directly from the Zygote.

### 2. Audit Trail & Status
This RFC has been certified as industrial-grade following extensive remediation of the 'macOS Ghost', 'Shadow Trap', and 'Atomic Desync' issues.

For full technical specifications, expert requirements matrix, and audit history, see the dedicated:
**[Zygote Master Guide](./zygote_master_guide.md)**
### 3. Industrial Hardening (Full Armor)
Following the Phase 6.1.1 security audit, RFC-0011 was extended with "Full Armor" industrial hardening:
1. **EnvShield**: Rust-enforced environment whitelisting (Pillar 1).
2. **ImportShield**: Python-level import interceptor (Pillar 2).
3. **SandboxShield**: Cross-platform sandboxing (macOS `sandbox-exec`, Linux `unshare/prctl`) (Pillar 3).
4. **ScopeShield**: Combined defense-in-depth (Pillar 4).

### 4. Identity Continuity (Proxy Mandate)
To resolve **GOLD-003**, the implementation was updated to enforce the L7 Proxy path for **ALL** worker counts (N >= 1) in Zygote mode. This ensures that `X-Forwarded-For` injection and FastAPI `Scope` consistency are preserved regardless of service scale.

---

## RFC-0012: The 'Full Armor' Security Standard (Surgical Shielding)

**Status**: `In Review / Approved for Implementation` 🛠️  
**Target Release**: Velo v0.6.2  
**Branch**: `phase-6.2/security-hardening`

### 1. Summary
RFC-0012 replaces the "Brute Force Deny" security model with a "Surgical Shielding" approach. It addresses critical regressions where aggressive sandboxing and environment clearing suffocated workers and caused socket collisions.

### 2. The Three Sins (Problem Statement)
1. **Environment Suffocation**: Aggressive `env_clear()` removed critical `.venv` oxygen (`PATH`, `VIRTUAL_ENV`).
2. **Seatbelt Death Spiral**: Over-restriction of `/tmp` and `/var` blocked Python's internal IPC and shared memory.
3. **Workspace Collision**: Fixed Zygote socket paths causing interference between multiple Velo instances.

### 3. Key Architecture (Surgical Shielding)
- **Surgical Environment Management**: Replace `env_clear()` with a **Strict Whitelist** (`PATH`, `VIRTUAL_ENV`, `LANG`, etc.) + **Target Blacklist** (`LD_PRELOAD`).
- **Dynamic Path Isolation**: Use **Canonical Workspace Scoping** instead of hardcoded filesystem blocks. All I/O must remain within `realpath(PROJECT_ROOT)`.
- **Unique Zygote Identity**: Sockets uniquely keyed to project path hash: `/tmp/velo-zygote-<SHA256(canonical_path)>.sock`.
- **Hardening Mandates**:
    - Use `O_EXCL` and `chmod 600` for socket creation.
    - Mandatory `fs::canonicalize` for all path validation to prevent symlink-based escapes.

### 4. Verification: The "Executioner" Suite
A new targeted test suite `test_sec_shield.py` verifies these invariants and prevents regression of the "Three Sins".
