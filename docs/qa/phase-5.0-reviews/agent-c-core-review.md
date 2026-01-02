# Agent C (Security Expert) -> Review Agent B Core Flow Design

> **Reviewer**: Agent C (Security Expert)  
> **Review Target**: Agent B Core Flow Test Matrix (B-01 ~ B-10)  
> **Date**: 2026-01-03  
> **Stance**: From security perspective, review core flow for security implications

---

## Core Review Findings

### 1. B-02 Import Hook Registration -> Hook Hijacking Risk

**Original Design**: Verify VeloFinder at sys.meta_path[0]

**Agent C Security Supplement**:

| ID | Security Scenario | Risk |
|----|-------------------|------|
| C-B-02a | **Malicious module pre-registers** | Third-party module inserts hook first |
| C-B-02b | **Hook removed** | Runtime sys.meta_path.remove() |
| C-B-02c | **Hook order changed** | Other code insert(0, evil_hook) |

```python
# C-B-02a: Hook hijacking detection
def test_hook_hijacking_detection():
    """Velo should detect if another hook is inserted before it"""
    velo_start()  # VeloFinder at [0]
    
    evil_hook = EvilFinder()
    sys.meta_path.insert(0, evil_hook)  # Hijack!
    
    # Velo should detect and warn on next import
    assert "HookPositionChanged" in capture_warnings()
```

---

### 2. B-03/B-04 Cache Hit/Miss -> Cache Poisoning

**Original Design**: Fingerprint change triggers rebuild

**Agent C Security Supplement**:

| ID | Security Scenario | Risk |
|----|-------------------|------|
| C-B-03a | **Fingerprint collision** | Different environments same fingerprint |
| C-B-03b | **Cache directory poisoning** | Attacker pre-plants malicious bundle |
| C-B-04a | **Injection during rebuild** | File replaced during rebuild process |

```python
# C-B-03b: Cache directory poisoning
def test_cache_poisoning_prevention():
    """Pre-existing cache must be validated before use"""
    # Attacker pre-plants malicious bundle in .velo/cache/
    plant_malicious_bundle(".velo/cache/bundle.veloc")
    
    # First velo run must validate bundle integrity
    result = velo_run("--fast", "main.py")
    
    # If fingerprint doesn't match, should rebuild not use
    assert result.used_fresh_bundle
```

---

### 3. B-05 Fallback Mechanism -> Fallback Oracle

**Original Design**: Fallback to standard import when bundle corrupted

**Agent C Security Supplement**:

| ID | Security Scenario | Risk |
|----|-------------------|------|
| C-B-05a | **Fallback information leak** | Error message exposes paths |
| C-B-05b | **Fallback performance attack** | Deliberately trigger fallback to bypass security |
| C-B-05c | **Bundle reuse after fallback** | Attacker fixes bundle |

```python
# C-B-05b: Fallback as security bypass
def test_fallback_not_bypass_security():
    """Fallback mode must still apply security checks"""
    # In fallback mode, standard import should still have basic security
    # Cannot load arbitrary .pyc just because of fallback
```

---

### 4. B-06 Native Extension -> Load Security

**Original Design**: .so goes through filesystem

**Agent C Security Supplement**:

| ID | Security Scenario | Risk |
|----|-------------------|------|
| C-B-06a | **.so path injection** | Malicious .so replacement |
| C-B-06b | **DYLD_LIBRARY_PATH hijack** | Environment variable attack |
| C-B-06c | **.so signature verification** | macOS code signing |

```python
# C-B-06a: .so path injection
def test_so_path_injection_prevention():
    """Native extension paths must be validated"""
    # Create malicious .so in priority path
    create_malicious_so("/tmp/numpy/core.so")
    
    # Velo should only load .so from project venv
    result = velo_run("--fast", "import_numpy.py")
    
    assert "loaded from /tmp" not in result.so_paths
```

---

### 5. B-07/B-08 Multi-Version/Multi-Platform -> Downgrade Attack

**Original Design**: Independent bundle paths for each

**Agent C Security Supplement**:

| ID | Security Scenario | Risk |
|----|-------------------|------|
| C-B-07a | **Version downgrade attack** | Use old bundle to bypass security fixes |
| C-B-08a | **Platform spoofing** | macOS bundle loaded on Linux |

```python
# C-B-07a: Version downgrade attack
def test_version_downgrade_prevention():
    """Old version bundles must not be usable in new environments"""
    # Python 3.11 bundle should not work in 3.12
    # Even if attacker manually copies
    copy_bundle("3.11/bundle.veloc", "3.12/bundle.veloc")
    
    result = velo_run("--fast", "main.py", python="3.12")
    assert result.rebuilt_bundle  # Must rebuild, can't use old
```

---

### 6. B-09/B-10 Performance Tests -> Side-Channel Attack

**Original Design**: Performance benchmarks

**Agent C Security Supplement**:

| ID | Security Scenario | Risk |
|----|-------------------|------|
| C-B-09a | **Timing side-channel** | Load time leaks module existence |
| C-B-10a | **Cache side-channel** | warm vs cold exposes information |

```python
# C-B-09a: Timing side-channel mitigation
def test_constant_time_module_lookup():
    """Module lookup time should not leak existence"""
    time_exist = measure_import_time("numpy")  # exists
    time_not_exist = measure_import_time("not_a_module")  # doesn't exist
    
    # Time difference should be within noise range
    assert abs(time_exist - time_not_exist) < 1 * MS
```

---

## Agent C Summary

| Original Case | Agent C Enhancement |
|---------------|---------------------|
| B-02 Hook | +3 |
| B-03/04 Cache | +3 |
| B-05 Fallback | +3 |
| B-06 Native | +3 |
| B-07/08 Version | +2 |
| B-09/10 Perf | +2 |

**Total**: Core flow tests supplemented with **16 items** from security perspective

---

**Agent C Sign-off**: Independent review complete  
**Recommendation**: Set C-B-03b (cache poisoning) and C-B-06a (.so injection) as **P0**
