# Council Review: RFC-0031 (Kinetic Optimization)

> **Authority**: [SOP-001 Master Lifecycle](../SOP-001-master-lifecycle.md)
> **Target**: [RFC-0031: Kinetic Optimization](../../docs/rfcs/0031-kinetic-optimization.md)
> **Status**: **CONDITIONAL APPROVAL**

## 1. The Summons (Reviewers)

| Role | Persona | Focus |
|:---|:---|:---|
| **Rust Core Dev** | `SYSTEMS_SAFETY` | Dependency weight & Memory safety |
| **Python Core Dev** | `RUNTIME_INTERNALS` | Worker pipe blocking behavior |
| **HPC Engineer** | `PERFORMANCE` | Allocator pressure & Critical path latency |

## 2. The Critique

### 🦀 Rust Core Dev (Systems)
> "I see you suggested the `governor` crate for rate limiting. That pulls in `parking_lot` and other heavy dependencies. For Velo's 'Titanium' standard, we prefer minimal deps."

*   **Critique**: `governor` is overkill for simple log dropping.
*   **Requirement (P0)**: Use a lightweight `AtomicU64` timestamp-based token bucket or a simple `Quanta` based solution. **Reject** heavy dependencies for this micro-feature.
*   **Safety**: Buffer pooling looks safe, provided `buf.clear()` is enforced.

### 🐍 Python Core Dev (Runtime)
> "Dropping logs on the Supervisor side is actually a huge stability win for Python. If the Supervisor is slow (busy writing to disk), the pipe fills up, and the Python worker's `print()` blocks, causing a deadlock."

*   **Endorsement**: By implementing "Drop on Overflow", we ensure the `stdout` pipe remains drained. This prevents **Worker Deadlock** during high-load scenarios.
*   **Optimization**: Ensure we don't drop the *first* evidence of an attack.
*   **Requirement (P1)**: The first `[SPOOFED]` tag of a session MUST always be logged (Forensic Evidence), even if rate limited.

### ⚡ HPC Engineer (Performance)
> "Channel-based pooling is fine, but `std::sync::mpsc` can be contended. Since `core_ipc` is multi-threaded (per request), verify the channel implementation."

*   **Critique**: `std::sync::Mutex<Vec<T>>` might actually be faster than a Channel for simple pooling if specific lock contention is low.
*   **Endorsement**: The `64KB` cap aligns perfectly with Linux default pipe size (`/proc/sys/fs/pipe-max-size`), minimizing syscalls.
*   **Requirement (P0)**: Benchmark `fork` latency. If `Channel` overhead > `malloc` overhead (unlikely, but possible for small packets), switch to `crossbeam` or simple `Mutex`.

## 3. The Verdict

**Final Decision**: **CONDITIONAL APPROVAL**

The design is sound, but the implementation must adhere to strict dependency hygiene.

### 🛑 Blocking Requirements (P0)
1.  **No Heavy Deps**: Do not use `governor`. Implement a native `Atomic` token bucket.
2.  **Forensic Preservation**: Always log the **first** spoofed message per worker lifecycle.
3.  **Buffer Hygiene**: Enforce `buf.clear()` immediately upon retrieval from pool.

### 📝 Action Items
*   [ ] Update RFC-0031 to specify "Native Atomic Rate Limiter" instead of `governor`.
*   [ ] Update RFC-0031 to include "First-Spoof Retention" policy.
*   [ ] Proceed to Implementation.
