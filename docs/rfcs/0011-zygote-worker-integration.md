# RFC-0011: Zygote Worker Integration

> **Status**: DRAFT  
> **Author**: Architect (ID-LOCK-001)  
> **Created**: 2026-01-04  
> **Target Version**: v0.6.2+  
> **Branch**: `phase-6.1.1/zygote-worker-integration`  
> **Parent RFC**: [RFC-0010](./0010-phase-6.1-serve-analyze.md)

---

## Executive Summary

This RFC addresses a critical architectural gap: **uvicorn/gunicorn workers are NOT being forked from Zygote**, negating the pre-warming benefit for multi-worker deployments.

**Current State**:
```
Velo → Zygote → uvicorn parent → uvicorn spawns its own workers
                                 (multiprocessing.spawn, NOT Zygote fork)
```

**Target State**:
```
Velo → Zygote pre-warms → Velo manages worker pool (via Zygote fork)
                          → Each worker inherits pre-warmed state
```

---

## 1. Problem Statement

### 1.1 Verification Evidence

```
Process Tree (phase-6.1/serve-analyze):
29705  velo-zygote (standalone, NOT utilized by workers)
29706  uvicorn parent
29708  uvicorn worker (multiprocessing.spawn)  ← NOT from Zygote
29709  uvicorn worker (multiprocessing.spawn)  ← NOT from Zygote
```

### 1.2 Impact

| Metric | Current | With Zygote Workers |
|--------|---------|---------------------|
| Worker cold start | ~200ms | ~10ms |
| Memory per worker | Full copy | COW shared |
| Module re-import | Yes (per worker) | No (inherited) |

---

## 2. Proposed Architecture

### 2.1 Worker Lifecycle

```
┌─────────────────────────────────────────────────────────────┐
│                    Velo Supervisor                           │
├─────────────────────────────────────────────────────────────┤
│  1. Start Zygote daemon (pre-warm modules)                  │
│  2. Receive HTTP request or --workers N                      │
│  3. Fork worker from Zygote (not uvicorn's spawn)           │
│  4. Worker runs ASGI app directly                            │
│  5. Velo manages worker pool (restart, scale, health)       │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Worker ownership** | Velo (not uvicorn) | Must fork from Zygote |
| **ASGI protocol** | Direct (no uvicorn) | Avoid double-spawn |
| **HTTP stack** | `hyper` or `tiny_http` | Rust-native, Zygote-compatible |
| **Load balancing** | Round-robin to workers | Simple, predictable |

---

## 3. Implementation Options

### Option A: Replace uvicorn entirely (High effort)

Velo implements HTTP server + ASGI protocol, workers fork from Zygote.

**Pros**: Full control, maximum performance  
**Cons**: Large scope, needs ASGI expertise

### Option B: Zygote-aware uvicorn fork (Medium effort)

Modify uvicorn to use Zygote for worker spawning via custom reloader.

**Pros**: Leverage existing uvicorn code  
**Cons**: uvicorn internals are complex

### Option C: Hybrid approach (Recommended)

Velo manages worker pool, each worker runs uvicorn in single-worker mode.

```
Velo Supervisor
├── Fork from Zygote → Worker 1 (uvicorn --workers 1)
├── Fork from Zygote → Worker 2 (uvicorn --workers 1)
└── Fork from Zygote → Worker 3 (uvicorn --workers 1)
```

**Pros**: Simpler implementation, uvicorn handles ASGI  
**Cons**: Slightly more memory (per-worker uvicorn overhead)

---

## 4. Acceptance Criteria

- [ ] Workers forked from Zygote (verified via process tree)
- [ ] Worker cold start <20ms (vs current ~200ms)
- [ ] Memory sharing via COW (verified via /proc/smaps)
- [ ] All RFC-0010 features still work (--reload, --health-bind, etc.)
- [ ] No regression in single-worker mode

---

## 5. Timeline

| Phase | Scope | Estimate |
|-------|-------|----------|
| Design | Architecture validation | 1 week |
| Core | Worker pool + Zygote fork | 2 weeks |
| Integration | uvicorn single-worker mode | 1 week |
| Testing | Performance + stability | 1 week |
| **Total** | | **5 weeks** |

---

## 6. Risks

| Risk | Mitigation |
|------|------------|
| uvicorn internal changes | Pin version, test each upgrade |
| Zygote state corruption | Worker isolation, health checks |
| Signal handling complexity | RAII + ShutdownCoordinator (from RFC-0010) |

---

## 7. Open Questions

1. **gunicorn compatibility**: Apply same pattern?
2. **--workers auto-scaling**: Use CPU count or memory-based?
3. **Worker restart strategy**: Rolling vs. all-at-once?

---

## 8. References

- [RFC-0010 Phase 6.1 Serve, Analyze & Polish](./0010-phase-6.1-serve-analyze.md)
- [RFC-0002 Phase 3 Zygote Mode](./0002-phase-3-zygote.md)
- [Uvicorn Worker Internals](https://www.uvicorn.org/)

---

**Status**: DRAFT - Awaiting Architect review and CTO approval.
