# Agent C (Security Expert) -> Review Agent A Edge Test Design

> **Reviewer**: Agent C (Security Expert)  
> **Review Target**: Agent A Edge Test Matrix (A-01 ~ A-10)  
> **Date**: 2026-01-03  
> **Stance**: From security perspective, review edge tests for security implications

---

## Core Review Findings

### 1. A-01 Bundle Size Boundary -> Security Enhancement

**Original Design**: Test 255.9MB / 256MB / 256.1MB boundary

**Agent C Security Supplement**:

| ID | Security Scenario | Risk |
|----|-------------------|------|
| C-A-01a | **Exactly 256MB - 1 byte** | Boundary value may be mishandled |
| C-A-01b | **Negative size declaration** | Integer interpretation differences |
| C-A-01c | **Bundle size vs header size mismatch** | Logic vulnerability |

```rust
// C-A-01c: Size mismatch attack
#[test]
fn test_size_mismatch_attack() {
    // Header claims 100MB, actual file 1MB
    // Must use actual file size, don't trust header
}
```

---

### 2. A-04 Module Name Limit -> DoS Risk

**Original Design**: 1000 character module name

**Agent C Security Supplement**:

| ID | Security Scenario | Risk |
|----|-------------------|------|
| C-A-04a | **1MB module name** | Memory exhaustion |
| C-A-04b | **Control character module name** | Log injection |
| C-A-04c | **Newline module name** | Log spoofing |

```python
# C-A-04b: Log injection via module name
def test_module_name_log_injection():
    """Module names with control chars must be sanitized in logs"""
    evil_name = "safe\x1b[31mFAKE_ERROR\x1b[0m"
    bundle = create_bundle_with_module_name(evil_name)
    logs = capture_logs(load_bundle(bundle))
    
    # Must escape control characters
    assert "\x1b" not in logs
```

---

### 3. A-08 NaN/Inf in offset -> Type Safety

**Original Design**: Tamper with offset in index

**Agent C Security Supplement**:

| ID | Security Scenario | Risk |
|----|-------------------|------|
| C-A-08a | **rkyv deserialization attack** | Type confusion |
| C-A-08b | **Unknown field injection** | Future compatibility attack |

```rust
// C-A-08a: rkyv deserialization safety
#[test]
fn test_rkyv_malformed_input() {
    // Construct format-correct but semantically-wrong rkyv data
    // rkyv won't auto-validate business logic
}
```

---

### 4. A-09 Negative offset -> Memory Safety

**Original Design**: offset = -1

**Agent C Security Supplement**:

| ID | Security Scenario | Memory Impact |
|----|-------------------|---------------|
| C-A-09a | **offset = u64::MAX** | Wraps to small value |
| C-A-09b | **offset in header region** | Self-reference attack |
| C-A-09c | **offset exactly points to magic bytes** | Execute "VELO" as code |

```rust
// C-A-09b: Self-reference attack
#[test]
fn test_offset_points_to_header() {
    // Module data offset points to header region
    // May cause header to be interpreted as bytecode
    let entry = ModuleEntry {
        offset: 0,  // Points to "VELO" magic
        size: 64,
        ..
    };
    assert!(validate_entry(&entry).is_err());
}
```

---

### 5. A-10 Overlapping modules -> Data Isolation

**Original Design**: Two modules with overlapping offset

**Agent C Security Supplement**:

| ID | Security Scenario | Security Impact |
|----|-------------------|-----------------|
| C-A-10a | **Complete overlap** | Same data different module names |
| C-A-10b | **Partial overlap** | Data contamination |
| C-A-10c | **Index and data overlap** | Structure corruption |

```python
# C-A-10a: Same data, different names (alias attack)
def test_module_aliasing_attack():
    """Two module names pointing to same bytecode is suspicious"""
    # Attacker may use this to bypass module name checks
    bundle = create_bundle_with_overlapping_modules(
        "safe_module", "evil_module", same_offset=True
    )
    result = load_bundle(bundle)
    assert "OverlappingModules" in str(result.err())
```

---

### 6. New: Security Expert Found Agent A Omissions

| ID | Threat Type | Why Agent A Missed |
|----|-------------|-------------------|
| **C-A-NEW-01** | **Timezone attack** | mtime interpreted differently in different timezones |
| **C-A-NEW-02** | **inode reuse** | Delete and recreate may reuse inode |
| **C-A-NEW-03** | **Sparse file attack** | Claims large but actual disk small |

---

## Agent C Summary

| Original Case | Agent C Enhancement |
|---------------|---------------------|
| A-01 Size | +3 |
| A-04 Name | +3 |
| A-08 NaN | +2 |
| A-09 Offset | +3 |
| A-10 Overlap | +3 |
| (New) | +3 |

**Total**: Edge tests supplemented with **17 items** from security perspective

---

**Agent C Sign-off**: Independent review complete  
**Recommendation**: Set C-A-09b (self-reference attack) and C-A-10c (structure overlap) as **P0**
