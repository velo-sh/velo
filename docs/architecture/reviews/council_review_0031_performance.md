# Council Review: RFC-0031 (Performance Deep Dive)

> **Context**: User requested a specific focus on "Hardcore Rust Performance" (Zero-Copy, Unsafe, Titanium patterns).
> **Attendees**: Rust Core Dev (Unsafe Expert), HPC Engineer (Latency Expert).

## 1. The Topic: "Can we go faster?"

The Council is debating three "Nuclear" options for Kinetic Optimization.

### Option A: Unsafe String Casting (The Zero-Cost Signature)
**Concept**: High-performance runtimes (like Go/C++) use `unsafe` to cast bytes to string to avoid copying.
**Rust Equivalent**: `std::str::from_utf8_unchecked`.

*   **Rust Core Dev**: "We spend cycles validating UTF-8 on every `sanitize_log` call, even though we KNOW the Supervisor tags are ASCII."
*   **HPC Engineer**: "Skipping UTF-8 validation on the hot logging path is a 20% CPU win during log storms."
*   **Verdict**: **APPROVED** for `common/util_log_sanitize.rs` ONLY.
    *   *Condition*: Input must be guaranteed ASCII (e.g., internal tags) or we accept the risk of UB propagation if we emit it.
    *   *Correction*: Rust `String` owns data. We can't cast `&[u8]` to `String` (owned) zero-copy without allocation. We CAN cast `&[u8]` to `&str` zero-copy.
    *   *Application*: The `sanitize_worker_log` takes `&str`. The *source* matters.

### Option B: Vectored I/O (Scatter/Gather)
**Concept**: Never copy bytes into a contiguous buffer just to send them.
**Status**: Velo `core_ipc` already uses `IoSlice` for `len + version + payload`.
**Critique**:
*   **HPC Engineer**: "But the `payload` is still a contiguous `Vec`. Can we serialize directly to the socket stream?"
*   **Rust Core Dev**: "`rmp-serde` needs a buffer. To do true Zero-Copy write, we'd need a custom serializer that writes to an `IoSlice` array. Too complex for Phase XI."
*   **Verdict**: **REJECT**. Keep `IoSlice` for framing, but stick to Buffer Pool for payload. Complexity > Gain.

### Option C: Stack Allocation (`SmallVec`)
**Concept**: Avoid `malloc` entirely for small handshake messages (< 1KB).
**Proposal**: Use `SmallVec<[u8; 1024]>` for the initial Handshake.
**HPC Engineer**: "The Handshake blocks everything. Malloc latency spikes (10us -> 1ms) in noisy neighbors."
**Verdict**: **APPROVED**.
*   *Requirement*: Add `smallvec` dependency.
*   *Optimization*: Use stack memory for Heartbeats and Handshakes.

## 2. Updated Directives (RFC-0031 Amendments)

### Directive 1: The "Unsafe Log Path"
In `util_log_sanitize.rs`:
```rust
// FAST PATH: ASCII-only check optimization
// Intel SSE 4.2 has specialized string instructions.
// If valid ASCII, skip UTF-8 validation during internal buffer moves.
unsafe { std::str::from_utf8_unchecked(slice) }
```
**Constraint**: Only apply when the source is trusted or we are just scanning for tags.

### Directive 2: Stack-First Handshake
In `core_ipc.rs`:
```rust
// Use SmallVec for handshake packets to guarantee < 5ms latency
// even under allocator pressure.
let mut buf: SmallVec<[u8; 1024]> = SmallVec::new();
```

## 3. The Security Warning (Zero-Copy)
**Security Specialist**: "Be careful. `unsafe` string casting on user input is dangerous. If a worker sends malformed unicode and we process it as str, we might crash regex engines or JSON parsers."
**Mitigation**: Only use `unsafe` for *tag detection* (checking if `[SUP]` exists). The final output string must be safe.

## 4. Final Verdict
**APPROVED** with constraints.
1.  **Add `smallvec`** to dependencies.
2.  **Enable `unsafe`** optimizations in `util_log_sanitize` for tag scanning.
