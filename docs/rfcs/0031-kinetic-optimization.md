# RFC-0031: Kinetic Optimization (Titanium Hardcore)

> **Status**: DRAFT
> **Feature**: Kinetic Performance (Phase XI)
> **Driver**: ID-LOCK-001 (Architect)
> **Philosophy**: Zero-Cost Abstractions or Nothing.

## 1. Abstract

This RFC proposes two specific optimizations for Velo's "Kinetic" architecture, derived directly from **Rust's Zero-Cost** principles and **Hardware Sympathy**:
1.  **Resilience**: Log Rate Limiting to prevent DoS via log flooding.
2.  **Efficiency**: IPC Buffer Pooling to eliminate allocator pressure during high-frequency fork operations.

## 2. Motivation

Velo's current Zygote IPC (`RFC-0013`) and Logging (`RFC-0012`) implementations are functionally correct but naive in resource usage:
-   **Logging**: A compromised or buggy worker can flood the supervisor with infinite log lines, causing high disk I/O or OOM.
-   **IPC**: Every fork request allocates new `Vec<u8>` buffers for serialization, putting pressure on the allocator and increasing fragmentation.

Adopting "The Titanium Way" (Zero-Cost + Defensive Limits) moves Velo from "Working" to "Titanium".

## 3. Part A: Log Rate Limiting (DoS Protection)

### 3.1 The Vulnerability
Current state in `src/common/util_log_sanitize.rs`:
```rust
// Unbounded processing
pub fn filter_worker_output(output: &str) -> String {
    output.lines().map(sanitize).collect()
}
```
A worker loop `while True: print("[SUP] spoof")` will saturate the CPU and supervisor logs.

### 3.2 The Solution: Token Bucket
Introduce a `RateLimiter` per worker pipe.

**Specification**:
-   **Limit**: Default `100` messages/second per worker.
-   **Burst**: Allow `50` messages burst.
-   **Action**: Drop messages exceeding limit.
-   **Feedback**: Emit a single `[RATE-LIMITED]` warning every second if drops occur.

**Implementation Note**:
-   **CONSTRAINT**: Do NOT use heavy crates like `governor`. Use a lightweight `AtomicU64` timestamp bucket or `quanta`.
-   **Forensic Preservation**: The *first* `[SPOOFED]` tag of any worker lifecycle MUST always be logged (bypass limit) to preserve evidence.
-   **SPOOFED** tags should have a *stricter* limit (e.g., 10/sec).

## 4. Part B: IPC Buffer Pooling (Memory Efficiency)

### 4.1 The Overhead
Current state in `src/zygote/core_ipc.rs`:
```rust
fn write_message(...) {
    let mut buf = Vec::new(); // Malloc #1
    let mut ser = Serializer::new(&mut buf);
    // ...
}
```

### 4.2 The Solution: Bounded Buffer Recycler
**Concept**: Combat **Allocator Latency** (syscalls & locks) and **Fragmentation** using pre-warmed memory.

**Rust Idiom**:
Use a high-performance **Concurrent Queue** (e.g., `crossbeam::queue::ArrayQueue`) or a simple `Mutex<Vec<Vec<u8>>>` (Stack).

**Hardcore Pattern**:
```rust
// Bounded to prevent memory explosion (Backpressure)
// "Hot Cache" of pre-warmed buffers
static BUFFER_REC_QUEUE: Lazy<ArrayQueue<Vec<u8>>> = ...
```

**Workflow**:
1.  `let buf = pool.get() || Vec::with_capacity(4096);`
2.  `buf.clear();` (Retain capacity)
3.  Serialize into `buf`.
4.  Write to socket.
5.  `pool.put(buf);` (If pool not full)

**Constraint**:
-   Max buffer size in pool: `64KB` (prevent hoarding giant buffers).
-   If `buf.capacity() > 64KB`, drop it instead of returning to pool.

## 5. Part C: Hardcore Optimizations (Zero-Copy & Stack)

> **Authority**: Performance Council Deep Dive

### 5.1 Stack-First Handshake (`SmallVec`)
**Motivation**: `malloc` latency is unpredictable.
**Change**: Use `SmallVec<[u8; 1024]>` for initial handshake packets.
**Benefit**: Zero heap allocation for 99% of control messages.

### 5.2 Experimental: Unsafe String Casting (Benchmark Gated)
**Status**: **PROVISIONAL** (Requires >15% CPU gain to adopt)
**Motivation**: Validating UTF-8 for every log line is expensive.
**Strategy**:
1. Implement the *Safe Path* (Standard `String::from_utf8_lossy`) first.
2. Benchmark against `unsafe { from_utf8_unchecked }`.
3. **Decision**: Only enable `unsafe` optimization if the benchmark shows significant (>15%) cleanup throughput improvement.
**Safety**: Code must be behind a `#[cfg(feature = "unsafe_log_fast_path")]` feature gate, disabled by default.

## 6. Part D: The Nuclear Option II (Future Audio/Video Tech)

> **Context**: User requested "Audio/Video Grade" Zero-Copy tech.
> **Status**: Phase XII Research (Post-0031).

### 6.1 True Zero-Copy Deserialization (`rkyv`)
**Problem**: `MessagePack` (rmp-serde) still requires parsing/copying from buffer to struct.
**Solution**: Use `rkyv`. It guarantees the *serialized* representation is the same as the *in-memory* representation.
**Benefit**: `Access time = 0`. No parsing. Just a pointer cast (validated).

### 6.2 Lock-Free Shared Memory Ring Buffer (`rtrb`)
**Problem**: Unix Sockets still tax the kernel (syscalls, copying from user to kernel space).
**Solution**: **SPSC Ring Buffer in Shared Memory (`shm_open` + `mmap`)**.
**Benefit**:
*   **Kernel Bypass**: Reader/Writer coordinate via Atomic Indices in RAM. No syscalls.
*   **Latency**: Sub-microsecond (Audio/HFT grade).
*   **Safety**: Use `rtrb` crate (wait-free, safe Rust wrapper).

## 7. Security Implications

*   **Rate Limiting**: Critical for preventing Side-Channel DoS where a tenant spams logs to degrade neighbors.
*   **Buffer Reuse**: Must ensure `buf.clear()` is called to prevent data leakage between requests.
*   **Unsafe**: Strict audit required for any `unsafe` block.

## 7. Verification Plan

1.  **DoS Benchmark**:
    *   Spawn a worker that prints 1,000,000 lines.
    *   Expect Supervisor CPU usage < 10%.
    *   Expect Log file size < 10MB.
2.  **Allocation Benchmark**:
    *   Profile `fork` loop.
    *   Expect `malloc` calls to drop by >90%.

## 7. Approval
> Pending Council Review
