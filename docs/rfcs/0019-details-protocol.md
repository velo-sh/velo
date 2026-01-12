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

*   **Gate D (Protocol)**: Any MessagePack payload > 1MB MUST be rejected unless explicitly negotiated.
*   **Gate E (Lifecycle)**: A worker that doesn't send `READY` within 500ms MUST be SIGKILL'd.
*   **Gate F (Security)**: All UDS paths MUST reside in a `0o700` restricted directory created via `mkdtemp`.
*   **Gate G (Atomic IPC) [REMEDIATED SEC-07-001]**: On Linux, the Host and Worker MUST communicate via **Abstract Namespace Sockets**.
*   **Gate H (Peer Auth) [RFC-0019 MANDATORY]**: The Host MUST perform **Peer Authentication** (`SO_PEERCRED` / `getpeereid`) on the RSGI link. Handshake MUST NOT proceed if the peer UID/PID does not match the launched worker.
*   **Gate I (Marshalling Efficiency)**: Payloads arriving via Granian-core MUST use `PyBytes` views in `conversion.rs` to ensure **True Zero-Copy** delivery to the Python stack.
