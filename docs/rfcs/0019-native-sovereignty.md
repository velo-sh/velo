# RFC-0019: Native Sovereignty (Granian Native Runtime)

**Status**: DRAFT → APPROVED (Phase 7.2)
**Author**: Architect
**Date**: 2026-01-09 (Updated: 2026-01-14)

## 0. Detailed Specifications
*   **Protocol Design**: [0019-details-protocol.md](0019-details-protocol.md) (Phase 7.x legacy)
*   **Performance Benefits**: [0019-appendix-performance.md](0019-appendix-performance.md)
*   **WebSocket Support**: [RFC-0025](./0025-websocket-architecture.md)
*   **Native TLS**: [RFC-0026](./0026-native-tls-integration.md)
*   **HTTP/2**: [RFC-0027](./0027-http2-support.md)

> [!IMPORTANT]
> **Current Architectural Evolution** (Jan 14, 2026)
>
> This RFC has been updated to adopt the **Granian Native Runtime** architecture:
> - **Before (Phase 7.x)**: UDS + MessagePack IPC (~50-100μs/request)
> - **After (Phase 7.2)**: PyO3 Direct Call (~1-5μs/request)
>
> See [Section 3.5](#35-phase-9x-granian-native-architecture-current) for the new unified architecture.

## 1. Summary
"Native Sovereignty" replaces the Python-based execution host (Uvicorn/Gunicorn) with a high-performance, Rust-native engine powered by **Granian**.

| Phase | Architecture | Latency |
|:---|:---|:---|
| 7.x (Legacy) | UDS + MessagePack | ~50-100μs |
| **Phase 7.2** | **PyO3 Direct Call** | **~1-5μs** |

### 1.1 Scope: ASGI Web Server Mode Only

> [!IMPORTANT]
> This RFC applies **only to ASGI Web Server mode** (`velo serve`). Other Velo modes continue to use their existing architectures.

| Mode | Command | Architecture | This RFC |
|:---|:---|:---|:---|
| **ASGI Web Server** | `velo serve main:app` | Granian + PyO3 + Multi-Worker | ✅ **Applies** |
| Script Runner | `velo run script.py` | Zygote + Single Process | ❌ Unchanged |
| Bundle Executable | `velo bundle` | Embedded Python | ❌ Unchanged |

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      VELO RUNNING MODES                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  MODE 1: velo serve main:app  [THIS RFC]                          │  │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐           │  │
│  │  │  Master     │───▶│  Worker 0   │ .. │  Worker N   │           │  │
│  │  │  HTTP/TLS   │    │  Granian    │    │  Granian    │           │  │
│  │  └─────────────┘    └─────────────┘    └─────────────┘           │  │
│  │  Multi-Worker, Load Balancing, HTTP/WebSocket, High Concurrency  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  MODE 2: velo run script.py  [UNCHANGED]                          │  │
│  │  ┌─────────────┐    ┌─────────────────────────────────┐          │  │
│  │  │  Velo CLI   │───▶│  Python + Zygote (fast import)  │          │  │
│  │  └─────────────┘    └─────────────────────────────────┘          │  │
│  │  Single Process, Fast Startup (~50ms), Batch/CLI                 │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  MODE 3: ./my-app (after velo bundle)  [UNCHANGED]                │  │
│  │  ┌─────────────────────────────────────────────────────────────┐ │  │
│  │  │  Single Executable: Velo + Embedded Python + Dependencies   │ │  │
│  │  └─────────────────────────────────────────────────────────────┘ │  │
│  │  No Python Install Required, Self-Contained Distribution        │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Invariant**: Changes to ASGI Web Server mode MUST NOT break Script Runner or Bundle modes.

## 2. Motivation
Current limitations of the Uvicorn-wrapper model:
*   **Double Handling**: Requests are parsed by Rust (L7 Proxy) then re-parsed by Uvicorn.
*   **Signal Impedance**: Propagation of signals (SIGTERM, SIGUSR1) between Rust and Python is brittle.
*   **Dependency Leak**: Users must have `uvicorn` and its dependencies in their project `.venv`.

## 3. Architectural Blueprint

### 3.1 The Native Host Topology (Granian-Powered)
The Velo binary becomes the **Master Execution Host**, integrating the **Granian** L7 engine.

```
┌───────────────────────────────────────────────────────────────┐
│                    Velo Master (Supervisor)                   │
│   - Process management                                        │
│   - Health checks                                             │
│   - Load balancing                                            │
└───────────────────────────────────────────────────────────────┘
                               │
                               │ fork() COW
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                    Granian Worker (Forked)                    │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  Rust Runtime (Tokio)                                   │  │
│  │  ┌───────────────────────────────────────────────────┐  │  │
│  │  │  Hyper HTTP/WebSocket Server                      │  │  │
│  │  │  ┌─────────────────────────────────────────────┐  │  │  │
│  │  │  │  PyO3 Bridge (~1-5μs)                       │  │  │  │
│  │  │  │  ┌───────────────────────────────────────┐  │  │  │  │
│  │  │  │  │  Python ASGI App                      │  │  │  │  │
│  │  │  │  │  (Pre-warmed via Zygote)              │  │  │  │  │
│  │  │  │  └───────────────────────────────────────┘  │  │  │  │
│  │  │  └─────────────────────────────────────────────┘  │  │  │
│  │  └───────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

### 3.1.1 Request Flow (Client → FastAPI)

```
  ┌─────────┐
  │ Client  │  HTTP/HTTPS Request
  └────┬────┘
       │
       ▼ (1) TCP Connection
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                    Velo Master (Rust/Tokio)                              │
  │  ┌───────────────────────────────────────────────────────────────────┐  │
  │  │  (2) TLS Termination (rustls) - if HTTPS                          │  │
  │  │  (3) HTTP Parsing (hyper) - parse headers, body                   │  │
  │  │  (4) Load Balancer - select Worker (Round Robin / Least Conn)     │  │
  │  └───────────────────────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────────────────────┘
       │
       ▼ (5) PyO3 Direct Call (~1-5μs)
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                    Granian Worker (Forked Process)                       │
  │  ┌───────────────────────────────────────────────────────────────────┐  │
  │  │  (6) ASGI Scope Building (Rust-side)                              │  │
  │  │  (7) PyO3 → Python: await app(scope, receive, send)               │  │
  │  └───────────────────────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────────────────────┘
       │
       ▼ (8) ASGI 3.0 Interface
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                    FastAPI / Starlette                                   │
  │  (9)  Routing: match @app.post("/api/predict")                          │
  │  (10) Middleware Chain: Auth → CORS → Logging                           │
  │  (11) Dependency Injection: Depends(get_db), Depends(get_model)         │
  │  (12) Request Validation (Pydantic)                                     │
  │  (13) Your Business Logic: model.predict(input)                         │
  │  (14) Response Serialization (Pydantic → JSON)                          │
  └─────────────────────────────────────────────────────────────────────────┘
       │
       ▼ (15) Response: Worker → Master → Client
```

### 3.1.2 Multi-Worker Architecture

```
                              ┌─────────────────────┐
                              │    External Client  │
                              └──────────┬──────────┘
                                         │ TCP/HTTP(S)
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                         VELO MASTER (Supervisor)                                │
│  • TCP Listener (0.0.0.0:8000)     • Load Balancer                             │
│  • TLS Termination (rustls)        • Health Monitor                            │
│  • HTTP Parsing (hyper)            • Signal Handler (SIGTERM, SIGINT)          │
│                                                                                 │
│              ┌──────────────────────────┼──────────────────────────┐           │
│              │                          │                          │           │
│              ▼                          ▼                          ▼           │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐    │
│  │  WORKER 0 (PID 1001)│  │  WORKER 1 (PID 1002)│  │  WORKER 2 (PID 1003)│    │
│  │  ┌───────────────┐  │  │  ┌───────────────┐  │  │  ┌───────────────┐  │    │
│  │  │ Rust (Tokio)  │  │  │  │ Rust (Tokio)  │  │  │  │ Rust (Tokio)  │  │    │
│  │  └───────┬───────┘  │  │  └───────┬───────┘  │  │  └───────┬───────┘  │    │
│  │          │ PyO3     │  │          │ PyO3     │  │          │ PyO3     │    │
│  │          ▼          │  │          ▼          │  │          ▼          │    │
│  │  ┌───────────────┐  │  │  ┌───────────────┐  │  │  ┌───────────────┐  │    │
│  │  │ Python + GIL  │  │  │  │ Python + GIL  │  │  │  │ Python + GIL  │  │    │
│  │  │ (独立进程)    │  │  │  │ (独立进程)    │  │  │  │ (独立进程)    │  │    │
│  │  └───────┬───────┘  │  │  └───────┬───────┘  │  │  └───────┬───────┘  │    │
│  │          ▼          │  │          ▼          │  │          ▼          │    │
│  │  ┌───────────────┐  │  │  ┌───────────────┐  │  │  ┌───────────────┐  │    │
│  │  │ FastAPI App   │  │  │  │ FastAPI App   │  │  │  │ FastAPI App   │  │    │
│  │  │ (COW Shared)  │  │  │  │ (COW Shared)  │  │  │  │ (COW Shared)  │  │    │
│  │  └───────────────┘  │  │  └───────────────┘  │  │  └───────────────┘  │    │
│  └─────────────────────┘  └─────────────────────┘  └─────────────────────┘    │
│                                                                                 │
│  Memory Layout:                                                                 │
│  ┌─ COW SHARED (Read-Only) ──────────────────────────────────────────────────┐ │
│  │  • Python interpreter (~50MB)  • torch/numpy libraries                    │ │
│  │  • FastAPI/Starlette code      • ML model weights (Zygote pre-load)       │ │
│  └───────────────────────────────────────────────────────────────────────────┘ │
│  ┌─ PRIVATE (Per-Worker) ─────────────────────────────────────────────────────┐│
│  │  • Request/response buffers    • Event loop state    • GIL state          ││
│  └───────────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────┘
```

| Aspect | Description |
|:---|:---|
| **Process Isolation** | Each Worker is a separate process; crash doesn't affect others |
| **Independent GIL** | Each Worker has its own GIL; true parallelism |
| **COW Sharing** | After Zygote fork, memory pages are shared (~50ms cold start) |
| **PyO3 Call** | ~1-5μs latency, no serialization overhead |

### 3.1.3 Zygote + PyO3 Integration Model (Architectural Clarification)

> [!IMPORTANT]
> **Eliminating Ambiguity**: Zygote and PyO3 are **complementary mechanisms** operating at different levels:
> - **Zygote/Fork** = Process-level (creating workers)
> - **PyO3** = Intra-process (Rust↔Python calls within each worker)

#### Lifecycle Stages

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         STAGE 1: ZYGOTE PRE-WARM                            │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Python Interpreter starts                                             │  │
│  │  → import torch, pandas, fastapi (heavy libs)                          │  │
│  │  → Load ML model weights into memory                                   │  │
│  │  → FREEZE: Ready for fork()                                            │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                             fork() COW
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         STAGE 2: WORKER SPAWNING                            │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Velo Master calls fork() N times                                      │  │
│  │  → Each fork creates Worker with COPIED memory (COW)                   │  │
│  │  → Each Worker has: Rust Runtime + Python Interpreter + Loaded Libs    │  │
│  │  → Workers are ISOLATED processes (independent GIL, crash isolation)   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                           per-request
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         STAGE 3: REQUEST HANDLING (PyO3)                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  HTTP Request arrives at Worker                                        │  │
│  │  → Rust (Hyper) parses HTTP                                            │  │
│  │  → PyO3 Direct Call: Rust → Python (SAME PROCESS, ~1-5μs)              │  │
│  │  → Python ASGI App executes                                            │  │
│  │  → PyO3 returns response: Python → Rust                                │  │
│  │  → Rust sends HTTP response                                            │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Why This Works

| Concern | Resolution |
|:---|:---|
| "PyO3 requires same-process" | ✅ Rust and Python ARE in the same process (each Worker) |
| "Zygote uses multi-process" | ✅ Multiple Workers exist; each is a separate process |
| "GIL blocks parallelism" | ✅ Each Worker has its own GIL; N workers = N-way parallelism |
| "Fork copies everything" | ✅ COW ensures only modified pages are copied (memory efficient) |

#### Strategic Dissection Clarification

Velo's "Strategic Dissection" of Granian means:
1. **KEEP**: Granian's L7 engine (HTTP parsing, ASGI state machine, PyO3 bindings)
2. **REPLACE**: Granian's process management with Velo's Zygote/Fork lifecycle
3. **RESULT**: Faster cold-start (~50ms vs 500ms+) while preserving PyO3 performance




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

> [!WARNING]
> **Phase 7.x Legacy**: The RSGI-Velo Protocol above is replaced in Phase 7.2 by direct PyO3 calls.
> See Section 3.5 for the current architecture.

### 3.5 Current: Granian Native Architecture (Phase 7.2)

> [!IMPORTANT]
> This section describes the **current recommended architecture** as of Phase 7.2.

#### 3.5.1 Architecture Evolution

| Phase | IPC Mechanism | Latency | Status |
|:---|:---|:---|:---|
| 7.x | UDS + MessagePack | ~50-100μs | **Legacy** |
| **Phase 7.2** | **PyO3 Direct Call** | **~1-5μs** | **Current** |

#### 3.5.2 Key Benefits

| Aspect | Improvement |
|:---|:---|
| **Latency** | 10-50x faster (no serialization) |
| **Code** | -1300 lines (delete `src/rsgi/`, `velo_zygote/rsgi.py`) |
| **WebSocket** | Native via `tokio-tungstenite` (see RFC-0025) |
| **Maintenance** | Single codebase, not two |

#### 3.5.3 Implementation Requirements

Refer to RFC-0025 Section 6 for blocking conditions:
- **C1**: Zygote Phase Capability Whitelist
- **C2**: Worker Lifecycle State Machine
- **C3**: Granian ABI Freeze Strategy

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
| **Huge Pages (SHM)** | 2MB pages for model weights | ⭐⭐⭐ | Medium |
| **Hot Path Inlining** | `#[inline(always)]` critical paths | ⭐⭐ | Low |
| **Branch Prediction Hints** | `likely()`/`unlikely()` annotations | ⭐ | Low |

#### Zero-Copy Large Body Passing (memfd + mmap)
**Status**: 🟡 CONSIDERATION (Not Committed)

> [!WARNING]
> **Stability-First Principle**: This technology is documented as a research consideration only.
> If stability issues arise during evaluation, it SHOULD NOT be adopted.

**Mechanism**:
```
Rust Host:
  1. memfd_create("body") → fd
  2. mmap(fd) → write body data
  3. SCM_RIGHTS → send fd to worker

Python Worker:
  4. recv fd via SCM_RIGHTS
  5. mmap.mmap(fd) → zero-copy read
  6. Pass to FastAPI as bytes-like
```

**Applicable Scenarios**:
| Body Size | Strategy | Reason |
|:---|:---|:---|
| < 64KB | MessagePack (Phase 7.2) | mmap syscall overhead > copy |
| 64KB - 10MB | **memfd + mmap** | True zero-copy |
| > 10MB | Streaming + mmap | Chunked transfer |

**Stability Concerns**:
| Risk | Description | Mitigation |
|:---|:---|:---|
| **Lifecycle Management** | When to munmap? | Explicit close in `finally` |
| **Python GC** | mmap object dangling | `with` context manager |
| **SCM_RIGHTS Complexity** | fd passing error handling | Fallback to MessagePack |
| **Platform Variance** | macOS vs Linux behavior | Extensive QA testing |

**Adoption Criteria (All MUST be met)**:
1. ✅ Benchmark shows >50% improvement for 1MB+ bodies
2. ✅ Zero stability issues in 4-hour soak test
3. ✅ Fallback path implemented and tested
4. ✅ macOS and Linux both verified


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
| **HTTP/3 (QUIC)** | 🟡 WATCHING | Granian planned, Phase 8.x |
| **WebTransport** | 🔮 RESEARCH | Future real-time applications |

### 8.14 Memory Management Strategy (Stability-First)

> [!IMPORTANT]
> **Core Principle**: Prioritize STABILITY first, then adopt highest-performance mature technologies.
> Rust-internal memory is safe by design; Rust↔Python boundary requires defensive architecture.

#### 8.14.1 Safety Zones

| Zone | Risk Level | Technology Freedom |
|:---|:---|:---|
| **Rust Internal** | 🟢 Low | Full freedom: arenas, pools, ring buffers |
| **Rust↔Python Boundary** | 🔴 High | Defensive: explicit ownership, reference counting |
| **Python Internal** | 🟡 Medium | Managed by GC, minimize allocations |

#### 8.14.2 Rust-Internal Memory (Safe Zone)

These techniques are safe within Rust's ownership model:

| Technique | Crate | Use Case | Phase |
|:---|:---|:---|:---|
| **Buffer Pool** | `object-pool` | Pre-allocated IO buffers | 7.2 |
| **SPSC Ring Buffer** | `rtrb`, `ringbuf` | Lock-free request queuing | 8.x |
| **Memory Arena** | `bumpalo` | Per-request allocations | 8.x |
| **Slab Allocator** | `slab` | Fixed-size worker slots | 8.x |

**Safety Guarantees**:
- Rust's borrow checker prevents use-after-free
- No runtime overhead for memory safety
- Compile-time guarantee of no data races

#### 8.14.3 Rust↔Python Boundary (Danger Zone)

> [!CAUTION]
> This boundary requires explicit defensive design. Memory lifetime crosses language runtimes.

**Potential Hazards**:
| Hazard | Cause | Mitigation |
|:---|:---|:---|
| **Memory Leak** | Python holds Rust reference too long | Timeout + explicit drop |
| **Use-After-Free** | Rust frees while Python holds view | Reference counting via PyO3 |
| **GIL Deadlock** | Rust waits for Python, Python waits for Rust | Async handoff, never block |
| **Double-Free** | Both Rust and Python try to free | Single ownership boundary |

**Defensive Architecture**:
```
┌─────────────────────────────────────────────────────────────┐
│                 Rust (Owns All Memory)                      │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Buffer Pool: [64KB] [64KB] [64KB]                  │    │
│  │  ↓                                                  │    │
│  │  Request arrives → borrow buffer                   │    │
│  │  ↓                                                  │    │
│  │  [BOUNDARY] PyBytes::new(py, &buffer)              │    │  ← View only, Rust owns
│  │  ↓                                                  │    │
│  │  Python processes (read-only view)                 │    │
│  │  ↓                                                  │    │
│  │  Response done → buffer returned to pool           │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

**Boundary Rules**:
1. **Rust Owns, Python Borrows**: All buffers live in Rust; Python receives views only
2. **Explicit Lifetime**: Each request buffer has a bounded lifetime (timeout)
3. **Reference Count Audit**: Log PyO3 reference count at boundary crossing
4. **Panic Boundary**: Rust panics must NOT propagate to Python

#### 8.14.4 Adoption Roadmap

| Technique | Zone | Phase | Priority | Risk |
|:---|:---|:---|:---|:---|
| **Object Pool (buffers)** | Rust | 7.2 | ⭐⭐⭐ | Low |
| **PyBytes views** | Boundary | 7.2 | ⭐⭐⭐ | Medium |
| **SPSC Ring Buffer** | Rust | 8.x | ⭐⭐ | Low |
| **Memory Arena** | Rust | 8.x | ⭐⭐ | Low |
| **Zero-copy mmap** | Boundary | Phase 8.x | ⭐ | High |

#### 8.14.5 Verification Strategy

| Check | Method | Frequency |
|:---|:---|:---|
| **Memory Leak** | Valgrind / ASAN | CI (weekly) |
| **Use-After-Free** | Miri (Rust) | CI (PR) |
| **Reference Count** | PyO3 debug logging | Debug builds |
| **Stress Test** | 10K QPS for 1 hour | Release validation |

### 8.15 Future Optimization Vision: "The Velo Compiler" (Phase 10.x Research)
**Status**: 🔮 RESEARCH ONLY

> [!NOTE]
> **Strategic Goal**: Move beyond interpreter limitations by implementing a "Shadow Compiler" that stabilizes over time.
> **Constraint**: 100% Backward Compatibility. Must run standard Python code (Django, NumPy, Pydantic) without modification.

#### 8.15.1 Velo Shadow Compiler Strategy
Instead of Just-In-Time (JIT) compilation which competes for resources during requests, Velo proposes an **Idle-Time Compiling** strategy.

1.  **Observability First**: Runtime records hot-spot functions and type information during peak traffic.
2.  **Idle-Time Compilation**: When system load drops (or in a background thread), Velo invokes the Shadow Compiler.
3.  **AOT-like Stability**: Compiles hot Python functions into native machine code (or specialized bytecode).
4.  **Persistent Caching**: Compiled artifacts are cached to disk (`~/.velo/cache/v1/`).
5.  **Cold-Start Bonus**: Next restart loads cached native code immediately.

#### 8.15.2 Architecture: The "Safe-Fail" JIT
| Component | Responsibility | Failure Mode |
|:---|:---|:---|
| **Python Interpreter** | Main execution engine | N/A (Baseline) |
| **Shadow Compiler** | Compiles functions to native shared objects | Log error, abort compilation |
| **Hot-Swap Engine** | Replaces PyFunction pointer with NativeFunction | **Fallback to Interpreter** |

> [!IMPORTANT]
> **Stability-First Rule**: If the Shadow Compiler produces code that segfaults or behaves differently, the fallback mechanism MUST instantly revert to the standard Interpreter. The process MUST NOT crash.

#### 8.15.3 Technology Candidates
1.  **Copy-and-Patch JIT** (Python 3.13 strategy) - Likely the winner.
2.  **Cranelift / LLVM** - For heavy numerical computing (Scientific workloads).
3.  **WASM Intermediate** - For sandboxed, safe native execution.

---

## 9. Grand Council Review Summary

**Initial Review**: 2026-01-09 (Phase 7.x UDS Architecture)
**Re-Evaluation**: 2026-01-14 (Phase 7.2 Granian Native Architecture)
**Verdict**: ✅ **APPROVED**

| Persona | Vote | Rationale |
|:---|:---|:---|
| HPC / Runtime Architect | ✅ **STRONG YES** | ~1-5μs latency via PyO3 |
| Security Engineer | ✅ **YES** | Process isolation preserved via fork() |
| Rust Core / Systems | ✅ **YES** | -1300 lines of code |
| Python Runtime Engineer | ✅ **YES** | Standard PyO3 integration |
| CTO | ✅ **YES** | Leverages existing Granian investment |

**P0 Blocking Issues**: C1, C2, C3 (must be satisfied before implementation)

---

## 10. References

- [Granian GitHub](https://github.com/emmett-framework/granian)
- [PyO3 Documentation](https://pyo3.rs/)
- [Zygote Process Model](https://source.android.com/docs/core/runtime)
- [tokio-tungstenite](https://docs.rs/tokio-tungstenite)
- [ASGI Specification](https://asgi.readthedocs.io/)

---

**Last Updated**: 2026-01-14

