# QA Delivery Checklist Template

Use this checklist after completing each testing task to ensure quality.

---

## Feature: [Feature Name]
## Phase: [X.Y]
## Date: [YYYY-MM-DD]

---

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
