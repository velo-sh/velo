# RFC-0025: WebSocket Support

**Status**: APPROVED
**Author**: Architect
**Date**: 2026-01-14
**Phase**: Current (Part of Granian Native Runtime)

## Related Documents

- [RFC-0019: Native Sovereignty - Granian Architecture](./0019-native-sovereignty.md) ← **Main Architecture**
- [Granian WebSocket Source](../../vendor/granian/src/ws.rs)

---

## 1. Summary

This RFC specifies WebSocket support in Velo's Granian-native runtime.

WebSocket is automatically available when using the Granian Worker architecture defined in RFC-0019. This document covers WebSocket-specific configuration and verification.

---

## 2. Granian WebSocket Components

| Component | Location | Capability |
|:---|:---|:---|
| `HyperWebsocket` | `vendor/granian/src/ws.rs` | Rust-native WS upgrade via `tokio-tungstenite` |
| `RSGIWebsocketTransport` | `vendor/granian/src/rsgi/io.rs` | PyO3-bound `receive()/send_bytes()/send_str()` |
| `websockets_enabled` | `vendor/granian/src/rsgi/serve.rs` | Configuration flag |

---

## 3. Architecture

```
┌─────────┐      WS Upgrade      ┌──────────────────────────────────┐
│ Client  │ ─────────────────▶   │     Granian Worker (Rust)        │
│         │ ◀───────────────────│                                  │
└─────────┘                      │  ┌─────────────────────────────┐ │
           WS frames             │  │  tokio-tungstenite          │ │
           (binary)              │  │  ┌───────────────────────┐  │ │
                                 │  │  │   PyO3 Callbacks      │  │ │
                                 │  │  │   RSGIWebsocketTransport │ │
                                 │  │  └───────────────────────┘  │ │
                                 │  └─────────────────────────────┘ │
                                 │               ▲                  │
                                 │               │ Direct Call      │
                                 │               ▼                  │
                                 │  ┌─────────────────────────────┐ │
                                 │  │   Python ASGI App           │ │
                                 │  │   scope["type"] = "websocket"│ │
                                 │  └─────────────────────────────┘ │
                                 └──────────────────────────────────┘
```

---

## 4. Performance

| Metric | Latency |
|:---|:---|
| WS Upgrade Handshake | ~10-20μs |
| WS Frame (text/binary) | **~1-5μs** |
| WS Close | ~5-10μs |

---

## 5. ASGI WebSocket Interface

### 5.1 Scope

```python
{
    "type": "websocket",
    "asgi": {"version": "3.0", "spec_version": "2.3"},
    "http_version": "1.1",
    "scheme": "ws",  # or "wss"
    "path": "/ws",
    "query_string": b"",
    "headers": [...],
    "subprotocols": ["graphql-ws"],  # if requested
}
```

### 5.2 Events

| Event | Direction | Description |
|:---|:---|:---|
| `websocket.connect` | receive | Client initiated connection |
| `websocket.accept` | send | Server accepts connection |
| `websocket.receive` | receive | Message from client |
| `websocket.send` | send | Message to client |
| `websocket.disconnect` | receive | Client disconnected |
| `websocket.close` | send | Server closes connection |

---

## 6. Example Usage

### FastAPI

```python
from fastapi import FastAPI, WebSocket

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Echo: {data}")
```

### Starlette

```python
from starlette.websockets import WebSocket

async def websocket_route(websocket: WebSocket):
    await websocket.accept()
    async for message in websocket.iter_text():
        await websocket.send_text(f"Echo: {message}")
```

---

## 7. Security Invariants

| Gate | Requirement | Verification |
|:---|:---|:---|
| **Gate H** | Worker process isolation | `test_ws_process_isolation` |
| **Gate E** | WS handshake timeout (500ms) | `test_ws_handshake_timeout` |
| **Gate P** | Origin validation (if configured) | `test_ws_origin_check` |

---

## 8. Verification Tests

```bash
# Run WebSocket integration tests
pytest tests/qa/phase_9/test_websocket.py -v
```

### Test Cases

- [ ] `test_ws_echo` - Basic echo test
- [ ] `test_ws_binary` - Binary message support
- [ ] `test_ws_subprotocol` - Subprotocol negotiation
- [ ] `test_ws_close_code` - Close code propagation
- [ ] `test_ws_max_connections` - Connection limit enforcement

---

## 9. Configuration

```toml
# pyproject.toml
[tool.velo.websocket]
max_connections = 1000          # Maximum concurrent WS connections
handshake_timeout_ms = 500      # Handshake timeout
ping_interval_secs = 30         # Keep-alive ping interval
max_message_size_bytes = 65536  # Maximum message size (64KB)
```

---

## 10. References

- [WebSocket RFC 6455](https://tools.ietf.org/html/rfc6455)
- [ASGI WebSocket Spec](https://asgi.readthedocs.io/en/latest/specs/www.html#websocket)
- [tokio-tungstenite](https://docs.rs/tokio-tungstenite)

---

**Last Updated**: 2026-01-14
