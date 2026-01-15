# RFC-0027: HTTP/2 Support via Granian Integration

**Status**: DRAFT
**Author**: Architect
**Date**: 2026-01-14
**Phase**: 8.x (Future Feature)

## Related Documents

- [RFC-0019: Native Sovereignty](./0019-native-sovereignty.md)
- [RFC-0026: Native TLS via Granian Integration](./0026-native-tls-integration.md)
- [SPEC-0005: SSOT Master Standard](../architecture/SPEC-0005-SSOT-MASTER-STANDARD.md)

---

## 1. Summary

This RFC proposes enabling HTTP/2 support in Velo's RSGI mode by leveraging Granian's existing `HTTP2Config` implementation, enabling connection multiplexing, header compression, and server push.

> [!IMPORTANT]
> **Design Principle**: Granian Core (`vendor/granian/`) already provides production-ready HTTP/2 via `hyper`. We should **integrate, not reinvent**.

---

## 2. Background

### 2.1 Current State

Velo RSGI mode currently:
- Supports HTTP/1.1 only
- Opens new TCP connection per request (no multiplexing)
- No header compression (HPACK)
- No server push capability

### 2.2 HTTP/2 Benefits

| Feature | HTTP/1.1 | HTTP/2 | Impact |
|:---|:---|:---|:---|
| **Multiplexing** | 1 request/conn | Multiple requests/conn | Fewer connections, lower latency |
| **Header Compression** | None | HPACK | 30-50% header size reduction |
| **Server Push** | None | Proactive resource push | Faster page loads |
| **Binary Protocol** | Text-based | Binary framing | More efficient parsing |

### 2.3 Granian's Existing HTTP/2 Capability

Located in `vendor/granian/src/workers.rs`:

```rust
#[derive(Clone)]
pub(crate) struct HTTP2Config {
    pub keep_alive_interval: u64,
    pub keep_alive_timeout: u64,
    pub max_concurrent_streams: u32,
    pub max_frame_size: u32,
    pub max_headers_size: u32,
    pub max_send_buffer_size: usize,
}
```

Additionally, `WorkerConfig` supports:
```rust
http_mode: &str,  // "1", "2", or "auto"
```

---

## 3. Architecture

### 3.1 Protocol Negotiation

```
┌─────────┐          ALPN Negotiation          ┌──────────────┐
│ Client  │ ─────────────────────────────────▶ │  Velo Host   │
│         │   ClientHello: ["h2", "http/1.1"]  │              │
│         │ ◀───────────────────────────────── │              │
│         │   ServerHello: "h2"                │              │
└─────────┘                                    └──────────────┘
                        │
                        ▼
              ┌─────────────────┐
              │   HTTP/2 Conn   │
              │ ┌─────┐ ┌─────┐ │
              │ │ Str1│ │ Str2│ │  Multiplexed Streams
              │ └─────┘ └─────┘ │
              │ ┌─────┐ ┌─────┐ │
              │ │ Str3│ │ Str4│ │
              │ └─────┘ └─────┘ │
              └─────────────────┘
```

### 3.2 Configuration Interface

```toml
# pyproject.toml
[tool.velo.http2]
enabled = true                    # Default: false (Phase 8.x), true (Phase 9.x)
max_concurrent_streams = 100      # Default: 100
max_frame_size = 16384            # Default: 16KB
keep_alive_interval = 30          # Seconds
keep_alive_timeout = 60           # Seconds
```

### 3.3 CLI Interface

```bash
# Enable HTTP/2
velo serve main:app --http2

# With TLS (required for browsers)
velo serve main:app --http2 --tls-cert certs/server.crt --tls-key certs/server.key

# Auto-negotiate (HTTP/1.1 fallback)
velo serve main:app --http-mode auto
```

---

## 4. Implementation Plan

### Phase 8.3: HTTP/2 over TLS (h2)

| Step | File | Change |
|:---|:---|:---|
| 1 | `src/config.rs` | Add HTTP/2 configuration fields |
| 2 | `src/serve/runner.rs` | Configure `hyper` for HTTP/2 mode |
| 3 | `src/serve/runner.rs` | Add ALPN negotiation ("h2", "http/1.1") |
| 4 | `tests/qa/phase_8_3/test_http2.py` | Add HTTP/2 integration tests |

### Phase 8.4: HTTP/2 Cleartext (h2c) - Optional

| Step | File | Change |
|:---|:---|:---|
| 1 | `src/serve/runner.rs` | Support h2c upgrade (non-TLS) |
| 2 | Document as development-only feature | (Not for production) |

---

## 5. Compatibility Matrix

| Protocol | TLS Required | Browser Support | Use Case |
|:---|:---|:---|:---|
| **HTTP/1.1** | ❌ | ✅ All | Legacy, debugging |
| **h2 (HTTP/2 over TLS)** | ✅ | ✅ All modern | Production web |
| **h2c (HTTP/2 Cleartext)** | ❌ | ❌ None | gRPC, internal services |

> [!WARNING]
> **Browser Requirement**: All major browsers (Chrome, Firefox, Safari) require TLS for HTTP/2. RFC-0026 (TLS) is a prerequisite.

---

## 6. Performance Projections

| Scenario | HTTP/1.1 | HTTP/2 | Improvement |
|:---|:---|:---|:---|
| **100 concurrent requests** | 100 TCP connections | 1 TCP connection | 99% fewer connections |
| **Header overhead (typical)** | ~800 bytes/req | ~50 bytes/req | 94% reduction (HPACK) |
| **Time to first byte (RTT)** | 1 RTT + handshake | 0 RTT (multiplexed) | Significant for high-latency |

---

## 7. Security Invariants

| Gate | Requirement | Verification |
|:---|:---|:---|
| **Gate H2** | Enforce max concurrent streams | `test_http2_stream_limit` |
| **Gate H2** | Reject oversized frames | `test_http2_frame_size_limit` |
| **Gate H2** | Handle GOAWAY gracefully | `test_http2_goaway` |

---

## 8. ASGI Compatibility

HTTP/2 is transparent to ASGI applications:

```python
# This works identically on HTTP/1.1 and HTTP/2
async def app(scope, receive, send):
    assert scope["type"] == "http"
    # HTTP/2 specific info available via:
    # scope.get("http_version") -> "2"
```

The RSGI Host handles protocol differences internally.

---

## 9. Grand Council Review Summary

**Date**: 2026-01-14
**Verdict**: ✅ **PRE-APPROVED (Phase 8.x)**

| Persona | Vote | Rationale |
|:---|:---|:---|
| HPC Engineer | ✅ | Multiplexing reduces head-of-line blocking |
| Network SRE | ✅ | Fewer connections = easier to manage at scale |
| Security Engineer | ✅ | ALPN enforces TLS; no security regression |
| CTO | ✅ | Enterprise feature; differentiator from competitors |

**P0 Blocking Issues**: None

**Dependency**: RFC-0026 (Native TLS) must be implemented first for browser compatibility.

---

## 10. References

- [HTTP/2 RFC 7540](https://tools.ietf.org/html/rfc7540)
- [HPACK RFC 7541](https://tools.ietf.org/html/rfc7541)
- [hyper HTTP/2 Support](https://docs.rs/hyper/latest/hyper/)
- [Granian HTTP2Config Source](../../vendor/granian/src/workers.rs)

---

**Last Updated**: 2026-01-14
