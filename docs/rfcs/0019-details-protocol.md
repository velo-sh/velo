# Protocol Design: RFC-0019 (Native Sovereignty)

This document specifies the binary interaction protocol (RSGI-Velo) used between the Rust Master Host and the Python Workers.

## 1. Handshake Protocol (MessagePack)

The handshake ensures that the Worker is ready to receive requests and supports the host's required features.

### 1.1 Worker `READY` Message
Sent by the Python worker immediately after startup and **Taint Re-randomization** (RFC-0013).

```yaml
type: "READY"
version: "1.0.0" (Granian-compatible)
capabilities:
  streaming: true
  fd_passing: true
  protocols: ["rsgi/1.0", "asgi/3.0"]
  marshall_hints: ["zero_copy_views", "msgpack_native"]
worker_id: "worker-{pid}"
```

### 1.2 Host `AUTH_OK` Message
Sent by the Rust host to acknowledge the worker.

```yaml
type: "AUTH_OK"
session_id: "v-83ff"
max_request_size: 10485760 # 10MB
```

---

## 2. Request/Response Framing

### 2.1 Request Start (`REQ_START`)
```python
# MessagePack Structure
[
  0x01,         # Type ID
  request_id,   # u64
  method,       # String ("GET", "POST", etc.)
  path,         # String
  headers,      # List of (String, String) pairs
  has_body      # Boolean
]
```

### 2.2 Response Start (`RES_START`)
```python
# MessagePack Structure
[
  0x03,         # Type ID
  request_id,   # u64
  status_code,  # u16
  headers       # List of (String, String) pairs
]
```

---

## 3. FD Passing Specification (Performance)

To eliminate the overhead of socket creation for every worker-host link, Velo uses `SCM_RIGHTS`.

1.  **Rust Side**: Pre-binds a pair of UDS sockets using `socketpair(2)`.
2.  **Passing**: The Host passes the worker-end of the pair as **File Descriptor 3** (inherited) or via `sendmsg` if using a persistent control link.
3.  **Python Side**: Workers use `socket.fromfd(3, socket.AF_UNIX, socket.SOCK_STREAM)` to instantly connect back to the host's data plane.

---

## 4. Architectural Quality Gates

### Security Gates
*   **Gate D (Protocol)**: Any MessagePack payload > 1MB MUST be rejected unless explicitly negotiated.
*   **Gate F (Security)**: All UDS paths MUST reside in a `0o700` restricted directory created via `mkdtemp`.
*   **Gate G (Atomic IPC) [REMEDIATED SEC-07-001]**: On Linux, the Host and Worker MUST communicate via **Abstract Namespace Sockets**.
*   **Gate H (Peer Auth) [RFC-0019 MANDATORY]**: The Host MUST perform **Peer Authentication** (`SO_PEERCRED` / `getpeereid`) on the RSGI link. Handshake MUST NOT proceed if the peer UID/PID does not match the launched worker.

### Lifecycle Gates
*   **Gate E (Lifecycle)**: A worker that doesn't send `READY` within 500ms MUST be SIGKILL'd.
*   **Gate J (Signal Hygiene) [Cloud Native Expert]**: SIGTERM received by Host MUST be translated to `{"type": "lifespan.shutdown"}` and sent to all Workers via RSGI. Workers MUST complete in-flight requests before exiting.

### Performance Gates (HPC Engineer Recommendations)
*   **Gate I (Marshalling Efficiency)**: Payloads arriving via Granian-core MUST use `PyBytes` views in `conversion.rs` to ensure **True Zero-Copy** delivery to the Python stack.
*   **Gate K (Rust-Side Encoding) [MANDATORY]**: All MessagePack encoding MUST happen in Rust (`rmp_serde::to_vec`). Python receives bytes via UDS and decodes locally.
*   **Gate L (GIL Minimization)**: HTTP parsing, TLS termination, and protocol framing MUST execute entirely in Rust (zero GIL). GIL acquisition is ONLY permitted for ASGI dispatch and user code execution.

### Runtime Integration Gates (Rust Core Dev Recommendations)
*   **Gate M (Tokio Runtime Sharing) [P1 CRITICAL]**: Velo MUST pass its global `tokio::Runtime` to Granian Core. Granian MUST NOT create its own Runtime. Violation causes thread pool explosion.
*   **Gate N (Executor Boundary)**: Granian's async Python bridge MUST use the provided Velo Runtime for all IO operations. Blocking Python code MUST be offloaded via `tokio::task::spawn_blocking`.

---

## 5. Hybrid Serialization Strategy (Phase 7.2)

> [!IMPORTANT]
> Due to Velo's multi-process architecture (Rust Host ↔ UDS ↔ Python Worker), PyO3 direct object passing is NOT possible. This section defines the hybrid strategy for optimal performance.

### 5.1 Request Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│  Rust Host (PID 1)                                              │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  1. HTTP bytes arrive (Hyper)                               ││
│  │  2. rmp_serde::to_vec() → MessagePack bytes                ││  ← rmp-serde
│  │  3. UDS send(bytes)                                        ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                            │ UDS (bytes)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Python Worker (PID 2)                                          │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  4. socket.recv() → raw bytes                              ││
│  │  5. memoryview(bytes) → zero-copy slice                    ││  ← memoryview
│  │  6. msgpack.unpackb(view) → dict                           ││
│  │  7. sys.intern(header_name) → cached string                ││  ← sys.intern
│  │  8. Pass to FastAPI                                        ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Technology Responsibilities

| Technology | Location | Stage | Purpose |
|:---|:---|:---|:---|
| **rmp-serde** | Rust | Encoding | Compact binary, fast serialization |
| **memoryview** | Python | Receiving | Avoid bytes slice copy |
| **sys.intern** | Python | Processing | Cache common strings (headers) |

### 5.3 Python Worker Reference Implementation

```python
import msgpack
import sys

def process_request(raw_bytes: bytes) -> tuple:
    # 1. memoryview: avoid slice copy
    view = memoryview(raw_bytes)
    
    # 2. Decode MessagePack (raw=False returns str directly)
    request = msgpack.unpackb(view, raw=False, use_list=False)
    
    # 3. sys.intern: cache common header names
    headers = {
        sys.intern(k): v 
        for k, v in request["headers"]
    }
    
    return request["method"], request["path"], headers
```

### 5.4 Optimization Notes

| Optimization | Benefit | Notes |
|:---|:---|:---|
| `raw=False` | Skip manual `.decode()` | msgpack returns str directly |
| `use_list=False` | Return tuple instead of list | Immutable, slightly faster |
| `sys.intern(k)` only | Intern header names, not values | Values are user data |

### 5.5 Quality Gates

*   **Gate O (Hybrid Strategy) [Phase 7.2 MANDATORY]**: All three techniques (`rmp-serde`, `memoryview`, `sys.intern`) MUST be implemented in Phase 7.2.
*   **Gate P (String Interning)**: Only HTTP header NAMES may be interned. Header VALUES and body content MUST NOT be interned (security + memory).
