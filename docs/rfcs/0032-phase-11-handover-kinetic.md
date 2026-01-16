# RFC-0032: Phase 11 Implementation Handover (Kinetic Optimization)

> **Status**: 🚧 READY FOR DEV
> **Target Version**: v0.11.0 (Kinetic)
> **Parent RFCs**: [RFC-0031](./0031-kinetic-optimization.md) (Tactics), [SPEC-0007](../architecture/SPEC-0007-PERFORMANCE-MASTER-STANDARD.md) (Standard)
> **Date**: 2026-01-17

---

## 1. Executive Summary

This document instructs the **Developer Role** to implement "Titanium Hardcore" performance optimizations. The goal is to maximize **DoS Resilience** and **IPC Efficiency** using purely Rust-native, low-overhead patterns.

**Changes required in**:
- `src/common/util_log_sanitize.rs` (Rate Limiting)
- `src/zygote/core_ipc.rs` (Buffer Pooling, SmallVec)

---

## 2. Mandatory "Red Lines" (Architect Mandate)

### 🔴 Red Line #1: Zero HEAVY Dependencies
- **Forbidden**: Do NOT use `governor` or `tokio-rate-limit`.
- **Requirement**: Implement a simple **Atomic Token Bucket** using `std::sync::atomic::AtomicU64`.
- **Reason**: We cannot afford the dependency weight context switching cost for a simple log guard.

### 🔴 Red Line #2: Forensic Preservation
- **Rule**: If a worker spams logs, you MUST drop the excess, **EXCEPT** for the very first violation.
- **Requirement**: The first `[SPOOFED]` tag or rate-limit breach of a worker's lifecycle **MUST** be logged to preserving evidence.

### 🔴 Red Line #3: Feature-Gated Unsafe
- **Rule**: Any `unsafe` optimization (like `from_utf8_unchecked`) MUST be behind `#[cfg(feature = "unsafe_log_fast_path")]`.
- **Default**: Disabled.

---

## 3. Implementation Guide

### 3.1 Log Rate Limiter (`src/common/util_log_sanitize.rs`)
**Spec**:
- **Bucket**: 100 tokens max. Refill 10/sec.
- **Action**: Return `None` if bucket empty.
- **Warning**: Emit `[RATE-LIMITED]` log max once per second.

### 3.2 Bounded Buffer Recycler (`src/zygote/core_ipc.rs`)
**Spec**:
- **Structure**: `static BUFFER_POOL: Lazy<ArrayQueue<Vec<u8>>>`
- **Capacity**: 128 items.
- **Item Size**: Max 64KB. If `buf.capacity() > 64KB`, drop it (do not return to pool).
- **Pattern**:
    ```rust
    let mut buf = POOL.pop().unwrap_or_else(|| Vec::with_capacity(4096));
    buf.clear(); // CRITICAL: Prevent info leak
    // use buf...
    if buf.capacity() <= 65536 { POOL.push(buf); }
    ```

### 3.3 Stack Handshake
**Spec**:
- Use `smallvec` crate.
- `SmallVec<[u8; 1024]>` for initial handshake serialization.

---

## 4. Verification Requirements

The Developer MUST implement and pass the following verification steps:

1.  **DoS Stress Test**:
    *   Script: `tests/stress/log_flood.py`
    *   Condition: Worker prints 1M lines. Supervisor CPU < 10%. Log file < 10MB.
2.  **Allocation Benchmark**:
    *   Command: `cargo bench --bench ipcfork`
    *   Condition: `malloc` count reduced by > 90% compared to baseline.

---

## 5. Next Steps for Developer

1.  `cargo add smallvec crossbeam-queue`
2.  Implement `RateLimiter` struct.
3.  Refactor `core_ipc.rs` to use `BufferPool`.
4.  Run Benchmarks.

**Architect Sign-off**: ✅ Approved via RFC-0031
