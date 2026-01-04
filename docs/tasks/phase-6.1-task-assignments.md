# Phase 6.1 Task Assignments

> **From**: Architect  
> **Date**: 2026-01-04  
> **Branch**: `phase-6.1/serve-analyze`  
> **RFC**: [0010-phase-6.1-serve-analyze.md](file:///Users/gjwang/eclipse-workspace/rust_source/velo_arch/docs/rfcs/0010-phase-6.1-serve-analyze.md)

---

## 🦀 Rust Developer Tasks

### Week 1: Core (Day 1-5)

| # | Task | RFC Section | Files |
|---|------|-------------|-------|
| D1 | Add CLI args: `--bind`, `--timeout`, `--health-bind`, `--pid-file`, `--log-format` | §5.1.1 | `src/cmd/serve.rs` |
| D2 | Implement `ManagedChild` RAII wrapper (kill on Drop/panic) | §4.9.3, §12.3.3 | `src/serve/runner.rs` |
| D3 | Implement `ShutdownCoordinator` (SIGTERM/SIGINT handling) | §4.9.4 | `src/serve/runner.rs` |
| D4 | Add Gunicorn support for Django/Flask | §4.2, §5.1.3 | `src/serve/framework.rs` |
| D5 | Implement graceful shutdown with timeout | §4.3 | `src/serve/runner.rs` |

### Week 2: Experience (Day 1-5)

| # | Task | RFC Section | Files |
|---|------|-------------|-------|
| D6 | Integrate `notify` crate for file watching | §5.3.1 | `src/serve/watcher.rs` [NEW] |
| D7 | Implement debouncing state machine | §4.4, §5.3.1 | `src/serve/watcher.rs` |
| D8 | Add `ServeError` enum with exit codes | §4.9.1 | `src/serve/error.rs` [NEW] |
| D9 | Implement `velo analyze --graph` savings report | §5.4 | `src/cmd/analyze.rs` |
| D10 | Colored output with timing breakdown | §4.12.6, §5.5 | `src/serve/runner.rs` |

### Week 3: Polish

| # | Task | RFC Section | Files |
|---|------|-------------|-------|
| D11 | Implement "Did you mean?" suggestions (strsim) | §4.12.2 | `src/cmd/serve.rs` |
| D12 | Source-pointing errors (Rust-style) | §4.12.1 | `src/serve/error.rs` |
| D13 | `--prod` mode (no reload, auto workers) | §5.1.1 | `src/cmd/serve.rs` |

---

## 🐍 Python Developer Tasks

| # | Task | RFC Section | Files |
|---|------|-------------|-------|
| P1 | Create `detect_app.py` with AST-based detection | §5.2.2 | `python/detect_app.py` [NEW] |
| P2 | Support factory pattern (`create_app()`) | §4.8, §5.2.2 | `python/detect_app.py` |
| P3 | Return POSIX-style paths (`.as_posix()`) | §12.3.1 | `python/detect_app.py` |

**Deadline**: End of Week 1

---

## 🧪 QA Engineer Tasks

### Security Tests (P0 - Week 1)

| # | Task | RFC Section | Test File |
|---|------|-------------|-----------|
| Q1 | Command injection test (SEC-P0-001) | §4.10.1 | `tests/security/test_command_injection.py` |
| Q2 | Path traversal test (SEC-P0-002) | §4.10.2 | `tests/security/test_path_traversal.py` |
| Q3 | PID file TOCTOU test (SEC-P0-003) | §4.10.3 | `tests/security/test_pid_file.py` |
| Q4 | Health info disclosure test (SEC-P0-004) | §4.10.4 | `tests/security/test_health_endpoint.py` |
| Q5 | Env sanitization test (SEC-P0-005) | §4.10.5 | `tests/security/test_env_sanitization.py` |
| Q6 | Watcher rate limit test (SEC-P0-006) | §4.10.6 | `tests/security/test_watcher_rate_limit.py` |

### Performance Tests (P0 - Week 2)

| # | Task | Threshold | Test File |
|---|------|-----------|-----------|
| Q7 | Cold startup benchmark | <20ms | `tests/performance/test_thresholds.py` |
| Q8 | Restart latency test | <50ms | `tests/performance/test_restart_latency.py` |
| Q9 | Memory overhead test | <50MB | `tests/performance/test_thresholds.py` |

### CI & Accessibility (Week 2-3)

| # | Task | RFC Section | Files |
|---|------|-------------|-------|
| Q10 | Create CI workflow | §4.11 | `.github/workflows/phase-6.1-qa.yml` |
| Q11 | NO_COLOR support test | §4.16 | `tests/accessibility/test_no_color.py` |
| Q12 | Zombie prevention test | §12.3.3 | `tests/systems/test_zombie_prevention.rs` |

---

## Acceptance Criteria

| Metric | Target |
|--------|--------|
| Zero-config success rate | >80% for FastAPI |
| Restart latency | <50ms |
| Security test coverage | 100% on §4.10 |
| Cold startup | <20ms |
