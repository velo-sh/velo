# Engineering Note: Scalable TOCTOU Defense for Large Bundles

**Target Phase**: 7.x (Large Project Support)
**Constraint**: Cannot read entire bundle to RAM (> 1GB projects).
**Security Invariant**: H-5 (Adversarial Resistance) must hold for streamed/mmapped data.

## 1. The Challenge
Current "Atomic Window" (Read-all-to-RAM) prevents TOCTOU during the `Verify -> Execute` phase. With 1GB+ bundles, a user may want to use `mmap` or streaming. If an attacker modifies the disk while Velo is executing from `mmap`, they can inject code *after* the initial header validation.

## 2. Proposed Scalable Defense (H-11)

### A. Merkle Tree / Block-Level Hashing
Instead of a single Global Hash (H-1), large bundles will implement a **Block Hash Table**:
- **Chunking**: Split the bundle into 4KB blocks (matches hardware page size).
- **Verification**: As the `FastLoader` accesses a block (via `mmap` or partial `read`), it verifies the 4KB chunk against its pre-computed BLAKE3 hash.
- **Root Hash**: The Bundle Header only stores the Merkle Root.

### B. Linux `memfd` & Sealing
For high-security environments:
1. `memfd_create()`: Create an anonymous file in RAM.
2. `splice()`: Stream data from disk to `memfd` (Zero-copy).
3. `F_ADD_SEALS`: Apply `F_SEAL_WRITE` and `F_SEAL_GROW`.
4. **Result**: The file becomes **Immutable** at the kernel level. No attacker, regardless of process priority, can modify the data being executed.

## 3. Implementation Status
- **Phase 6.0**: Uses Atomic RAM Window (Safe for current < 256MB limit).
- **Phase 7.x**: Will prioritize Merkle Tree integration into the Rkyv serializer.

---
**Verdict**: The "Atomic" principle remains, but shifts from "Atomic File Read" to "Atomic Block Access" or "Kernel-Level Immutability".
