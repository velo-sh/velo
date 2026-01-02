# Agent B (Conservative QA) -> Review Agent C Security Design

> **Reviewer**: Agent B (Core Flow Stability)  
> **Review Target**: Agent C Security Test Matrix (C-01 ~ C-10)  
> **Date**: 2026-01-03  
> **Stance**: From stability and regression testing perspective, review security mechanism reliability

---

## Core Review Findings

### 1. C-01 ~ C-10 Lack Regression Test Hardening

**Issue**: Security tests are one-time, but security vulnerabilities "sneak back" with code changes.

**Agent B Recommendation**:

| Security Case | Regression Requirement |
|---------------|------------------------|
| C-01 Symlink | Must run every PR, add to CI Gate |
| C-03 TOCTOU | Run at least daily (resource intensive) |
| C-04 Hash Bypass | Must run every PR |

```yaml
# .github/workflows/security-regression.yml
security-gate:
  runs-on: ubuntu-latest
  steps:
    - name: Run Critical Security Tests
      run: |
        pytest tests/qa/phase5/security/ -m "critical" --tb=short
        # C-01, C-03, C-04 must pass before merge
```

---

### 2. C-05 CRC32 Collision Test Insufficient

**Issue**: C-05 says "SHA-256 still detects", but doesn't test CRC32 collision + SHA-256 match extreme case.

**Agent B Supplement**:

| ID | Scenario | Test Purpose |
|----|----------|--------------|
| B-C-05a | **CRC32 collision + SHA-256 correct** | Confirm module loads correctly even with CRC32 collision |
| B-C-05b | **CRC32 correct + SHA-256 wrong** | Confirm SHA-256 is final security boundary |

```python
# B-C-05a: CRC32 collision scenario
def test_crc32_collision_still_loads():
    """Even with CRC32 collision, correct SHA-256 should load successfully"""
    # Construct two modules with same CRC32 but different content
    # As long as SHA-256 is correct, should load normally
```

---

### 3. Security Check Error Handling Stability

**Issue**: System behavior may be inconsistent after security check failure.

**Agent B Supplementary Cases**:

| ID | Scenario | Expected Behavior | Why Important |
|----|----------|-------------------|---------------|
| B-C-SEC-01 | **Fallback after security failure** | Must fallback to standard import | Ensure availability |
| B-C-SEC-02 | **Consecutive security failures** | 2nd, 3rd failures should not crash | Stability |
| B-C-SEC-03 | **Partial security check failure** | Single module failure, others continue | Isolation |

```python
# B-C-SEC-01: Security failure graceful fallback
def test_security_failure_fallback():
    """After security check fails, must fallback to standard import"""
    # 1. Create a bundle with permission error
    create_world_writable_bundle()
    
    # 2. Run velo --fast
    result = velo_run("--fast", "main.py")
    
    # 3. Must succeed (via fallback)
    assert result.returncode == 0
    assert "Fallback to standard import" in result.stderr
```

---

### 4. Multi-Python Version Security Behavior Consistency

**Issue**: Security checks may behave differently on Python 3.11/3.12/3.13.

**Agent B Supplementary Cases**:

| ID | Scenario | Test Matrix |
|----|----------|-------------|
| B-C-VER-01 | **Symlink detection consistency** | 3.11 x 3.12 x 3.13 |
| B-C-VER-02 | **Permission check consistency** | macOS x Linux |
| B-C-VER-03 | **Marshal version differences** | Different version marshal formats |

```python
# B-C-VER-01: Cross-version security consistency
@pytest.mark.parametrize("python_version", ["3.11", "3.12", "3.13"])
def test_symlink_rejection_consistent(python_version):
    """Symlink rejection must work on all Python versions"""
    with python_env(python_version):
        result = test_symlink_bypass()
        assert result.rejected
```

---

### 5. Security Test Performance Impact

**Issue**: Security checks cannot significantly impact cold start performance.

**Agent B Supplementary Cases**:

| ID | Metric | Threshold |
|----|--------|-----------|
| B-C-PERF-01 | **SHA-256 verification overhead** | < 5ms (4MB bundle) |
| B-C-PERF-02 | **Permission check overhead** | < 1ms |
| B-C-PERF-03 | **Total security check overhead** | < 10% cold start time |

```python
# B-C-PERF-01: Security overhead benchmark
def test_security_overhead_acceptable():
    """Security checks must not exceed 10% of cold start time"""
    # Without security
    time_no_sec = benchmark_cold_start(security_enabled=False)
    
    # With security
    time_with_sec = benchmark_cold_start(security_enabled=True)
    
    overhead = (time_with_sec - time_no_sec) / time_no_sec
    assert overhead < 0.10  # < 10%
```

---

### 6. Security Logging and Observability

**Issue**: Security events must have clear logs for post-incident audit.

**Agent B Supplementary Cases**:

| ID | Scenario | Log Requirement |
|----|----------|-----------------|
| B-C-LOG-01 | **Symlink rejection** | Log original path and resolved path |
| B-C-LOG-02 | **Hash mismatch** | Log expected hash and actual hash |
| B-C-LOG-03 | **Permission rejection** | Log file permission bits |

```python
# B-C-LOG-01: Security event logging
def test_security_event_logging():
    """Security rejections must be logged with details"""
    result = trigger_symlink_rejection()
    
    assert "SecurityRejection" in result.logs
    assert "original_path" in result.logs
    assert "resolved_path" in result.logs
```

---

## Agent B Summary

| Review Dimension | Supplementary Cases |
|------------------|---------------------|
| Regression hardening | CI config recommendation |
| CRC32/SHA-256 boundary | +2 (B-C-05a~b) |
| Error handling stability | +3 (B-C-SEC-01~03) |
| Multi-version consistency | +3 (B-C-VER-01~03) |
| Performance impact | +3 (B-C-PERF-01~03) |
| Logging observability | +3 (B-C-LOG-01~03) |

**Total**: Security tests supplemented with **14 items** from stability perspective

---

## Agent B Priority Recommendations

| Priority | Cases | Reason |
|----------|-------|--------|
| **P0** | B-C-SEC-01 | Security failure must remain available |
| **P0** | B-C-PERF-03 | Performance degradation leads users to disable security |
| **P1** | B-C-VER-01~03 | Multi-version consistency |
| **P2** | B-C-LOG-01~03 | Audit capability |

---

**Agent B Sign-off**: Independent review complete  
**Recommendation**: Security checks must be in CI Gate, not just "nice to have"
