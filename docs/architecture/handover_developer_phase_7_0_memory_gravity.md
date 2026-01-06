# Handover: Developer (Phase 7.0 - Memory Gravity Core)

> **Mission**: Implement the **TITANIUM-Grade** Memory Gravity infrastructure relative to RFC-0015.
> **Role**: Developer (ID-LOCK-002)
> **Compliance Level**: **STRICT**. No deviations from H-Invariants allowed.

## 1. High-Level Architecture

You are building the **Trust-Domain-Local Execution Fabric**.
- **Rust Host**: Owns lifecycle, allocation, sealing, and cleanup.
- **Python Worker**: Zero-copy consumer (Read-Only).
- **Communication**: Unix Domain Socket (SCM_RIGHTS FD passing).

---

## 2. Critical Implementation Tasks (Invariants)

### A. The Registry (`src/shm/registry.rs`)

**Task**: Implement `MemoryRegistry` with strict lifecycle control.

1.  **H-26: Host Death Containment (Priority 1)**
    - **Requirement**: Use PID Namespaces.
    - **Action**: Verify `creation_flags` or container runtime config ensures Host is PID 1 in its namespace.
    - **Defense**: If Host dies, Kernel MUST auto-reap all workers.
    
2.  **H-23: Seal Ordering (Priority 1)**
    - **Algorithm**:
      ```rust
      // 1. Create
      let fd = memfd_create(name, MFD_CLOEXEC | MFD_ALLOW_SEALING)?;
      // 2. Map RW
      let ptr = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0)?;
      // 3. Populate
      populate_from_safetensors(ptr, data)?;
      // 4. Unmap RW (CRITICAL BARRIER)
      munmap(ptr, size)?;
      // 5. Map RO Check
      let ptr_ro = mmap(NULL, size, PROT_READ, MAP_SHARED, fd, 0)?;
      // 6. Verify Maps (H-23.6)
      verify_no_writable_maps(pid)?; 
      // 7. Seal
      fcntl(fd, F_ADD_SEALS, F_SEAL_WRITE | F_SEAL_SHRINK | F_SEAL_GROW)?;
      ```

3.  **H-29: Alignment Enforcement (The Padding Paradox)**
    - **Action**: Implement the padding algorithm defined in RFC-0015 Appendix A.
    - **Constraint**: `(sizeof(u64) + header_len) % 64 == 0`.
    - **Fail-Fast**: If existing header is misaligned and cannot be padded (edge case), abort loading.

4.  **H-30: NUMA Fail-Fast (Strict Mode)**
    - **Action**: On startup, query `libnuma`.
    - **Check**: If `num_nodes > 1` AND `VELO_STRICT_NUMA=1`:
      - Allocated memory MUST be bound to specific node (`mbind`).
      - Worker PID MUST be pinned to same node.
      - If mismatch functionality -> **PANIC**.

### B. The Python Wrapper (`velo_zygote/memory.py`)

1.  **H-17: Immutability Defense**
    - **Action**: Monkey-patch `torch.Tensor.data_ptr()` or use a descriptor to warn on access.
    - **Safety**: Wrap `mmap` buffer in `contextlib.ExitStack` to ensure strict resource tracking.

2.  **H-31: Lazy Unmap Support**
    - **Action**: Handle `SHM_EXPIRE` message.
    - **Logic**: When Host broadcasts expire, Python MUST drop all tensor references within 100ms.

---

## 3. Day 2 "Engineering Reality"

- **Execution Barrier**: You rely on **100ms Grace Period**. Do NOT attempt complex ack protocols for v0.7.0.
- **FD Containment**: If you detect a worker writing to shared memory (via side-channel), **SIGKILL** it immediately.

## 4. Verification Requirements (Unit Tests)

You must write these specific tests in `tests/shm_tests.rs`:

- **L3-SHM-10 (Malicious Worker)**:
  - Fork a child.
  - Pass the sealed FD.
  - Child tries: `mprotect(PROT_WRITE)`, `write()`, `ftruncate()`.
  - **Assert**: All MUST fail with `EPERM`.

- **L4-SHM-11 (Alignment)**:
  - Generate random safetensors headers (lengths 1..1024).
  - Run `write_aligned_safetensors`.
  - **Assert**: Output file tensor offset is always `% 64 == 0`.

## 5. Artifacts Checklist
- [ ] `src/shm/mod.rs` (Module def)
- [ ] `src/shm/registry.rs` (Core Logic)
- [ ] `src/shm/alignment.rs` (H-29 Padding)
- [ ] `velo_zygote/memory.py` (Python binding)
- [ ] `tests/shm_tests.rs` (Security tests)
