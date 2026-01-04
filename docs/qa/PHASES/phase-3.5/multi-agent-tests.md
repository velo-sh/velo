# Phase 3.5 Ecosystem Integration - Multi-Agent QA Test Design

> **Method**: 4 independent QA perspectives for comprehensive coverage  
> **Related Matrix**: [phase-3.5-test-matrix.md](./phase-3.5-test-matrix.md)

---

## Agent A: Edge Case Hunter (Aggressive)

**Mission**: Find every corner case that breaks the system.

### Serve CLI Edge Cases (EDGE-SERVE-xxx)

| ID | Test Case | Attack Vector |
|----|-----------|---------------|
| EDGE-SERVE-001 | Very long app path | `velo serve aaaa...aaa:app` (4096 chars) |
| EDGE-SERVE-002 | Unicode in app name | `velo serve 中文:应用` |
| EDGE-SERVE-003 | Colon in module path | `velo serve path:to:module:app` |
| EDGE-SERVE-004 | Empty module | `velo serve :app` |
| EDGE-SERVE-005 | Empty app | `velo serve main:` |
| EDGE-SERVE-006 | Special chars | `velo serve "$(cmd):app"` |

### WorkerPool Edge Cases (EDGE-POOL-xxx)

| ID | Test Case | Attack Vector |
|----|-----------|---------------|
| EDGE-POOL-001 | Start during shutdown | `velo serve` while SIGTERM in progress |
| EDGE-POOL-002 | Rapid worker kills | Kill workers faster than restart |
| EDGE-POOL-003 | OOM in worker | Memory exhaustion mid-request |
| EDGE-POOL-004 | Fork bomb attempt | Worker tries to fork recursively |
| EDGE-POOL-005 | CPU starvation | 100% CPU in one worker |
| EDGE-POOL-006 | Infinite loop in import | App hangs on import |

### Signal Edge Cases (EDGE-SIG-xxx)

| ID | Test Case | Attack Vector |
|----|-----------|---------------|
| EDGE-SIG-001 | Signal during fork | SIGTERM arrives mid-fork |
| EDGE-SIG-002 | Nested signals | SIGTERM then SIGINT |
| EDGE-SIG-003 | Signal storm | 100 SIGCHLD in 1 second |
| EDGE-SIG-004 | Invalid signal | Non-standard signal number |
| EDGE-SIG-005 | Blocked signals | Process ignores SIGTERM |

---

## Agent B: Stability Guardian (Conservative)

**Mission**: Ensure core functionality never regresses.

### Core Flow Tests (CORE-SERVE-xxx)

| ID | Test Case | Expected | Critical |
|----|-----------|----------|----------|
| CORE-SERVE-001 | Basic startup | Server listens on port | ⭐⭐⭐ |
| CORE-SERVE-002 | Health endpoint | Returns 200 OK | ⭐⭐⭐ |
| CORE-SERVE-003 | Graceful shutdown | No orphan processes | ⭐⭐⭐ |
| CORE-SERVE-004 | Worker spawn | Correct worker count | ⭐⭐ |
| CORE-SERVE-005 | Log output | Startup info visible | ⭐⭐ |

### Regression Tests (REG-SERVE-xxx)

| ID | Test Case | Baseline | Check |
|----|-----------|----------|-------|
| REG-SERVE-001 | `velo run` still works | Phase 3 timing | No regression |
| REG-SERVE-002 | `velo zygote` still works | All commands | Compatible |
| REG-SERVE-003 | Cache hit performance | 4.5ms | Still < 10ms |
| REG-SERVE-004 | `--profile` unchanged | Output format | Unchanged |
| REG-SERVE-005 | Exit codes preserved | 0/1/42 | Unchanged |

### Idempotency Tests (IDEM-SERVE-xxx)

| ID | Test Case | Runs | Check |
|----|-----------|------|-------|
| IDEM-SERVE-001 | Same request 100x | 100 | All identical response |
| IDEM-SERVE-002 | Restart server 10x | 10 | No state drift |
| IDEM-SERVE-003 | Worker cycle 50x | 50 | Memory stable |

---

## Agent C: Security Specialist

**Mission**: Find every security vulnerability.

### Network Security (SEC-NET-xxx)

| ID | Test Case | Risk | Check |
|----|-----------|------|-------|
| SEC-NET-001 | Bind to 0.0.0.0 | Exposure | Warning shown |
| SEC-NET-002 | Port < 1024 | Privilege | Sudo hint |
| SEC-NET-003 | Socket hijacking | MITM | Socket permissions |
| SEC-NET-004 | Request smuggling | Bypass | HTTP parsing strict |
| SEC-NET-005 | Header injection | XSS | Headers sanitized |

### Process Security (SEC-PROC-xxx)

| ID | Test Case | Risk | Check |
|----|-----------|------|-------|
| SEC-PROC-001 | Worker runs as root | Danger | Refuse or warn |
| SEC-PROC-002 | Env var leakage | Secret leak | Clean env |
| SEC-PROC-003 | FD inheritance | FD leak | FDs closed |
| SEC-PROC-004 | /proc access | Info leak | Limited access |
| SEC-PROC-005 | Core dump | Secret dump | Disabled by default |

### Input Validation (SEC-INP-xxx)

| ID | Test Case | Risk | Check |
|----|-----------|------|-------|
| SEC-INP-001 | Path traversal in app | Code exec | `../` blocked |
| SEC-INP-002 | Symlink to outside | Escape | Resolved safely |
| SEC-INP-003 | Module injection | Import hijack | Validated |
| SEC-INP-004 | Port overflow | Bind error | Range checked |
| SEC-INP-005 | Worker count overflow | DoS | Capped |

### Configuration Security (SEC-CFG-xxx)

| ID | Test Case | Risk | Check |
|----|-----------|------|-------|
| SEC-CFG-001 | Config file permissions | Tamper | 0600 expected |
| SEC-CFG-002 | Env override attack | Hijack | Explicit only |
| SEC-CFG-003 | Debug mode in prod | Info leak | Warn if DEBUG |
| SEC-CFG-004 | Auto-reload in prod | Race | Warn if reload |

---

## Leader Summary: Consolidated Matrix

### Priority Classification

| Priority | Tests | Coverage |
|----------|-------|----------|
| P0 (Blocking) | CORE-SERVE-*, REG-SERVE-001/002 | Core stability |
| P1 (Critical) | SEC-NET-*, SEC-PROC-* | Security |
| P2 (High) | EDGE-SERVE-*, EDGE-POOL-* | Edge cases |
| P3 (Medium) | SEC-INP-*, IDEM-* | Isolation |

### Cross-Review Completed ✅

| Original Agent | Reviewed By | Tests Added | Focus |
|----------------|-------------|-------------|-------|
| Agent C (Security) | A + B | 6 | XR-SEC-EDGE-*, XR-SEC-STAB-* |
| Agent A (Edge) | B + C | 6 | XR-EDGE-STAB-*, XR-EDGE-SEC-* |
| Agent B (Stability) | A + C | 6 | XR-STAB-EDGE-*, XR-STAB-SEC-* |

### Total Test Count

| Agent | Original | Cross-Review | Total |
|-------|----------|--------------|-------|
| Agent A (Edge) | 17 | +6 | **23** |
| Agent B (Stability) | 13 | +6 | **19** |
| Agent C (Security) | 18 | +6 | **24** |
---

## QA Leader: The BRUTAL TESTS (Try to Break It)

**Mission**: Combine the worst from all agents and go further. If the system survives these, it's production-ready.

### CHAOS Tests (Resource Exhaustion)

| ID | Test Case | Attack Vector |
|----|-----------|---------------|
| CHAOS-RES-001 | FD Exhaustion | Open 10,000 file descriptors |
| CHAOS-RES-002 | Memory Bomb | Allocate GBs of memory |
| CHAOS-RES-003 | Fork Bomb | Recursive fork attempts |
| CHAOS-RES-004 | Thread Bomb | Create 1000+ threads |
| CHAOS-TIME-001 | Rapid Start/Stop | 20x rapid process cycling |
| CHAOS-TIME-002 | Port Race | 5 processes same port |

### INJECT Tests (All Injection Types)

| ID | Test Case | Payloads |
|----|-----------|----------|
| INJECT-001 | Shell Metacharacters | \`;id\`, \`$(whoami)\`, \`\|cat\` |
| INJECT-002 | Python Code | \`__import__\`, \`eval\`, \`exec\` |
| INJECT-003 | SQL Style | \`'; DROP TABLE\`, \`1' OR '1'='1\` |
| INJECT-004 | Path Traversal | All variants inc. URL-encoded |

### CRASH Tests (Crash Inputs)

| ID | Test Case | Input |
|----|-----------|-------|
| CRASH-001 | Null Bytes | \`\x00\` everywhere |
| CRASH-002 | Format Strings | \`%n%n%n\`, \`%99999$s\` |
| CRASH-003 | Unicode Bombs | BOM, RTL override, surrogates |
| CRASH-004 | Long Inputs | 1KB to 1MB strings |

### HANG Tests (Deadlock Attempts)

| ID | Test Case | Attack |
|----|-----------|--------|
| HANG-001 | Symlink Loop | a→b→a infinite redirect |
| HANG-002 | ReDoS | Catastrophic backtracking input |
| HANG-003 | Deep Path | 100-level nested directory |

### LEAK Tests (Information Disclosure)

| ID | Test Case | Check |
|----|-----------|-------|
| LEAK-001 | Error Messages | No internal paths |
| LEAK-002 | Env Exposure | Secrets not in output |
| LEAK-003 | Stack Traces | No Rust backtraces |

### MEGA Tests (Combined Attacks)

| ID | Test Case | Method |
|----|-----------|--------|
| MEGA-001 | Everything at Once | 6 attack types simultaneous |
| MEGA-002 | Under Pressure | Attacks while system stressed |

---

## Final Test Count

| Agent | Tests |
|-------|-------|
| Agent A (Edge) | 23 |
| Agent B (Stability) | 19 |
| Agent C (Security) | 24 |
| **QA Leader (Brutal)** | **25** |
| **Total** | **91** |

### Execution Order

1. **Gate 0**: CORE-SERVE-* (must pass first)
2. **Gate 1**: REG-SERVE-* (no regression)
3. **Gate 2**: SEC-* (security validation)
4. **Gate 3**: EDGE-* (edge cases)
5. **Gate 4**: IDEM-* (consistency)
6. **Gate 5**: Leader Brutal (final boss)

---

**Approved by Leader** ✅

---

**Document End**
