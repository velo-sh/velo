# Phase 0: Architecture Alignment Record (Phase 6.1)

**Status**: 🟢 IN-PROGRESS (Deep Audit)
**Leader**: Velo QA Working Group
**Build Target**: v0.6.1

---

## 1. Technical Mandates (MUST/SHALL)

| ID | Category | Requirement Description | Success Criteria |
|:---|:---|:---|:---|
| **ENG-P0-001** | Architecture | Managed Subprocess Model | Rust MUST own signals; No PyO3 direct calls. |
| **ENG-P0-002** | Stability | 300ms Watcher Debounce | Sliding window; ignore events during restart. |
| **MAC-P0-001** | Platform | FSEvents 100ms Latency | Configured via `notify::Config` on macOS. |
| **MAC-P0-002** | Platform | Signal Reset in Fork | `libc::signal` reset to `DFL` in `pre_exec`. |
| **LNX-P0-001** | Platform | inotify Limit Warning | Warn if `/proc/sys/fs/inotify/max_user_watches` < 65536. |
| **LNX-P0-002** | Platform | Container Polling Fallback | 500ms polling if `/.dockerenv` or `cgroup` detected. |
| **CN-P0-001** | Cloud | Health Endpoints | `/healthz` (200), `/readyz` (503 until steady state). |
| **CN-P0-002** | Cloud | SIGTERM Forwarding | Forward to child; wait 30s (timeout) for drain. |
| **CN-P0-003** | Cloud | JSON Structured Logging | Valid JSON schema with `timing_ms` field. |
| **DO-P0-001** | DevOps | PID File Safety | Atomic write with `O_EXCL` (no arbitrary overwrite). |
| **PY-P0-001** | Python | ASGI Lifespan Support | Wait for `lifespan.shutdown.complete` from app. |
| **PY-P0-004** | Python | Fresh Process Guarantee | 100% clean `sys.modules` on every restart. |
| **RS-P0-003** | Rust | RAII Child Cleanup | `Drop` trait MUST kill child and reap zombie. |

## 2. Security "Red Lines" (SEC-P0)

| ID | Requirement | Threat Mitigated | Verification Method |
|:---|:---|:---|:---|
| **SEC-P0-001** | Command Injection | Shell metacharacter rejection | Regex + Forbidden char blacklist check. |
| **SEC-P0-002** | Path Traversal | Rooted scan directory | `canonicalize()` + `starts_with()` project dir. |
| **SEC-P0-003** | PID Symlink Attack | Arbitrary file overwrite | `O_EXCL` flag usage in Rust `OpenOptions`. |
| **SEC-P0-004** | Health Reconnaissance | Information disclosure | 0-metadata response (Status code ONLY). |
| **SEC-P0-005** | Env Hijacking | Execution redirection | Mandatory removal of `PYTHONPATH`, `LD_PRELOAD`. |
| **SEC-P0-006** | Watcher Exhaustion | Resource DoS | Rate limit (100 events/sec) + Throttling. |

## 3. ADR-0010-001 Design Hardening
- **Validation**: MUST occur in `src/cmd/serve.rs` (Fail-fast).
- **Blacklist**: Explicitly forbidden characters: `| & ; $ ` \ " ' < > \n`.
- **Precedence**: CLI flags > ENV vars > Defaults.
- **Signal Reset**: macOS MUST reset signals in `pre_exec`.

## 4. Performance & DX Invariants

- **Hot Restart**: P50 < 50ms, P95 < 100ms.
- **Memory Overhead**: < 50MB (total Velo overhead).
- **Error Fidelity**: Rust-style `-->` and `^^^` markers in error output.
- **Scaling**: Handle 10,000 files with < 3% idle CPU.

---

## 4. Open Questions / Ambiguities
- [ ] **SEC-P0-005**: If Velo removes `PYTHONPATH`, how does it handle legitimate local developer packages? (Assumed: Velo injects project root but wipes parent `PYTHONPATH`).
- [ ] **LNX-P0-002**: Does "poll mode" affect the 300ms debounce timer?

---
**QA Verdict (Phase 0)**: 🟡 Pending Final Extraction Review
