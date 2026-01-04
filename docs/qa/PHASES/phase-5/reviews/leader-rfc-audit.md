# QA Leader: RFC-0006 Phase 5.0 Fast Loader Line-by-Line Security Audit

> **Auditor**: QA Leader  
> **Audit Target**: Agent C Security Test Matrix (C-01 ~ C-10)  
> **Date**: 2026-01-03  
> **Audit Standard**: tiered-testing-guide.md + Security First Principles  
> **Stance**: Never let a single vulnerability slip through

---

## Audit Methodology

```
For each section of RFC-0006:
1. Extract security-related claims
2. Verify if there is corresponding test coverage
3. Identify hidden assumptions and blind spots
4. Mark risk level (S0/S1/S2/S3)
5. Specify test requirements
```

---

# Part 1: Technical Design Audit (Section 2.1 - 2.17)

## Section 2.3 Runtime Flow Audit

**RFC Claim**:
```
velo run main.py
├─ 1. Load fingerprint (from Phase 1.5 cache)
│     if fingerprint unchanged:
│         use cached bundle  ←── FAST PATH
```

### Finding #1: Fingerprint Verification Unclear

| Issue | RFC only says "fingerprint unchanged" but doesn't specify how to verify |
|-------|------------------------------------------------------------------------|
| Risk | S0: Attacker may forge fingerprint to use malicious bundle |
| Test Requirement | Verify if fingerprint is cryptographically signed |

```python
# AUDIT-001: Fingerprint integrity
def test_fingerprint_not_forgeable():
    """Fingerprint must be cryptographically bound to bundle"""
    original_fp = get_fingerprint()
    modify_bundle_content()
    assert get_fingerprint() != original_fp  # Must change
```

---

## Section 2.5 Bundle Format Audit

**RFC Claim**:
```rust
struct BundleHeader {
    magic: [u8; 4],           // "VELO"
    version: u32,             // Format version
    abi_tag: [u8; 32],        // "cp312-darwin-arm64"
    ...
}
```

### Finding #2: Magic Verification Bypass

| Issue | Only checking 4 bytes "VELO" is too weak |
|-------|------------------------------------------|
| Risk | S1: Other format files may coincidentally match |
| Test Requirement | Verify magic + version + abi triple check |

```python
# AUDIT-002: Magic collision
def test_magic_collision_rejected():
    """Files starting with VELO but wrong format must be rejected"""
    fake_bundle = b"VELO" + b"\x00" * 1000
    assert load_bundle(fake_bundle).is_err()
```

### Finding #3: version Field Range Undefined

| Issue | version: u32 but valid range not specified |
|-------|-------------------------------------------|
| Risk | S1: Future version compatibility issues |
| Test Requirement | Verify behavior when version > current_version |

```python
# AUDIT-003: Future version handling
def test_future_version_rejected():
    """Bundle with future version must fail gracefully"""
    bundle = create_bundle(version=999999)
    result = load_bundle(bundle)
    assert "UnsupportedVersion" in result.err()
```

### Finding #4: abi_tag Fixed Length Risk

| Issue | abi_tag: [u8; 32] fixed length |
|-------|--------------------------------|
| Risk | S2: Some platforms' abi_tag may be truncated if too long |
| Test Requirement | Verify boundary length handling |

---

## Section 2.6 Import-Order Data Layout Audit

**RFC Claim**:
```rust
fn build_bundle(project: &Path) -> Result<()> {
    let import_graph = load_import_graph(project)?;
    let sorted = topological_sort(&import_graph);
```

### Finding #5: import_graph Not Verified

| Issue | load_import_graph() loads from file without integrity verification |
|-------|-------------------------------------------------------------------|
| Risk | S0: Attacker can tamper import_graph.json to change module order |
| Test Requirement | import_graph.json must have signature or hash verification |

```python
# AUDIT-005: Import graph tampering
def test_import_graph_tampering_detected():
    """Modified import_graph.json must trigger rebuild"""
    build_bundle()
    tamper_with("import_graph.json")
    result = velo_run("--fast")
    assert result.rebuilt or result.rejected
```

---

## Section 2.11 Integrity Verification Audit

**RFC Claim**:
```rust
fn verify_bundle(bundle: &[u8]) -> Result<()> {
    let header = parse_header(bundle)?;
    let computed = sha256(&bundle[data_offset..]);
    if computed != header.content_hash {
        return Err(BundleCorrupted);
    }
}
```

### Finding #6: Header Not Covered by Hash

| Issue | SHA-256 only verifies data section, not header |
|-------|------------------------------------------------|
| Risk | S0: Attacker can modify header (e.g., module_count) without triggering verification |
| Test Requirement | Header must be included in hash calculation |

```python
# AUDIT-006: Header excluded from hash
def test_header_modification_detected():
    """Header changes must invalidate content_hash"""
    bundle = create_valid_bundle()
    modify_header_module_count(bundle, 9999)
    result = load_bundle(bundle)
    assert "HashMismatch" in result.err()  # Must detect!
```

### Finding #7: data_offset Source Untrusted

| Issue | `&bundle[data_offset..]`'s data_offset comes from header |
|-------|----------------------------------------------------------|
| Risk | S0: Attacker can set data_offset = 1, skipping header |
| Test Requirement | data_offset must verify >= header_size |

```python
# AUDIT-007: data_offset manipulation
def test_data_offset_underflow():
    """data_offset pointing into header must be rejected"""
    bundle = create_bundle_with_data_offset(1)  # Points into magic
    result = load_bundle(bundle)
    assert "InvalidOffset" in result.err()
```

---

## Section 2.15.4 CRC32 Per-Module Audit

**RFC Claim**:
```
| Level | Algorithm | Purpose | Speed |
|-------|-----------|---------|-------|
| **Bundle** | SHA-256 | Security/tamper detection | ~500 MB/s |
| **Module** | CRC32 | Fast corruption detection | ~20 GB/s |
```

### Finding #8: Dual Verification Timing Issue

| Issue | Verification order of SHA-256 and CRC32 not specified |
|-------|------------------------------------------------------|
| Risk | S2: Checking CRC32 first may be used as timing oracle |
| Test Requirement | SHA-256 must be verified before CRC32 |

---

## Section 2.17 Secure Loading Protocol Audit

**RFC Claim**:
```rust
fn validate_bundle_security(path: &Path) -> Result<()> {
    // Reject world-writable
    if mode & 0o002 != 0 {
        return Err(InsecurePermissions);
    }
    
    // Reject /tmp and shared directories
    if path.starts_with("/tmp") {
        return Err(InsecureLocation);
    }
}
```

### Finding #9: Incomplete Path Check

| Issue | Only checks `/tmp`, misses other dangerous paths |
|-------|--------------------------------------------------|
| Risk | S0: `/var/tmp`, `/dev/shm`, `$TMPDIR` not checked |
| Test Requirement | All world-writable directories must be rejected |

```python
# AUDIT-009: Incomplete temp directory check
DANGEROUS_PATHS = [
    "/tmp",
    "/var/tmp",
    "/dev/shm",
    os.environ.get("TMPDIR", "/tmp"),
    "/run/user/1000",  # Linux user temp
]

@pytest.mark.parametrize("path", DANGEROUS_PATHS)
def test_dangerous_path_rejected(path):
    """All temp/shared directories must be rejected"""
    bundle_path = f"{path}/bundle.veloc"
    result = velo_load(bundle_path)
    assert "InsecureLocation" in result.err()
```

### Finding #10: starts_with() Bypass

| Issue | `path.starts_with("/tmp")` can be bypassed by `/tmp2` |
|-------|-------------------------------------------------------|
| Risk | S1: Directory named `/tmp2` or `/tmpxxx` won't be rejected |
| Test Requirement | Use component-level matching instead of prefix matching |

```python
# AUDIT-010: starts_with bypass
def test_starts_with_bypass():
    """Path /tmp2/bundle.veloc should NOT be rejected (not /tmp)"""
    os.makedirs("/tmp2", exist_ok=True)
    result = velo_load("/tmp2/bundle.veloc")
    # Expected behavior needs clarification!
```

### Finding #11: Symlink Check Missing

| Issue | validate_bundle_security() doesn't mention symlink |
|-------|---------------------------------------------------|
| Risk | S0: When symlink points to /tmp, path itself doesn't start with /tmp |
| Test Requirement | Must canonicalize before checking |

```python
# AUDIT-011: Symlink bypass (Not mentioned in RFC!)
def test_symlink_bypass_detected():
    """Symlink to /tmp must be detected via canonicalization"""
    os.symlink("/tmp/evil.veloc", "safe_looking.veloc")
    result = velo_load("safe_looking.veloc")
    assert "InsecureLocation" in result.err()
```

---

## Section 2.17 Marshal Security Audit

**RFC Claim**:
```
> [!CAUTION]
> `marshal.loads()` is a dangerous operation. Strict protocol required.
```

### Finding #12: marshal.loads() Depth Limit Undefined

| Issue | RFC doesn't specify recursion depth limit |
|-------|------------------------------------------|
| Risk | S0: DoS via deeply nested code objects |
| Test Requirement | Verify Python's built-in limit is sufficient |

```python
# AUDIT-012: marshal recursion depth
def test_marshal_recursion_bomb():
    """Deeply nested code objects must not crash"""
    # Create depth-10000 nested code object
    evil_bytecode = create_nested_code_object(depth=10000)
    result = marshal.loads(evil_bytecode)
    # Should throw ValueError, not RecursionError or crash
```

---

# Part 2: Implementation Plan Audit (Section 3)

## Section 3.4 Implementation Tips Audit

**RFC Claim**:
```rust
let file = OpenOptions::new()
    .read(true).write(true).create(true)
    .mode(0o600)  // Owner-only
    .open(".velo/cache/build.lock")?;
```

### Finding #13: O_CLOEXEC Not Explicitly Used

| Issue | No `O_CLOEXEC` or `FD_CLOEXEC` visible |
|-------|----------------------------------------|
| Risk | S2: Child process after fork may inherit lock file |
| Test Requirement | Verify Rust std default behavior |

---

## Section 3.5 Pre-Flight Checks Audit

**RFC Claim**:
```rust
const MAX_BUNDLE_SIZE: u64 = 256 * 1024 * 1024; // 256MB Hard Limit
```

### Finding #14: 32-bit Platform Difference

| Issue | 256MB may exceed address space on 32-bit systems |
|-------|--------------------------------------------------|
| Risk | S1: 32-bit systems may OOM |
| Test Requirement | 32-bit platforms should have lower limit |

```python
# AUDIT-014: 32-bit platform limit
def test_32bit_bundle_limit():
    """32-bit platforms should have lower bundle limit"""
    if platform.architecture()[0] == '32bit':
        assert MAX_BUNDLE_SIZE <= 64 * MB
```

---

# Part 3: Risk Mitigation Audit (Section 6)

## Section 6.6 TOCTOU Prevention Audit

**RFC Claim**:
```rust
// CORRECT: Atomic verification
let data = fs::read(path)?;           // 1. Read entire file to RAM
let hash = sha256(&data[header_end..]); // 2. Verify in memory
```

### Finding #15: fs::read() Itself Not Atomic

| Issue | fs::read() for large files may involve multiple syscalls |
|-------|----------------------------------------------------------|
| Risk | S1: Attacker may replace file during read |
| Test Requirement | Verify behavior when file is replaced during read |

```python
# AUDIT-015: Read during modification
def test_file_modified_during_read():
    """Bundle modified during read should be detected"""
    # Use FUSE to simulate slow read
    # Replace file content during read
    # Verify final hash matches original or fails
```

---

# Part 4: Comparison with tiered-testing-guide.md

## Gap Analysis

| tiered-testing-guide Requirement | RFC-0006 Coverage | Gap |
|---------------------------------|-------------------|-----|
| Tier 0 Smoke (Binary/CLI) | velo build, velo run --fast | None |
| Tier 1 Security | Security design exists but tests incomplete | **Findings #1-15** |
| Tier 2 Integration | No complete integration test plan | Needs supplement |
| Tier 3 Chaos | No stress test design | Needs supplement |
| Agent A (Edge) | Edge cases not fully covered | See A-01~A-10 |
| Agent B (Stability) | Regression hardening insufficient | See B-01~B-10 |
| Agent C (Security) | Security tests need major enhancement | **Key audit findings** |

---

# Audit Results Summary

## By Severity

| Severity | Count | Finding IDs |
|----------|-------|-------------|
| S0 Critical | **8** | #1, #5, #6, #7, #9, #11, #12, #15 |
| S1 Major | **4** | #2, #3, #10, #14 |
| S2 Medium | **2** | #4, #8 |
| S3 Low | **1** | #13 |

## P0 Blocking Items List

```python
P0_BLOCKING_ISSUES = [
    "AUDIT-001: Fingerprint cryptographic binding",
    "AUDIT-005: Import graph tampering detection",
    "AUDIT-006: Header excluded from hash coverage",
    "AUDIT-007: data_offset boundary validation",
    "AUDIT-009: Incomplete temp directory whitelist",
    "AUDIT-011: Symlink bypass via canonicalization",
    "AUDIT-012: Marshal recursion depth bomb",
    "AUDIT-015: fs::read atomicity assumption",
]
```

---

## Audit Recommendations

### 1. Must Fix Before Phase 5.0.1

- [ ] AUDIT-006: Extend content_hash to cover entire file
- [ ] AUDIT-007: Add data_offset >= sizeof(header) check
- [ ] AUDIT-009: Complete dangerous path blacklist
- [ ] AUDIT-011: Add symlink resolution

### 2. Must Fix Before Phase 5.0 GA

- [ ] AUDIT-001: Fingerprint signing mechanism
- [ ] AUDIT-005: Import graph integrity verification
- [ ] AUDIT-012: Document marshal depth limit

### 3. Can Defer to Phase 5.1

- [ ] AUDIT-004: abi_tag length extension
- [ ] AUDIT-013: Explicit O_CLOEXEC usage

---

**QA Leader Sign-off**: Audit complete  
**Conclusion**: RFC-0006 has **8 P0 security issues**, not recommended to proceed to implementation in current state.

---

**Document End**
