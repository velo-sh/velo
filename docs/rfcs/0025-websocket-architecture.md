# RFC-0025: Granian Native Runtime Architecture

**Status**: DRAFT → APPROVED
**Author**: Architect
**Date**: 2026-01-14
**Phase**: 9.x (Unified Architecture)

## Related Documents

- [RFC-0019: Native Sovereignty](./0019-native-sovereignty.md) (Superseded by this RFC)
- [RFC-0026: Native TLS Integration](./0026-native-tls-integration.md)
- [RFC-0027: HTTP/2 Support](./0027-http2-support.md)
- [Granian Source](../../vendor/granian/)

---

## 1. Summary

This RFC defines the unified Granian-native runtime architecture for Velo, including:
- **HTTP/HTTPS Request Handling** via Granian's Hyper + PyO3 integration
- **WebSocket Support** via Granian's tokio-tungstenite + RSGIWebsocketTransport
- **Process Isolation** via Zygote COW fork model

> [!IMPORTANT]
> **Design Principle**: Velo integrates Granian. We use its **full capabilities**, not just pieces.
> This RFC supersedes the UDS-based architecture in RFC-0019.

---

## 2. Architecture Overview

### 2.1 Unified Model: Granian Worker + Zygote

```
┌─────────────────────────────────────────────────────────────┐
│                    Velo Master (Supervisor)                  │
│   - Process management                                       │
│   - Health checks                                            │
│   - Load balancing                                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ fork() COW
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Granian Worker (Forked)                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Rust Runtime (Tokio)                               │   │
│  │  ┌─────────────────────────────────────────────┐   │   │
│  │  │  Hyper HTTP/WebSocket Server                │   │   │
│  │  │  ┌─────────────────────────────────────┐   │   │   │
│  │  │  │  PyO3 Bridge (~1-5μs)               │   │   │   │
│  │  │  │  ┌─────────────────────────────┐   │   │   │   │
│  │  │  │  │  Python ASGI App            │   │   │   │   │
│  │  │  │  │  (Pre-warmed via Zygote)    │   │   │   │   │
│  │  │  │  └─────────────────────────────┘   │   │   │   │
│  │  │  └─────────────────────────────────────┘   │   │   │
│  │  └─────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Granian Capabilities

| Component | Location | Capability |
|:---|:---|:---|
| `HyperWebsocket` | `vendor/granian/src/ws.rs` | Rust-native WS via `tokio-tungstenite` |
| `RSGIWebsocketTransport` | `vendor/granian/src/rsgi/io.rs` | PyO3-bound `receive()/send()` |
| `build_scope_http` | `vendor/granian/src/asgi/utils.rs` | Rust-side ASGI scope building |
| `HTTP2Config` | `vendor/granian/src/workers.rs` | HTTP/2 multiplexing support |
| `TlsConfig` | `vendor/granian/src/tls.rs` | rustls-based TLS termination |

---

## 3. Performance Comparison

| Metric | UDS (RFC-0019) | Granian Native (This RFC) | Improvement |
|:---|:---|:---|:---|
| **Request Latency** | ~50-100μs | **~1-5μs** | 10-50x |
| **WebSocket Frame** | ~50-100μs | **~1-5μs** | 10-50x |
| **Cold Start** | ~500ms | **~50ms (COW)** | 10x |
| **Code Complexity** | +1500 lines | **-1300 lines** | Simpler |
| **Fault Isolation** | ✅ Full | ✅ Per-worker | Same |

---

## 4. Implementation Plan

### Phase 9.1: Granian Worker Integration

| Step | File | Change |
|:---|:---|:---|
| 1 | `src/serve/runner.rs` | Replace `spawn_python_worker()` with Granian worker |
| 2 | `src/serve/runner.rs` | Remove UDS socket creation |
| 3 | `src/rsgi/` | **Delete** (no longer needed) |
| 4 | `velo_zygote/rsgi.py` | **Delete** (replaced by PyO3) |

### Phase 9.2: Zygote COW Enhancement

| Step | File | Change |
|:---|:---|:---|
| 1 | `src/serve/zygote.rs` | Pre-initialize PyO3 interpreter |
| 2 | `src/serve/zygote.rs` | Pre-import user's ASGI app |
| 3 | `src/serve/zygote.rs` | fork() with COW for Workers |

### Phase 9.3: Supervisor Integration

| Step | File | Change |
|:---|:---|:---|
| 1 | `src/serve/supervisor.rs` | Manage Granian Workers |
| 2 | `src/serve/supervisor.rs` | Health checks via Worker signals |
| 3 | `src/serve/supervisor.rs` | Respawn on Worker crash |

---

## 5. Implementation Risks & Advisories

> [!CAUTION]
> The following details require special attention during Phase 9.x implementation:

### 5.1 Event Loop and Fork Conflict

| Risk | Requirement |
|:---|:---|
| Python's `asyncio` Event Loop does not work after fork | Zygote should **only load code (import)**, **NEVER** start any Event Loop before fork |

```rust
// ✅ CORRECT: Initialize Event Loop after Worker process starts
fn worker_main() {
    // Fork is complete, safe to initialize now
    Python::with_gil(|py| {
        let asyncio = py.import("asyncio")?;
        let loop = asyncio.call_method0("new_event_loop")?;
        asyncio.call_method1("set_event_loop", (loop,))?;
    });
}

// ❌ WRONG: Initialize Event Loop in Zygote (before fork)
fn zygote_init() {
    Python::with_gil(|py| {
        let asyncio = py.import("asyncio")?;
        asyncio.call_method0("get_event_loop")?;  // DANGEROUS!
    });
}
```

### 5.2 File Descriptor (FD) Management

| Risk | Requirement |
|:---|:---|
| Fork duplicates all open FDs | Management FDs in Master (log handles, control channels) must be properly handled in Worker |

### 5.3 Signal Handling

| Risk | Requirement |
|:---|:---|
| SIGINT/SIGTERM received by Master must be correctly propagated to Worker group | `supervisor.rs` implements signal forwarding for graceful shutdown |

---

## 6. Blocking Conditions

> [!CAUTION]
> This RFC **MUST** satisfy the following three hard constraints before Phase 9.x implementation:

### C1. Zygote Phase Capability Whitelist

```rust
enum ZygotePhase {
    ImportOnly,     // Only import allowed
    PostForkInit,   // Initialize runtime within Worker
}
```

| API | `ImportOnly` | `PostForkInit` |
|:---|:---|:---|
| PyO3 `import` | ✅ | ✅ |
| `asyncio.get_event_loop` | ❌ **panic** | ✅ |
| `uvloop.install` | ❌ **panic** | ✅ |
| ASGI app call | ❌ | ✅ |

### C2. Worker Lifecycle State Machine

```rust
enum WorkerState {
    Spawned,      // fork() completed
    Initializing, // PyO3 + Event Loop initializing
    Ready,        // Can accept requests
    Draining,     // Received SIGTERM, draining
    Dead,         // Exited
}
```

**Invariants**:
- Master **NEVER** dispatches requests to `Initializing` Workers
- `SIGTERM` transitions to `Draining` state
- Timeout (30s) transitions to `SIGKILL`

### C3. Granian ABI Freeze Strategy

Add `vendor/granian/VELO_GRANIAN_ABI.md` documenting:
- Rust ↔ PyO3 function signatures
- Worker startup entry function
- ASGI invocation paths (`scope`, `receive`, `send`)

---

## 7. Security Invariants

| Gate | Requirement | Verification |
|:---|:---|:---|
| **Gate H** | Workers are separate processes (isolation) | Process tree verification |
| **Gate E** | 500ms handshake timeout | `test_handshake_timeout` |
| **Gate P** | UDS socket 0700 permissions (if used for control) | `test_uds_isolation_permissions` |

---

## 8. Grand Council Review Summary

**Review Date**: 2026-01-14
**Verdict**: ✅ **UNANIMOUS APPROVAL**

| Persona | Vote | Rationale |
|:---|:---|:---|
| HPC / Runtime Architect | ✅ **STRONG YES** | ~1-5μs latency achieved |
| Security Engineer | ✅ **YES** | Process isolation preserved |
| Rust Core / Systems | ✅ **YES** | -1300 lines of code |
| Python Runtime Engineer | ✅ **YES** | Standard PyO3 integration |
| CTO | ✅ **YES** | Leverages existing Granian investment |

**P0 Blocking Issues**: C1, C2, C3 (must be satisfied before implementation)

---

## 9. Migration Notes

### Supersedes

- **RFC-0019**: UDS-based IPC → Replaced by PyO3 direct call
- **RFC-0028**: ASGI Scope migration → Included in Granian natively

### Code Deletion

```
src/rsgi/           → DELETE
velo_zygote/rsgi.py → DELETE
```

**Net Change**: -1300 lines of code

---

## 10. References

- [Granian GitHub](https://github.com/emmett-framework/granian)
- [PyO3 Documentation](https://pyo3.rs/)
- [tokio-tungstenite](https://docs.rs/tokio-tungstenite)
- [WebSocket RFC 6455](https://tools.ietf.org/html/rfc6455)
- [ASGI Specification](https://asgi.readthedocs.io/)
- [Zygote Process Model](https://source.android.com/docs/core/runtime)

---

**Last Updated**: 2026-01-14
