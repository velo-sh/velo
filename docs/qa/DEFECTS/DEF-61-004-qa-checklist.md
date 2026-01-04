# DEF-61-004: QA Handover Checklist

> **Parent**: [DEF-61-004-protocol-socket-isolation.md](./DEF-61-004-protocol-socket-isolation.md)
> **Type**: QA Task Assignment
> **Total Test Cases**: 17

---

## 📋 QA Summary

Verify Protocol Version Socket Isolation implementation, ensuring upgrade/downgrade scenarios work correctly.

**Test Scaffolding Status**: ✅ Complete (18 tests: 3 PASSED, 15 XFAIL awaiting dev)

---

## ✅ Test Implementation Checklist

### Phase 0: Test Setup

- [x] **0.1** Create test file `tests/qa/test_def_61_004_socket_isolation.py`
- [x] **0.2** Import required modules (pytest, mock, tempfile)
- [x] **0.3** Set up fixtures (temp directories, mock sockets)
- [x] **0.4** Create performance test file `tests/qa/test_def_61_004_performance.py`

### Phase 1: Core Tests (T1-T5)

- [ ] **T1** Version upgrade cleans old socket (xfail - awaiting dev)
- [ ] **T2** Socket path format correct (xfail - awaiting dev)
- [ ] **T3** Active socket NOT deleted (xfail - awaiting dev)
- [x] **T4** Directory permissions 0700 ✅ PASSED
- [x] **T5** Multi-user isolation ✅ PASSED

### Phase 2: Edge Case Tests (T6-T10)

- [ ] **T6** Long $TMPDIR path fallback (xfail - awaiting dev)
- [ ] **T7** Permission error graceful handling (xfail - awaiting dev)
- [ ] **T8** Concurrent startup no race (xfail - awaiting dev)
- [ ] **T9** Symlink attack protection (xfail - awaiting dev)
- [ ] **T10** Disk space exhausted (xfail - awaiting dev)

### Phase 3: Regression Tests (REG-001 to REG-004)

- [ ] **REG-001** Fresh install v0.6.2 (xfail - awaiting dev)
- [ ] **REG-002** Upgrade v0.6.1 → v0.6.2 (xfail - awaiting dev)
- [ ] **REG-003** Downgrade v0.6.2 → v0.6.1 (xfail - awaiting dev)
- [ ] **REG-004** Multi-user parallel (xfail - awaiting dev)

### Phase 4: Performance Tests

- [ ] **AC-9** `get_socket_dir()` < 1ms (xfail - awaiting dev)
- [ ] **AC-10** `cleanup_stale_sockets()` < 100ms (xfail - awaiting dev)
- [x] **AC-11** Socket connection < 5ms ✅ PASSED

---

## 📁 Test Files

| File | Tests |
|------|-------|
| `tests/qa/test_def_61_004_socket_isolation.py` | T1-T10, REG-001-004 |
| `tests/qa/test_def_61_004_performance.py` | AC-9, AC-10, AC-11 |

---

## 🔗 Reference Documents

- [DEF-61-004-qa-review.md](./DEF-61-004-qa-review.md) - Full pytest specification
- [DEF-61-004-protocol-socket-isolation.md](./DEF-61-004-protocol-socket-isolation.md) - Design document

---

## 🧪 Test Matrix

### Version Compatibility

| Scenario | New CLI | Old CLI | Expected |
|----------|---------|---------|----------|
| New Zygote only | ✅ Connect | ❌ Fail | Isolation |
| Old Zygote only | ❌ Fail | ✅ Connect | Isolation |
| Both running | ✅ Use new | ✅ Use old | Coexist |

### Platform Coverage

| Platform | Required |
|----------|----------|
| macOS (Intel) | ✅ |
| macOS (ARM) | ✅ |
| Linux (Ubuntu) | ✅ |
| Linux (Alpine) | Optional |

---

## ⚠️ Test Environment Requirements

1. **Two Velo versions**: v0.6.1 (JSON) and v0.6.2 (MessagePack)
2. **Multi-user testing**: Requires two different UID users
3. **Permission testing**: May require elevated privileges

---

## 🎯 Verification Criteria

| AC | Description | Test(s) | Pass Criteria |
|----|-------------|---------|---------------|
| AC-1 | Version in path | T2 | Path contains `zygote-v1.sock` |
| AC-2 | User isolation | T5 | Path contains `velo-{UID}/` |
| AC-3 | Connection test | T1, T3 | Active socket preserved |
| AC-4 | Permissions 0700 | T4 | `stat` verification |
| AC-5 | Benchmark | Manual | No 30s timeout |
| AC-6 | No regression | CI | All tests pass |
| AC-7 | Path < 108 | T6 | Fallback on long paths |
| AC-8 | Error handling | T7 | No panic |
| AC-9 | dir < 1ms | Perf | benchmark |
| AC-10 | cleanup < 100ms | Perf | benchmark |
| AC-11 | connect < 5ms | Perf | benchmark |

---

## 📊 Test Execution Order

```
1. Unit Tests (T1-T5)        ← Execute after Developer completes
2. Edge Case Tests (T6-T10)  ← After Developer fixes
3. Regression Tests          ← Before merge
4. Performance Tests         ← Final step
```

---

**QA Sign-off**: [ ] Ready to test
**Blocked by**: Developer implementation complete
