# DEF-61-004: QA Work Handover

> **From**: QA Engineer (Current Session)
> **To**: Next QA Engineer
> **Date**: 2026-01-04
> **Branch**: `hotfix/protocol-socket-isolation`
> **Commit**: `72579fb`

---

## 🎯 Problem Summary

**P0 BLOCKER**: Zygote warm start takes **30 seconds** instead of <1ms due to IPC protocol mismatch after binary upgrade.

| Component | Protocol |
|-----------|----------|
| Old Zygote (v0.6.1) | JSON |
| New CLI (v0.6.2) | MessagePack |

**Solution**: Version-specific socket paths with user isolation.
```
$TMPDIR/velo-{UID}/zygote-v{PROTOCOL_VERSION}.sock
```

---

## ✅ What Was Done

### 1. Test Scaffolding Created

| File | Tests | Status |
|------|-------|--------|
| `tests/qa/test_def_61_004_socket_isolation.py` | 14 | Ready |
| `tests/qa/test_def_61_004_performance.py` | 4 | Ready |

### 2. Test Results (Current)

```bash
# Run all DEF-61-004 tests
uv run pytest tests/qa/test_def_61_004*.py -v
```

| Category | Tests | PASSED | XFAIL |
|----------|-------|--------|-------|
| Core (T1-T5) | 5 | 2 | 3 |
| Edge (T6-T10) | 5 | 0 | 5 |
| Regression (REG-001-004) | 4 | 0 | 4 |
| Performance (AC-9-11) | 4 | 1 | 3 |
| **Total** | **18** | **3** | **15** |

### 3. Tests Already Passing

| Test | Description | Why It Passes |
|------|-------------|---------------|
| T4 | Directory permissions 0700 | Pure Python test, no dev code needed |
| T5 | Multi-user isolation | Path verification logic only |
| AC-11 | Socket connection < 5ms | Standard Unix socket test |

---

## ⏳ What's Pending (Blocked on Developer)

### Developer Must Implement:

| File | Function | Purpose |
|------|----------|---------|
| `src/zygote/ipc.rs` | `get_socket_dir()` | User-isolated directory |
| `src/zygote/ipc.rs` | `is_socket_alive()` | Connection test |
| `src/zygote/ipc.rs` | `cleanup_stale_sockets()` | Clean old sockets |
| `src/zygote/ipc.rs` | `default_socket_path()` | Versioned socket path |
| `velo_zygote/main.py` | `get_socket_dir()` | Python mirror |
| `velo_zygote/main.py` | `get_versioned_socket_path()` | Python mirror |

### Tests Awaiting Dev Implementation:

When developer implementation lands, update these tests by:
1. Remove `@pytest.mark.xfail` decorator
2. Uncomment the TODO sections
3. Import actual functions from `velo.zygote.ipc`

```python
# Example: tests/qa/test_def_61_004_socket_isolation.py

# BEFORE (current scaffolding):
@pytest.mark.xfail(reason="Awaiting developer implementation")
def test_t1_version_upgrade_cleans_old_socket(self, ...):
    # TODO: Call cleanup_stale_sockets() when implemented
    pytest.fail("Developer implementation required")

# AFTER (when dev is ready):
def test_t1_version_upgrade_cleans_old_socket(self, ...):
    from velo.zygote.ipc import cleanup_stale_sockets
    cleanup_stale_sockets()
    assert not old_socket.exists()
```

---

## 📋 QA Action Items for Next Session

### When Developer Implementation Lands:

- [ ] **1.** Pull latest changes from `hotfix/protocol-socket-isolation`
- [ ] **2.** Update T1, T2, T3 with actual imports and assertions
- [ ] **3.** Update T6-T10 edge case tests
- [ ] **4.** Update REG-001 to REG-004 regression tests
- [ ] **5.** Update AC-9, AC-10 performance benchmarks
- [ ] **6.** Run full test suite: `uv run pytest tests/qa/test_def_61_004*.py -v`
- [ ] **7.** Verify AC-5: Run `./scripts/benchmark_startup.sh` (no 30s timeout)
- [ ] **8.** Update test status in `DEF-61-004-qa-checklist.md`

### Acceptance Criteria Verification:

| AC | Description | How to Verify |
|----|-------------|---------------|
| AC-1 | Socket path has version | Check path contains `zygote-v1.sock` |
| AC-2 | User isolation | Check path contains `velo-{UID}/` |
| AC-3 | Connection test | T3: Active socket preserved |
| AC-4 | Permissions 0700 | T4: ✅ Already PASSED |
| AC-5 | No 30s timeout | Manual benchmark |
| AC-6 | No regression | CI: All 182 Rust tests pass |
| AC-7 | Path < 108 chars | T6: Long path fallback |
| AC-8 | Error handling | T7: No panic on permission error |
| AC-9 | dir < 1ms | Performance benchmark |
| AC-10 | cleanup < 100ms | Performance benchmark |
| AC-11 | connect < 5ms | ✅ Already PASSED |

---

## 🔧 How to Run Tests

```bash
# Switch to hotfix branch
git checkout hotfix/protocol-socket-isolation
git pull origin hotfix/protocol-socket-isolation

# Run DEF-61-004 tests only
uv run pytest tests/qa/test_def_61_004*.py -v

# Run with performance tests
uv run pytest tests/qa/test_def_61_004*.py -v -m performance

# Run specific test
uv run pytest tests/qa/test_def_61_004_socket_isolation.py::TestSocketPathFormat::test_t4_directory_permissions_0700 -v
```

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `docs/qa/DEFECTS/DEF-61-004-protocol-socket-isolation.md` | Design document |
| `docs/qa/DEFECTS/DEF-61-004-qa-review.md` | Full pytest specification |
| `docs/qa/DEFECTS/DEF-61-004-qa-checklist.md` | QA checklist (update this) |
| `docs/qa/DEFECTS/DEF-61-004-dev-checklist.md` | Developer checklist |
| `tests/qa/test_def_61_004_socket_isolation.py` | Core/Edge/Regression tests |
| `tests/qa/test_def_61_004_performance.py` | Performance tests |

---

## ⚠️ Known Issues / Gotchas

1. **Socket path length**: Unix sockets have 108-char limit. macOS `$TMPDIR` can be deeply nested.
2. **pytest.mark.performance**: Not registered in pytest.ini - shows warning but tests run fine.
3. **Multi-user tests**: REG-004 may require two different UID users to fully test.

---

## 📊 Git History

```
72579fb qa(DEF-61-004): Add test scaffolding for socket isolation
29e9ca6 ... (developer work on main design docs)
672167e docs: Add Dev and QA handover checklists
```

---

## 🔗 Related Documents

- **Parent RFC**: `docs/rfcs/OPT-0010-001-msgpack-ipc.md`
- **Defect Report**: `docs/qa/DEFECTS/DEF-OPT-002-zygote-ipc-mismatch.md`

---

**Handover Status**: ✅ Complete
**QA Scaffolding**: ✅ Ready
**Blocked On**: Developer implementation of `get_socket_dir()` and `cleanup_stale_sockets()` in `src/zygote/ipc.rs`
