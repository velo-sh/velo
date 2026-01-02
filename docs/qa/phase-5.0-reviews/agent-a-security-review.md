# Agent A (Aggressive QA) -> Review Agent C Security Design

> **Reviewer**: Agent A (Edge Case Specialist)  
> **Review Target**: Agent C Security Test Matrix (C-01 ~ C-10)  
> **Date**: 2026-01-03  
> **Stance**: From boundary conditions and attacker mindset, supplement security tests

---

## Core Review Findings

### 1. C-01 Symlink Bypass Needs Enhancement

**Existing Design Issue**:
C-01 only tests `/tmp/evil.veloc` scenario, missing more complex attack vectors.

**Agent A Supplementary Cases**:

| ID | Attack Scenario | Why More Dangerous |
|----|-----------------|-------------------|
| A-C-01a | **Multi-layer symlink chain** | `a->b->c->/tmp/evil.veloc` may bypass single-layer check |
| A-C-01b | **Relative path symlink** | `../../../tmp/evil.veloc` evades absolute path detection |
| A-C-01c | **Symlink loop** | `a->b->a` may cause infinite loop DoS |
| A-C-01d | **Symlink to symlink directory** | Parent directory is symlink |

```python
# A-C-01a: Multi-layer symlink chain
def test_symlink_chain_attack():
    """Chained symlinks must all be resolved"""
    os.symlink("/tmp", "link_a")
    os.symlink("link_a", "link_b")
    os.symlink("link_b/evil.veloc", ".velo/cache/bundle.veloc")
    # Must detect final target is /tmp
    assert velo_run("--fast").returncode != 0
```

---

### 2. C-03 TOCTOU Test Window Too Small

**Existing Design Issue**:
C-03 relies on "block after read, before parse" window, but actual attack window may be elsewhere.

**Agent A Supplementary Cases**:

| ID | Attack Timing | Test Method |
|----|---------------|-------------|
| A-C-03a | **Replace during read** | Use FUSE to simulate slow read, replace midway |
| A-C-03b | **Replace during hash calculation** | SHA-256 is streaming, file may change |
| A-C-03c | **Multi-threaded concurrency** | One thread reads, another writes |

```python
# A-C-03a: Slow read TOCTOU
def test_toctou_during_slow_read():
    """File replacement during slow read must be detected"""
    # Use FUSE mount to simulate 1ms per byte delay
    # Replace file during read
    # Verify: either read fails or hash mismatch
```

---

### 3. C-08 Memory Exhaustion Boundary Not Extreme Enough

**Existing Design Issue**:
C-08 only tests "claim 4GB but only 1KB", missing other memory attacks.

**Agent A Supplementary Cases**:

| ID | Attack Scenario | Expected Behavior |
|----|-----------------|-------------------|
| A-C-08a | **Claim 0 size, huge offset** | Early detection, don't attempt read |
| A-C-08b | **offset + size overflows to 0** | Integer overflow detection |
| A-C-08c | **100M modules of 1 byte each** | Memory allocation detection |

```rust
// A-C-08b: Integer overflow test
#[test]
fn test_offset_size_overflow() {
    let entry = ModuleEntry {
        offset: u64::MAX - 10,
        size: 100,  // offset + size wraps to small value
        ..
    };
    assert!(validate_entry(&entry, bundle_size).is_err());
}
```

---

### 4. C-09 Path Traversal Too Simple

**Existing Design Issue**:
C-09 only tests `../../../etc/passwd`, ignoring encoding bypasses.

**Agent A Supplementary Cases**:

| ID | Attack Payload | Bypass Technique |
|----|----------------|------------------|
| A-C-09a | `..%2f..%2f..%2fetc%2fpasswd` | URL encoding |
| A-C-09b | `....//....//etc/passwd` | Double-write bypass |
| A-C-09c | `\x00../etc/passwd` | Null byte injection |
| A-C-09d | `module/../../../etc/passwd` | Unicode + traversal |

```python
# A-C-09a: URL encoded path traversal
def test_path_traversal_variants():
    payloads = [
        "../../../etc/passwd",
        "..%2f..%2f..%2fetc%2fpasswd",
        "....//....//etc/passwd",
        "\x00../etc/passwd",
    ]
    for payload in payloads:
        bundle = create_bundle_with_module_name(payload)
        result = load_bundle(bundle)
        assert "InvalidModuleName" in str(result.err())
```

---

### 5. New: C-11 ~ C-15 (Agent A Discovered Omissions)

| ID | Threat Type | Attack Scenario | Why Important |
|----|-------------|-----------------|---------------|
| **A-C-11** | **Header tampering** | Modify module_count to huge value | May cause OOM |
| **A-C-12** | **Partial write attack** | Power failure mid-write | File integrity |
| **A-C-13** | **Hardlink attack** | Hardlink to system file | Different from symlink |
| **A-C-14** | **Bundle naming conflict** | `bundle.veloc` vs `Bundle.veloc` (case) | Filesystem differences |
| **A-C-15** | **Empty hash attack** | content_hash all 0x00 | Special value handling |

---

## Agent A Summary

| Original Case | Agent A Enhancement | New Cases |
|---------------|--------------------| ---------|
| C-01 | +4 | A-C-01a~d |
| C-03 | +3 | A-C-03a~c |
| C-08 | +3 | A-C-08a~c |
| C-09 | +4 | A-C-09a~d |
| (New) | +5 | A-C-11~15 |

**Total**: Security tests enhanced from 10 to **29 items**

---

**Agent A Sign-off**: Independent review complete  
**Recommendation**: Set A-C-01a (multi-layer symlink) and A-C-08b (integer overflow) as **P0**
