# Phase 5.0 Fast Loader: Final QA Test Matrix

> **Version**: v2.0 (First Principles Revision)  
> **Date**: 2026-01-03  
> **Principle**: Functionality verification first, security/edge second

---

## Test Level Overview

```
Level 5 ─── Chaos/Stress ─── Only run after L0-L4 pass
Level 4 ─── Security ─────── Only run after L0-L3 pass
Level 3 ─── Config ──────── Only run after L0-L2 pass
Level 2 ─── Sad Path ─────── Only run after L0-L1 pass
Level 1 ─── Happy Path ──── Only run after L0 passes
Level 0 ─── Smoke ─────────── Must pass FIRST ★
```

---

## L0: Smoke Tests (3 items - Must pass first)

| ID | Test | Validation | Expected |
|----|------|------------|----------|
| L0-01 | `velo build` | Bundle creation | exit 0, bundle.veloc exists |
| L0-02 | `velo run --fast main.py` | Program execution | exit 0, correct output |
| L0-03 | No performance regression | Not slower than CPython | time_fast ≤ time_cpython |

```python
# tests/qa/phase5/test_l0_smoke.py
class TestL0Smoke:
    def test_bundle_creation(self, project):
        result = run("velo build")
        assert result.returncode == 0
        assert (project / ".velo/cache/bundle.veloc").exists()
    
    def test_fast_execution(self, project):
        result = run("velo run --fast main.py")
        assert result.returncode == 0
        assert "Hello" in result.stdout
    
    def test_no_performance_regression(self, project):
        t_fast = measure("velo run --fast main.py")
        t_cpython = measure("python main.py")
        assert t_fast <= t_cpython * 1.1  # Allow 10% margin
```

---

## L1: Happy Path (5 items - Complete user journey)

| ID | Test | Validation | Expected |
|----|------|------------|----------|
| L1-01 | Cold start performance | First run faster than CPython | speedup >= 2x |
| L1-02 | Warm start performance | Second run faster | speedup >= 5x |
| L1-03 | FastAPI project | Real framework works | HTTP 200 |
| L1-04 | 100-module project | Scale support | All load correctly |
| L1-05 | Dependency tree | numpy/pandas etc | import succeeds |

```python
# tests/qa/phase5/test_l1_happy_path.py
class TestL1HappyPath:
    def test_cold_start_speedup(self, large_project):
        clear_cache()
        t_fast = measure("velo run --fast main.py")
        t_cpython = measure("python main.py")
        assert t_cpython / t_fast >= 2.0
    
    def test_warm_start_speedup(self, large_project):
        run("velo run --fast main.py")  # Warm up
        t_fast = measure("velo run --fast main.py")
        t_cpython = measure("python main.py")
        assert t_cpython / t_fast >= 5.0
    
    def test_fastapi_project(self, fastapi_project):
        proc = start("velo run --fast main:app")
        wait_for_port(8000)
        resp = requests.get("http://localhost:8000/")
        assert resp.status_code == 200
        proc.terminate()
```

---

## L2: Sad Path (4 items - Failure recovery)

| ID | Test | Scenario | Expected |
|----|------|----------|----------|
| L2-01 | Corrupted bundle | Random byte overwrite | Fallback succeeds, program runs |
| L2-02 | Missing module | Delete source file | Clear error message |
| L2-03 | Fingerprint change | Modify pyproject.toml | Auto rebuild |
| L2-04 | Disk space exhausted | Write failure | Graceful degradation |

```python
# tests/qa/phase5/test_l2_sad_path.py
class TestL2SadPath:
    def test_corrupted_bundle_fallback(self, project):
        run("velo build")
        corrupt_file(".velo/cache/bundle.veloc")
        result = run("velo run --fast main.py")
        assert result.returncode == 0  # Fallback works
        assert "Hello" in result.stdout
    
    def test_fingerprint_change_rebuild(self, project):
        run("velo build")
        mtime_before = get_mtime("bundle.veloc")
        modify("pyproject.toml")
        run("velo run --fast main.py")
        mtime_after = get_mtime("bundle.veloc")
        assert mtime_after > mtime_before  # Triggered rebuild
```

---

## L3: Config (5 items - Option validation)

| ID | Test | Option | Expected |
|----|------|--------|----------|
| L3-01 | `--rebuild` | Force rebuild | Rebuilds even without changes |
| L3-02 | `--no-deps` | Exclude dependencies | Bundle contains only project code |
| L3-03 | `--exclude` | Exclude modules | Specified modules not bundled |
| L3-04 | `--output` | Custom path | Bundle written to specified path |
| L3-05 | `--help` | Help info | Shows all options |

---

## L4: Security (10 items - Security verification)

**Prerequisite**: L0-L3 all pass

| ID | Test | Threat | Expected |
|----|------|--------|----------|
| L4-01 | Symlink attack | Points to /tmp | Reject loading |
| L4-02 | Multi-layer symlink | Chain bypass | Canonicalize detection |
| L4-03 | World-writable | Permission 0666 | Reject loading |
| L4-04 | Hash tampering | Modify content | Verification fails |
| L4-05 | Header tampering | Modify module_count | Verification covers header |
| L4-06 | Offset out of bounds | data_offset = 0 | Boundary check |
| L4-07 | Integer overflow | offset + size wrap | Detect and reject |
| L4-08 | Path traversal | `../../../etc/passwd` | Module name validation |
| L4-09 | Marshal bomb | Depth 10000 | Recursion limit |
| L4-10 | /var/tmp path | Dangerous directory | Complete blacklist |

---

## L5: Edge/Chaos (10 items - Extreme scenarios)

**Prerequisite**: L0-L4 all pass

| ID | Test | Scenario | Expected |
|----|------|----------|----------|
| L5-01 | 256MB boundary | Exactly 256MB | Success |
| L5-02 | 256.1MB exceeded | Over limit | Clear rejection |
| L5-03 | 10000 modules | Large scale | < 100ms load |
| L5-04 | 0 modules | Empty bundle | Reasonable handling |
| L5-05 | Unicode name | Japanese.py | Correct handling |
| L5-06 | Deep nesting | a.b.c.d...x50 | Correct parsing |
| L5-07 | Circular deps | A->B->A | Detect and error |
| L5-08 | Rebuild interrupted | SIGKILL | Recover normally |
| L5-09 | Concurrent build | Multi-process | flock protection |
| L5-10 | Memory pressure | Low memory env | Graceful degradation |

---

## CI Integration Recommendation

```yaml
# .github/workflows/phase5-qa.yml
jobs:
  l0-smoke:
    runs-on: ubuntu-latest
    steps:
      - run: pytest tests/qa/phase5/test_l0_*.py -v
  
  l1-happy:
    needs: l0-smoke
    steps:
      - run: pytest tests/qa/phase5/test_l1_*.py -v
  
  l2-sad:
    needs: l1-happy
    steps:
      - run: pytest tests/qa/phase5/test_l2_*.py -v
  
  l3-config:
    needs: l2-sad
    steps:
      - run: pytest tests/qa/phase5/test_l3_*.py -v
  
  l4-security:
    needs: l3-config
    steps:
      - run: pytest tests/qa/phase5/test_l4_*.py -v
  
  l5-chaos:
    needs: l4-security
    if: github.ref == 'refs/heads/main'
    steps:
      - run: pytest tests/qa/phase5/test_l5_*.py -v
```

---

## Test Count Summary

| Level | Count | Run Timing |
|-------|-------|------------|
| L0 Smoke | 3 | Every commit |
| L1 Happy | 5 | Every commit |
| L2 Sad | 4 | Every commit |
| L3 Config | 5 | Every PR |
| L4 Security | 10 | Every PR |
| L5 Chaos | 10 | main branch |
| **Total** | **37** | - |

---

**Document End**
