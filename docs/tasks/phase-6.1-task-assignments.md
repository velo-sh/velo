# Phase 6.1 Task Assignments

> **Role**: Execution Breakdown (RACI Support)  
> **RFC**: [0010-phase-6.1-serve-analyze.md](../rfcs/0010-phase-6.1-serve-analyze.md)  
> **Branch**: `phase-6.1/serve-analyze`  
> **Status**: ASSIGNED (2026-01-04)

---

## 🦀 Rust Developer Tasks

### Week 1: Core (Day 1-5)

| ID | Task | RFC Section | Deliverable |
|:---|:---|:---|:---|
| **D1** | CLI Argument Hardening: Add `--bind`, `--timeout`, `--health-bind`, `--pid-file`, `--log-format`. | §5.1.1 | `src/cmd/serve.rs` |
| **D2** | Implement `ManagedChild` RAII wrapper: Ensure subprocesses are killed and reaped on `Drop` (including panics). | §4.9.3, §12.3.3 | `src/serve/runner.rs` |
| **D3** | `ShutdownCoordinator`: Integrate `signal-hook` for SIGTERM/SIGINT propagation. | §4.9.4 | `src/serve/runner.rs` |
| **D4** | Framework Mapping: Add Gunicorn support for Django/Flask WSGI apps. | §4.2, §5.1.3 | `src/serve/framework.rs` |
| **D5** | Graceful Shutdown Logic: Implement the 30s drain timer before force-killing workers. | §4.3 | `src/serve/runner.rs` |

### Week 2: Experience (Day 1-5)

| ID | Task | RFC Section | Deliverable |
|:---|:---|:---|:---|
| **D6** | File Watcher Integration: Add `notify` crate with per-platform optimizations (macOS FSEvents latency). | §5.3.1 | `src/serve/watcher.rs` |
| **D7** | Debounce Engine: Implement 300ms cooldown state machine to prevent thrashing. | §4.4, §5.3.1 | `src/serve/watcher.rs` |
| **D8** | Error Strategy: Create `ServeError` enum with industry-standard exit codes (e.g. 98 for EADDRINUSE). | §4.9.1 | `src/serve/error.rs` |
| **D9** | Statistics Visualization: Implement `analyze --graph` "Savings Report" (stat() count). | §5.4 | `src/cmd/analyze.rs` |
| **D10**| UX Polish: Multi-modal coloring (Velo Cyan) and timing breakdown display. | §4.12.6, §5.5 | `src/serve/runner.rs` |

### Week 3: Transition & Polish

| ID | Task | RFC Section | Deliverable |
|:---|:---|:---|:---|
| **D11**| DX Typo Matching: Integrate `strsim` for Levenshtein-based CLI flag suggestions. | §4.12.2 | `src/cmd/serve.rs` |
| **D12**| Diagnostic UI: Rust-style source-pointing errors for failed detection. | §4.12.1 | `src/serve/error.rs` |
| **D13**| Production Mode: Implement `--prod` flag (reload disabled, auto-worker scaling). | §5.1.1 | `src/cmd/serve.rs` |
| **D14**| MessagePack IPC: Upgrade Rust↔Python IPC from JSON to MessagePack. | [FUTURE-msgpack-ipc](../rfcs/FUTURE-msgpack-ipc.md) | `src/zygote/ipc.rs`, `python/velo_zygote/` |

---

## 🐍 Python Developer Tasks

| ID | Task | RFC Section | Target |
|:---|:---|:---|:---|
| **P1** | AST Discovery: Create `detect_app.py` to identify FastAPI/Flask/Django entry points. | §5.2.2 | `python/detect_app.py` |
| **P2** | Factory Support: Implement search for `create_app()` patterns in module scope. | §4.8, §5.2.2 | `python/detect_app.py` |
| **P3** | Windows Compatibility: Enforce POSIX-style path returns (`as_posix()`). | §12.3.1 | `python/detect_app.py` |

---

## 🧪 QA Engineer Tasks

### Security & Safety (P0 - Week 1)

| ID | Task | Focus | Target Coverage |
|:---|:---|:---|:---|
| **Q1** | SEC-P0-001: Command injection rejection probes. | Injection | 100% |
| **Q2** | SEC-P0-002: Path traversal and canonicalization checks. | Traversal | 100% |
| **Q3** | SEC-P0-003: PID file race condition validation (`O_EXCL`). | Races | 100% |
| **Q4** | SEC-P0-004: Health endpoint info disclosure audit. | Disclosure | 100% |
| **Q5** | SEC-P0-005: Environment sanitization (`PYTHONPATH` removal). | Hijacking | 100% |
| **Q6** | SEC-P0-006: File watcher rate limiting and DoS prevention. | Stability | 100% |

### Performance & Integration (Week 2)

| ID | Task | Threshold | Metric |
|:---|:---|:---|:---|
| **Q7** | Startup Latency: Cold startup verification using Hyperfine. | <20ms | Speed |
| **Q8** | Restart Latency: File-change-to-ready timing. | <50ms | UX |
| **Q9** | Resource Footprint: Memory overhead monitoring under load. | <50MB | Efficiency |
| **Q12**| RAII Validation: Verify zero zombie processes after binary panic. | Atomic | Safety |

### CI & Accessibility (Week 3)

| ID | Task | Standard | Component |
|:---|:---|:---|:---|
| **Q10**| CI Automation: Scaffolding `.github/workflows/phase-6.1-qa.yml`. | Regression | Infrastructure |
| **Q11**| A11y Verification: `NO_COLOR` and ASCII fallback tests. | Inclusive | UX |

---

## Status Tracking Invariants

- **Definition of Done**: A task is only complete when its designated level in the [QA Test Plan](../qa/phase-6.1-qa-framework.md) is Green.
- **Panic Rule**: Changes to `src/serve/runner.rs` must include unit tests verifying `Drop` behavior.
- **Command Lock**: Every CLI argument change must update `docs/guides/phase-6.1-documentation-guide.md`.

---

*Reference: RFC-0010*
