# RFC-0025: WebSocket Support Architecture

**Status**: DRAFT  
**Author**: Architect  
**Date**: 2026-01-14  
**Phase**: 7.2 → 8.x (Multi-Phase Feature)

## Related Documents

- [RFC-0019: Native Sovereignty](./0019-native-sovereignty.md)
- [RFC-0024: Forensic Compatibility Specification](./0024-forensic-compatibility-specification.md)
- [SPEC-0005: SSOT Master Standard](../architecture/SPEC-0005-SSOT-MASTER-STANDARD.md)

---

## 1. Summary

This RFC defines the architecture for WebSocket support in Velo's RSGI (Native Sovereignty) mode. It documents the architectural decision between **Protocol Tunneling** and **Direct FD Passthrough**, with a detailed analysis of trade-offs.

---

## 2. Background

### 2.1 Current State

RSGI mode currently returns `501 Not Implemented` for WebSocket upgrade requests:

```rust
// src/rsgi/host.rs:230-239
if is_websocket {
    return Ok(Response::builder()
        .status(hyper::StatusCode::NOT_IMPLEMENTED)
        .body(Full::new(Bytes::from("WebSockets not yet supported in RSGI mode")))
        .unwrap());
}
```

### 2.2 Requirements (RFC-0024 P0)

WebSocket support is classified as **P0 Critical** in RFC-0024:

> *"[P0] WebSockets (Tunnelling): Full lifecycle verification of `connect`, `receive`, `send`, and `disconnect`. Focus: Successful handshake hijacking and bidirectional stream persistence."*

---

## 3. Architecture Options

### 3.1 Option A: Protocol Tunneling (SELECTED ✅)

**Concept**: The Rust Host handles all WebSocket protocol details (HTTP upgrade, frame parsing). Parsed frames are forwarded to Python workers via the existing UDS protocol as MessagePack messages.

```
┌─────────┐      TCP/WS       ┌──────────────┐      UDS Messages      ┌──────────────┐
│ Client  │ ───────────────▶  │  Rust Host   │ ────────────────────▶  │ Python Worker│
│         │ ◀─────────────── │ (owns socket)│ ◀──────────────────── │ (ASGI app)   │
└─────────┘                   └──────────────┘                        └──────────────┘
           WS frames                          [WS_RECV, id, "hello"]
           (binary)                           [WS_SEND, id, "Echo: hello"]
```

#### 3.1.1 Protocol Extension

New message types in `src/rsgi/protocol.rs`:

| Type ID | Name | Direction | Purpose |
|---------|------|-----------|---------|
| `0x30` | `WS_HANDSHAKE` | Host → Worker | Notify WebSocket upgrade detected |
| `0x31` | `WS_ACCEPT` | Worker → Host | Accept/reject connection |
| `0x32` | `WS_RECV` | Host → Worker | Forward received frame |
| `0x33` | `WS_SEND` | Worker → Host | Send frame to client |
| `0x34` | `WS_CLOSE` | Both | Close connection |

#### 3.1.2 Message Flow

```
Client                    Rust Host                   Python Worker
  │                           │                            │
  │──── GET /ws ────────────▶│                            │
  │     Upgrade: websocket    │                            │
  │                           │                            │
  │                           │── WS_HANDSHAKE ──────────▶│
  │                           │   [0x30, id, path, headers]│
  │                           │                            │
  │                           │                            │── app(scope, receive, send)
  │                           │                            │   scope["type"] = "websocket"
  │                           │                            │
  │                           │◀── WS_ACCEPT ─────────────│
  │                           │   [0x31, id, true, subproto]
  │                           │                            │
  │◀─── 101 Switching ────────│                            │
  │     Protocols             │                            │
  │                           │                            │
  │──── WS Frame ────────────▶│                            │
  │     "hello"               │                            │
  │                           │── WS_RECV ───────────────▶│
  │                           │   [0x32, id, TEXT, "hello"]│
  │                           │                            │
  │                           │◀── WS_SEND ───────────────│
  │                           │   [0x33, id, TEXT, "Echo"] │
  │◀─── WS Frame ─────────────│                            │
  │     "Echo: hello"         │                            │
  │                           │                            │
  │──── Close Frame ─────────▶│                            │
  │                           │── WS_CLOSE ──────────────▶│
  │                           │   [0x34, id, 1000, ""]     │
  │                           │                            │
```

#### 3.1.3 Advantages

1. **Sovereignty Preserved**: Rust Host maintains full control of external connections
2. **Operational Control**: Host can enforce timeouts, rate limits, connection caps
3. **Observability**: All WS traffic flows through Host, enabling logging/metrics
4. **Simplicity**: Python Worker uses standard ASGI `receive()/send()` callbacks
5. **Platform Agnostic**: No `SCM_RIGHTS` dependency

#### 3.1.4 Disadvantages

1. **Latency Overhead**: ~100-200μs per frame (MessagePack encode/decode + UDS I/O)
2. **Memory Copy**: Each frame is copied twice (client→Host, Host→Worker)

---

### 3.2 Option B: Direct FD Passthrough

**Concept**: After WebSocket upgrade, the Rust Host passes the raw socket file descriptor to Python via `SCM_RIGHTS`. Python then handles WebSocket framing directly.

```
┌─────────┐      TCP/WS       ┌──────────────┐      SCM_RIGHTS        ┌──────────────┐
│ Client  │ ───────────────▶  │  Rust Host   │ ───────(FD)─────────▶  │ Python Worker│
│         │ ◀─────────────── │ (gives up)   │                        │ (owns socket)│
└─────────┘                   └──────────────┘                        └──────────────┘
           WS frames                                                    socket.fromfd()
           (binary)                                                     Direct WS I/O
```

#### 3.2.1 SCM_RIGHTS Mechanism

Unix domain sockets support passing file descriptors between processes:

```c
// Rust side (sender)
struct cmsghdr cmsg = {
    .cmsg_level = SOL_SOCKET,
    .cmsg_type = SCM_RIGHTS,
    .cmsg_len = CMSG_LEN(sizeof(int)),
};
*((int*)CMSG_DATA(&cmsg)) = client_socket_fd;
sendmsg(worker_uds_fd, &msg, 0);
```

```python
# Python side (receiver)
import socket
fds = socket.recv_fds(worker_uds, maxfds=1)
client_fd = fds[0]
client_socket = socket.fromfd(client_fd, socket.AF_INET, socket.SOCK_STREAM)
```

#### 3.2.2 Advantages

1. **Near-Zero Latency**: ~1-5μs per frame (direct socket I/O)
2. **Zero Copy**: Frames go directly from kernel to Python
3. **Full WebSocket Library Support**: Can use `websockets` or `wsproto` directly

#### 3.2.3 Disadvantages

1. **Sovereignty Violation**: Python owns the socket; Host loses control
2. **Ownership Complexity**: Double-close race conditions possible
3. **Platform Dependent**: 
   - ✅ Linux: Full `SCM_RIGHTS` support
   - ⚠️ macOS: Works with `F_GETNOSIGPIPE` caveats
   - ❌ Windows: Not supported
4. **Lifecycle Management**: Host cannot force-close hung connections
5. **Hyper Complexity**: Extracting raw FD from `hyper::upgrade::Upgraded` is non-trivial

#### 3.2.4 Technical Challenges

##### Challenge 1: Ownership Transfer is Irreversible

```rust
// After passing FD, Rust CANNOT:
socket.shutdown(Shutdown::Both)?;  // Error: fd no longer owned

// Only option to kill stuck connection: SIGKILL the worker
```

##### Challenge 2: Double-Close Race

```
Timeline:
T0: Rust passes FD to Python
T1: Python creates socket.fromfd(fd)
T2: Rust's original fd goes out of scope → auto-close()?
T3: Python tries to use socket → "Bad file descriptor"
```

##### Challenge 3: Python Event Loop Integration

```python
# socket.fromfd() creates BLOCKING socket
client_sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)

# Must explicitly make non-blocking
client_sock.setblocking(False)

# Then integrate with asyncio
reader, writer = await asyncio.open_connection(sock=client_sock)
```

---

## 4. Decision Matrix

| Criteria | Protocol Tunneling | FD Passthrough |
|----------|-------------------|----------------|
| **Sovereignty** | ✅ Preserved | ❌ Violated |
| **Latency** | ~100-200μs | ~1-5μs |
| **Implementation Complexity** | Low | High |
| **Host Control** | ✅ Full | ❌ None |
| **Debug/Logging** | ✅ At Host | ❌ Must instrument Python |
| **Platform Support** | ✅ Universal | ⚠️ Unix-only |
| **ASGI Compatibility** | ✅ Native | ⚠️ Requires wrapping |

---

## 5. Use Case Analysis

| Use Case | Protocol Tunneling | FD Passthrough | Recommendation |
|----------|-------------------|----------------|----------------|
| Chat applications | ✅ Perfect | Overkill | Tunneling |
| Push notifications | ✅ Perfect | Overkill | Tunneling |
| Real-time dashboards | ✅ Perfect | Overkill | Tunneling |
| Collaborative editing | ✅ Good | Better | Tunneling |
| Multiplayer games | ⚠️ Latency visible | ✅ Better | Passthrough |
| Financial trading | ❌ Too slow | ✅ Required | Passthrough |
| Video conferencing | ⚠️ Maybe | ✅ Better | Passthrough |

**Conclusion**: Protocol Tunneling covers **99% of use cases**. FD Passthrough is only beneficial for sub-millisecond latency requirements.

---

## 6. Implementation Plan

### Phase 7.2: Protocol Tunneling (Current)

1. Add WebSocket message types to `protocol.rs` ✅
2. Implement `handle_websocket()` in `host.rs`
3. Add WebSocket scope handling in `rsgi.py`
4. Integration tests with FastAPI WebSocket

### Phase 8.x: FD Passthrough (Future Enhancement)

1. Add `X-Velo-WS-Mode: passthrough` header detection
2. Implement `SCM_RIGHTS` FD passing in Rust
3. Add `socket.recv_fds()` handling in Python
4. Document as opt-in for power users

### Configuration (Future)

```toml
# pyproject.toml
[tool.velo.websocket]
mode = "tunnel"  # default, or "passthrough"
```

---

## 7. Grand Council Review Summary

**Date**: 2026-01-14  
**Verdict**: ✅ APPROVED (Protocol Tunneling)

| Persona | Vote | Rationale |
|---------|------|-----------|
| Security Engineer | ✅ Tunneling | Preserves sovereignty boundary |
| Rust Core Dev | ✅ Tunneling | Avoids FD lifecycle complexity |
| Python Core Dev | ✅ Tunneling | ASGI interface fits naturally |
| HPC Engineer | ✅ Tunneling | 100μs acceptable for target use cases |
| Network SRE | ✅ Tunneling | Maintains operational control |

**P0 Blocking Issues**: None

---

## 8. References

- [WebSocket RFC 6455](https://tools.ietf.org/html/rfc6455)
- [ASGI WebSocket Spec](https://asgi.readthedocs.io/en/latest/specs/www.html#websocket)
- [SCM_RIGHTS man page](https://man7.org/linux/man-pages/man7/unix.7.html)
- [Granian WebSocket Implementation](../../vendor/granian/src/ws.rs)

---

**Last Updated**: 2026-01-14
