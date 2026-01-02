# Agent A (Aggressive QA) -> Review Agent B Core Flow Design

> **Reviewer**: Agent A (Edge Case Specialist)  
> **Review Target**: Agent B Core Flow Test Matrix (B-01 ~ B-10)  
> **Date**: 2026-01-03  
> **Stance**: From boundary conditions perspective, review core flow robustness

---

## Core Review Findings

### 1. B-01 Basic Bundle Loading -> Boundary Enhancement

**Original Design**: Valid bundle.veloc loads successfully

**Agent A Supplement**:

| ID | Boundary Scenario | Why Important |
|----|-------------------|---------------|
| A-B-01a | **First module load fails** | First module special handling |
| A-B-01b | **Last module load fails** | Tail boundary |
| A-B-01c | **Only 1 module** | Minimum set |
| A-B-01d | **__init__.py missing** | Incomplete package structure |

```python
# A-B-01c: Single module bundle
def test_single_module_bundle():
    """Minimum viable bundle with just one module"""
    bundle = create_bundle(modules=["single_module.py"])
    result = load_bundle(bundle)
    assert result.module_count == 1
    assert result.ok()
```

---

### 2. B-03/B-04 Cache Hit/Miss -> Boundary Conditions

**Original Design**: Fingerprint change triggers rebuild

**Agent A Supplement**:

| ID | Boundary Scenario | Why Important |
|----|-------------------|---------------|
| A-B-03a | **Fingerprint only 1 bit change** | Minimum change |
| A-B-03b | **Fingerprint file corrupted** | Error handling |
| A-B-04a | **Rebuild killed midway** | Partial write |
| A-B-04b | **Disk full during rebuild** | Resource exhaustion |

```python
# A-B-04a: Interrupted rebuild recovery
def test_rebuild_interrupted():
    """System should recover from interrupted rebuild"""
    # 1. Start rebuild
    # 2. Kill at 50% written
    # 3. Re-run should re-rebuild, not use corrupted
```

---

### 3. B-05 Fallback Mechanism -> Extreme Fallback

**Original Design**: Fallback when bundle corrupted

**Agent A Supplement**:

| ID | Boundary Scenario | Why Important |
|----|-------------------|---------------|
| A-B-05a | **Fallback to non-existent module** | Double failure |
| A-B-05b | **Bundle recovers after fallback** | State switching |
| A-B-05c | **100 consecutive fallbacks** | Performance/memory leak |

```python
# A-B-05c: Repeated fallback stress
def test_repeated_fallback_no_leak():
    """100x fallback should not leak memory"""
    for _ in range(100):
        corrupt_bundle()
        result = velo_run("--fast", "main.py")
        fix_bundle()
    
    assert memory_usage() < initial_memory * 1.1
```

---

### 4. B-06 Native Extension -> Boundary Scenarios

**Original Design**: .so goes through filesystem

**Agent A Supplement**:

| ID | Boundary Scenario | Why Important |
|----|-------------------|---------------|
| A-B-06a | **.so file 0 bytes** | Invalid binary |
| A-B-06b | **.so permission 000** | Unreadable |
| A-B-06c | **Same name .py and .so** | Priority conflict |
| A-B-06d | **.so in symlink directory** | Path resolution |

```python
# A-B-06c: .py vs .so priority
def test_py_so_priority():
    """When both numpy.py and numpy.so exist, .so takes priority"""
    create_file("numpy.py", "# fake")
    create_file("numpy.so", native_extension)
    
    result = import_module("numpy")
    assert result.loaded_from.endswith(".so")
```

---

### 5. B-09/B-10 Performance Tests -> Extreme Load

**Original Design**: 200 module benchmark

**Agent A Supplement**:

| ID | Boundary Scenario | Why Important |
|----|-------------------|---------------|
| A-B-09a | **0 modules performance** | Baseline |
| A-B-09b | **10000 modules performance** | Large scale |
| A-B-09c | **100KB per module** | Large modules |
| A-B-10a | **Frequent cold/hot switching** | Cache thrashing |

```python
# A-B-09b: Large scale performance
def test_10k_module_performance():
    """10000 modules should still be < 100ms cold start"""
    bundle = create_bundle(modules=[f"mod_{i}.py" for i in range(10000)])
    cold_start_time = benchmark_cold_start(bundle)
    
    assert cold_start_time < 100 * MS
```

---

## Agent A Summary

| Original Case | Agent A Enhancement |
|---------------|---------------------|
| B-01 Load | +4 |
| B-03/04 Cache | +4 |
| B-05 Fallback | +3 |
| B-06 Native | +4 |
| B-09/10 Perf | +4 |

**Total**: Core flow tests supplemented with **19 items** from boundary perspective

---

**Agent A Sign-off**: Independent review complete  
**Recommendation**: Set A-B-04a (rebuild interrupted) and A-B-05c (fallback leak) as **P0**
