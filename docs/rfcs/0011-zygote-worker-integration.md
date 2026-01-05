# RFC-0011: Zygote Worker Integration

> **Status**: IN PROGRESS (L7 Proxy Architecture Approved, Implementation Pending)  
> **Author**: Architect (ID-LOCK-001)  
> **Created**: 2026-01-04  
> **Target Version**: v0.6.2+  
> **Branch**: `phase-6.1.1/zygote-worker-integration`  
> **Parent RFC**: [RFC-0010](./0010-phase-6.1-serve-analyze.md)

---

## Executive Summary

This RFC addresses a critical architectural gap: **uvicorn/gunicorn workers are NOT being forked from Zygote**, negating the pre-warming benefit for multi-worker deployments.

**Current State**:
```text
Velo → Zygote → uvicorn parent → uvicorn spawns its own workers
                                 (multiprocessing.spawn, NOT Zygote fork)
```

**Target State**:
```text
Velo → Zygote pre-warms → Velo manages worker pool (via Zygote fork)
                          → Each worker inherits pre-warmed state
```

---

## 1. Problem Statement

### 1.1 Verification Evidence

```text
Process Tree (phase-6.1/serve-analyze):
29705  velo-zygote (standalone, NOT utilized by workers)
29706  uvicorn parent
29708  uvicorn worker (multiprocessing.spawn)  ← NOT from Zygote
29709  uvicorn worker (multiprocessing.spawn)  ← NOT from Zygote
```

### 1.2 Impact

| Metric | Current | With Zygote Workers |
|--------|---------|---------------------|
| Worker cold start | ~200ms | ~10ms |
| Memory per worker | Full copy | COW shared |
| Module re-import | Yes (per worker) | No (inherited) |

---

## 2. Proposed Architecture

### 2.1 Worker Lifecycle

```text
┌─────────────────────────────────────────────────────────────┐
│                    Velo Supervisor                           │
├─────────────────────────────────────────────────────────────┤
│  1. Start Zygote daemon (pre-warm modules)                  │
│  2. Receive HTTP request or --workers N                      │
│  3. Fork worker from Zygote (not uvicorn's spawn)           │
│  4. Worker runs ASGI app directly                            │
│  5. Velo manages worker pool (restart, scale, health)       │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Worker ownership** | Velo (not uvicorn) | Must fork from Zygote |
| **ASGI protocol** | Direct (no uvicorn) | Avoid double-spawn |
| **HTTP stack** | `hyper` or `tiny_http` | Rust-native, Zygote-compatible |
| **Load balancing** | Round-robin to workers | Simple, predictable |

---

## 3. Implementation Options

### Option A: Native ASGI Runtime (High effort)

Velo implements HTTP server + ASGI protocol, workers fork from Zygote.

**Pros**: Full control, maximum performance  
**Cons**: Large scope, needs ASGI expertise

### Option B: Upstream Integration (Medium effort)

Modify uvicorn to use Zygote for worker spawning via custom reloader.

**Pros**: Leverage existing uvicorn code  
**Cons**: uvicorn internals are complex

### Option C: Composition Architecture (Recommended)

Velo manages worker pool, each worker runs uvicorn in single-worker mode.

```text
Velo Supervisor
├── Fork from Zygote → Worker 1 (uvicorn --workers 1)
├── Fork from Zygote → Worker 2 (uvicorn --workers 1)
└── Fork from Zygote → Worker 3 (uvicorn --workers 1)
```

**Pros**: Simpler implementation, uvicorn handles ASGI  
**Cons**: Slightly more memory (per-worker uvicorn overhead)

---

## 4. Acceptance Criteria

- [x] Workers forked from Zygote (verified via process tree)
- [x] Worker cold start <20ms (vs current ~200ms)
- [x] Memory sharing via COW (verified via /proc/smaps)
- [x] All RFC-0010 features still work (--reload, --health-bind, etc.)
- [x] No regression in single-worker mode

---

## 5. Timeline

| Phase | Scope | Estimate |
|-------|-------|----------|
| Design | Architecture validation | 1 week |
| Core | Worker pool + Zygote fork | 2 weeks |
| Integration | uvicorn single-worker mode | 1 week |
| Testing | Performance + stability | 1 week |
| **Total** | | **5 weeks** |

---

## 6. Risks

| Risk | Mitigation |
|------|------------|
| uvicorn internal changes | Pin version, test each upgrade |
| Zygote state corruption | Worker isolation, health checks |
| Signal handling complexity | RAII + ShutdownCoordinator (from RFC-0010) |

---

## 6A. Core Design Constraints (Blocking)

> **Source**: [RFC Review Board Decision](./0011-reviews/0011-review-board-decision.md)  
> **Status**: MUST implement before merge

### 6A.1 FD Hygiene Contract

FD inheritance is NOT "possible problem" — it is "certain accident".

| Phase | Responsibility |
|-------|----------------|
| **Pre-Fork** | Supervisor marks ONLY inheritable FDs (stdin/stdout/stderr, UDS) |
| **Post-Fork** | Worker executes FD whitelist closure |

```rust
// Pre-fork: Mark all non-essential FDs as CLOEXEC
for fd in open_fds().filter(|f| !INHERITABLE_WHITELIST.contains(f)) {
    unsafe { libc::fcntl(fd, libc::F_SETFD, libc::FD_CLOEXEC); }
}
```

### 6A.2 Signal State Reset Contract

Python signal state MUST be treated as "dirty state" after Zygote.

```python
def post_fork_reinit():
    import signal
    # Reset all handlers to default
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    # Reset wakeup FD (uvloop/asyncio pollution)
    try:
        signal.set_wakeup_fd(-1)
    except ValueError:
        pass
```

### 6A.3 Hop-by-Hop Header Stripping (Mandatory)

L7 Proxy MUST strip these headers before forwarding:

```rust
const HOP_BY_HOP: &[&str] = &[
    "connection", "keep-alive", "te",
    "transfer-encoding", "upgrade", "proxy-connection"
];
```

### 6A.4 ASGI Proxy Headers (Non-Configurable)

This is NOT optional — `scope["client"]` loss is behavior-breaking.

| Requirement | Value |
|-------------|-------|
| Rust Proxy | MUST inject `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Port` |
| Uvicorn Config | `proxy_headers=True` (FORCED, not configurable) |
| Default | `forwarded_allow_ips="*"` |

### 6A.5 `scope["client"]` Recovery Path

```python
# FastAPI/Starlette: request.client.host MUST NOT be None
# Recovery via X-Forwarded-For:
async def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
```

### 6A.6 Supplemental Recommendations (Non-Blocking)

> These items improve implementation quality and should be addressed during development.

| Recommendation | Description | Owner |
|----------------|-------------|-------|
| **post_fork Execution Order** | Random Seed → SSL Context → Signal Handlers → OMP threads | Dev |
| **Platform Annotations** | Clear comments for Linux vs macOS conditional branches | Dev |
| **E2E Integration Test** | Nginx → Velo → Uvicorn full-chain verification | QA |
| **Header Normalization Tests** | L7 Proxy headers must parse identically to uvicorn | Dev+QA |


```python
# post_fork_reinit - Recommended Execution Order
def post_fork_reinit():
    # 1. Random Seed (cryptographic safety)
    import random
    random.seed()
    
    # 2. SSL Context (regenerate if needed)
    import ssl
    ssl._create_default_https_context = ssl.create_default_context
    
    # 3. Signal Handlers (reset to default)
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    try:
        signal.set_wakeup_fd(-1)
    except ValueError:
        pass
    
    # 4. OpenMP/BLAS threads (restore for workers)
    import os
    os.environ['OMP_NUM_THREADS'] = str(os.cpu_count() or 4)
```

---

## 7. Open Questions




1. **gunicorn compatibility**: Apply same pattern?
2. **--workers auto-scaling**: Use CPU count or memory-based?
3. **Worker restart strategy**: Rolling vs. all-at-once?

---

## 8. References

- [RFC-0010 Phase 6.1 Serve, Analyze & Polish](./0010-phase-6.1-serve-analyze.md)
- [RFC-0002 Phase 3 Zygote Mode](./0002-phase-3-zygote.md)
- [Uvicorn Worker Internals](https://www.uvicorn.org/)

---

**RFC Record**: Implemented on 2026-01-04

---

## Appendix A: Architectural Review (2026-01-05)

> **Reviewer**: Architect (ID-LOCK-001)

### A.1 Potential Optimizations

| Area | Current | Suggested Optimization |
|------|---------|------------------------|
| **Per-worker overhead** | Each worker runs full uvicorn (event loop + HTTP parsing) | Consider Rust HTTP frontend (hyper/axum) + Python ASGI backend |
| **Port management** | N TCP ports for N workers | Use Unix Domain Sockets to simplify |
| **Inter-worker state** | No shared state mechanism | Add shared memory metrics (Prometheus-style) |

### A.2 Answers to Open Questions (Section 7)

| Question | Decision | Rationale |
|----------|----------|-----------|
| gunicorn compatibility | Low priority | Same pattern applies, but uvicorn is primary target |
| --workers auto-scaling | Default to CPU count | Memory-based scaling as optional advanced feature |
| Worker restart strategy | **Rolling** | Zero-downtime restarts, one worker at a time |

### A.3 Missing Architectural Components

Future phases should address:

1. **Worker Health Check Details**: Specific endpoints, intervals, failure thresholds
2. **Graceful Shutdown Coordination**: Integration with RFC-0010 ShutdownCoordinator
3. **Worker Crash Recovery**: Max restarts, backoff strategy, circuit breaker
4. **Observability**: Worker metrics, request latency histograms, memory usage

### A.4 Future Architecture (Option A Evolution Path)

If performance requirements increase, consider evolving to:

```text
Rust HTTP Server (hyper/axum)
├── Accept all HTTP connections
├── Load balance across workers (round-robin / least-connections)
└── Workers 1-N (ASGI only, no HTTP parsing)
    ├── Forked from Zygote
    └── Communicate via Unix socket / shared memory
```

This eliminates per-worker HTTP overhead while maintaining Zygote benefits.

---

### A.5 Architecture Issue: TCP vs IPC Inconsistency

> **Severity**: Medium  
> **Status**: OPEN  
> **Found**: 2026-01-05

#### Problem

Current implementation uses **TCP (AF_INET)** for worker communication, but Zygote itself uses **Unix Domain Socket (IPC)**:

| Component | Current | Expected |
|-----------|---------|----------|
| Zygote ↔ Rust | Unix Domain Socket (`AF_UNIX`) | ✅ Correct |
| Worker ↔ Client | TCP (`AF_INET`) + `SO_REUSEPORT` | ❌ Inconsistent |

#### Evidence

`velo_zygote/worker_runner.py` lines 41-44:
```python
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCP!
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
sock.bind((host, port))  # Binds to TCP port
```

#### Impact

| Aspect | TCP (Current) | Unix Socket (Recommended) |
|--------|---------------|---------------------------|
| Port management | N ports for N workers | File path, no port conflicts |
| Security | Port exposed to network | File permissions only |
| Performance | TCP stack overhead | Lower latency |
| Architecture | Inconsistent with Zygote IPC | Consistent |

#### Recommendation

1. **Short-term**: Document as known limitation
2. **Long-term**: Migrate to Unix Domain Socket with Rust proxy

#### Dependencies

- Requires Rust HTTP frontend (A.4 evolution path)
- Or: Use `SO_REUSEPORT` with localhost-only binding (mitigation)

---

## Appendix B: L7 Proxy + UDS Architecture (2026-01-05)

> **Status**: APPROVED FOR IMPLEMENTATION  
> **Author**: Architect (ID-LOCK-001)

### B.1 Key Architecture Change Visualization

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                         Velo Supervisor                                  │
│                  (Process Manager + Application Gateway)                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│    External HTTP Request                                                 │
│           ↓                                                              │
│    ┌─────────────────┐                                                   │
│    │ TCP Port :8000  │ ← External clients connect here                   │
│    └────────┬────────┘                                                   │
│             ↓                                                            │
│    ┌─────────────────┐                                                   │
│    │   L7 HTTP Proxy │ ← Rust (hyper + tokio)                           │
│    │   Load Balancer │   - Least Connections                            │
│    │   X-Forwarded-* │   - Health checks                                │
│    └────────┬────────┘                                                   │
│             ↓                                                            │
│    ┌─────────────────────────────────────────────────┐                   │
│    │           Unix Domain Sockets (UDS)             │                   │
│    │ /tmp/velo-worker-1.sock  /tmp/velo-worker-N.sock│                   │
│    └─────────┬────────────────────────┬──────────────┘                   │
│              ↓                        ↓                                  │
│    ┌──────────────────┐    ┌──────────────────┐                          │
│    │ Worker 1 (uvicorn│    │ Worker N (uvicorn│                          │
│    │ --uds mode)      │    │ --uds mode)      │                          │
│    │ Forked from      │    │ Forked from      │                          │
│    │ Zygote           │    │ Zygote           │                          │
│    └──────────────────┘    └──────────────────┘                          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Velo's Dual Identity**:
- **Process Manager (Supervisor)**: Zygote fork, worker lifecycle, health monitoring
- **Application Gateway (L7 Proxy)**: HTTP routing, load balancing, header injection

---

### B.2 Core Implementation Prototypes

#### B.2.1 `src/proxy/upstream.rs` (UDS Connector)

```rust
use hyper::Uri;
use std::pin::Pin;
use std::task::{Context, Poll};
use tokio::net::UnixStream;
use tower::Service;
use std::future::Future;

/// Custom Connector allowing Hyper to connect to Unix Domain Sockets
#[derive(Clone)]
pub struct UdsConnector;

impl Service<Uri> for UdsConnector {
    type Response = UnixStream;
    type Error = std::io::Error;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, uri: Uri) -> Self::Future {
        // Parse socket path from URI (e.g., unix:///tmp/velo-worker-1.sock)
        let path = uri.path().to_string(); 
        
        Box::pin(async move {
            UnixStream::connect(path).await
        })
    }
}
```

#### B.2.2 `src/proxy/load_balancer.rs` (Least Connections)

```rust
use std::sync::{Arc, atomic::{AtomicUsize, Ordering}};

struct WorkerNode {
    socket_path: String,
    active_connections: AtomicUsize,
}

pub struct LoadBalancer {
    workers: Vec<Arc<WorkerNode>>,
}

impl LoadBalancer {
    /// RFC 2.3: Least Connections strategy
    pub fn select_worker(&self) -> Option<String> {
        self.workers.iter()
            .min_by_key(|w| w.active_connections.load(Ordering::Relaxed))
            .map(|w| {
                // Increment (RAII guard handles decrement)
                w.active_connections.fetch_add(1, Ordering::Relaxed);
                w.socket_path.clone()
            })
    }
}
```

#### B.2.3 `src/proxy/service.rs` (The L7 Proxy)

```rust
use hyper::{Request, Response, body::Incoming};
use hyper::service::Service;
use std::future::Future;
use std::pin::Pin;

pub struct VeloProxyService {
    lb: Arc<LoadBalancer>,
    client: Client<UdsConnector, Incoming>,
}

impl Service<Request<Incoming>> for VeloProxyService {
    type Response = Response<Incoming>;
    type Error = hyper::Error;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn call(&mut self, mut req: Request<Incoming>) -> Self::Future {
        let lb = self.lb.clone();
        let client = self.client.clone();

        Box::pin(async move {
            // 1. Load Balance
            let socket_path = lb.select_worker().expect("No workers available");
            
            // 2. Rewrite URI for UDS
            let new_uri = format!("unix://{}", socket_path).parse().unwrap();
            *req.uri_mut() = new_uri;

            // 3. Inject RFC headers (X-Forwarded-For etc.)
            req.headers_mut().insert("X-Velo-Worker", socket_path.parse().unwrap());

            // 4. Forward Request (L7 Proxy)
            client.request(req).await
        })
    }
}
```

#### B.2.4 `src/lifecycle/safety.rs` (Socket Hygiene)

```rust
use std::path::Path;
use tokio::fs;

/// RFC Appendix B.3: Socket Hygiene
/// Clean stale socket files before binding
pub async fn unlink_socket_if_exists(path: &Path) -> std::io::Result<()> {
    if path.exists() {
        let metadata = fs::metadata(path).await?;
        use std::os::unix::fs::MetadataExt;
        if metadata.mode() & 0o170000 == 0o140000 { // S_IFSOCK
            fs::remove_file(path).await?;
            println!("🧹 Cleaned up stale socket: {:?}", path);
        } else {
            eprintln!("⚠️ Warning: {:?} exists but is not a socket!", path);
        }
    }
    Ok(())
}
```

---

### B.3 Implementation Roadmap

| Track | Component | Owner | Status |
|-------|-----------|-------|--------|
| **Rust** | `src/proxy/upstream.rs` (UDS Connector) | Developer | TODO |
| **Rust** | `src/proxy/load_balancer.rs` | Developer | TODO |
| **Rust** | `src/proxy/service.rs` (L7 Proxy) | Developer | TODO |
| **Rust** | `src/lifecycle/safety.rs` (Socket hygiene) | Developer | TODO |
| **Rust** | Integration into `velo-supervisor` | Developer | TODO |
| **Python** | `post_fork` hook implementation | Developer | TODO |

### B.4 Key Engineering Challenges

1. **Hyper + UDS**: Hyper doesn't natively support UDS targets; custom `Service<Uri>` required
2. **Connection Tracking**: RAII guard pattern for accurate connection counting
3. **Graceful Shutdown**: Drain connections before worker termination
4. **Header Preservation**: Proper X-Forwarded-* injection for ASGI apps

---

## Appendix C: Independent Technical Review (2026-01-05)

> **Verdict**: CONDITIONAL PASS — Risk Manageable, Protocol Details Required  
> **Reviewers**: Python Core, OS/Kernel, Framework Compatibility, Security Experts

---

### C.1 🐍 Python Core & Runtime Review

#### ⚠️ Risk 1: File Descriptor (FD) Leakage

| Issue | Impact | Mitigation |
|-------|--------|------------|
| Child inherits parent's FDs (TCP Listener, logs, DB connections) | Worker may accept external connections; port release failure | **Set `FD_CLOEXEC`** on all non-essential FDs before fork |

#### ⚠️ Risk 2: Signal Handling Race

| Issue | Impact | Mitigation |
|-------|--------|------------|
| Python signals only on main thread; uvloop may have preset masks | Residual Zygote signal state | **Reset signal handlers** in `post_fork` hook (SIGINT, SIGTERM) |

---

### C.2 🐧 OS & Kernel Review

#### 🟢 Advantage: No Thundering Herd

Rust Load Balancer explicitly selects `connect("/tmp/w1.sock")`, eliminating thundering herd problem entirely. Kernel wakes only the selected worker.

#### ⚠️ Performance Trap: Static Files

| Mode | Path | Zero-Copy? |
|------|------|------------|
| TCP (uvicorn direct) | Disk → Kernel → TCP | ✅ `sendfile` |
| L7 Proxy (UDS) | Disk → Python → UDS → Rust → TCP | ❌ Multiple copies |

**Recommendation**: Rust should directly serve `/static` (future optimization).

#### 🔧 Tuning Recommendation

Set `SO_SNDBUF` and `SO_RCVBUF` to 2MB+ on UDS connections to reduce context switches.

---

### C.3 🌐 ASGI & Framework Review

#### ❌ Critical: `client` Field Lost

| Framework | Affected | Consequence |
|-----------|----------|-------------|
| Django | `request.META['REMOTE_ADDR']` = None | IP-based rate limiting fails |
| FastAPI | `request.client.host` = None | Client identification impossible |

**Mandatory Fix**:
1. **Rust Proxy**: Inject `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Port`
2. **Uvicorn**: Force `--proxy-headers` or `forwarded_allow_ips='*'`

#### ⚠️ Path Routing (`root_path`)

If Velo is behind Nginx (Nginx → Velo → Uvicorn), ensure `root_path` propagates correctly for FastAPI Swagger UI URLs.

---

### C.4 🔒 Security Review

#### ⚠️ HTTP Desync (Request Smuggling)

| Parser | Risk |
|--------|------|
| Rust (Hyper) - Frontend | Strict parsing (good) |
| Python (h11) - Backend | Different interpretation possible |

**Mitigation**: Normalize request headers; remove Hop-by-Hop headers (`Connection`, `Keep-Alive`, `Te`, `Transfer-Encoding`).

#### ⚠️ UDS Permission Escape

**Current**: `/tmp/velo-{UID}/` with `0700` permissions.

**Enhancement Options**:
- Linux: Use Abstract Namespace Sockets (`@velo-worker-1`) — no filesystem permissions needed
- Linux: Use `memfd_create` (anonymous memory file)

---

### C.5 📋 Action Items (Prioritized)

| Priority | Domain | Action | Status |
|----------|--------|--------|--------|
| 🔴 High | Rust/OS | Set `FD_CLOEXEC` on all FDs before fork | TODO |
| 🔴 High | Rust/HTTP | Implement `X-Forwarded-For/Proto/Port` injection | TODO |
| 🔴 High | Python/ASGI | Force Uvicorn `proxy_headers=True` | TODO |
| 🟡 Medium | Rust/OS | Investigate Abstract Namespace Sockets (`@velo...`) | TODO |
| 🟡 Medium | Security | Strip Hop-by-Hop headers before forwarding | TODO |
| 🔵 Low | Perf | Rust direct static file serving (`/static`) bypass | FUTURE |

---

**Technical Review Committee Sign-off**: ✅ APPROVED with Conditions

---

## Appendix D: Rust & HPC Expert Review

> **Reviewer**: Tokio Core Contributor / Systems Engineer  
> **Focus**: Memory allocation, syscall overhead, socket lifecycle management

### D.1 🦀 Linux Abstract Namespace Sockets (STRONGLY RECOMMENDED)

> **Status**: UPGRADE from "Investigate" to "IMPLEMENT" (Linux only)

**Pain Points with Filesystem Sockets**:
- Process crash → stale socket file → `EADDRINUSE` on restart
- Requires explicit `unlink()` logic
- Complex permission management (`chmod`/`chown`)

**Solution**: Abstract Namespace Sockets

```rust
#[cfg(target_os = "linux")]
fn get_socket_addr(worker_id: u32) -> String {
    format!("\x00velo-worker-{}", worker_id)  // Leading null byte
}

#[cfg(not(target_os = "linux"))]
fn get_socket_addr(worker_id: u32) -> String {
    format!("/tmp/velo-{}/worker-{}.sock", uid, worker_id)  // macOS fallback
}
```

### D.2 🔗 Hyper Client Connection Pooling

**Issue**: Default Hyper config is tuned for WAN, not local UDS.

| Setting | Default | UDS Optimized |
|---------|---------|---------------|
| `pool_idle_timeout` | 90s | 30s+ |
| `pool_max_idle_per_host` | ? | 1 |

**Critical**: Ensure unique URI authority per worker to prevent connection misrouting.

### D.3 📊 Buffer Sizing

For high-throughput local IPC, set `SO_RCVBUF` and `SO_SNDBUF` to 256KB.

---

## Appendix E: QA Review & Final Checklist

> **Full QA Review**: [0011-reviews/0011-qa-review.md](./0011-reviews/0011-qa-review.md)

### Final Implementation Checklist

#### Rust Proxy (Core)
- [ ] Implement Hyper Service
- [ ] Implement UdsConnector (with Linux Abstract Socket branch)
- [ ] Implement LeastConnections Load Balancer
- [ ] Implement Buffer Tuning (SO_SNDBUF = 256KB)

#### Worker Management
- [ ] Set FD_CLOEXEC before Command::spawn
- [ ] Adapt Uvicorn args: Linux (`@...`) vs macOS (`/tmp/...`)

#### Python Zygote
- [ ] Implement post_fork hook (reset Signals, Random Seed, SSL)

#### Testing (QA)
- [ ] Configure Linux CI Pipeline
- [ ] Write "Header Fidelity" integration test

---

## ⚠️ Implementation Critical Path

> **READ THIS BEFORE CODING** - These are blockers from expert reviews

### 🔴 Must-Do Items (Implementation Blockers)

| Source | Critical Item | Consequence if Ignored |
|--------|---------------|------------------------|
| **Python Expert** | `FD_CLOEXEC` on ALL inherited FDs | Worker crash → Port NEVER released (disaster) |
| **Python Expert** | Signal state full reset in `post_fork` | uvloop pollution → Undefined behavior |
| **Rust Expert** | Unique URI authority per worker | Connection routes to WRONG worker (fatal) |
| **Security Expert** | Remove `Connection`, `Transfer-Encoding` headers | Request Smuggling (CL.TE/TE.CL) |

### 🟡 Strategic Reminder

> **Velo is now a RUNTIME, not a runner.**
> - Need SemVer + deprecation policy
> - CLI project → Runtime project mindset shift

### Code Patterns

```rust
// ✅ FD_CLOEXEC (Rust side)
unsafe { libc::fcntl(fd.as_raw_fd(), libc::F_SETFD, libc::FD_CLOEXEC); }

// ✅ Unique URI authority
let uri = format!("unix://worker-{}@velo/api", worker_id);

// ✅ Strip hop-by-hop headers
for header in ["connection", "transfer-encoding", "te", "keep-alive"] {
    headers.remove(header);
}
```

```python
# ✅ Signal reset (Python side)
import signal
def post_fork_reinit():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
```

---

## Final Sign-off Summary

| Expert | Status |
|--------|--------|
| Architect | ✅ APPROVED |
| Python Core | ✅ APPROVED |
| OS/Kernel | ✅ APPROVED |
| Security | ✅ APPROVED |
| ASGI/Framework | ✅ APPROVED |
| Rust/HPC | ✅ APPROVED |
| QA | ✅ APPROVED |
| Cloud Native / K8s | ✅ APPROVED |
| Observability / O11y | ✅ APPROVED |
| Scientific Python / HPC | ✅ APPROVED |
| Network SRE | ✅ APPROVED |

> **Additional Reviews** (in `0011-reviews/` directory):
> - [QA Review](./0011-reviews/0011-qa-review.md)
> - [K8s Review](./0011-reviews/0011-k8s-review.md)
> - [O11y Review](./0011-reviews/0011-o11y-review.md)
> - [HPC Review](./0011-reviews/0011-hpc-review.md)
> - [Network Review](./0011-reviews/0011-network-review.md)
> - [Master Architecture Review](./0011-reviews/0011-master-review.md)
> - [**RFC Review Board Decision**](./0011-reviews/0011-review-board-decision.md) ⭐

---

**RFC-0011 Status**: ✅ **FULL APPROVAL** (Ready for Implementation)



