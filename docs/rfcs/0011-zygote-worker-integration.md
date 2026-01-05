# RFC-0011: Zygote Worker Integration

> **Status**: IMPLEMENTED  
> **Author**: Architect (ID-LOCK-001)  
> **Created**: 2026-01-04  
> **Target Version**: v0.6.2+  
> **Branch**: `phase-6.1.1/zygote-worker-integration`  
> **Parent RFC**: [RFC-0010](./0010-phase-6.1-serve-analyze.md)

---

## Executive Summary

This RFC addresses a critical architectural gap: **uvicorn/gunicorn workers are NOT being forked from Zygote**, negating the pre-warming benefit for multi-worker deployments.

**Current State**:
```text
Velo → Zygote → uvicorn parent → uvicorn spawns its own workers
                                 (multiprocessing.spawn, NOT Zygote fork)
```

**Target State**:
```text
Velo → Zygote pre-warms → Velo manages worker pool (via Zygote fork)
                          → Each worker inherits pre-warmed state
```

---

## 1. Problem Statement

### 1.1 Verification Evidence

```text
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

```text
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

```text
Velo Supervisor
├── Fork from Zygote → Worker 1 (uvicorn --workers 1)
├── Fork from Zygote → Worker 2 (uvicorn --workers 1)
└── Fork from Zygote → Worker 3 (uvicorn --workers 1)
```

**Pros**: Simpler implementation, uvicorn handles ASGI  
**Cons**: Slightly more memory (per-worker uvicorn overhead)

---

## 4. Acceptance Criteria

- [x] Workers forked from Zygote (verified via process tree)
- [x] Worker cold start <20ms (vs current ~200ms)
- [x] Memory sharing via COW (verified via /proc/smaps)
- [x] All RFC-0010 features still work (--reload, --health-bind, etc.)
- [x] No regression in single-worker mode

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

**RFC Record**: Implemented on 2026-01-04

---

## Appendix A: Architectural Review (2026-01-05)

> **Reviewer**: Architect (ID-LOCK-001)

### A.1 Potential Optimizations

| Area | Current | Suggested Optimization |
|------|---------|------------------------|
| **Per-worker overhead** | Each worker runs full uvicorn (event loop + HTTP parsing) | Consider Rust HTTP frontend (hyper/axum) + Python ASGI backend |
| **Port management** | N TCP ports for N workers | Use Unix Domain Sockets to simplify |
| **Inter-worker state** | No shared state mechanism | Add shared memory metrics (Prometheus-style) |

### A.2 Answers to Open Questions (Section 7)

| Question | Decision | Rationale |
|----------|----------|-----------|
| gunicorn compatibility | Low priority | Same pattern applies, but uvicorn is primary target |
| --workers auto-scaling | Default to CPU count | Memory-based scaling as optional advanced feature |
| Worker restart strategy | **Rolling** | Zero-downtime restarts, one worker at a time |

### A.3 Missing Architectural Components

Future phases should address:

1. **Worker Health Check Details**: Specific endpoints, intervals, failure thresholds
2. **Graceful Shutdown Coordination**: Integration with RFC-0010 ShutdownCoordinator
3. **Worker Crash Recovery**: Max restarts, backoff strategy, circuit breaker
4. **Observability**: Worker metrics, request latency histograms, memory usage

### A.4 Future Architecture (Option A Evolution Path)

If performance requirements increase, consider evolving to:

```text
Rust HTTP Server (hyper/axum)
├── Accept all HTTP connections
├── Load balance across workers (round-robin / least-connections)
└── Workers 1-N (ASGI only, no HTTP parsing)
    ├── Forked from Zygote
    └── Communicate via Unix socket / shared memory
```

This eliminates per-worker HTTP overhead while maintaining Zygote benefits.

---

### A.5 Architecture Issue: TCP vs IPC Inconsistency

> **Severity**: Medium  
> **Status**: OPEN  
> **Found**: 2026-01-05

#### Problem

Current implementation uses **TCP (AF_INET)** for worker communication, but Zygote itself uses **Unix Domain Socket (IPC)**:

| Component | Current | Expected |
|-----------|---------|----------|
| Zygote ↔ Rust | Unix Domain Socket (`AF_UNIX`) | ✅ Correct |
| Worker ↔ Client | TCP (`AF_INET`) + `SO_REUSEPORT` | ❌ Inconsistent |

#### Evidence

`velo_zygote/worker_runner.py` lines 41-44:
```python
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCP!
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
sock.bind((host, port))  # Binds to TCP port
```

#### Impact

| Aspect | TCP (Current) | Unix Socket (Recommended) |
|--------|---------------|---------------------------|
| Port management | N ports for N workers | File path, no port conflicts |
| Security | Port exposed to network | File permissions only |
| Performance | TCP stack overhead | Lower latency |
| Architecture | Inconsistent with Zygote IPC | Consistent |

#### Recommendation

1. **Short-term**: Document as known limitation
2. **Long-term**: Migrate to Unix Domain Socket with Rust proxy

#### Dependencies

- Requires Rust HTTP frontend (A.4 evolution path)
- Or: Use `SO_REUSEPORT` with localhost-only binding (mitigation)
