# Handover: Developer (Phase 7.0 - Memory Gravity Core)

> **Mission**: Implement the foundational SHM Registry in Rust for Zero-Copy Weight Sharing.
> **Role**: Developer (ID-LOCK-002)
> **SOP**: [SOP-001-master-lifecycle.md](../../docs/architecture/SOP-001-master-lifecycle.md)

## 1. Deliverables

### [NEW] `src/runtime/memory.rs`
- **Component**: `ShmRegistry`.
- **Action**: Use `memfd_create` (Linux) or `shm_open` (macOS) to create segments.
- **Logic**: Map a `.safetensors` file into memory and return a shared Handle.

### [MODIFY] `src/proxy/ipc.rs`
- **Action**: Add `SHM_ATTACH` message to the protocol.
- **Payload**: `{"name": "...", "fd": ...}` (Must support FD passing via SCM_RIGHTS).

### [MODIFY] `velo_zygote/main.py`
- **Action**: Implement `mmap_weights(fd, metadata)`.
- **Glue**: Use `numpy.frombuffer` or `torch.as_tensor` to wrap the memory.

## 2. Invariants (Architect's Red Lines)
1. **Read-Only Enforcement**: Segments MUST be `PROT_READ` only on the worker side.
2. **FD Safety**: Ensure FDs are NOT leaked on worker crash/restart.
3. **No Copying**: If `memcpy` is detected during weight attachment, the implementation FAILS.

## 3. Verification
- `test_shm_weight_sharing.py`: Assert that `id(model.layers[0].weights)` in Worker A and Worker B points to the same physical memory address (via `/proc/self/pagemap` or offset analysis).
