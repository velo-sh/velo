# Velo Transmutation Engine: A Technical Whitepaper
**Subtitle**: "Python is a precise natural language" — 0xMaster
**Status**: PUBLIC
**Version**: 1.1 (Phase IV Strategy)

---

## 1. Executive Summary
This whitepaper outlines the architectural vision for **Velo Phase IV: The DSL Transmutation**. 

> "Python is a precise natural language." — 0xMaster

We embrace this philosophy to transcend the limitations of the Python Runtime. We view Python source code not merely as an interpreted script, but as the **natural language interface** for configuring and orchestrating a high-performance **Rust/Tokio Runtime**.

By bridging the gap between Python coroutines and Tokio tasks, and by compiling compute-heavy logic into WebAssembly (WASM), we aim to achieve **nanosecond-level scheduling latency** and **native execution speed**, while preserving the expressive power of this precise natural language.

## 2. The Problem: "Two Worlds" Architecture
Current state-of-the-art Python ASGI servers (including Velo Phase 7) suffer from a fundamental "Two Worlds" split:

*   **The Rust World (Kernel)**: Uses `Tokio` for I/O. Extremely fast, work-stealing scheduler, thread-per-core scalability.
*   **The Python World (Userland)**: Uses `asyncio` Event Loop. Single-threaded, GIL-bound, overhead in task switching.

**The Bottleneck**: Every I/O operation requires a "Context Switch" across the FFI boundary. 
1.  Rust finishes I/O -> Acquires GIL -> Wakes Python Loop.
2.  Python Loop wakes -> Schedules Task -> Task runs.
This "Handoff" adds significant latency (microseconds) compared to pure Go/Rust (nanoseconds).

## 3. The Solution: Unified Scheduler Architecture

We propose to **eliminate the Python Event Loop** entirely for critical paths. Instead, Python `async/await` syntax will drive the **Tokio Scheduler** directly.

### 3.1 Core Tech I: The Rusty Wrapper (`velo.spawn`)
**Goal**: Run Python Coroutines as native Tokio Tasks.

#### Developer Experience
```python
# No more asyncio.create_task()
velo.spawn(my_coroutine()) 
```

#### Implementation Magic
Velo implements a custom `Future` in Rust: `PyCoroutineWrapper`.
1.  **Poll**: When Tokio polls this wrapper, it temporarily acquires the GIL.
2.  **Drive**: It calls `.send()` on the Python coroutine object.
3.  **Bridge**: If the python coroutine yields a future (e.g., socket read), Velo intercepts it.
4.  **Short-Circuit**: Instead of returning control to a Python Loop, Velo registers the **Tokio Waker** directly to the underlying resource.
5.  **Result**: The Python coroutine is "parked" in Rust. When I/O completes, **Tokio** wakes it up, not Python.

### 3.2 Core Tech II: WASM Transmutation (The Logic Engine)
**Goal**: Remove the GIL entirely for business logic.

#### Developer Experience
```python
@velo.compile(backend="wasm")
async def heavy_compute(data: bytes):
    hash = calc_hash(data)
    await db.save(hash)
```

#### Implementation Magic
1.  **Transmutation**: Velo compiles the Python function (subset) into **WASM**.
2.  **Asyncify**: Since WASM lacks native async, we use "Asyncify" to save/restore stack state, bridging it to Rust `Futures`.
3.  **WasmFuture**: A Rust `Future` that drives the WASM VM (`Wasmtime`).
4.  **Unified**: `WasmFuture` implementation runs on the **same Tokio Thread Pool** as I/O tasks.

## 4. The Endgame Architecture

```mermaid
graph TD
    A[User Code: Python] -->|velo.spawn| B(Rusty Wrapper)
    A -->|@velo.compile| C(WASM Module)
    
    subgraph "Velo Runtime (Rust)"
        B -->|Poll| D{Tokio Scheduler}
        C -->|Poll| D
        D -->|Work Stealing| T1[Thread 1]
        D -->|Work Stealing| T2[Thread 2]
    end
    
    T1 -->|Execute| E[epoll / io_uring]
```

## 5. Strategic Value
1.  **Performance**: Eliminates the "Interpreter Tax" for I/O scheduling and compute.
2.  **Density**: High-density concurrency (thousands of workers) via COW + WASM Shared Memory.
3.  **Ecosystem**: Fully compatible with existing Python libraries (via Rusty Wrapper fallback).

**Verdict**: Velo becomes the **System Apex**, offering the speed of Go/Rust with the simplicity of Python.
