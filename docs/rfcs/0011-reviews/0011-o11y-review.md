# RFC-0011 Observability / OpenTelemetry Review

> **Status**: ✅ PASS with Mandatory Context Propagation  
> **Parent**: [RFC-0011](../0011-zygote-worker-integration.md)

---

## Critical Requirements

### 🔴 W3C Trace Context Propagation

Rust must Extract → Inject `traceparent` header.

### 🔴 X-Request-ID Correlation

- Rust generates UUID
- Inject into UDS request
- Python logs with same ID

### Metrics

| Metric | Source | Labels |
|--------|--------|--------|
| `velo_request_duration_seconds` | Rust | status, method |
| `velo_worker_queue_depth` | Rust | - |
| `http_server_duration_seconds` | Python | route, method |

**Anti-pattern**: Don't record raw URL path in Rust → Cardinality explosion!

---

**O11y Sign-off**: ✅ Approved
