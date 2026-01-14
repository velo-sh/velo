# RFC-0028: Zygote Test Executor

**Status**: DRAFT
**Author**: Architect
**Date**: 2026-01-14
**Phase**: Phase 8.x

## Related Documents
- [RFC-0019: Native Sovereignty](./0019-native-sovereignty.md) (Zygote Architecture)
- [RFC-0018: Integrated Custody](./0018-integrated-custody.md) (Environment Management)

---

## 1. Summary

Zygote Test Executor enables **sub-millisecond test process spawning** by leveraging Zygote's COW (Copy-on-Write) architecture. Instead of loading Python + dependencies for each test, we fork from a pre-warmed Zygote, achieving 100-1000x speedup for large test suites.

| Metric | Traditional pytest | Zygote Test Executor |
|:---|:---|:---|
| **Per-test startup** | 500ms - 2s | **~1ms** |
| **1000 tests** | 30+ min | **~30 sec** |
| **Memory per test** | Full copy | **COW delta (~1MB)** |

---

## 2. Motivation

Current test execution pain points:
- **Import overhead**: Each pytest process imports heavy dependencies (torch, pandas)
- **No sharing**: Each process loads identical libraries independently
- **Slow iteration**: Large test suites block developer feedback loops

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      ZYGOTE TEST EXECUTOR                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Phase 1: Pre-warm (Once)                                                   │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Python + pytest + fixtures + your_app imported                        │  │
│  │  Zygote FROZEN, waiting for fork commands                              │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│                             fork() × N                                      │
│                                    ▼                                        │
│  Phase 2: Parallel Execution (Per-test)                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │   Test 1    │  │   Test 2    │  │   Test 3    │  │   Test N    │        │
│  │   (COW)     │  │   (COW)     │  │   (COW)     │  │   (COW)     │        │
│  │   ~1ms      │  │   ~1ms      │  │   ~1ms      │  │   ~1ms      │        │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘        │
│         │                │                │                │               │
│         ▼                ▼                ▼                ▼               │
│  Phase 3: Immediate Reclaim                                                 │
│      exit(0)         exit(1)         exit(0)         exit(0)               │
│       ↓                ↓                ↓                ↓                 │
│    [RECLAIMED]     [RECLAIMED]     [RECLAIMED]     [RECLAIMED]             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Memory Model

| Component | Memory | Sharing |
|:---|:---|:---|
| **Zygote base** | ~500MB (Python + libs) | COW shared across all tests |
| **Per-test delta** | ~1MB (test state) | Private, reclaimed on exit |
| **1000 tests peak** | ~500MB + 8 × 1MB | (8 = parallel workers) |

### 3.2 Execution Flow

```
velo test -- pytest tests/ -n auto

    ↓

1. Collect: pytest --collect-only → [test_a, test_b, ...]
2. Pre-warm: Zygote imports pytest, fixtures, app
3. Fork Pool: Create N worker slots (N = CPU cores)
4. Dispatch: Each worker receives test items via IPC
5. Execute: Worker runs test, captures result
6. Reclaim: Worker exits, memory freed instantly
7. Aggregate: Collect results, report
```

---

## 4. Interface

```bash
# Basic usage
velo test -- pytest tests/

# Parallel workers
velo test --workers 8 -- pytest tests/

# With Zygote pre-warm modules
velo test --preload "torch,pandas,myapp" -- pytest tests/
```

---

## 5. Performance Targets

| Scenario | Target |
|:---|:---|
| **Fork latency** | < 2ms |
| **Test isolation** | Full process isolation |
| **Memory overhead** | < 2MB per concurrent test |
| **Speedup vs pytest** | 10-100x for import-heavy suites |

---

## 6. Quality Gates

| Gate | Requirement |
|:---|:---|
| **Gate A** | Each test runs in isolated process (no state leak) |
| **Gate B** | Test failures propagate correct exit codes |
| **Gate C** | stdout/stderr captured per-test |
| **Gate D** | Compatible with pytest fixtures and markers |

---

## 7. Alternatives Considered

| Alternative | Rejected Because |
|:---|:---|
| **pytest-xdist** | Still loads Python per worker, no COW |
| **pytest --forked** | No pre-warming, fork per test |
| **In-process parallel** | GIL contention, no isolation |

---

**Last Updated**: 2026-01-14
