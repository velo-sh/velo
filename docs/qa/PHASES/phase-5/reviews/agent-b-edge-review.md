# Agent B (Conservative QA) -> Review Agent A Edge Test Design

> **Reviewer**: Agent B (Core Flow Stability)  
> **Review Target**: Agent A Edge Test Matrix (A-01 ~ A-10)  
> **Date**: 2026-01-03  
> **Stance**: From regression testing and stability perspective, review edge test maintainability

---

## Core Review Findings

### 1. Edge Test Regression Value Assessment

**Issue**: Not all edge tests need to run on every PR.

**Agent B Classification Recommendation**:

| ID | Regression Value | Run Frequency |
|----|------------------|---------------|
| A-01 (Size boundary) | High | Every PR |
| A-02 (0 modules) | High | Every PR |
| A-03 (10000 modules) | Medium | Daily |
| A-04 (Long name) | Medium | Weekly |
| A-05 (Deep nesting) | Low | Weekly |
| A-06 (Circular deps) | High | Every PR |
| A-07 (Unicode) | Medium | Daily |
| A-08 (NaN offset) | High | Every PR |
| A-09 (Negative offset) | High | Every PR |
| A-10 (Overlapping) | High | Every PR |

```yaml
# .github/workflows/edge-tests.yml
edge-fast:  # Every PR
  - A-01, A-02, A-06, A-08, A-09, A-10

edge-daily:  # Scheduled
  - A-03, A-07

edge-weekly:  # Slower tests
  - A-04, A-05
```

---

### 2. A-03 (10000 modules) -> Stability Risk

**Issue**: Extreme tests may cause CI timeout or resource exhaustion.

**Agent B Supplement**:

| ID | Stability Recommendation |
|----|-------------------------|
| B-A-03a | **Set timeout** (5 minutes) |
| B-A-03b | **Set memory limit** (2GB) |
| B-A-03c | **Isolate run** (separate CI job) |

```python
# B-A-03a: Timeout protection
@pytest.mark.timeout(300)  # 5 minutes max
@pytest.mark.limit_memory("2GB")
def test_10k_modules():
    ...
```

---

### 3. A-06 (Circular deps) -> Detection Consistency

**Issue**: Circular dependency detection must be consistent with Python standard behavior.

**Agent B Supplement**:

| ID | Consistency Test |
|----|------------------|
| B-A-06a | **Compare with CPython behavior** |
| B-A-06b | **Verify error message format** |
| B-A-06c | **Ensure no infinite loop** |

```python
# B-A-06a: CPython consistency
def test_circular_dep_consistent_with_cpython():
    """Velo circular dep error should match CPython behavior"""
    velo_result = velo_run("--fast", "circular_import.py")
    cpython_result = python_run("circular_import.py")
    
    # Both should produce same type of error
    assert type(velo_result.error) == type(cpython_result.error)
```

---

### 4. A-07 (Unicode) -> Multi-Platform Consistency

**Issue**: Unicode handling may differ across OS/filesystem.

**Agent B Supplement**:

| ID | Platform Test |
|----|---------------|
| B-A-07a | **macOS HFS+ NFC normalization** |
| B-A-07b | **Linux ext4 raw bytes** |
| B-A-07c | **Windows NTFS case sensitivity** |

```python
# B-A-07: Platform-specific unicode
@pytest.mark.parametrize("platform", ["macos", "linux", "windows"])
def test_unicode_platform_consistency(platform):
    """Unicode module names must work consistently across platforms"""
    # Japanese module.py
    ...
```

---

### 5. Edge Test Error Message Readability

**Issue**: Edge tests don't just verify behavior, they also verify user experience.

**Agent B Supplement**:

| Original Case | Error Message Requirement |
|---------------|---------------------------|
| A-01 (Too large) | "Bundle size 256.1MB exceeds limit of 256MB" |
| A-06 (Circular) | "Circular import detected: A -> B -> C -> A" |
| A-08 (Invalid offset) | "Invalid module offset: expected 0-N, got NaN" |

```python
# B-A-ERR-01: Error message quality
def test_error_messages_are_helpful():
    """Error messages must include actionable information"""
    result = load_oversized_bundle()
    
    assert "256.1MB" in result.stderr  # Actual size
    assert "256MB" in result.stderr     # Limit
    assert "reduce" in result.stderr.lower()  # Suggestion
```

---

### 6. Edge Test Isolation from Core Flow

**Issue**: Edge tests should not affect core flow tests.

**Agent B Supplement**:

| ID | Isolation Requirement |
|----|----------------------|
| B-A-ISO-01 | **Independent temp directory** |
| B-A-ISO-02 | **Cleanup after test** |
| B-A-ISO-03 | **Don't modify global state** |

```python
# B-A-ISO-01: Test isolation
@pytest.fixture(autouse=True)
def isolated_test_env(tmp_path):
    """Each edge test runs in isolated environment"""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    yield
    os.chdir(original_cwd)
    # Cleanup happens automatically
```

---

## Agent B Summary

| Review Dimension | Supplement Count |
|------------------|------------------|
| Regression frequency classification | 10 items classified |
| Stability protection | +3 |
| Consistency tests | +3 |
| Multi-platform tests | +3 |
| Error message quality | +3 |
| Test isolation | +3 |

**Total**: Edge tests supplemented with **15 items** from stability perspective

---

**Agent B Sign-off**: Independent review complete  
**Recommendation**: Divide edge tests into fast/daily/weekly tiers to avoid CI timeout
