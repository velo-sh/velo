# SPEC-0007: Velo High-Performance Master Standard (The Black Magic Guide)

**Status**: DRAFT (Proposed for Phase 7.2)
**Author**: Architect
**Date**: 2026-01-14

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

### 4.5 Core Components
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
