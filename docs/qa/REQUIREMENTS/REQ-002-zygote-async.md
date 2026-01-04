# QA Test Requirement: Phase 5.1 Zygote Async Mode

**QA-REQ-002**: Zygote 10ms Optimization Verification

## Background

Phase 5.1 adds `--async` mode to eliminate 30ms stdout wait overhead.
Target: Zygote warm ≤15ms (from 43ms).

---

## Test Requirements

### PERF-5.1-001: Async Mode Performance

**Precondition**: DEV-5.1-001/002/003 implemented

**Steps**:
```bash
cd ../velo-benchmarks/bench_fastapi
velo zygote stop
velo run --zygote bench.py  # warm up Zygote

# Measure async mode (5 runs)
for i in {1..5}; do
  time velo run --zygote --async bench.py
done
```

**Expected**: Each run **≤ 20ms** (target 15ms, 5ms margin)

---

### PERF-5.1-002: Sync Mode Baseline

**Steps**:
```bash
# Compare with sync mode (default)
time velo run --zygote bench.py
```

**Expected**: ~40-50ms (unchanged from Phase 5.0)

---

### FUNC-5.1-001: Async Mode Executes Script

**Steps**:
```bash
# Create test script that writes to file
echo 'with open("/tmp/async_test.txt", "w") as f: f.write("async_ok")' > /tmp/test_async.py

velo run --zygote --async /tmp/test_async.py
sleep 0.5  # Wait for background execution
cat /tmp/async_test.txt
```

**Expected**: File contains "async_ok"

---

### FUNC-5.1-002: Async Mode stdout Logging (Optional)

**Steps**:
```bash
velo run --zygote --async --stdout-file /tmp/out.log bench.py
sleep 1
cat /tmp/out.log
```

**Expected**: stdout captured to file

---

### REG-5.1-001: Sync Mode Unchanged

**Steps**:
```bash
# Run full benchmark with sync mode
python benchmark_projects.py --project fastapi
```

**Expected**: Results match Phase 5.0 (~43ms Zygote warm)

---

## Success Criteria

| Test | Pass Criteria |
|------|---------------|
| PERF-5.1-001 | Async mode ≤ 20ms |
| PERF-5.1-002 | Sync mode ~40-50ms |
| FUNC-5.1-001 | Script executes correctly |
| REG-5.1-001 | No regression in sync mode |
