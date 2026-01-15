# Definition of Done (DoD)

This document defines the quality gates for Velo features and releases.

---

## Quality Gate Model

```
  Dev Work      Gate 1         QA Work       Gate 2        Release
 ─────────── ► ─────────── ► ─────────── ► ─────────── ► ───────────
              Dev Handoff                  QA Sign-off
              Checklist                    Checklist
```

---

## Gate 1: Dev Handoff Checklist

> **⚠️ Dev MUST complete ALL items before notifying QA for testing.**

### Code Standards

- [ ] **CI Pipeline Passes**
  - `cargo fmt --check` ✅
  - `cargo clippy -- -D warnings` ✅
  - `cargo test` ✅

- [ ] **Pre-commit Hook Runs Clean**
  ```bash
  git commit  # Hook must pass without --no-verify
  ```

- [ ] **No New Warnings**
  - Zero new compiler warnings
  - Zero new clippy warnings
  - Any `#[allow(...)]` has justification comment

### Self-Testing

- [ ] **Happy Path Works**
  - Feature runs successfully in local environment
  - Demo script provided and verified

- [ ] **Edge Cases Handled**
  - Error messages are clear and actionable
  - No panics on bad input (use `Result` instead)

- [ ] **Regression Check**
  - Existing tests still pass
  - **Performance Invariants (SPEC-0007)**: Verified via `pytest -m perf`
  - `benchmark_projects.py --all` shows no regression > 5%

### Documentation Prepared

- [ ] **PR Description Complete**
  - What changed and why
  - How to test manually
  - Related RFC/Issue linked

- [ ] **Code Comments**
  - Non-obvious logic has comments
  - Public functions have doc comments

### Handoff Artifacts

- [ ] **Test Script Provided**
  - `scripts/test-<feature>.sh` or equivalent
  - QA can run without asking questions

- [ ] **Known Limitations Documented**
  - Any incomplete items listed in PR
  - Workarounds documented if needed

---

## Gate 2: QA Sign-off Checklist

> **⚠️ QA MUST complete ALL items before approving for release.**

### Functional Testing

- [ ] **Core Scenarios Pass**
  - All items in QA Test Matrix marked ✅
  - Evidence captured (terminal output / screenshots)

- [ ] **Error Handling Verified**
  - Invalid input produces helpful error
  - Recovery from corrupted state tested
  - No crashes or hangs observed

### Platform Compatibility

- [ ] **Primary Platforms Tested**
  - macOS (ARM) - Python 3.11, 3.12
  - Ubuntu 22.04 - Python 3.11, 3.12

- [ ] **Secondary Platforms** (at least 1)
  - macOS (Intel)
  - Windows 11
  - Other Linux distros

### Performance Verification (SPEC-0007 / INV-PERF)

| Metric | Gate Requirement | Actual | Pass |
|:---|:---|:---|:---|
| **Cold Start (Zygote)** | < 50ms (INV-PERF-002) | | ☐ |
| **Zero-Copy (memfd)** | Verified > 1MB (INV-PERF-001) | | ☐ |
| **Binary Size** | < 500KB (Titanium Grade) | | ☐ |

### Regression Check

- [ ] **Existing Features Work**
  - `velo run` still works
  - `velo --help` correct
  - Cache migration handled (if applicable)

### Documentation Verified

- [ ] **README Accurate**
  - Examples still work
  - Version numbers correct

- [ ] **CHANGELOG Updated**
  - New features listed
  - Breaking changes noted

---

## Sign-off Template

### Dev → QA Handoff

```markdown
## Ready for QA

**Feature**: [Feature Name]
**PR**: #XXX
**RFC**: [Link if applicable]

### Dev Checklist
- [x] CI passes
- [x] Pre-commit clean
- [x] Self-tested on macOS ARM
- [x] Test script: `scripts/test-xxx.sh`

### Known Limitations
- None / List them here

### How to Test
1. Step 1
2. Step 2
3. Expected result

@qa-team Ready for testing
```

### QA → Release Approval

```markdown
## QA Sign-off

**Feature**: [Feature Name]
**PR**: #XXX
**Tested By**: [QA Name]
**Date**: YYYY-MM-DD

### Test Results
- [x] Core scenarios: 12/12 pass
- [x] Platform: macOS ARM, Ubuntu 22.04
- [x] Performance: Within baseline

### Issues Found
- None / List with severity

### Recommendation
✅ APPROVED for release
```

---

## Escalation Process

### If Dev Submits Without Complete Checklist

1. QA **returns PR immediately** with comment:
   ```
   ❌ Returned: Dev Handoff Checklist incomplete
   Missing: [list items]
   Please complete and re-submit.
   ```

2. PR is **blocked** until checklist complete

### If QA Finds Blockers

| Severity | Action |
|----------|--------|
| Critical (crash/data loss) | Block release, return to Dev |
| High (feature broken) | Block release, return to Dev |
| Medium (edge case) | Dev decision: fix or document |
| Low (cosmetic) | Create issue, proceed |

---

## Release Checklist (Post QA)

- [ ] Version bumped in `Cargo.toml`
- [ ] CHANGELOG finalized
- [ ] Git tag created
- [ ] GitHub Release published
- [ ] Announcement posted (if major)

---

**Last Updated**: 2026-01-01
