# Phase 13: `velo test` - QA Verification Checklist

> **RFC**: [RFC-0028](../../rfcs/0028-zygote-test-executor.md) (APPROVED)  
> **Branch**: `phase-13/velo-test`  
> **Prerequisite**: Developer completes Phase 1-3

---

## Pre-QA Checklist

- [ ] Developer confirms Phase 3 complete
- [ ] `cargo test --all` passes (CI green)
- [ ] `cargo build --release` successful
- [ ] Read RFC-0028 section 12 (P0/P1 requirements)

---

## Gate A: Basic Functionality

### A.1 CLI Smoke Tests

| Test | Command | Expected |
|:---|:---|:---|
| Help text | `velo test --help` | Shows usage |
| Single test | `velo test tests/qa/phase5/test_bench.py::TestBenchCommand::test_bench_001_command_exists` | PASSED |
| Directory | `velo test tests/qa/phase5/` | All tests run |
| Tier filter | `velo test -m tier0 tests/qa/` | Only tier0 tests |

### A.2 Zygote Integration

| Test | Command | Expected |
|:---|:---|:---|
| Auto-start | `velo test ...` (Zygote not running) | Zygote starts automatically |
| Pre-warm | `velo test --preload torch,pandas ...` | Modules preloaded |
| Fallback | `velo test --no-zygote ...` | Works without Zygote |

---

## Gate B: Fork Safety (P0 Critical)

### B.1 GIL Deadlock Test (P0-2)

```bash
# Create test with threading
cat > /tmp/test_threading.py << 'EOF'
import threading
import time

def test_with_threads():
    results = []
    def worker():
        time.sleep(0.01)
        results.append(1)
    
    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(results) == 5
EOF

velo test /tmp/test_threading.py
```
- [ ] Test completes without deadlock

### B.2 Fixture Reinit Test (P0-1)

```python
# Create test with database-like resource
# tests/qa/phase13/test_fixture_reinit.py
import pytest

_connection_id = None

@pytest.fixture(scope="session")
def db_connection():
    global _connection_id
    _connection_id = id(object())  # Simulate connection
    return _connection_id

def test_connection_valid(db_connection):
    # In forked child, this should be reinitialized
    assert db_connection is not None
```
- [ ] Test passes with `--velo`
- [ ] `pytest_velo_fork_reinit` hook called

### B.3 atexit Cleanup Test (P0-3)

```bash
# Verify atexit handlers don't run twice
velo test tests/qa/phase5/test_l0_smoke.py -v 2>&1 | grep -c "cleanup"
```
- [ ] Cleanup messages appear only once

---

## Gate C: Performance

### C.1 Fork Latency Benchmark

```bash
velo test tests/qa/phase5/test_bench.py --benchmark 2>&1 | grep "fork_latency"
```
- [ ] Fork latency < 2ms

### C.2 Speedup Comparison

```bash
# Baseline (vanilla pytest)
time pytest tests/qa/phase5/ --ignore=tests/qa/phase5/test_zygote_preload.py

# With Velo
time velo test tests/qa/phase5/ --ignore=tests/qa/phase5/test_zygote_preload.py
```
- [ ] Velo faster than vanilla pytest
- [ ] Document speedup ratio: ___x

### C.3 Memory Efficiency

```bash
# Run 10 parallel tests, check memory
velo test tests/qa/phase5/ --workers 10 &
PID=$!
sleep 2
ps -o rss= -p $PID  # Resident Set Size
```
- [ ] Memory per worker < 50MB (COW working)

---

## Gate D: Compatibility

### D.1 pytest Features

| Feature | Test Command | Expected |
|:---|:---|:---|
| Fixtures | `velo test tests/qa/ -k fixture` | PASSED |
| Markers | `velo test -m "not slow" tests/qa/` | Filtered correctly |
| Parametrize | `velo test tests/qa/ -k parametrize` | PASSED |
| Capture | `velo test tests/qa/ -s` | stdout visible |

### D.2 xdist Mutual Exclusivity (P1-1)

```bash
velo test tests/qa/phase5/ -n 4 --velo
```
- [ ] Warning emitted
- [ ] `--velo` disabled, xdist takes over

---

## Gate E: Error Handling

### E.1 Test Failure Reporting

```bash
cat > /tmp/test_fail.py << 'EOF'
def test_intentional_fail():
    assert 1 == 2, "This should fail"
EOF

velo test /tmp/test_fail.py
```
- [ ] Exit code = 1
- [ ] Error message visible
- [ ] Stack trace correct

### E.2 Timeout Handling

```bash
cat > /tmp/test_timeout.py << 'EOF'
import time
def test_slow():
    time.sleep(60)  # Too slow
EOF

timeout 5 velo test /tmp/test_timeout.py
```
- [ ] Graceful timeout handling
- [ ] Worker process killed

---

## Final Verification

- [ ] All Gates (A-E) pass
- [ ] No memory leaks (run 100+ tests cycle)
- [ ] CI pipeline green
- [ ] Performance baseline recorded

---

## Sign-off

| Role | Name | Date | Status |
|:---|:---|:---|:---|
| QA Lead | | | ☐ APPROVED |
| Architect | | | ☐ APPROVED |

---

**After QA sign-off: Merge `phase-13/velo-test` → `main`**
