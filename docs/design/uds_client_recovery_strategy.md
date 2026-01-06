# UDS Client Recovery & Resiliency Strategy

> **RFC**: [RFC-0011: Zygote Worker Integration](../implementation/rfc_master_record.md)  
> **Status**: Approved Strategy
> **Scope**: Client-side behavior when interacting with Velo L7 Proxy and Zygote Workers.

## 1. Overview

Velo's Layer 7 Proxy acts as the entry point for all client traffic in Zygote mode. It balances traffic across multiple UDS (Unix Domain Socket) connected workers. Resilience is built into the proxy to handle worker failures, zygote restarts, and socket disconnects without disrupting the client experience whenever possible.

## 2. Failure Scenarios & Recovery

### 2.1 Worker Process Crash (Unix Signal)
**Scenario**: A worker process dies (e.g., OOM, segfault) while processing a request or idle.
**Detection**:
- **Idle**: `LoadBalancer` health check (deep health check) detects dead socket connection.
- **Active**: Hyper client receives `BrokenPipe` or `ConnectionReset` on UDS IO.
**Recovery**:
- Proxy: Returns `502 Bad Gateway` to client immediately if request was in-flight (non-idempotent).
- Load Balancer: Removes worker from `Healthy` pool.
- Zygote: Automatically reaps zombie process and spawns replacement (managed by `WorkerManager`).
- **Client Action**: Safe to retry idempotent requests (GET/HEAD). Non-idempotent (POST/PUT) should be retried with caution.

### 2.2 Worker Socket Unreachable (Connection Refused)
**Scenario**: Load Balancer attempts to route to a worker that is technically "up" but UDS backlog is full or socket file is missing.
**Recovery**:
- Proxy: Tries next healthy worker in the pool (Round Robin / Least Conns).
- **Client Action**: Transparent to client. If all workers fail, returns `503 Service Unavailable`.

### 2.3 Zygote Restarts
**Scenario**: The main Zygote process is restarted (e.g., deployment, config change).
**Impact**:
- All existing worker UDS sockets become invalid.
- New Zygote spawns new workers with *new* socket paths (different versions/IDs).
**Recovery**:
- **Velo**: `Runner` detects Zygote exit/restart.
- **Proxy**: Re-initializes `LoadBalancer` with new socket list once Zygote is ready.
- **Traffic**: During the gap (approx. 100-500ms), requests may fail with 503.
- **Client Action**: Implement exponential backoff retry.
  - Suggestion: Initial backoff 100ms, max 2s, jitter +/- 20%.

## 3. Error Codes Reference

| HTTP Code | Velo Internal Code | Description | Client Action |
|-----------|--------------------|-------------|---------------|
| **502** | `UpstreamConnectionFailed` | Worker connected but dropped connection. | Retry if idempotent. Check server logs. |
| **502** | `UpstreamFrameError` | Malformed HTTP response from worker. | Do not retry. Bug in worker app. |
| **503** | `NoHealthyWorkers` | All workers down or failing health checks. | Retry with backoff. Alert Ops. |
| **504** | `UpstreamTimeout` | Worker took >30s (default) to respond. | Do not retry immediately. |

## 4. Connection Pooling Reconnection

Hyper's `Client` maintains a connection pool to UDS workers.
- **Idle Timeout**: Connections open > 90s are closed.
- **Max Life**: Connections older than 1hr are cycled.
- **Disconnect**: If a pooled connection is found dead upon reuse, Hyper automatically attempts to open a *new* connection to the same worker (or load balancer picks new worker).

## 5. Client Library Guidelines (scope[client])

Clients connecting to Velo Serve should:
1. **Enable Keep-Alive**: Reuse TCP connections to the Proxy.
2. **Handle 503**: Treat as temporary unavailability (e.g., startup/deployment gap).
3. **Trace Context**: Propagate `traceparent` header if participating in distributed tracing.

---
*Derived from: docs/uds-client-recovery.md (2026-01-05).*
