# Leader Architectural Audit: Phase 6.1 Serve Implementation

**Date**: 2026-01-04  
**Audit Role**: Independent Audit Leader  
**Status**: 🚀 **SIGNED-OFF (100% COMPLIANT)**  
**Target**: `src/{cli.rs, cmd/serve.rs, serve/*}`

---

## Traceability Matrix

| Requirement ID | Mandate Description | Implementation Location | Line-by-Line Evidence | Status |
|----------------|---------------------|-------------------------|-----------------------|--------|
| **SEC-P0-001** | Shell Injection Prevention | `src/serve/config.rs` | [L109-134](file://./src/serve/config.rs#L109-134) uses strict Regex `r"^[a-zA-Z_][a-zA-Z0-9_.]*:[a-zA-Z_][a-zA-Z0-9_]*(\(\))?$"` and forbidden character check. | ✅ |
| **SEC-P0-002** | Path Traversal Protection | `src/serve/config.rs` | [L143-160](file://./src/serve/config.rs#L143-160) implements `validate_scan_path` using `canonicalize()` and `starts_with()` check. | ✅ |
| **SEC-P0-003** | PID File Safety (RAII) | `src/serve/runner.rs` | [L722-766](file://./src/serve/runner.rs#L722-766) `ManagedChild` ensures PID file cleanup on `Drop`. | ✅ |
| **SEC-P0-004** | Minimal Health Response | `src/serve/health.rs` | [L84-96](file://./src/serve/health.rs#L84-96) `handle_request` returns ONLY static status strings ("OK"), zero metadata. | ✅ |
| **SEC-P0-005** | Env Sanitization (ADR D3) | `src/serve/runner.rs` | [L136-150](file://./src/serve/runner.rs#L136-150) explicitly removes `PYTHONPATH`, `PYTHONHOME`, `LD_PRELOAD`, etc. | ✅ |
| **SEC-P0-006** | Watcher Rate Limiting | `src/serve/watcher.rs` | [L193-212](file://./src/serve/watcher.rs#L193-212) implements token-bucket-like limit (100 events/sec). | ✅ |
| **MAC-P0-001** | macOS Low-latency | `src/serve/watcher.rs` | [L88-91](file://./src/serve/watcher.rs#L88-91) sets `Duration::from_millis(100)` for macOS in `get_config`. | ✅ |
| **MAC-P0-002** | macOS Signal Reset | `src/serve/runner.rs` | [L376-384](file://./src/serve/runner.rs#L376-384) uses `pre_exec` to reset `SIGINT` and `SIGTERM` to `SIG_DFL`. | ✅ |
| **LNX-P0-001** | Linux inotify limit | `src/serve/watcher.rs` | [L129-137](file://./src/serve/watcher.rs#L129-137) checks `/proc/sys/fs/inotify/max_user_watches` and warns if < 65536. | ✅ |
| **LNX-P0-002** | Container Detection | `src/serve/watcher.rs` | [L94-114](file://./src/serve/watcher.rs#L94-114) checks `/.dockerenv` and `/proc/1/cgroup` for poll mode fallback. | ✅ |
| **CN-P0-001** | Health Server Architecture | `src/serve/health.rs` | Implements thread-based server using `tiny_http` as requested in RFC. | ✅ |
| **CN-P0-003** | JSON Logging (ADR D5) | `src/serve/runner.rs` | [L28-72](file://./src/serve/runner.rs#L28-72) `ServeLogger` implements RFC-0010 §4.7.2 JSON format with timestamp and log flushing. | ✅ |
| **D12** | Rich Error Display | `src/cli.rs` | [L108-111](file://./src/cli.rs#L108-111) intercepts `ServeError` and redirects to `format_source_pointed()`. | ✅ |

---

## Expert Recommendations Verification

1. **Recommendation #1 (Signal Threading)**: DONE. `spawn_signal_forwarder` ([L425-442](file://./src/serve/runner.rs#L425-442)) uses `signal-hook` in a dedicated background thread.
2. **Recommendation #2 (Decoupled Logic)**: DONE. Server logic moved to `src/serve/`, CLI only handles parsing and error display.

## Conclusion

The implementation has been audited against **RFC-0010 (The Hook)** and **ADR-0010-001 (Gap Decisions)**. All "Red Line" security requirements are verified and traced directly to the code. No deviations found.

**Audit Sign-off**: ✍️ *Velo Independent Auditor*
