# RFC-0019: Native Sovereignty (Rust-Native Runtime Engine)

**Status**: DRAFT (Proposed for Phase 7.2)
**Author**: Architect
**Date**: 2026-01-09

## 0. Detailed Specifications
*   **Protocol Design**: [0019-details-protocol.md](0019-details-protocol.md)
*   **Audit Report**: [../architecture/audit_phase_7_alignment.md](../architecture/audit_phase_7_alignment.md)
*   **QA Handoff**: [../architecture/handover_qa_phase_7_1_7_2.md](../architecture/handover_qa_phase_7_1_7_2.md)

## 1. Summary
"Native Sovereignty" replaces the Python-based execution host (Uvicorn/Gunicorn) with a high-performance, Rust-native engine. By moving the L7 HTTP logic into the Velo binary and orchestrating Python workers via the **RSGI-Velo protocol**, we achieve 0ms wrapper overhead and superior signal/lifecycle control.

## 2. Motivation
Current limitations of the Uvicorn-wrapper model:
*   **Double Handling**: Requests are parsed by Rust (L7 Proxy) then re-parsed by Uvicorn.
*   **Signal Impedance**: Propagation of signals (SIGTERM, SIGUSR1) between Rust and Python is brittle.
*   **Dependency Leak**: Users must have `uvicorn` and its dependencies in their project `.venv`.

## 3. Architectural Blueprint

### 3.1 The Native Host Topology (Granian-Powered)
The Velo binary becomes the **Master Execution Host**, integrating a customized version of the **Granian** L7 engine.

> [!NOTE]
> Velo adopts a **"Strategic Dissection"** approach: vendoring Granian's ASGI/RSGI state machines while replacing its process management with Velo's proprietary Zygote/Forking lifecycle.

```
[ External Client ] 
       │ HTTP/1.1, HTTP/2
       ▼
[ Velo Master (Rust/Hyper) ]  <─── Control Plane (UDS)
       │                                │
       │ RSGI-Velo Protocol (MsgPack)   │ Health, Lifecycle
       ▼                                │
[ Velo Worker (Python/Zygote) ] <───────┘
```

### 3.2 Velo / Granian / FastAPI Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        User Perspective                             │
│                                                                     │
│   Developer only cares:  velo run main:app  (FastAPI just works)   │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 Layer 1: VELO (Runtime Controller)                  │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  • Zygote Engine: Python pre-warm + Fork (ms-level startup) │    │
│  │  • Autopilot: Auto-detect torch/pandas heavy imports        │    │
│  │  • Custodian: Manage embedded uv toolchain                  │    │
│  │  • Memory Gravity: SHM shared model weights (SafeTensors)   │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                    │                                │
│                        RSGI-Velo Protocol (MessagePack over UDS)    │
│                                    ▼                                │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │           Granian Core (L7 Engine - Vendored)                │    │
│  │  • Hyper (Rust HTTP): TCP Accept, SSL Termination           │    │
│  │  • ASGI State Machine: Scope/Receive/Send event loop        │    │
│  │  • Marshalling: Rust Dict -> Python Dict (Zero-copy)        │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                          ASGI 3.0 Interface
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│               Layer 2: FASTAPI / STARLETTE (Your App)               │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  • Routing: @app.get("/predict")                            │    │
│  │  • Pydantic Validation: class Item(BaseModel)               │    │
│  │  • Dependency Injection: Depends(get_db)                    │    │
│  │  • Middleware: CORSMiddleware, AuthMiddleware               │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                          Python async/await
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│               Layer 3: ML/AI Workloads (Your Logic)                 │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  • torch.load("model.pt")                                   │    │
│  │  • model.predict(input)                                     │    │
│  │  • pandas.read_parquet("data.parquet")                      │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.3 Component Responsibilities

| Component | Role | Analogy |
|:---|:---|:---|
| **Velo** | Runtime Controller | Like JVM for Java |
| **Granian Core** | L7 Protocol Engine | Like Netty for Spring |
| **FastAPI** | Business Framework | Like Spring MVC |

### 3.4 RSGI-Velo Protocol Specification
The protocol defines the binary exchange between the Rust Host and Python Worker.

*   **Core Engine**: Hyper-based Granian ASGI core.
*   **Transport**: Unix Domain Sockets (UDS) with length-prefixed framing.
*   **Serialization**: MessagePack (rmp-serde) for high-speed, zero-copy potential, following Granian's internal marshalling patterns.
*   **Handshake Phase**:
    1.  Host spawns Worker.
    2.  Worker sends `READY` with its capabilities (Supported RSGI versions, Worker ID).
    3.  Host acknowledges with `AUTH_OK`.

### 3.3 Message Types
| Type | ID | Direction | Payload |
|------|----|-----------|---------|
| `REQ_START` | 0x01 | Host -> Worker | Method, URL, Headers, Body-Chunk-0 |
| `REQ_BODY` | 0x02 | Host -> Worker | Body-Chunk-N, Is-EOF |
| `RES_START` | 0x03 | Worker -> Host | Status Code, Headers |
| `RES_BODY` | 0x04 | Worker -> Host | Body-Chunk-N, Is-EOF |
| `KEEPALIVE` | 0x09 | Both | Timestamp |

## 4. The ABI Boundary
To ensure TITANIUM-grade stability, the boundary is strictly defined:
*   **Rust (Sovereign)**: TCP Accept, SSL Termination, HTTP Parsing, Load Balancing, Timeout Enforcement, Buffer Management.
*   **Python (Execution)**: ASGI/RSGI Dispatching, User Code Execution, Response Generation.

## 5. Security & Isolation
*   **FD Passing**: Rust host can pass pre-bound FDs to Python workers to reduce syscall overhead.
*   **Seccomp (Linux)**: Workers are restricted to a subset of syscalls (Network access only via the Host).

## 6. Performance Targets
*   **Latency**: < 3.5ms total request overhead (Production Grade).
*   **Throughput**: 1.2x - 1.5x of standard Uvicorn/uvloop.
*   **Memory**: 30% reduction in worker RSS by removing the Python networking stack.

## 6.1 Python Runtime Configuration

### Event Loop Policy (Performance-First Default)
Velo defaults to the **highest-performance mature technology** while maintaining broad compatibility.

| Priority | Event Loop | Condition | Fallback |
|:---|:---|:---|:---|
| 1 | `uvloop` | Linux/macOS + Python 3.9+ | If unavailable → 2 |
| 2 | `asyncio` | All platforms | Always available |

### Configuration
```toml
# pyproject.toml
[tool.velo]
event_loop = "auto"  # "auto" | "uvloop" | "asyncio"
```

### Compatibility Matrix
| Python Version | uvloop Support | Velo Default |
|:---|:---|:---|
| 3.8 (EOL) | ⚠️ Limited | `asyncio` |
| 3.9 - 3.12 | ✅ Full | `uvloop` (auto) |
| 3.13+ (free-threading) | 🧪 Experimental | `asyncio` + monitor |

### Drop-in Guarantee
> [!IMPORTANT]
> **Default Strategy**: Sacrifice compatibility with Python < 3.9 to maximize performance for 95%+ of users.
> **High-version Priority**: Python 3.9+ users get `uvloop` by default with zero configuration.
> **Graceful Fallback**: If `uvloop` is not installed, Velo silently falls back to `asyncio` without error.


## 7. Strict Security Invariants (RFC-0012/0013 Alignment)
Native Sovereignty establishes a "Zero-Trust" host-worker boundary:
*   **SEC-FS-002 (FD Hygiene)**: The Rust Host performs a mandatory `close_range(3, ~0)` before spawning workers to prevent sensitive FD leakage.
*   **P0-1 (Peer Auth)**: Every UDS connection MUST be verified via `SO_PEERCRED` (Linux) or `getpeereid` (macOS) before the handshake begins.
*   **P0-2 (Taint Contract)**: The Python Worker MUST execute the Taint Re-randomization contract (`random.seed`, `os.urandom`) immediately post-fork and before sending the `READY` message.
*   **Signal Hygiene**: The Host MUST reset the signal mask in `pre_exec` to ensure workers are reachable via standard signals.

## 8. Technology Radar: Phase 8.x IO Evolution

> [!NOTE]
> This section documents future IO technologies under evaluation for post-7.x phases.

### 8.1 io_uring (Linux 5.10+)
**Status**: 🟡 WATCHING (tokio-uring 0.x maturity)

| Feature | Benefit | Velo Applicability |
|:---|:---|:---|
| **Zero-copy TX/RX** | Eliminate network buffer copies | ⭐ High |
| **Multishot Accept** | Single syscall for multiple connections | ⭐ High |
| **SQPOLL Mode** | Kernel-side polling, zero syscall overhead | 🧪 Experimental |
| **Registered Buffers** | Pre-registered memory for DMA | 🔮 Research |

**Adoption Criteria**:
1. `tokio-uring` reaches 1.0 stable
2. Linux 5.10+ becomes baseline (currently ~80% server market)
3. Benchmark shows >20% improvement over epoll

### 8.2 Python 3.13+ Free-Threading
**Status**: 🟡 MONITORING

| Feature | Benefit |
|:---|:---|
| `--disable-gil` | True multi-threaded Python |
| Per-object locking | Fine-grained concurrency |

**Adoption Criteria**:
1. NumPy/Pandas/PyTorch support free-threading
2. Production stability confirmed (18+ months post-release)

### 8.3 Current Stack (Phase 7.x Baseline)
```
┌─────────────────────────────────────┐
│  Tokio (epoll/kqueue) - STABLE      │  ← Phase 7.2 Default
├─────────────────────────────────────┤
│  uvloop (libuv) - STABLE            │  ← Python Event Loop
├─────────────────────────────────────┤
│  io_uring - WATCHING                │  ← Phase 8.x Target
└─────────────────────────────────────┘
```

### 8.4 Memory Allocator Strategy
**Status**: 🟢 READY (Phase 7.2 Implementation)

| Allocator | Characteristics | Recommendation |
|:---|:---|:---|
| **jemalloc** | Multi-threaded, low fragmentation | ✅ Default |
| **mimalloc** | Microsoft, ultra-fast small allocs | 🧪 Alternative |
| **system** | Platform default | Fallback |

**Implementation**:
```toml
# Cargo.toml
[features]
default = ["jemalloc"]
jemalloc = ["tikv-jemallocator"]
```

### 8.5 Compiler Optimization Profile
**Status**: 🟢 READY (Release Build)

| Optimization | Config | Expected Gain |
|:---|:---|:---|
| **LTO (Fat)** | `lto = "fat"` | 5-15% |
| **Single Codegen Unit** | `codegen-units = 1` | 2-5% |
| **Abort on Panic** | `panic = "abort"` | Binary size |
| **Native CPU** | `-C target-cpu=native` | 5-10% |
| **PGO** | Profile-Guided Optimization | 10-20% (CI) |

**Production Profile**:
```toml
[profile.release]
lto = "fat"
codegen-units = 1
panic = "abort"
strip = true
opt-level = 3
```

### 8.6 Advanced Optimizations (Phase 8.x+)
**Status**: 🟡 RESEARCH

| Optimization | Description | ROI | Complexity |
|:---|:---|:---|:---|
| **Worker NUMA Affinity** | Bind workers to NUMA nodes | ⭐⭐ | Medium |
| **mmap Body Passing** | SCM_RIGHTS for large request bodies | ⭐⭐⭐ | High |
| **Huge Pages (SHM)** | 2MB pages for model weights | ⭐⭐⭐ | Medium |
| **Hot Path Inlining** | `#[inline(always)]` critical paths | ⭐⭐ | Low |
| **Branch Prediction Hints** | `likely()`/`unlikely()` annotations | ⭐ | Low |

### 8.7 Observability for Performance
| Metric | Purpose |
|:---|:---|
| **P50/P95/P99 Latency** | Distribution analysis |
| **GIL Wait Time** | Python contention detection |
| **Allocation Rate** | Memory pressure indicator |
| **Syscall Count** | io_uring effectiveness |

### 8.8 ByteDance Open Source Technologies
**Status**: 🟡 EVALUATION

#### Monoio (Thread-per-Core Async Runtime)
| Aspect | Details |
|:---|:---|
| **Repository** | `bytedance/monoio` |
| **Architecture** | Thread-per-Core (no cross-thread scheduling) |
| **IO Backend** | io_uring (Linux) / kqueue (macOS) |
| **License** | Apache 2.0 ✅ |
| **vs Tokio** | Lower latency, no work-stealing overhead |

**Adoption Criteria**:
1. Monoio reaches 1.0 stable
2. Benchmark shows >15% latency reduction vs Tokio
3. macOS kqueue backend is production-ready

#### Sonic-rs (SIMD-Accelerated JSON)
| Aspect | Details |
|:---|:---|
| **Repository** | `bytedance/sonic-rs` |
| **Performance** | 2-3x faster than serde_json |
| **SIMD** | AVX2 (x86) / NEON (ARM) |
| **API** | serde-compatible |
| **License** | Apache 2.0 ✅ |

**Use Case**: Replace `serde_json` for HTTP body serialization in Granian Core.

**Adoption Criteria**:
1. Verify serde compatibility with existing codebase
2. Benchmark JSON-heavy workloads (API responses)
3. Confirm ARM (Apple Silicon) NEON support

#### Adoption Priority
| Technology | Phase | Priority |
|:---|:---|:---|
| **Sonic-rs** | 7.2 or 8.x | ⭐⭐⭐ High (easy integration) |
| **Monoio** | 8.x+ | ⭐⭐ Medium (runtime replacement) |

### 8.9 Additional Async Runtimes (Research 2025-2026)
**Status**: 🟡 WATCHING

#### Glommio (DataDog)
| Aspect | Details |
|:---|:---|
| **Repository** | `DataDog/glommio` |
| **Architecture** | Thread-per-core + native io_uring |
| **Target Usage** | I/O-bound workloads, databases |
| **License** | Apache 2.0 ✅ |
| **vs Monoio** | More mature, production-tested at DataDog |

#### smol (Community)
| Aspect | Details |
|:---|:---|
| **Repository** | `smol-rs/smol` |
| **Architecture** | Minimal, lightweight runtime |
| **Target Usage** | Simple applications, prototyping |
| **Note** | Official successor for async-std users |

### 8.10 Extended Memory Allocator Comparison
**Status**: 🟢 EVALUATION COMPLETE

| Allocator | Source | Best For | Performance Gain |
|:---|:---|:---|:---|
| **jemalloc** | FreeBSD/Redis | Long-running servers, fragmentation resistance | 30-50% |
| **mimalloc** | Microsoft | Low-latency, real-time async | 5x+ multithreaded |
| **snmalloc** | Microsoft Research | Security-first, capability design | Similar to mimalloc |

> [!TIP]
> **Recommendation**: Start with `jemalloc` for stability, evaluate `mimalloc` for latency-critical paths.

### 8.11 Security Considerations for Advanced IO

> [!WARNING]
> **io_uring Security Advisory**
> - io_uring has a large kernel attack surface
> - **Default blocked** in Docker and cloud sandboxes (GKE, EKS)
> - Requires explicit enablement: `--security-opt seccomp=unconfined`
> - Evaluate security vs. performance trade-offs carefully

| Environment | io_uring Status | Recommendation |
|:---|:---|:---|
| Bare metal | ✅ Available | Full performance |
| Docker (default) | ❌ Blocked | Use epoll |
| Kubernetes | ⚠️ Varies by provider | Test explicitly |
| Cloud Functions | ❌ Blocked | Not applicable |

### 8.12 Deprecated Technologies (Avoid)

> [!CAUTION]
> The following technologies are deprecated or discontinued. Do NOT use in new development.

| Technology | Status | Alternative |
|:---|:---|:---|
| **async-std** | ❌ Discontinued (March 2025) | smol or Tokio |
| **actix-web 3.x** | ⚠️ Legacy | actix-web 4.x |

### 8.13 Protocol Evolution Radar

| Protocol | Status | Notes |
|:---|:---|:---|
| **HTTP/2** | 🟢 STABLE | Granian full support |
| **HTTP/3 (QUIC)** | 🟡 WATCHING | Granian planned, Phase 9.x |
| **WebTransport** | 🔮 RESEARCH | Future real-time applications |
