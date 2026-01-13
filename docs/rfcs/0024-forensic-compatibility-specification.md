# RFC-0024: Forensic Compatibility Specification

**Status**: DRAFT (Proposed for Phase 7.2)
**Author**: Architect
**Date**: 2026-01-14

## 1. Summary
This specification defines the mandatory compatibility baseline for Velo in **Native Sovereignty (RSGI)** mode. It ensures that user applications migrating from Uvicorn/Gunicorn to Velo experience "Zero Friction" and "Zero Conflict," maintaining 100% behavioral parity with standard ASGI expectations while operating under Velo's hardened environment features.

## 2. Framework Matrix (Deep Dive)
Velo must verify the integrity of the `scope` dictionary and event loop behavior across the following frameworks:

| Framework | Type | Core Audit Focus | Priority |
|:---:|:---:|:---|:---:|
| **Starlette** | ASGI | 100% RFC-compliant `scope` dictionary integrity. | P0 |
| **Litestar** | ASGI | High-performance routing and custom Type Hint handling. | P1 |
| **Sanic** | ASGI | Custom ASGI-mode converter and signal handling. | P1 |
| **BlackSheep** | ASGI | Cython-based high-performance execution paths. | P2 |
| **Falcon** | ASGI | Strict specification validation and header parsing. | P2 |

## 3. IO Patterns & Protocol Sovereignty
Verify the RSGI-to-ASGI protocol stack stability under extreme IO scenarios:

- **[P0] WebSockets (Tunnelling)**:
    - *Scenario*: Full lifecycle verification of `connect`, `receive`, `send`, and `disconnect`.
    - *Focus*: Successful handshake hijacking and bi-directional stream persistence.
- **[P1] Server-Sent Events (SSE)**:
    - *Scenario*: Long-lived, irregular data streams (e.g., streaming AI inference).
    - *Focus*: Prevention of proxy-layer buffer starvation and timeout management.
- **[P1] Large File Uploads (Multi-part)**:
    - *Scenario*: Verification of 100MB+ multi-part form uploads.
    - *Focus*: Memory pressure on SHM (Shared Memory) and backpressure handling.
- **[P2] Response Compression**:
    - *Scenario*: Gzip/Brotli middleware verification.
    - *Focus*: Correct header manipulation and binary stream integrity.

## 4. Middleware & Interception
Ensure Velo's **Environment Shield** does not interfere with observability and security middleware:

- **[P1] Sentry Integration**: 
    - *Scenario*: `SentryAsgiMiddleware` error capturing.
    - *Focus*: Context extraction and ensuring thread isolation doesn't cause trace loss.
- **[P1] Prometheus/OpenTelemetry**:
    - *Scenario*: Native metric collection and tracing.
    - *Focus*: Ensuring the Zygote process model doesn't cause metric data collisions.
- **[P1] Auth Interceptors**:
    - *Scenario*: Custom JWT/OAuth2 validation middleware.
    - *Focus*: Preservation and modification logic of the `Authorization` header.

## 5. Runtime & Dependency Sovereignty
Prevent Velo's internal dependencies from causing "Dependency Hijacking" in user space:

- **[P0] Dependency Shadowing**:
    - *Scenario*: Version conflicts between Velo internals and user apps (e.g., `msgpack`).
    - *Focus*: `sys.path` priority ensuring user-installed versions take precedence.
- **[P1] Signal Hijacking**:
    - *Scenario*: User-defined `signal.signal(SIGINT, ...)` handlers.
    - *Focus*: Verification that they do not break Velo Host's worker lifecycle management.
- **[P2] Global State Leakage**:
    - *Scenario*: Environment mutation during the import phase.
    - *Focus*: Cross-worker pollution detection in Zygote mode.

## 6. Advanced Architecture Patterns (Expert Level)

### 6.1 Context-Aware Forking (ContextVars Preservation)
- **Best Practice**: In a Zygote model, forking can leave stale `contextvars` or thread-local state in the child. 
- **Mechanism**: Velo MUST implement a `post_fork_reset()` hook that clears known framework-level context storage (e.g., `starlette.request_context`, `aiotask_context`) before the first request is accepted. This prevents "Request Bleeding" where data from the warm-up phase leaks into real user requests.

### 6.2 Self-Diagnostic Protocol Handshakes
- **Best Practice**: Instead of a silent failure when a framework sends a non-compliant ASGI message, Velo will implement **"Protocol Sincerity."**
- **Mechanism**: If the RSGI bridge detects an invalid scope key or an illegal header character, it will return a specialized `502 Bad Gateway` with a `X-Velo-Error-Code` (e.g., `VELO-COMPAT-001`) and log the exact mismatched field to the supervisor for forensic analysis.

### 6.3 Post-Fork Re-initialization (Pool Sovereignty)
- **Best Practice**: Heavy resources (DB connection pools, Redis clients, SSL contexts) initialized during the Zygote warm-up phase become "Poisoned" after a fork due to shared FDs.
- **Mechanism**: Frameworks should be validated against their ability to use `on_startup` hooks correctly. Velo will explicitly support a `VELO_FORCE_REINIT` signal that triggers standard framework "re-connect" logic post-fork.

### 6.4 Graceful Rotation (High-Water Mark)
- **Best Practice**: Long-running workers with memory fragmentation (common in Python ML apps) should be rotated based on memory usage, not just request count.
- **Mechanism**: Velo will monitor RSS. Once a "High-Water Mark" is hit, the supervisor will signal the worker to finish current requests and then autonomously `exit(0)`, allowing a fresh Zygote fork to take over.

---

## 7. Robustness Invariants
- **[P0] Hard Exit Containment**: Immediate detection of `os._exit(0)` via `SIGCHLD` and triggering of the auto-respawn logic.
- **[P0] Infinite Hang Isolation**: Cutting connections and recycling resources when a handler enters an infinite loop (Timeout enforcement).
- **[P1] Output Flood Protection**: Preventing deadlock when an application generates massive bursts of log/stdout data.

## 7. Execution Strategy
P0 scenarios outlined in this RFC SHALL be integrated into the core testing suite at `tests/qa/phase_7_2/test_framework_compatibility.py` and serve as the mandatory "Admission Criteria" for the Phase 7.2 release.
