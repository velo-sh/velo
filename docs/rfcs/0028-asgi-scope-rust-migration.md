# RFC-0028: ASGI Scope Rust Migration

**Status**: DRAFT
**Author**: Architect
**Date**: 2026-01-14
**Phase**: 8.x (Performance Optimization)

## Related Documents

- [RFC-0019: Native Sovereignty](./0019-native-sovereignty.md)
- [RFC-0025: WebSocket Support Architecture](./0025-websocket-architecture.md)
- [Grand Council Review](../../.gemini/antigravity/brain/1dbcffb0-3d27-473e-9568-25c3bf767836/council_review_asgi_scope.md)

---

## 1. Summary

This RFC proposes migrating ASGI `scope` dictionary construction from Python (`velo_zygote/rsgi.py`) to Rust (`vendor/granian/src/asgi/utils.rs`) to reduce per-request latency and fix a known compliance bug.

> [!IMPORTANT]
> **Design Principle**: Granian Core already provides optimized ASGI scope building with `pyo3::intern!` pre-interned keys. We should **integrate, not reinvent**.

---

## 2. Background

### 2.1 Current Implementation (Python)

**Location**: `velo_zygote/rsgi.py:227-240`

```python
scope = {
    "type": "http",
    "asgi": {"version": "3.0", "spec_version": "2.3"},
    "http_version": "1.1",
    "method": method,
    "scheme": "http",
    "path": clean_path,
    "raw_path": clean_path.encode("ascii", errors="replace"),
    "query_string": query_string.encode("ascii", errors="replace"),
    "headers": asgi_headers,
    "client": tuple(client) if client else None,
    "server": None,  # ⚠️ BUG: Should be (host, port) tuple
    "rsgi.id": req_id,
}
```

**Issues**:
1. **Performance**: ~2-10μs per request (multiple allocations)
2. **Bug**: `server` field is always `None`, violating ASGI 3.0 spec
3. **Redundancy**: Granian already implements this correctly

### 2.2 Granian Implementation (Rust)

**Location**: `vendor/granian/src/asgi/utils.rs:116-126`

```rust
#[inline]
pub(super) fn build_scope_http(
    py: Python,
    req: request::Parts,
    server: SockAddr,
    client: SockAddr,
    scheme: HTTPProto,
) -> PyResult<Bound<PyDict>> {
    build_scope_common!(py, scope, req, server, client, scheme.as_str(), "http");
    scope_set!(py, scope, "method", req.method.as_str());
    Ok(scope)
}
```

**Advantages**:
1. **Performance**: ~0.5-2μs per request (single allocation, pre-interned keys)
2. **Correct**: Populates `server` field properly
3. **Maintained**: Part of upstream Granian project

---

## 3. Motivation

### 3.1 Performance

| Metric | Python Impl | Rust Impl | Improvement |
|:---|:---|:---|:---|
| **p50 Latency** | ~5μs | ~1μs | **80% reduction** |
| **p99 Latency** | ~10μs | ~2μs | **80% reduction** |
| **Allocations** | ~10-15/req | ~1/req | **93% reduction** |
| **CPU (100K RPS)** | +500-800ms/sec | Baseline | **Significant** |

### 3.2 Bug Fix

Current implementation has `scope["server"] = None`. This causes issues with:
- Starlette's `Request.url` property (uses `server` to build URL)
- Any middleware that needs server address information

### 3.3 Code Reduction

Remove ~30 lines of scope-building code from `rsgi.py`, reducing maintenance burden.

---

## 4. Architecture

### 4.1 Integration Point

```
┌─────────────────────────────────────────────────────────────┐
│                    Velo RSGI Host (Rust)                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │        granian::asgi::utils::build_scope_http()     │   │
│  │  ┌─────────────────────────────────────────────┐   │   │
│  │  │  pyo3::intern! pre-interned keys            │   │   │
│  │  │  "type", "method", "path", "headers", etc.  │   │   │
│  │  └─────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           ▼ scope: PyDict                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │        velo_zygote/rsgi.py (Python Worker)          │   │
│  │        await app(scope, receive, send)              │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Message Protocol Change

Extend `ReqStart` message to include pre-built scope:

```
# Current (TYPE_REQ_START = 0x01)
[0x01, req_id, method, path, headers, has_body, client]

# New (TYPE_REQ_START_V2 = 0x05)
[0x05, req_id, scope_dict, has_body]
```

Where `scope_dict` is a full ASGI scope dictionary built by Rust.

---

## 5. Implementation Plan

### Phase 8.1: Rust-side Scope Building

| Step | File | Change |
|:---|:---|:---|
| 1 | `src/rsgi/protocol.rs` | Add `TYPE_REQ_START_V2 = 0x05` |
| 2 | `src/rsgi/host.rs` | Call `granian::asgi::utils::build_scope_http()` |
| 3 | `src/rsgi/host.rs` | Serialize scope dict via MessagePack |

### Phase 8.2: Python-side Adaptation

| Step | File | Change |
|:---|:---|:---|
| 1 | `velo_zygote/rsgi.py` | Handle `TYPE_REQ_START_V2` |
| 2 | `velo_zygote/rsgi.py` | Use scope dict directly (no local construction) |
| 3 | `velo_zygote/rsgi.py` | Keep fallback for `TYPE_REQ_START` (backward compat) |

### Phase 8.3: Configuration & Rollout

```toml
# pyproject.toml
[tool.velo.performance]
rust_scope = true  # Default: false (Phase 8.x), true (Phase 9.x)
```

---

## 6. Fallback Mechanism

For debugging and compatibility, keep Python scope building as fallback:

```python
# velo_zygote/rsgi.py
if msg[0] == TYPE_REQ_START_V2:
    # Rust-built scope (optimized path)
    _, req_id, scope, has_body = msg
elif msg[0] == TYPE_REQ_START:
    # Legacy: Python-built scope (fallback)
    scope = self._build_scope_python(msg)
```

Environment variable override:
```bash
VELO_DEBUG_PYTHON_SCOPE=1 velo serve main:app
```

---

## 7. Verification Criteria

### 7.1 Functional Tests

- [ ] All Phase 7.2 RSGI tests pass with Rust scope
- [ ] FastAPI WebSocket test passes
- [ ] Starlette `Request.url` returns correct value (tests `server` field)
- [ ] Django async view test passes

### 7.2 Performance Benchmark

```bash
# Baseline (Python scope)
wrk -t4 -c100 -d30s http://localhost:8000/

# After migration (Rust scope)
wrk -t4 -c100 -d30s http://localhost:8000/

# Pass criteria:
# - p99 latency reduction > 3μs
# - Throughput increase > 5%
```

### 7.3 Compatibility Matrix

| Framework | Test Case | Status |
|:---|:---|:---|
| FastAPI | `test_fastapi_basic.py` | Required |
| Starlette | `test_starlette_url.py` | Required |
| Django Async | `test_django_async.py` | Required |
| Quart | `test_quart_basic.py` | Nice-to-have |

---

## 8. Security Invariants

| Gate | Requirement | Verification |
|:---|:---|:---|
| **Gate H** | Scope built from validated request only | Rust Host validates before scope creation |
| **Gate P** | No header injection via scope | `PyBytes::new()` handles raw bytes safely |
| **Gate E** | Scope serialization timeout | MessagePack has size limits |

---

## 9. Grand Council Review Summary

**Date**: 2026-01-14
**Verdict**: ✅ **APPROVED (Phase 8.x)**

| Persona | Vote | Rationale |
|:---|:---|:---|
| HPC Engineer | ✅ | 5-8μs savings per request is meaningful at scale |
| Python Core Dev | ✅ | Fixes `server=None` bug; full ASGI 3.0 compliance |
| Rust Core Dev | ✅ | No `unsafe`; GIL safety structurally enforced |
| Framework Specialist | ✅ | Improves Starlette compatibility |
| Security Engineer | ✅ | No security regression |
| CTO | ✅ | Defer until Phase 7.3 stability fixes complete |

**P0 Blocking Issues**: None
**Dependency**: Complete Phase 7.3 stability fixes first

---

## 10. References

- [ASGI 3.0 Specification](https://asgi.readthedocs.io/en/latest/specs/main.html)
- [PyO3 Interned Strings](https://pyo3.rs/v0.21/types#interned-strings)
- [Granian ASGI Utils Source](../../vendor/granian/src/asgi/utils.rs)
- [Velo RSGI Bridge Source](../../velo_zygote/rsgi.py)

---

**Last Updated**: 2026-01-14
