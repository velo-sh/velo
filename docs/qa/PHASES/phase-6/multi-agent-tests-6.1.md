# Phase 6.1 Serve & Analyze - Multi-Agent QA Test Design

> **Method**: 4 independent QA perspectives for comprehensive coverage  
> **RFC**: [RFC-0010](../rfcs/0010-phase-6.1-serve-analyze.md)  
> **Branch**: `phase-6.1/serve-analyze`

---

## Agent A: Edge Case Hunter (激进派)

**Mission**: Find every corner case that breaks the system.

### Serve CLI Edge Cases (EDGE-61-SERVE-xxx)

| ID | Test Case | Attack Vector |
|----|-----------|---------------|
| EDGE-61-SERVE-001 | Very long app path | `velo serve aaaa...aaa:app` (4096 chars) |
| EDGE-61-SERVE-002 | Unicode in app name | `velo serve 中文模块:应用` |
| EDGE-61-SERVE-003 | Multiple colons | `velo serve path:to:module:app` |
| EDGE-61-SERVE-004 | Empty module | `velo serve :app` |
| EDGE-61-SERVE-005 | Empty app | `velo serve main:` |
| EDGE-61-SERVE-006 | Shell metacharacters | `velo serve "$(cmd):app"` |
| EDGE-61-SERVE-007 | Newlines in arg | `velo serve "main\nid":app` |
| EDGE-61-SERVE-008 | Null bytes | `velo serve "main\x00evil":app` |

### Framework Detection Edge Cases (EDGE-61-DETECT-xxx)

| ID | Test Case | Attack Vector |
|----|-----------|---------------|
| EDGE-61-DETECT-001 | Multiple apps in file | 3 FastAPI instances |
| EDGE-61-DETECT-002 | No app found | Empty `main.py` |
| EDGE-61-DETECT-003 | Nested `create_app()` | Factory in class method |
| EDGE-61-DETECT-004 | Conditional app creation | `if DEBUG: app = Flask()` |
| EDGE-61-DETECT-005 | Import side-effects | App created during import |

### File Watcher Edge Cases (EDGE-61-WATCH-xxx)

| ID | Test Case | Attack Vector |
|----|-----------|---------------|
| EDGE-61-WATCH-001 | Rapid file changes | 100 changes in 1 second |
| EDGE-61-WATCH-002 | Symlink modification | Change through symlink |
| EDGE-61-WATCH-003 | Delete watched directory | `rm -rf src/` while running |
| EDGE-61-WATCH-004 | Rename watched file | `mv main.py app.py` |
| EDGE-61-WATCH-005 | Permission denied | `chmod 000 main.py` |

### DX Excellence Tests (EDGE-61-DX-xxx) [GAP-09/10]

| ID | Test Case | Expected |
|----|-----------|----------|
| EDGE-61-DX-001 | Typo suggestions | `--relod` → "Did you mean `--reload`?" |
| EDGE-61-DX-002 | Source-pointing error | Error shows `main.py:42:10` |
| EDGE-61-A11Y-001 | ASCII-only terminal | `TERM=dumb` produces valid output |

---

## Agent B: Stability Guardian (保守派)

**Mission**: Ensure core functionality never regresses.

### Core Flow Tests (CORE-61-xxx)

| ID | Test Case | Expected | Critical |
|----|-----------|----------|----------|
| CORE-61-001 | Basic `velo serve` | Server listens on port | ⭐⭐⭐ |
| CORE-61-002 | Health endpoint | `/health` returns 200 OK | ⭐⭐⭐ |
| CORE-61-003 | Graceful shutdown | SIGTERM → clean exit | ⭐⭐⭐ |
| CORE-61-004 | FastAPI detection | Detects `app = FastAPI()` | ⭐⭐⭐ |
| CORE-61-005 | Flask detection | Detects `app = Flask(__name__)` | ⭐⭐ |
| CORE-61-006 | Django detection | Detects `application` WSGI | ⭐⭐ |
| CORE-61-007 | `create_app()` factory | Detects factory pattern | ⭐⭐ |
| CORE-61-008 | Hot reload trigger | File change → restart | ⭐⭐ |
| CORE-61-009 | `analyze --graph` output | ASCII graph rendered | ⭐⭐ |
| CORE-61-010 | Savings report | stat() count displayed | ⭐ |
| CORE-61-011 | ASGI Lifespan shutdown [GAP-01] | Waits for `shutdown` event | ⭐⭐⭐ |
| CORE-61-012 | Gunicorn config override [GAP-02] | CLI > gunicorn.conf.py | ⭐⭐ |
| CORE-61-013 | 30s drain timeout [GAP-08] | Grace period before kill | ⭐⭐ |

### Platform Parity Tests (PLAT-61-xxx) [GAP-05/06/07]

| ID | Test Case | Platform | Expected |
|----|-----------|----------|----------|
| PLAT-61-001 | FSEvents low-latency | macOS | <0.1s detection |
| PLAT-61-002 | inotify limit warning | Linux | Warns on low `max_user_watches` |
| PLAT-61-003 | Container polling fallback | Docker | inotify fails → polling mode |

### Regression Tests (REG-61-xxx)

| ID | Test Case | Baseline | Check |
|----|-----------|----------|-------|
| REG-61-001 | `velo run` unchanged | Phase 6.0 timing | No regression |
| REG-61-002 | `velo bundle` unchanged | All commands | Compatible |
| REG-61-003 | Cache hit performance | <10ms | Still fast |
| REG-61-004 | Exit codes preserved | 0/1/42/98 | Unchanged |

### Idempotency Tests (IDEM-61-xxx)

| ID | Test Case | Runs | Check |
|----|-----------|------|-------|
| IDEM-61-001 | Same request 100x | 100 | All identical response |
| IDEM-61-002 | Restart server 10x | 10 | No state drift |
| IDEM-61-003 | Worker cycle 50x | 50 | Memory stable |

---

## Agent C: Security Specialist (安全专家)

**Mission**: Find every security vulnerability.

### Command Injection (SEC-61-INJ-xxx)

| ID | Test Case | Payload | Expected |
|----|-----------|---------|----------|
| SEC-61-INJ-001 | Shell semicolon | `main:app; rm -rf /` | Rejected |
| SEC-61-INJ-002 | Command substitution | `main:$(id):app` | Rejected |
| SEC-61-INJ-003 | Pipe injection | `main:app \| cat /etc/passwd` | Rejected |
| SEC-61-INJ-004 | Backtick execution | `` main:`id`:app `` | Rejected |
| SEC-61-INJ-005 | Newline injection | `main:app\nid` | Rejected |
| SEC-61-INJ-006 | Ampersand chain | `main:app && whoami` | Rejected |

### Path Traversal (SEC-61-PATH-xxx)

| ID | Test Case | Payload | Expected |
|----|-----------|---------|----------|
| SEC-61-PATH-001 | Parent directory | `--detect-in ../../../etc` | Rejected |
| SEC-61-PATH-002 | Symlink escape | Link to `/tmp` | Rejected |
| SEC-61-PATH-003 | URL-encoded traversal | `%2e%2e%2f` | Rejected |
| SEC-61-PATH-004 | Null byte truncation | `path\x00../etc` | Rejected |

### PID File Security (SEC-61-PID-xxx)

| ID | Test Case | Attack | Expected |
|----|-----------|--------|----------|
| SEC-61-PID-001 | Existing file | Pre-existing `velo.pid` | Rejected |
| SEC-61-PID-002 | Symlink attack | Symlink to vital file | Rejected |
| SEC-61-PID-003 | Race condition | Concurrent writes | Only one wins (O_EXCL) |

### Environment Security (SEC-61-ENV-xxx)

| ID | Test Case | Check | Expected |
|----|-----------|-------|----------|
| SEC-61-ENV-001 | PYTHONPATH sanitized | No hijacking | Removed |
| SEC-61-ENV-002 | LD_PRELOAD sanitized | No injection | Removed |
| SEC-61-ENV-003 | Health endpoint leakage | No secrets | Minimal info |
| SEC-61-ENV-004 | LD_LIBRARY_PATH sanitized [GAP-04] | No library injection | Removed |

---

## QA Leader: Brutal Tests (终极测试)

**Mission**: Combine the worst from all agents. If the system survives these, it's production-ready.

### CHAOS Tests (Resource Exhaustion)

| ID | Test Case | Attack Vector |
|----|-----------|---------------|
| CHAOS-61-RES-001 | FD Exhaustion | Open 10,000 file descriptors |
| CHAOS-61-RES-002 | Memory Bomb | Allocate GBs of memory |
| CHAOS-61-RES-003 | Fork Bomb | Recursive fork attempts |
| CHAOS-61-TIME-001 | Rapid Start/Stop | 20x rapid process cycling |
| CHAOS-61-TIME-002 | Port Race | 5 processes same port |

### MEGA Tests (Combined Attacks)

| ID | Test Case | Method |
|----|-----------|--------|
| MEGA-61-001 | Everything at Once | All injection types simultaneous |
| MEGA-61-002 | Under Pressure | Attacks while system stressed |
| MEGA-61-003 | Zombie Hunt [GAP-03] | Panic → verify 0 orphan processes |

### Accessibility Tests (A11Y-61-xxx) [GAP-11/12]

| ID | Test Case | Check |
|----|-----------|-------|
| A11Y-61-001 | NO_COLOR support | No ANSI escapes when `NO_COLOR=1` |
| A11Y-61-002 | Text+icon multimodal | Success uses both icon AND text label |

---

## Final Test Count

| Agent | Tests |
|-------|-------|
| Agent A (Edge) | 21 |
| Agent B (Stability) | 23 |
| Agent C (Security) | 18 |
| **QA Leader (Brutal)** | **10** |
| **Total** | **72** |

### Execution Order (Gates)

1. **Gate 0**: CORE-61-* (must pass first)
2. **Gate 1**: SEC-61-* (security validation)
3. **Gate 2**: REG-61-* (no regression)
4. **Gate 3**: EDGE-61-* (edge cases)
5. **Gate 4**: IDEM-61-* (consistency)
6. **Gate 5**: Leader Brutal (final boss)

---

**✅ Leader Approved** (2026-01-04)

> Gap analysis completed. 12 missing tests added per [LEADER-GAP-ANALYSIS.md](./phase-6.1-reviews/LEADER-GAP-ANALYSIS.md).

---

*Document End*
