# RFC-0029: Unified Granian Worker Architecture

**Status**: DRAFT
**Author**: Architect
**Date**: 2026-01-14
**Phase**: 9.x (Architectural Evolution)
**Priority**: P0 - Strategic

## Related Documents

- [RFC-0019: Native Sovereignty](./0019-native-sovereignty.md)
- [RFC-0025: WebSocket Support Architecture](./0025-websocket-architecture.md)
- [Granian Source](../../vendor/granian/)

---

## 1. Summary

This RFC proposes a fundamental architectural evolution: **replacing UDS-based IPC with Granian's native PyO3 Worker model**, while preserving Velo's process isolation and Zygote COW pre-warming advantages.

> [!IMPORTANT]
> **Paradigm Shift**: Velo already integrates Granian. We should use its full capabilities, not just pieces.

---

## 2. Problem Statement

### 2.1 Current Architecture (RFC-0019)

```
┌─────────────────┐          UDS          ┌─────────────────┐
│   Rust Host     │ ←───────────────────→ │  Python Worker  │
│   (no Python)   │   MessagePack IPC     │   (no Rust)     │
│                 │   ~50-100μs/frame     │                 │
└─────────────────┘                       └─────────────────┘
```

**Issues**:
1. **Latency**: UDS + MessagePack adds ~50-100μs per request
2. **Redundancy**: Granian already solves this problem with PyO3
3. **Complexity**: Two separate codebases (Rust Host + Python Worker)

### 2.2 Granian Native Architecture

```
┌─────────────────────────────────────────┐
│         Granian Worker (Rust)           │
│  ┌─────────────────────────────────┐   │
│  │     PyO3 Embedded Python        │   │
│  │     ~1-5μs per call             │   │
│  └─────────────────────────────────┘   │
│                  ↓                      │
│  ┌─────────────────────────────────┐   │
│  │     Python ASGI App             │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

**We already have this code in `vendor/granian/`!**

---

## 3. Proposed Architecture

### 3.1 Unified Model: Granian Worker + Zygote

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
│  │  │  Hyper HTTP Server                          │   │   │
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

### 3.2 Key Innovation: Zygote + PyO3

| Step | Action | Benefit |
|:---|:---|:---|
| 1 | Zygote pre-loads Python + App modules | Fast fork |
| 2 | fork() creates Worker | COW memory sharing |
| 3 | Worker uses PyO3 for ASGI calls | ~1-5μs latency |
| 4 | Worker crash → Master respawns | Isolation preserved |

---

## 4. Performance Comparison

| Metric | UDS (RFC-0019) | Granian Native | Unified (RFC-0029) |
|:---|:---|:---|:---|
| **Request Latency** | ~50-100μs | ~1-5μs | **~1-5μs** |
| **WebSocket Frame** | ~50-100μs | ~1-5μs | **~1-5μs** |
| **Cold Start** | ~500ms | ~500ms | **~50ms (COW)** |
| **Memory per Worker** | High (separate process) | Medium | **Low (COW sharing)** |
| **Fault Isolation** | ✅ Full | ✅ Per-worker | **✅ Per-worker** |

---

## 5. Implementation Plan

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

## 6. Code Simplification

### Before (RFC-0019)

```
src/
├── rsgi/
│   ├── host.rs          # Rust Host (UDS server)
│   ├── protocol.rs      # MessagePack protocol
│   └── mod.rs
├── serve/
│   ├── runner.rs        # Spawns Python worker
│   └── zygote.rs        # Pre-warms Python
velo_zygote/
├── rsgi.py              # Python Worker (UDS client)
├── bridge.py            # ASGI bridge
└── ...
```

### After (RFC-0029)

```
src/
├── serve/
│   ├── runner.rs        # Uses Granian Worker directly
│   ├── zygote.rs        # Pre-warms PyO3 + App
│   └── supervisor.rs    # Manages Workers
vendor/
└── granian/             # Already integrated!
```

**Lines of Code**:
- **Deleted**: ~1500 lines (rsgi/, velo_zygote/rsgi.py)
- **Added**: ~200 lines (Granian integration)
- **Net**: **-1300 lines**

---

## 7. Preserved Invariants

| RFC-0019 Requirement | Status in RFC-0029 |
|:---|:---|
| **Gate H (Sovereignty)** | ✅ Workers run as separate processes |
| **Gate P (Performance)** | ✅ Improved: ~1-5μs vs ~50-100μs |
| **Gate R (Respawn)** | ✅ Master respawns crashed Workers |
| **Gate J (Graceful Shutdown)** | ✅ Master signals Workers |
| **Zygote COW** | ✅ Enhanced: Pre-warms PyO3 + App |

---

## 8. Migration Path

### For Existing Velo Users

```bash
# No CLI change!
velo serve app:main  # Works identically, but 10-50x faster
```

### For Developers

```python
# No app code change!
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
async def root():
    return {"hello": "world"}

# WebSocket also works identically
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    data = await websocket.receive_text()
    await websocket.send_text(f"Echo: {data}")
```

---

## 9. Risk Analysis

| Risk | Mitigation |
|:---|:---|
| **PyO3 GIL contention** | Each Worker has its own GIL (separate process) |
| **Python crash affects Rust** | Per-worker isolation; crash = respawn |
| **Breaking change** | No API change; internal only |
| **Granian upstream divergence** | Vendor lock; periodic sync |

### 9.5 Implementation Risks & Advisories

> [!CAUTION]
> The following details require special attention during Phase 9.x implementation:

#### 9.5.1 Event Loop and Fork Conflict

| Risk | Requirement |
|:---|:---|
| Python's `asyncio` Event Loop does not work after fork (Epoll/Kqueue handles become invalid) | Zygote should **only load code (import)**, **NEVER** start any Event Loop before fork |

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

#### 9.5.2 File Descriptor (FD) Management

| Risk | Requirement |
|:---|:---|
| Fork duplicates all open FDs | Management FDs in Master (log handles, control channels) must be properly handled in Worker |

```rust
// Close inherited management FDs immediately after Worker starts
fn worker_post_fork_cleanup() {
    // Close Master's control channel
    if let Some(ctrl_fd) = MASTER_CONTROL_FD.take() {
        unsafe { libc::close(ctrl_fd); }
    }
    
    // Listen Socket handling:
    // Option A: SO_REUSEPORT (each Worker accepts independently)
    // Option B: Parent-child inheritance (Master accepts, passes to Worker)
}
```

#### 9.5.3 Signal Handling

| Risk | Requirement |
|:---|:---|
| SIGINT/SIGTERM received by Master must be correctly propagated to Worker group | `supervisor.rs` implements signal forwarding for graceful shutdown |

```rust
// src/serve/supervisor.rs
async fn handle_shutdown(&self) {
    // 1. Stop accepting new connections
    self.listener.pause();
    
    // 2. Notify all Workers to gracefully shutdown
    for worker in &self.workers {
        worker.send_signal(Signal::SIGTERM)?;
    }
    
    // 3. Wait for Workers to complete (with timeout)
    tokio::time::timeout(
        Duration::from_secs(30),
        self.wait_all_workers()
    ).await?;
    
    // 4. Force-kill timed-out Workers
    for worker in self.workers.iter().filter(|w| w.is_running()) {
        worker.send_signal(Signal::SIGKILL)?;
    }
}
```



## 10. Grand Council Review (Final)

### 10.1 Expert Evaluations

#### 🧠 HPC / Runtime Architect

> **Comment**: *"This is a return from distributed system thinking to runtime thinking.
> You no longer pretend Python is a remote node, but acknowledge it as a heterogeneous compute domain in the same process space."*

| Approval Point | Description |
|:---|:---|
| μs-level call path | From ~50-100μs down to ~1-5μs |
| Eliminated serialization/deserialization | No MessagePack overhead |
| WebSocket is no longer a "tunnel protocol" | Native tungstenite |

**Vote**: ✅ **STRONG YES**

---

#### 🛡 Security Engineer

| Concern | Conclusion |
|:---|:---|
| Gate H (Sovereignty) | Worker is still an independent process ✅ |
| FD Leakage | §9.5.2 provides cleanup strategy ✅ |
| Post-fork state pollution | §9.5.1 prohibits Event Loop before fork ✅ |
| GIL Isolation | GIL does not cross Workers ✅ |

**Vote**: ✅ **YES** (with condition C1)

---

#### 🧰 Rust Core / Systems Engineer

| Approval Point | Description |
|:---|:---|
| -1300 LOC | Delete entire rsgi/ subsystem |
| Rust responsibility purification | Only scheduling, supervision, I/O remain |

| Risk Warning | Mitigation |
|:---|:---|
| Granian vendoring | Freeze ABI layer (condition C3) |
| PyO3 version upgrade | Lock with Rust toolchain |

**Vote**: ✅ **YES**

---

#### 🐍 Python Runtime Engineer

> **Comment**: *"The warning in §9.5.1 is professional-grade, demonstrating kernel-level understanding of Python runtime, not just framework-level."*

| Approval Point | Description |
|:---|:---|
| No custom Python bridge | Standard PyO3 |
| ASGI fully native | Direct invocation |
| WebSocket is no longer "protocolized" | Native tungstenite |

**Vote**: ✅ **YES**

---

### 10.2 Blocking Conditions

> [!CAUTION]
> RFC-0029 **MUST** satisfy the following three hard constraints before Phase 9.x implementation:

#### C1. Zygote Phase Capability Whitelist

Introduce semantic-level isolation in `zygote.rs`:

```rust
/// Zygote execution phase - determines what operations are allowed
enum ZygotePhase {
    ImportOnly,     // Only import allowed
    PostForkInit,   // Initialize runtime within Worker
}
```

**Enforced Constraints**:

| API | `ImportOnly` | `PostForkInit` |
|:---|:---|:---|
| PyO3 `import` | ✅ | ✅ |
| `asyncio.get_event_loop` | ❌ **panic** | ✅ |
| `uvloop.install` | ❌ **panic** | ✅ |
| ASGI app call | ❌ | ✅ |

---

#### C2. Worker Lifecycle State Machine

`supervisor.rs` must explicitly model:

```rust
/// Worker lifecycle states
enum WorkerState {
    Spawned,      // fork() completed
    Initializing, // PyO3 + Event Loop initializing
    Ready,        // Can accept requests
    Draining,     // Received SIGTERM, draining
    Dead,         // Exited
}
```

**State Transition Rules**:

```
Spawned → Initializing → Ready → Draining → Dead
                           ↑         ↓
                           └── SIGTERM ──┘
```

**Invariants**:
- Master **NEVER** dispatches requests to `Initializing` Workers
- `SIGTERM` transitions to `Draining` state
- Timeout (30s) transitions to `SIGKILL`

---

#### C3. Granian ABI Freeze Strategy

Add to `vendor/granian/`:

```
vendor/granian/VELO_GRANIAN_ABI.md
```

**Required Content**:

| Boundary | Frozen Content |
|:---|:---|
| Rust ↔ PyO3 | Function signatures, type definitions |
| Worker startup | Entry function, initialization order |
| ASGI invocation | `scope`, `receive`, `send` paths |

**Purpose**: Prevent "unconscious upstream sync" from breaking runtime contracts.

---

### 10.3 Final Verdict

| Persona | Vote | Condition |
|:---|:---|:---|
| HPC / Runtime Architect | ✅ **STRONG YES** | - |
| Security Engineer | ✅ **YES** | C1 |
| Rust Core / Systems | ✅ **YES** | C3 |
| Python Runtime Engineer | ✅ **YES** | - |

**P0 Blocking Issues**: C1, C2, C3 (must be satisfied before implementation)



---

## 11. Summary

| Aspect | RFC-0019 (Current) | RFC-0029 (Proposed) |
|:---|:---|:---|
| **Latency** | ~50-100μs | **~1-5μs** |
| **Cold Start** | ~500ms | **~50ms (COW)** |
| **Code Complexity** | ~1500 lines (rsgi/) | **-1300 lines** |
| **Isolation** | ✅ | ✅ (same) |
| **WebSocket** | Protocol Tunneling | **Native PyO3** |

> [!IMPORTANT]
> **This is the design we should have had from the start.** We integrated Granian but didn't fully use it.

---

## 12. References

- [Granian GitHub](https://github.com/emmett-framework/granian)
- [PyO3 Documentation](https://pyo3.rs/)
- [RFC-0019: Native Sovereignty](./0019-native-sovereignty.md)
- [Zygote Process Model](https://source.android.com/docs/core/runtime)

---

**Last Updated**: 2026-01-14
