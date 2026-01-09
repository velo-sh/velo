# Grand Council Review: RFC-0017 Test Tier Discovery

**Date**: 2026-01-09
**RFC**: RFC-0017 Test Tier Discovery Convention
**Status**: APPROVED WITH OBSERVATIONS

---

## Council Composition

| Persona | Focus |
|---|---|
| **QA Lead** | Test methodology, coverage, enforcement |
| **Python Core Dev** | pytest internals, marker semantics |
| **DevOps/CI Engineer** | CI pipeline integration, runtime |
| **Technical Writer** | Documentation clarity, adoption path |

---

## Phase II: The Critique

### 🔍 QA Lead

**Approval**: ✅ APPROVED

> "This is exactly how we should have structured tests from day one. The tier definitions are clear, the SLAs are realistic, and the enforcement mechanism (pre-commit hook) ensures compliance."

**Observations**:
1. **P2**: Consider adding a `@pytest.mark.flaky` marker for tests with known intermittent issues, so they can be tracked and fixed separately.
2. **P2**: The Appendix A decision tree is excellent - ensure it's referenced in QA SOP.

---

### 🐍 Python Core Dev

**Approval**: ✅ APPROVED

> "The pytest marker approach is idiomatic and well-supported. The pyproject.toml configuration is correct."

**Observations**:
1. **P1**: Clarify what happens when a test has multiple tier markers (e.g., `@tier1 @tier2`). Recommend: "Most restrictive tier wins" or "Error on multiple tier markers".
2. **P2**: Consider using `pytestmark = [pytest.mark.tier1]` syntax for module-level markers to allow future multi-marker support.

---

### 🔧 DevOps/CI Engineer

**Approval**: ✅ APPROVED

> "Auto-discovery eliminates the sync-drift problem between local-ci and remote-ci. The command syntax is simple and CI-friendly."

**Observations**:
1. **P1**: Add a CI smoke test that verifies no test files are orphaned (exist but never collected). Example:
   ```bash
   # Count files vs collected tests
   pytest --collect-only tests/qa/ | grep "test session starts"
   ```
2. **P2**: The `test-suites.conf` file can become purely documentary (listing what each tier should contain) once markers are adopted.

---

### 📝 Technical Writer

**Approval**: ✅ APPROVED

> "The RFC is well-structured. The migration path is clear. The decision tree in Appendix A is a nice touch."

**Observations**:
1. **P2**: Add a one-paragraph TL;DR at the top for busy readers.
2. **P2**: The "Affected Documents" section is good - ensure each linked doc gets updated when RFC is implemented.

---

## Phase III: The Verdict

### 🏛️ VERDICT: **APPROVED**

No P0 blocking issues identified.

### Summary of Observations

| Priority | Issue | Owner |
|---|---|---|
| P1 | Clarify multiple-tier-marker behavior | RFC Author |
| P1 | Add orphan test detection to CI | DevOps |
| P2 | Consider `@flaky` marker | QA |
| P2 | Add TL;DR paragraph | RFC Author |
| P2 | Update `test-suites.conf` to be documentary | DevOps |

---

## Recommended Next Steps

1. **Address P1 observations** in RFC (optional before implementation)
2. **Proceed to Phase 1 implementation**: Add markers to existing tests
3. **Update QA SOP** to reference RFC-0017 tier definitions

---

**Council Session Closed**: 2026-01-09 17:42
