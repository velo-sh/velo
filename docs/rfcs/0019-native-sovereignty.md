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

## 7. Strict Security Invariants (RFC-0012/0013 Alignment)
Native Sovereignty establishes a "Zero-Trust" host-worker boundary:
*   **SEC-FS-002 (FD Hygiene)**: The Rust Host performs a mandatory `close_range(3, ~0)` before spawning workers to prevent sensitive FD leakage.
*   **P0-1 (Peer Auth)**: Every UDS connection MUST be verified via `SO_PEERCRED` (Linux) or `getpeereid` (macOS) before the handshake begins.
*   **P0-2 (Taint Contract)**: The Python Worker MUST execute the Taint Re-randomization contract (`random.seed`, `os.urandom`) immediately post-fork and before sending the `READY` message.
*   **Signal Hygiene**: The Host MUST reset the signal mask in `pre_exec` to ensure workers are reachable via standard signals.
