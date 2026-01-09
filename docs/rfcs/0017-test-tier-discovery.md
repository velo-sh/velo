# RFC-0017: Test Tier Discovery Convention

**Status**: DRAFT
**Owner**: QA/Architecture Team
**Created**: 2026-01-09
**Last Updated**: 2026-01-09
**Related**: RFC-0016 (Environment Convergence), QA SOP

---

> **TL;DR**: Tests declare their tier via `@pytest.mark.tierN` markers. CI auto-discovers all tests. No more manual file lists. No more sync drift.

## 1. Problem Statement

The current test infrastructure exhibits **Test Discovery Fragmentation**:

| Symptom | Impact |
|---|---|
| **Explicit file lists** in `test-suites.conf` | New tests silently missed in CI if not added to list |
| **Local-CI / Remote-CI drift** | Some tests run in GitHub Actions but not in `local-ci.sh --docker` |
| **Manual synchronization required** | Developer must remember to update multiple locations |
| **No semantic tier classification** | Fast vs slow, unit vs E2E tests intermingled |

### 1.1 Root Cause
Tests are selected by **file path enumeration**, not by **declared semantics**. This violates DRY and creates maintenance burden.

---

## 2. The Solution: pytest Marker-Based Auto-Discovery

Adopt a `cargo test`-like model where tests **declare their tier** via pytest markers, and CI **discovers** all tests automatically.

### 2.1 Tier Definitions

| Tier | Marker | SLA | Description | Example |
|---|---|---|---|---|
| **Tier 0** | `@pytest.mark.tier0` | < 30s | Unit tests, no external dependencies | `test_fingerprint.py` |
| **Tier 1** | `@pytest.mark.tier1` | < 2min | Integration tests, needs velo binary | `test_kinetic_protocol_integrity.py` |
| **Tier 2** | `@pytest.mark.tier2` | < 5min | E2E tests, full Zygote runtime | `phase_6_1_1/test_*.py` |
| **Tier 3** | `@pytest.mark.tier3` | < 5min | Hardened security/stability tests | `test_phase6_1_*_hardened.py` |

### 2.2 Platform Markers

| Marker | Description |
|---|---|
| `@pytest.mark.linux_only` | Requires Linux-specific features (Abstract Sockets, NUMA) |
| `@pytest.mark.macos_only` | Requires macOS-specific features (sandbox-exec) |
| `@pytest.mark.slow` | Tests that exceed tier SLA (for optional exclusion) |
| `@pytest.mark.zygote_required` | Requires Zygote mode (not fallback uvicorn) |

---

## 3. Specification

### 3.1 pyproject.toml Configuration

```toml
[tool.pytest.ini_options]
markers = [
    "tier0: Unit tests - no external deps, <30s",
    "tier1: Integration tests - needs binary, <2min",
    "tier2: E2E tests - full runtime, <5min",
    "tier3: Hardened tests - security/stability",
    "linux_only: Linux-specific features",
    "macos_only: macOS-specific features",
    "slow: Tests exceeding tier SLA",
    "zygote_required: Requires Zygote mode",
]

# Default: run all tests in tests/qa/
testpaths = ["tests/qa"]
```

### 3.2 CI Commands

```bash
# Quick local check (Tier 0 + 1)
pytest -m "tier0 or tier1" tests/qa/

# Full Docker CI (All tiers)
pytest tests/qa/

# Security-focused (Tier 3 only)
pytest -m "tier3" tests/qa/

# Skip platform-specific (cross-platform run)
pytest -m "not linux_only and not macos_only" tests/qa/

# Fast subset (exclude slow)
pytest -m "not slow" tests/qa/
```

### 3.3 Test File Conventions

Every test file MUST declare at least one tier marker at the class or module level:

```python
# Option A: Module-level default
pytestmark = pytest.mark.tier1

# Option B: Class-level
@pytest.mark.tier2
class TestGoldenPath:
    ...

# Option C: Function-level override
@pytest.mark.tier0
def test_simple_unit():
    ...
```

### 3.4 Enforcement

A pre-commit hook or CI check SHALL verify:
1. Every test file in `tests/qa/` has at least one tier marker.
2. No test file is "orphaned" (exists but never collected).

### 3.5 Multi-Marker Conflict Resolution (P1-Council)

**Rule**: A test function/class SHALL have exactly ONE tier marker. Multiple tier markers are forbidden.

| Scenario | Result |
|---|---|
| `@tier1 @tier2` on same function | ❌ **ERROR**: Pre-commit hook MUST reject |
| `@tier1` on class, `@tier2` on method | ✅ OK: Method-level overrides class-level |
| `@tier1 @linux_only` | ✅ OK: Tier + platform markers are allowed |

**Rationale**: Tier markers represent mutually exclusive categories. A test cannot be both a "unit test" and an "E2E test" simultaneously.

### 3.6 Orphan Test Detection (P1-Council)

CI SHALL run the following check to detect orphaned tests:

```bash
#!/bin/bash
# scripts/check-orphan-tests.sh
set -e

# Count Python test files
TEST_FILES=$(find tests/qa -name "test_*.py" | wc -l | tr -d ' ')

# Count collected tests (files that pytest actually discovers)
COLLECTED=$(pytest --collect-only -q tests/qa/ 2>/dev/null | grep -c "test_" || echo 0)

# If files > 0 but collected == 0, something is wrong
if [[ "$TEST_FILES" -gt 0 && "$COLLECTED" -eq 0 ]]; then
    echo "❌ ORPHAN TEST DETECTED: $TEST_FILES test files exist but 0 tests collected!"
    exit 1
fi

echo "✅ All test files are properly collected ($COLLECTED tests from $TEST_FILES files)"
```

**Integration**: Add this check to `scripts/ci-common.sh` as a pre-test validation step.

---

## 4. Migration Path

### Phase 1: Add markers to existing tests (Non-breaking)
- Add tier markers to all existing test files.
- Tests continue to work without markers (backwards compatible).

### Phase 2: Update CI scripts
- Replace explicit file lists in `test-suites.conf` with marker-based commands.
- `local-ci.sh` uses `pytest tests/qa/` for full discovery.

### Phase 3: Add enforcement
- Pre-commit hook rejects unmarked tests.
- CI fails if any test file lacks a tier marker.

---

## 5. Benefits

| Before | After |
|---|---|
| Add test file → manually update `test-suites.conf` | Add test file → add marker → done |
| Local/CI test lists can diverge | Single source: pytest discovery |
| No semantic classification | Clear tier semantics with defined SLAs |
| Platform-specific tests mixed with general | Explicit platform markers |

---

## 6. Affected Documents

The following documents SHALL be updated once this RFC is approved:

1. **QA SOP** (`docs/qa/`): Add tier definitions and marker requirements.
2. **STANDARDS.md**: Add "Test Classification" section.
3. **pyproject.toml**: Add marker definitions.
4. **test-suites.conf**: Convert to marker-based commands (or deprecate).
5. **All test files in `tests/qa/`**: Add tier markers.

---

## 7. Decision Record

| Date | Decision | Rationale |
|---|---|---|
| 2026-01-09 | DRAFT v1 | Initial proposal for review |
| 2026-01-09 | DRAFT v2 | Addressed P1 observations from Grand Council: multi-marker conflict rules (3.5), orphan detection (3.6), TL;DR added |

---

## Appendix A: Tier Assignment Guide

When assigning a tier to a new test, use this decision tree:

```
Does the test require the velo binary running?
├─ No  → Does it need any I/O or subprocess?
│        ├─ No  → Tier 0 (Pure Unit)
│        └─ Yes → Tier 1 (Integration)
└─ Yes → Does it test Zygote worker lifecycle?
         ├─ No  → Tier 1 (Binary Integration)
         └─ Yes → Is it an adversarial/hardened scenario?
                  ├─ No  → Tier 2 (E2E)
                  └─ Yes → Tier 3 (Hardened)
```
