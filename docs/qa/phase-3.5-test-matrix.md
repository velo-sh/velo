# Phase 3.5 Ecosystem Integration - QA Test Matrix

> **Related RFC**: RFC-0003 (pending)  
> **Target Release**: v0.3.5  
> **QA Lead**: Multi-Agent Architecture

---

## 1. Test Environment Setup

```bash
# Build Velo with serve support
cargo build --release

# Ensure uv environment with frameworks
uv sync
uv pip install fastapi uvicorn django flask
```

---

## 2. Phase 3.5.1: `velo serve` Command

### 2.1 CLI Validation (SERVE-CLI-xxx)

| ID | Scenario | Command | Expected Result | Pass/Fail |
|----|----------|---------|-----------------|-----------|
| SERVE-CLI-001 | Help displays serve | `velo --help` | "serve" in output | ☐ |
| SERVE-CLI-002 | Serve subcommand help | `velo serve --help` | Shows options | ☐ |
| SERVE-CLI-003 | Missing app argument | `velo serve` | Error: missing app | ☐ |
| SERVE-CLI-004 | Invalid app format | `velo serve nocolon` | Error: invalid format | ☐ |
| SERVE-CLI-005 | Unknown option | `velo serve main:app --foo` | Error: unknown option | ☐ |

### 2.2 Option Parsing (SERVE-OPT-xxx)

| ID | Option | Valid Value | Invalid Value | Pass/Fail |
|----|--------|-------------|---------------|-----------|
| SERVE-OPT-001 | `--port` | `8000` | `abc` (error) | ☐ |
| SERVE-OPT-002 | `--workers` | `4` | `-1` (error) | ☐ |
| SERVE-OPT-003 | `--host` | `0.0.0.0` | - | ☐ |
| SERVE-OPT-004 | `--reload` | flag only | - | ☐ |

---

## 3. Phase 3.5.2: WorkerPool & Signal Handling

### 3.1 Worker Lifecycle (POOL-xxx)

| ID | Scenario | Steps | Expected Result | Pass/Fail |
|----|----------|-------|-----------------|-----------|
| POOL-001 | Start workers | `velo serve main:app --workers 4` | 4 workers running | ☐ |
| POOL-002 | Worker crash recovery | Kill one worker | Auto-restart | ☐ |
| POOL-003 | Scale down | Reduce workers config | Graceful shutdown | ☐ |
| POOL-004 | Zero workers | `--workers 0` | Error or default to 1 | ☐ |
| POOL-005 | Max workers limit | `--workers 1000` | Capped or warned | ☐ |

### 3.2 Signal Handling (SIG-xxx) - Rust 2024 Compliant

| ID | Signal | Expected Behavior | Pass/Fail |
|----|--------|-------------------|-----------|
| SIG-001 | SIGTERM | Graceful shutdown, exit 0 | ☐ |
| SIG-002 | SIGINT (Ctrl+C) | Graceful shutdown | ☐ |
| SIG-003 | SIGHUP | Reload config (optional) | ☐ |
| SIG-004 | Double SIGTERM | Force kill | ☐ |
| SIG-005 | SIGKILL | Immediate exit (OS) | ☐ |

### 3.3 Framework Detection (FW-xxx)

| ID | Framework | Detection Method | Preload Modules | Pass/Fail |
|----|-----------|------------------|-----------------|-----------|
| FW-001 | FastAPI | `fastapi` in deps | `fastapi, starlette, pydantic` | ☐ |
| FW-002 | Django | `django` in deps | `django, django.core` | ☐ |
| FW-003 | Flask | `flask` in deps | `flask, werkzeug` | ☐ |
| FW-004 | Unknown | No match | Generic preload | ☐ |

---

## 4. Phase 3.5.3: Integration & Performance

### 4.1 E2E Tests (E2E-xxx)

| ID | Scenario | Steps | Expected | Pass/Fail |
|----|----------|-------|----------|-----------|
| E2E-001 | FastAPI health | `velo serve main:app`, curl /health | 200 OK | ☐ |
| E2E-002 | With Zygote | Auto-Zygote integration | < 100ms first worker | ☐ |
| E2E-003 | Hot reload | Modify app.py, auto-reload | Changes reflected | ☐ |
| E2E-004 | Shutdown | SIGTERM during requests | No dropped requests | ☐ |

### 4.2 Performance Metrics

| ID | Metric | Target | Actual | Pass/Fail |
|----|--------|--------|--------|-----------|
| PERF-3.5-001 | First worker startup | < 100ms | | ☐ |
| PERF-3.5-002 | Request latency (P99) | < 50ms | | ☐ |
| PERF-3.5-003 | Memory per worker (COW) | < 50% standalone | | ☐ |

---

## 5. Error Handling (ERR-3.5-xxx)

| ID | Scenario | Expected | Pass/Fail |
|----|----------|----------|-----------|
| ERR-3.5-001 | App module not found | Clear error message | ☐ |
| ERR-3.5-002 | Port already in use | Error + suggestion | ☐ |
| ERR-3.5-003 | uvicorn not installed | Install hint + fallback | ☐ |
| ERR-3.5-004 | App crashes on start | Error propagated | ☐ |
| ERR-3.5-005 | Permission denied (port 80) | Sudo hint | ☐ |

---

## 6. Sign-off

| Gate | Criteria | Status |
|------|----------|--------|
| Phase 3.5.1 | CLI + option parsing | ☐ |
| Phase 3.5.2 | WorkerPool + signals | ☐ |
| Phase 3.5.3 | E2E + performance | ☐ |

| Role | Name | Date | Signature |
|------|------|------|-----------|
| QA Lead | | | |
| Dev Lead | | | |
| Architect | | | |

---

**Document End**
