# Agent B & C -> Review Agent A Edge Implementation

> **Reviewers**: Agent B (Core) & Agent C (Security)  
> **Target**: Agent A Edge Tests (EDGE-601 ~ EDGE-604)  
> **Date**: 2026-01-03  

---

## 🔍 Review Findings

### 1. EDGE-601 Deep DAG (Agent B Perspective)
**Observation**: Checks success but not efficiency.
**Gap**: Deep DAGs might cause O(N^2) or O(N!) lookups if the cache isn't properly memoized.
**Recommendation**: 
- [ ] **B-A-EDGE-05**: Assert `stat()` count is exactly 1 (build-time) or 0 (runtime) even for 100 levels.

### 2. EDGE-603 Symlink Bypass (Agent C Perspective)
**Observation**: Swap test is within bundle.
**Gap**: "Jailbreak" via symlink.
**Recommendation**: 
- [ ] **C-A-EDGE-06**: Verify that a symlink pointing to `/etc/passwd` inside the bundle triggers a `SecurityError` during graph construction.

---

## 📈 Supplement Test Cases

| ID | Scenario | Agent | Risk |
|----|----------|-------|------|
| **B-A-609** | **0-byte Graph Section** | B | Verify loader doesn't hang on empty rkyv buffer |
| **C-A-610** | **Colliding source_hashes** | C | Deterministic collision of 32-bit hashes for different files |

---

**Sign-off**: ✅ Approved with Supplements.
