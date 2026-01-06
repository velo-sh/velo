# H-31 Deep Dive: The In-Flight Execution Barrier

> **Status**: RESEARCH / ADVISORY
> **Context**: RFC-0015 Memory Gravity
> **Problem**: Host `munmap()` synchronization with Worker CPU pipeline.

## 1. The Physics of the Problem

In userspace Linux, **it is impossible to guarantee** that a `munmap()` call on the Host does not cause a SIGBUS/SEGV on a Worker that is effectively "still executing" instructions referencing that memory.

**The Race Condition**:
1. **Time T0**: Worker CPU Pipeline fetches instruction `vmovups ymm0, [ptr]`.
2. **Time T0 + ε**: Worker CPU Speculative Load Unit accesses `ptr`.
3. **Time T0 + 2ε**: Host calls `munmap(ptr)`.
4. **Time T0 + 3ε**: TLB Shootdown propagates.
5. **Time T0 + 4ε**: Worker instruction commits (or faults).

There is no "Quiesce" primitive in standard Linux `mmap` API to say "wait until all remote TLBs and Pipelines have flushed this address".

## 2. Solution Landscape

### Solution 1: Execution Quiescence Barrier (Ack) - *The Controlled Path*
**Mechanism**:
1. Host sends `QUIESCE_REQUEST` to Worker.
2. Worker finishes current batch, hits a safe point (barrier), and replies `QUIESCED`.
3. Host `munmap()`.

- **Pros**: Deterministic, OS-independent.
- **Cons**: Requires Worker cooperation (code change), still has theoretical micro-architectural race (speculation).

### Solution 2: Lazy Unmap + TTL - *The v0.7.0 Engineering Selection*
**Mechanism**:
1. Host marks segment as `EXPIRED`.
2. Host waits `Grace_Period` (e.g., 100ms).
3. Host `munmap()`.

- **Pros**: Simple, Zero Worker Code Change, Works for "Good Enough" production.
- **Cons**: Probabilistic, not deterministic.

### Solution 3: Kernel / TEE Support - *The Theoretical Ideal*
**Mechanism**:
- Rely on Kernel `madvise(MADV_DONTNEED)` with a new flag wait for process quiescence (features not present in mainline Linux).
- Or run within a TEE/Enclave that enforces memory view updates atomically.

- **Pros**: 100% Safe.
- **Cons**: Does not exist in standard Linux.

## 3. Hostile Verdict

> "You cannot guarantee 100% safety for `munmap` in userspace Linux. Any attempt to do so is betting against the CPU pipeline."

**Decision for v0.7.0**:
- Accept **Solution 2 (Lazy Unmap)**.
- Acknowledge the theoretical race as a hardware/OS limitation.
- **H-31** is marked as a "Day 2" requirement because fixing it requires moving to Solution 1 (Protocol Change) or Solution 3 (Kernel Change).
