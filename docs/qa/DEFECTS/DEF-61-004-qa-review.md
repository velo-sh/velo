# DEF-61-004: QA Expert Review Appendix

> **Parent**: [DEF-61-004-protocol-socket-isolation.md](./DEF-61-004-protocol-socket-isolation.md)
> **Type**: QA Review Attachment
> **Status**: ⚠️ Conditional Approval

**Document**: DEF-61-004-protocol-socket-isolation.md
**Review Date**: 2026-01-04
**Reviewers**: 4 QA Experts

---

## QA Expert 1: Test Architect

### Verdict: ⚠️ Test Coverage Insufficient

**Additional Test Cases Required**:

| ID | Scenario | Priority | Description |
|----|----------|----------|-------------|
| T6 | Long $TMPDIR path | P0 | macOS deep path >80 chars triggers fallback |
| T7 | Directory permission error | P1 | Existing dir with 0755 permissions |
| T8 | Concurrent Zygote startup | P1 | Race condition in socket creation |
| T9 | Symlink attack attempt | P2 | `/tmp/velo-{UID}` -> `/etc` |
| T10 | Disk space exhausted | P2 | Socket creation fails gracefully |

---

## QA Expert 2: Regression Test Specialist

### Verdict: ⚠️ Regression Matrix Missing

**Upgrade/Downgrade Test Matrix**:

```
┌──────────────────────────────────────────────────────────────┐
│                  Version Compatibility Matrix                 │
├──────────────────┬────────────┬────────────┬────────────────┤
│     Scenario     │ New CLI    │ Old CLI    │ Expected       │
│                  │ (v0.6.2)   │ (v0.6.1)   │ Behavior       │
├──────────────────┼────────────┼────────────┼────────────────┤
│ New Zygote only  │ ✅ Connect │ ❌ Fail    │ Version isolation │
│ Old Zygote only  │ ❌ Fail    │ ✅ Connect │ Version isolation │
│ No Zygote        │ ✅ Start   │ ✅ Start   │ Each starts own │
│ Both running     │ ✅ Use new │ ✅ Use old │ Coexistence OK  │
│ Upgrade mid-run  │ ✅ New     │ N/A        │ Seamless        │
│ Downgrade        │ N/A        │ ✅ Old     │ Seamless        │
└──────────────────┴────────────┴────────────┴────────────────┘
```

**Required Regression Tests**:

1. **REG-001**: Fresh install v0.6.2, start Zygote, verify new socket path
2. **REG-002**: Upgrade v0.6.1 → v0.6.2 with running Zygote, verify cleanup
3. **REG-003**: Downgrade v0.6.2 → v0.6.1, verify old still works
4. **REG-004**: Two users on same system, verify isolation

---

## QA Expert 3: Performance Test Specialist

### Verdict: ✅ OK with Performance ACs

**Performance Acceptance Criteria**:

| AC | Metric | Threshold | Rationale |
|----|--------|-----------|-----------|
| AC-9 | `get_socket_dir()` latency | < 1ms | No startup regression |
| AC-10 | `cleanup_stale_sockets()` | < 100ms | Even with 10 stale sockets |
| AC-11 | Socket connection time | < 5ms | No IPC regression |

**Benchmark Script**:

```bash
#!/bin/bash
# DEF-61-004 Performance Verification

echo "Testing socket dir creation..."
time for i in {1..100}; do
    rm -rf /tmp/velo-$(id -u) 2>/dev/null
    ./target/release/velo zygote status >/dev/null 2>&1
done

echo "Testing cleanup with stale sockets..."
mkdir -p /tmp/velo-$(id -u)
for i in {1..10}; do
    touch /tmp/velo-$(id -u)/zygote-v$i.sock
done
time ./target/release/velo zygote start 2>&1 | head -5
```

---

## QA Expert 4: Test Automation Specialist

### Verdict: ⚠️ Test Code Specification Required

**pytest Test Specification**:

```python
# tests/qa/test_def_61_004_socket_isolation.py
"""
DEF-61-004: Protocol Version Socket Isolation
QA Test Suite
"""

import os
import stat
import socket
import tempfile
import threading
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestSocketPathFormat:
    """AC-1, AC-2: Socket path format verification"""
    
    def test_socket_path_includes_version(self):
        """T2: Socket path contains zygote-v{VERSION}.sock"""
        # Call get_socket_path() and verify format
        # Expected: /tmp/velo-{UID}/zygote-v1.sock
        pass
    
    def test_socket_path_includes_uid(self):
        """T5: Socket path contains user UID"""
        uid = os.getuid()
        # Verify path contains f"velo-{uid}"
        pass


class TestSocketDirPermissions:
    """AC-4: Directory permission verification"""
    
    def test_socket_dir_created_with_0700(self, tmp_path):
        """T4: Socket directory has 0700 permissions"""
        # Create socket dir
        # Verify mode == 0o700
        pass
    
    def test_weak_permissions_warning(self, tmp_path, capsys):
        """T7: Warn if directory has weak permissions"""
        # Pre-create dir with 0755
        # Call get_socket_dir()
        # Verify warning printed
        pass


class TestPathLengthLimit:
    """AC-7: Socket path length < 108 chars"""
    
    def test_short_tmpdir_uses_tmpdir(self):
        """Normal case: use $TMPDIR"""
        pass
    
    def test_long_tmpdir_falls_back(self):
        """T6: Falls back to /tmp when $TMPDIR too long"""
        long_path = "/very" + "/deep" * 20 + "/path"
        with patch.dict(os.environ, {'TMPDIR': long_path}):
            # Verify fallback to /tmp
            pass


class TestStaleSocketCleanup:
    """AC-3: Connection test before deletion"""
    
    def test_stale_socket_deleted(self, tmp_path):
        """T1: Stale socket is deleted"""
        # Create fake old socket file
        # Run cleanup
        # Verify deleted
        pass
    
    def test_active_socket_preserved(self, tmp_path):
        """T3: Active socket is NOT deleted"""
        # Create listening socket
        # Run cleanup
        # Verify NOT deleted
        pass
    
    def test_cleanup_permission_denied_no_crash(self, tmp_path):
        """T7: Cleanup handles permission errors gracefully"""
        # Create read-only socket file
        # Run cleanup
        # Verify no exception, warning printed
        pass


class TestConcurrency:
    """Edge case: concurrent operations"""
    
    def test_concurrent_zygote_start(self):
        """T8: Concurrent starts don't race"""
        results = []
        
        def start_zygote():
            # Start Zygote
            # Record success/failure
            pass
        
        threads = [threading.Thread(target=start_zygote) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Verify exactly one succeeded or all gracefully handled
        pass


class TestVersionUpgrade:
    """Regression tests for upgrade scenarios"""
    
    def test_upgrade_cleans_old_socket(self):
        """REG-002: Upgrade v0.6.1 → v0.6.2 cleans old socket"""
        pass
    
    def test_downgrade_still_works(self):
        """REG-003: Downgrade v0.6.2 → v0.6.1 still works"""
        pass


@pytest.mark.performance
class TestPerformance:
    """AC-9, AC-10: Performance verification"""
    
    def test_get_socket_dir_latency(self, benchmark):
        """AC-9: get_socket_dir() < 1ms"""
        # result = benchmark(get_socket_dir)
        # assert result.stats.mean < 0.001
        pass
    
    def test_cleanup_latency_10_sockets(self, benchmark, tmp_path):
        """AC-10: cleanup_stale_sockets() < 100ms with 10 sockets"""
        # Create 10 stale sockets
        # result = benchmark(cleanup_stale_sockets)
        # assert result.stats.mean < 0.1
        pass
```

---

## Combined QA Recommendations

### Must Fix (P0)

1. **Add T6-T10 test cases** to cover edge cases
2. **Create regression test matrix** for upgrade/downgrade
3. **Create pytest test file** with test specifications

### Should Fix (P1)

4. **Add performance ACs** (AC-9, AC-10, AC-11)
5. **Add benchmark script** for CI verification

### Nice to Have (P2)

6. **Add fuzz testing** for socket path edge cases
7. **Add chaos testing** for cleanup robustness

---

## Updated Acceptance Criteria

| AC | Description | Source |
|----|-------------|--------|
| AC-1 | Socket path includes version | Core |
| AC-2 | User-isolated directory | Unix Expert |
| AC-3 | Connection test before cleanup | Process Expert |
| AC-4 | Directory permissions 0700 | Security Expert |
| AC-5 | Benchmark passes | Core |
| AC-6 | No regression | Core |
| AC-7 | Path length < 108 | Unix Expert |
| AC-8 | Graceful error handling | Core |
| **AC-9** | `get_socket_dir()` < 1ms | **QA Performance** |
| **AC-10** | `cleanup_stale_sockets()` < 100ms | **QA Performance** |
| **AC-11** | Socket connection < 5ms | **QA Performance** |

---

## Updated Test Case Count

| Category | Count |
|----------|-------|
| Core (T1-T5) | 5 |
| Edge Cases (T6-T10) | 5 |
| Regression (REG-001 to REG-004) | 4 |
| Performance | 3 |
| **Total** | **17** |

---

**QA Sign-off**: ⚠️ Conditional Approval
**Condition**: Add T6-T10 and pytest spec before implementation
**Reviewers**: 4 QA Experts
