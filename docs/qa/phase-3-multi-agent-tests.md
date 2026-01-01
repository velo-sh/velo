# Phase 3 Zygote - Multi-Agent QA Test Design

> **Method**: 4 independent QA perspectives for comprehensive coverage

---

## Agent A: Edge Case Hunter (Aggressive)

**Mission**: Find every corner case that breaks the system.

### Lifecycle Edge Cases (EDGE-ZYG-xxx)

| ID | Test Case | Attack Vector |
|----|-----------|---------------|
| EDGE-ZYG-001 | Start during shutdown | `velo zygote start` while stop is running |
| EDGE-ZYG-002 | Stop during worker spawn | SIGTERM while fork() in progress |
| EDGE-ZYG-003 | Status during crash | Query status as Zygote crashes |
| EDGE-ZYG-004 | Zero workers limit | `max_workers = 0` |
| EDGE-ZYG-005 | 64-bit PID overflow | Simulate very large PID |

### Fork Edge Cases (EDGE-FORK-xxx)

| ID | Test Case | Attack Vector |
|----|-----------|---------------|
| EDGE-FORK-001 | Fork in signal handler | Signal arrives during fork |
| EDGE-FORK-002 | Thread + fork mix | Multi-threaded script with fork |
| EDGE-FORK-003 | setuid after fork | Worker tries to change UID |
| EDGE-FORK-004 | chroot escape | Worker tries to chroot |
| EDGE-FORK-005 | OOM during fork | Memory exhausted mid-fork |

### IPC Edge Cases (EDGE-IPC-xxx)

| ID | Test Case | Attack Vector |
|----|-----------|---------------|
| EDGE-IPC-001 | Socket at EOF | Send, close immediately |
| EDGE-IPC-002 | Half-open connection | Connect, never send |
| EDGE-IPC-003 | Unicode socket path | Path with emoji |
| EDGE-IPC-004 | Very long socket path | Path > PATH_MAX |
| EDGE-IPC-005 | Symlink to socket | Socket path is symlink |

---

## Agent B: Stability Guardian (Conservative)

**Mission**: Ensure core functionality never regresses.

### Core Flow Tests (CORE-xxx)

| ID | Test Case | Expected | Critical |
|----|-----------|----------|----------|
| CORE-001 | Happy path: start/run/stop | All succeed | ⭐⭐⭐ |
| CORE-002 | Simple script execution | Correct output | ⭐⭐⭐ |
| CORE-003 | Script with arguments | Args passed correctly | ⭐⭐⭐ |
| CORE-004 | Script exit code | Propagated correctly | ⭐⭐⭐ |
| CORE-005 | stdout/stderr separation | Streams isolated | ⭐⭐ |

### Regression Tests (REG-xxx)

| ID | Test Case | Baseline | Check |
|----|-----------|----------|-------|
| REG-001 | velo run (no zygote) | Phase 1.5 timing | No regression |
| REG-002 | cache hit still works | 12ms | Still < 20ms |
| REG-003 | velo info still works | All sections | All present |
| REG-004 | --profile still works | Output format | Unchanged |
| REG-005 | ABI detection intact | Warning works | Still warns |

### Idempotency Tests (IDEM-xxx)

| ID | Test Case | Runs | Check |
|----|-----------|------|-------|
| IDEM-001 | Same script 100x | 100 | All identical output |
| IDEM-002 | Start same script 10x parallel | 10 | No corruption |
| IDEM-003 | Restart Zygote 10x | 10 | No state drift |

---

## Agent C: Security Specialist

**Mission**: Find every security vulnerability.

### Permission Tests (SEC-PERM-xxx)

| ID | Test Case | Risk | Check |
|----|-----------|------|-------|
| SEC-PERM-001 | Socket world-readable | Info leak | Socket mode = 0600 |
| SEC-PERM-002 | Worker inherits Zygote env | Secret leak | Env isolated |
| SEC-PERM-003 | PID file permissions | Injection | PID file mode = 0600 |
| SEC-PERM-004 | Config file injection | Code exec | Config path validated |
| SEC-PERM-005 | Socket path traversal | Hijack | Path normalized |

### Privilege Tests (SEC-PRIV-xxx)

| ID | Test Case | Risk | Check |
|----|-----------|------|-------|
| SEC-PRIV-001 | Zygote runs as root | Danger | Should refuse or warn |
| SEC-PRIV-002 | Worker privilege escalation | Rootkit | No SUID inheritance |
| SEC-PRIV-003 | Capability leak | Container escape | No caps passed |
| SEC-PRIV-004 | /proc access from worker | Info leak | Limited /proc access |

### Data Isolation Tests (SEC-ISO-xxx)

| ID | Test Case | Risk | Check |
|----|-----------|------|-------|
| SEC-ISO-001 | Worker reads other worker's memory | Data leak | Memory isolated |
| SEC-ISO-002 | Worker accesses Zygote FDs | FD leak | FDs closed after fork |
| SEC-ISO-003 | Worker modifies shared preload | Corrupt | Preload read-only |
| SEC-ISO-004 | Env var leakage between workers | Secret leak | Clean env each time |
| SEC-ISO-005 | Temp file collision | Race | Unique temp paths |

### Input Validation (SEC-INP-xxx)

| ID | Test Case | Risk | Check |
|----|-----------|------|-------|
| SEC-INP-001 | Script path injection | Code exec | Path sanitized |
| SEC-INP-002 | Argument injection | Shell escape | Args quoted |
| SEC-INP-003 | Module name injection | Import hijack | Module validated |
| SEC-INP-004 | Config value injection | RCE | Values escaped |
| SEC-INP-005 | IPC command injection | Arbitrary cmd | Protocol strict |

---

## Leader Summary: Consolidated Matrix

### Priority Classification

| Priority | Tests | Coverage |
|----------|-------|----------|
| P0 (Blocking) | CORE-001 to 005, REG-001 to 002 | Core stability |
| P1 (Critical) | SEC-PERM-*, SEC-PRIV-* | Security |
| P2 (High) | EDGE-ZYG-*, EDGE-FORK-* | Edge cases |
| P3 (Medium) | SEC-ISO-*, IDEM-* | Isolation, consistency |

### Total Test Count

| Agent | Tests | Focus |
|-------|-------|-------|
| Agent A (Edge) | 15 | Break it |
| Agent B (Regression) | 13 | Keep it stable |
| Agent C (Security) | 19 | Secure it |
| **Total** | **47** | Full coverage |

### Execution Order

1. **Gate 0**: CORE-* (must pass first)
2. **Gate 1**: REG-* (no regression)
3. **Gate 2**: SEC-* (security validation)
4. **Gate 3**: EDGE-* (edge cases)
5. **Gate 4**: IDEM-* (consistency)

---

**Approved by Leader** ✅

---

## Leader Consolidation: Cross-Review Matrix

### Cross-Review Completed

| Original Agent | Reviewed By | Tests Added | Focus |
|----------------|-------------|-------------|-------|
| Agent C (Security) | A + B | 6 | Edge cases + stability in security |
| Agent B (Stability) | A + C | 6 | Edge cases + security in stability |
| Agent A (Edge) | B + C | 5 | Stability + security after edge cases |

### Final Test Count

| File | Original | Cross-Review | Total |
|------|----------|--------------|-------|
| `test_phase3_agent_a_edge.py` | 8 | +5 | **13** |
| `test_phase3_agent_b_stability.py` | 11 | +6 | **17** |
| `test_phase3_agent_c_security.py` | 12 | +6 | **18** |
| **Multi-Agent Subtotal** | 31 | +17 | **48** |

### Cross-Review Patterns

1. **Stability → Edge Cases**: Recovery after edge case handling
2. **Security → Edge Cases**: No permission/info leak after edge case
3. **Edge Cases → Stability**: Unusual inputs don't crash core flow
4. **Security → Stability**: Error messages don't leak info
5. **Edge Cases → Security**: Race conditions in security checks
6. **Stability → Security**: Consistent security behavior under load

---

**Document End**

