# SPEC-0007: Velo High-Performance Master Standard (The Black Magic Guide)

**Status**: APPROVED (Phase 7.3 Stabilization)
**Author**: Architect
**Date**: 2026-01-16
**Related RFCs**: [RFC-0019](../rfcs/0019-native-sovereignty.md), [RFC-0013](../rfcs/0013-top100-baseline.md), [RFC-0031](../rfcs/0031-kinetic-optimization.md)

## 0. The Performance Codex (Index)
> **Organization**: This Standard consolidates the following specialized documents:

| Document | Role | Scope |
|:---|:---|:---|
| **SPEC-0007** (This Doc) | **The Law** | Governance, Coding Standards, Invariants |
| [RFC-0019 (Native)](../rfcs/0019-native-sovereignty.md) | **The Strategy** | Architecture, Memory Safety Zones, Allocator Stats |
| [RFC-0031 (Kinetic)](../rfcs/0031-kinetic-optimization.md) | **The Tactics** | Specific Optimization Logic (Hardcore Mode) |
| [RFC-0013 (Baseline)](../rfcs/0013-top100-baseline.md) | **The Ruler** | Benchmarking Methodology (Top 100) |

## 1. Introduction
Velo is engineered for "Industrial Sincerity," where performance is not a patch but a structural property. This standard consolidates the "Black Magic" patterns that allow Velo to bridge the Rust-Python gap with near-zero overhead.

## 2. Zero-Copy Sovereignty (The 0-Copy Axiom)
Velo mandates that data shall never be copied across the language boundary if it can be mapped.

### 2.1 Memory Gravity (SHM)
- **Concept**: Model weights and large datasets are owned by the Rust Host in **Shared Memory (SHM)**.
- **Magic**: Python workers attach to these segments using `mmap`. Tensors are wrapped as `read-only views`, eliminating the 10s-60s model loading time during worker respawns.

### 2.2 RSGI Header Transmutation
- **Concept**: HTTP headers arriving in Rust are converted to Python `dict` objects using specialized PyO3 marshalling.
- **Magic**: Utilizing `PyBytes` views and interned strings to ensure that the header dictionary is delivered to FastAPI with **Zero-Copy** semantics.

### 2.3 Large Body Passing (memfd)
- **Concept**: Body payloads > 64KB bypass the UDS socket.
- **Magic**: The Host uses `memfd_create` to create an anonymous file in RAM, writes the body, and passes the **File Descriptor (FD)** to the Worker via `SCM_RIGHTS`. The Worker then `mmap`s the FD, achieving true physical zero-copy for large uploads/downloads.

## 3. Instant Sovereignty (Zygote Engine)
Velo eliminates Python's "Import Tax" through pre-warming.

- **Mechanism**: The Velo Supervisor starts a **Zygote** process that performs all heavy imports (Torch, Pandas, Transformers).
- **Magic**: When a new Worker is needed, the Zygote uses `OS fork()`. Due to **Copy-on-Write (COW)**, the worker starts in **< 10ms** with all libraries already resident in memory.

## 4. Mechanical Sympathy (Industrial Stack)
Velo utilizes a titanium-grade tech stack to minimize runtime jitter.

### 4.1 Triple-Tier Compilation Strategy
To balance development velocity with production performance, Velo enforces three compilation tiers:

| Tier | Command | Optimization | Goal |
|:---|:---|:---|:---|
| **Dev** | `cargo build` | `opt-level = 0` | **Velocity**: Max compilation speed, incremental linking. |
| **Release** | `cargo build --release` | `opt-level = 2` | **Regression**: Balanced performance for CI & QA. |
| **Production** | `cargo build --profile production` | `opt-level = 3` | **Titanium**: Max speed, LTO-Fat, Strip, Panic-Abort. |

### 4.2 Environment-Aware Infrastructure
To minimize "drift" while maximizing resource efficiency:

| Environment | Primary Profile | Optimization Secret |
|:---|:---|:---|
| **Local Dev** | `dev` | **ZLD/Mold Linker**: Reduce link time by 5x-10x. |
| **CI (PR)** | `dev` | **rust-cache**: Persistent caching of `target/` and registry. |
| **CI (Main)** | `production` | **PGO (Profile Guided Optimization)**: Optimize based on real traces. |
| **Docker (Release)**| `production` | **cargo-chef**: Layered caching of compiled dependencies. |

### 4.3 CI Best Practices (SOP-005)
To balance speed and resource consumption in CI:

1. **Disable Incremental Compilation**: Set `CARGO_INCREMENTAL=0` in CI. Incremental builds create large cache snapshots that bloat GHA cache and slow down I/O.
2. **Linker Sovereignty**: Mandate the use of `mold` (Linux) or `zld` (macOS) in CI workflows to bypass the single-threaded link bottleneck.
3. **Sparse Registry**: Use `CARGO_REGISTRY_SPARSE=true` to speed up dependency index fetching.
4. **Cache Pruning**: Only cache `~/.cargo/registry` and specific `target/` artifacts to prevent cache eviction.

### 4.4 Docker Optimization (The Chef Pattern)
Velo Docker images MUST use a multi-stage `cargo-chef` workflow:

```dockerfile
# Stage 1: Compute Recipe
FROM lukemathwalker/cargo-chef:latest-rust-1.92.0 AS chef
WORKDIR /app
COPY . .
RUN cargo chef prepare --recipe-json recipe.json

# Stage 2: Cache Dependencies
FROM chef AS builder
COPY --from=chef /app/recipe.json recipe.json
RUN cargo chef cook --release --recipe-json recipe.json
# Build application
COPY . .
RUN cargo build --profile production

# Stage 3: Runtime
FROM debian:bookworm-slim
COPY --from=builder /app/target/production/velo /usr/local/bin/velo
```

### 4.5 Tiered CI Orchestration
To balance feedback speed with production integrity, Velo CI follows a tiered execution model:

| Phase | Trigger | Profile | Primary Activity | Requirement |
|:---|:---|:---|:---|:---|
| **Tier 1: Fast Pass** | Every PR / Push | `dev` | `cargo check` + Unit Tests | **< 5 min**: Catch regressions early. |
| **Tier 2: Integration** | Merge to `main` | `release` | Full QA Suite + Stress Tests | **< 15 min**: Verify stable integration. |
| **Tier 3: Certification** | Nightly / Tags | `production` | Benchmarks + PGO + Audit | **Industrial Grade**: Final artifact quality. |

### 4.6 Core Components
| Component | Technology | Performance Value |
|:---|:---|:---|
| **Allocator** | `jemalloc` | Low fragmentation, high-concurrency heap |
| **IO Backend** | `Tokio` (epoll/kqueue) | Multi-core non-blocking execution |
| **Serialization** | `rkyv` / `MsgPack` | SIMD-accelerated, zero-copy deserialization |
| **Compiler** | `LTO = "fat"` | Cross-crate link-time optimization |

## 5. Shadow Optimization (Future Vision)
- **Idle-Time Compiling**: Velo records hot-paths during peak traffic and compiles them to native code during idle periods (Shadow Compiler).
- **Predictive Warming**: Anticipates load spikes to pre-fork Workers before they are needed.

## 6. Industrial Invariants
1. **INV-PERF-001**: Any body payload > 1MB MUST utilize the `memfd + SCM_RIGHTS` path.
2. **INV-PERF-002**: Worker cold-start (including FastAPI init) MUST remain below **50ms**.
3. **INV-PERF-003**: No Python worker shall manage its own event loop; the Rust Host drives the execution pulse.

## 7. The Kinetic Coding Standard (Titanium Hardcore)
> **Added**: Phase XI (2026-01-16)
> **Philosophy**: Hardware Sympathy. Zero Allocation.

To achieve **< 50ms startup** and **DoS Resilience**, all Velo code must adhere to these "Hardcore" patterns.

### 7.1 Memory: The Hierarchy of Speed
1.  **Stack First**: For small artifacts (< 1KB) like Handshake packets or Heartbeats, use `SmallVec` or array on stack. **NEVER `malloc`**.
2.  **Recycle Second**: For repetitive hot-path objects (IPC Buffers), use a **Bounded Recycler** (`ArrayQueue<Vec<u8>>`).
    *   *Constraint*: Max pool size = 128. Max item size = 64KB.
    *   *Why?*: Go uses Channels to dodge GC; Rust uses Recyclers to dodge **Allocator Contention** (`malloc` locks).
3.  **Heap Last**: `Vec::new()` is forbidden in the `fork()` or `serve()` hot loop.

### 7.2 Concurrency: Sharding & Locality
1.  **Shard the Locks**: If a Mutex protects a map, split it into `N = CPU` shards.
    *   *Pattern*: `Vec<Mutex<HashMap>>` instead of `Mutex<HashMap>`.
2.  **Local Queues**: A Worker should pull from a local MPSC channel first, and only "steal" from a global queue if empty.
    *   *Why*: Reduces CPU cache thrashing.

### 7.3 Resilience: Defensive Coding
1.  **Rate Limit Everything**: No error log or warning shall be emitted without a `RateLimiter` (Token Bucket).
    *   *Rule*: "Logs must not kill the disk."
2.  **Bounded Queues**: `unbounded_channel` is **STRICTLY PROHIBITED**. Every queue must backpressure.

### 7.4 Unsafe: The Nuclear Option (Experimental)
*   **Zero-Copy String Casting**: `unsafe { from_utf8_unchecked }` is permitted **ONLY** for:
    *   Internal, trusted tags (e.g., `[SUP]`, `[SID:...]`).
    *   High-frequency scanning paths (> 10k ops/sec).
*   **Audit**: Must be gated behind `#[cfg(feature = "unsafe_log_fast_path")]`.
