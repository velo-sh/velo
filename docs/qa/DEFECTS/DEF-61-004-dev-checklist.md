# DEF-61-004: Developer Handover Checklist

> **Parent**: [DEF-61-004-protocol-socket-isolation.md](./DEF-61-004-protocol-socket-isolation.md)
> **Type**: Developer Task Assignment
> **Estimated Hours**: 4.5h

---

## Task Summary

Implement protocol version socket isolation to resolve 30-second timeout after binary upgrade.

---

## Implementation Checklist

### Phase 1: Rust Side (2h)

- [ ] **1.1** Modify `src/zygote/ipc.rs`
  - [ ] Export `PROTOCOL_VERSION` constant
  - [ ] Implement `get_socket_dir()` - user-isolated directory
  - [ ] Implement `is_socket_alive()` - connection test
  - [ ] Implement `cleanup_stale_sockets()` - cleanup old sockets
  - [ ] Modify `default_socket_path()` - include version number

- [ ] **1.2** Modify `src/zygote/mod.rs`
  - [ ] Call `cleanup_stale_sockets()` in `ZygoteLauncher::start()`

### Phase 2: Python Side (1h)

- [ ] **2.1** Modify `velo_zygote/main.py`
  - [ ] Add `get_socket_dir()` function
  - [ ] Add `get_versioned_socket_path()` function
  - [ ] Modify `ZygoteServer` to use new path

### Phase 3: Edge Cases (1h)

- [ ] **3.1** Permission handling
  - [ ] Set 0700 permissions after directory creation
  - [ ] Verify permissions were set correctly

- [ ] **3.2** Path length limit
  - [ ] Check path < 108 characters
  - [ ] Fall back to `/tmp` if too long

- [ ] **3.3** Error handling
  - [ ] Ignore permission errors during cleanup
  - [ ] Return gracefully if directory doesn't exist

### Phase 4: Verification (0.5h)

- [ ] **4.1** Run `cargo test`
- [ ] **4.2** Run `./scripts/benchmark_startup.sh`
- [ ] **4.3** Verify upgrade scenario

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/zygote/ipc.rs` | +4 functions, modify 1 |
| `src/zygote/mod.rs` | +1 call |
| `velo_zygote/main.py` | +2 functions, modify 1 |

---

## Reference Documents

- [DEF-61-004-protocol-socket-isolation.md](./DEF-61-004-protocol-socket-isolation.md) - Full design
- [DEF-61-004-qa-review.md](./DEF-61-004-qa-review.md) - QA test specifications

---

## Critical Implementation Notes

1. **Permissions**: Verify mode is 0700 after `set_permissions`
2. **Path length**: Unix Socket limit is 108 chars, macOS deep $TMPDIR needs fallback
3. **Error handling**: `cleanup_stale_sockets()` must not panic

---

## Acceptance Criteria

| AC | Description | Test |
|----|-------------|------|
| AC-1 | Socket path includes version | T2 |
| AC-2 | User-isolated directory | T5 |
| AC-3 | Connection test before cleanup | T3 |
| AC-4 | Directory permissions 0700 | T4 |
| AC-5 | Benchmark passes | Manual |
| AC-6 | No regression | CI |
| AC-7 | Path length < 108 | T6 |
| AC-8 | Graceful error handling | T7 |

---

**Developer Sign-off**: [ ] Ready to implement
**Estimated Completion**: 4.5 hours
