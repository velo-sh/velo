# QA Delivery Checklist Template

Use this checklist after completing each testing task to ensure quality.

---

## Feature: [Feature Name]
## Phase: [X.Y]
## Date: [YYYY-MM-DD]

---

### Gate 0: Performance Regression (BLOCKING)

> **CRITICAL**: Performance is Velo's core value. Any regression is a blocking defect.

- [ ] **PERF-001: Cache Hit No Slower Than First Run**
  - Run: `pytest tests/qa/test_performance.py::TestPerformanceRegression -v`
  - Cached runs must NOT be slower than first run
  - Fail = extra Python spawn on cache hit (50-100ms overhead)
  
- [ ] **PERF-002: Cache Hit Under 100ms**
  - Simple script cached run < 100ms
  
- [ ] **Benchmark Comparison**
  - Run: `python benchmark_projects.py --all -n 5`
  - Result: No project > 5% slower than CPython

### Gate 1: Test Coverage

- [ ] **Happy Path Tests** - All normal use cases pass
- [ ] **Boundary Condition Tests** - Edge values, null values, limits
- [ ] **Adversarial Tests** - Try to BREAK it!
  - [ ] Corrupted input
  - [ ] Malicious input
  - [ ] Concurrency/race conditions
  - [ ] Resource exhaustion

### Gate 2: CI Integration

- [ ] **Local Tests Pass** - `uv run python -m pytest tests/qa/ -v`
- [ ] **CI Tests Pass** - GitHub Actions green
- [ ] **No Flaky Tests** - Stable across 3 consecutive runs

### Gate 3: Documentation

- [ ] **Test Cases Documented** - Clear docstrings
- [ ] **Known Limitations Recorded** - Comments explain limitations
- [ ] **Defect Report Created** - Bugs found are documented

### Gate 4: Sign-off

- [ ] **Dev Acceptance Tests Pass** - `./scripts/test-phase1.5.sh`
- [ ] **QA Adversarial Tests Pass** - All green
- [ ] **Performance Metrics Met** - DoD requirements satisfied
- [ ] **Ready for Release** - No blocking issues

---

## Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| QA | | | |
| Dev | | | |

---

## Defect Summary

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| - | - | No defects found | - |

---

**Checklist Complete = Ready to Ship ✅**
