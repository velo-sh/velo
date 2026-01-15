# Native RSGI Compatibility & Best Practices Guide

This guide documents the integration requirements, performance optimizations, and best practices for running Python applications on the Velo Native RSGI runtime (Phase 7.2+).

## 🚀 The Native Advantage
Velo Native leverages PyO3 for in-process communication between Rust and Python, eliminating the overhead of UDS/MessagePack and reaching sub-5μs bridge latency.

## 🏁 Compatibility Matrix

| Component | Status | Recommendation |
|-----------|--------|----------------|
| **FastAPI** | ✅ Full | Use FastAPI 0.115.0+ |
| **Starlette** | ✅ Full | Use Starlette 0.40.0+ |
| **Django (ASGI)** | ✅ Full | Supported via unified bridge |
| **WebSockets** | ✅ RFC-0025 | Native binary/text frame support |
| **POST Body** | ✅ 1MB+ | Verified for JSON/Form/Binary |
| **WSGI (Flask)** | 🔴 Not Supported | Planned for Phase 8.0 |

## 💡 Best Practices

### 1. Adopt the Native Signature
For maximum performance, write your applications to target the native RSGI signature directly:
```python
async def app(scope, proto):
    # Direct access to Rust objects
    await proto.response_start(200, [("content-type", "text/plain")])
    await proto.response_body(b"Hello from Velo Native")
```

### 2. Header Hygiene
Velo implements industrial-grade security limits for headers. 
- **Recommendation**: Keep header blocks under 16KB and avoid sending 100+ tiny headers.
- **Security Interception**: Velo will correctly return `431 Request Header Fields Too Large` to prevent resource exhaustion attacks.

### 3. Protocol Isolation (Starvation Prevention)
During extreme "mixed protocol storms" (e.g., hundreds of concurrent WebSocket handshakes vs. HTTP), internal context switching may lead to HTTP starvation.
- **Recommendation**: For mission-critical high-frequency WebSocket apps, isolate them in a dedicated worker pool using Velo's worker labels.

### 4. Zygote Utilization
Always use Zygote for industrial deployments.
- **Benefit**: Provides robust worker isolation, Copy-on-Write (COW) memory efficiency, and rapid signal re-entry resilience.

## 🛡️ Security Certification
Velo has been verified against:
- **Header Flood**: Blocked with 431.
- **Body Overflow**: Limits enforced at Rust level.
- **Signal DOS**: Isolation maintained during signal storms.

---
**Version:** 1.0 (Phase 7.2 Certified)
**Date:** 2026-01-15
