# Phase 5.0 Fast Loader: P0 Security Blocking Checklist

> **Author**: QA Leader  
> **Date**: 2026-01-03  
> **Status**: BLOCKING IMPLEMENTATION

---

## Executive Summary

**RFC-0006 is not ready for implementation.**

Through QA Leader independent audit + three-party Agent cross-review:

| Category | S0 Critical | S1 Major | Total |
|----------|-------------|----------|-------|
| Leader Audit | 8 | 4 | 12 |
| Agent A Additions | 3 | 2 | 5 |
| Agent B Additions | 1 | 3 | 4 |
| Agent C Additions | 4 | 2 | 6 |
| **Total** | **16** | **11** | **27** |

---

## P0 Blocking Items (Must fix before implementation)

### 1. Hash Coverage Range (AUDIT-006)

**Problem**: content_hash only covers data section, header unprotected  
**Attack**: Modify module_count causing out-of-bounds read  
**Fix**: `content_hash = sha256(entire_file)`

### 2. data_offset Validation (AUDIT-007)

**Problem**: data_offset from untrusted header, boundary not validated  
**Attack**: `data_offset = 0` causes magic to be treated as bytecode  
**Fix**: `assert data_offset >= sizeof(BundleHeader)`

### 3. Symlink Bypass (AUDIT-011, A-C-01a)

**Problem**: Path check doesn't use canonicalize()  
**Attack**: Symlink chain bypasses /tmp check  
**Fix**: Three-layer check: raw + read_link + canonicalize

### 4. Incomplete Dangerous Paths (AUDIT-009)

**Problem**: Only checks /tmp, misses /var/tmp, /dev/shm, $TMPDIR  
**Fix**: Complete blacklist + is_world_writable() check

### 5. Fingerprint Not Signed (AUDIT-001)

**Problem**: Fingerprint can be forged  
**Attack**: Replace bundle but keep fingerprint  
**Fix**: fingerprint = HMAC(env_hash, bundle_hash)

### 6. Import Graph Not Verified (AUDIT-005)

**Problem**: import_graph.json can be tampered  
**Attack**: Change module load order, inject dependencies  
**Fix**: Integrate into fingerprint calculation

### 7. Marshal Recursion Bomb (AUDIT-012)

**Problem**: No recursion depth limit for marshal.loads()  
**Attack**: Deeply nested code object (depth 10000) -> stack overflow  
**Fix**: Explicitly set sys.setrecursionlimit() or pre-check

### 8. Read Atomicity Assumption (AUDIT-015)

**Problem**: fs::read() for large files is non-atomic  
**Attack**: Replace file content during read  
**Fix**: flock() or double-check verification after read

---

## P1 Blocking Items (Can fix during implementation, must complete before GA)

| ID | Problem | Fix |
|----|---------|-----|
| AUDIT-002 | Magic collision | Add extra validation bytes |
| AUDIT-003 | Future version handling | Explicitly reject version > current |
| AUDIT-010 | starts_with bypass | Component-level path matching |
| AUDIT-014 | 32-bit limit | Platform-specific MAX_SIZE |
| C-B-03b | Cache poisoning | Cache integrity verification |
| C-B-06a | .so path injection | Venv path whitelist |
| A-B-04a | Rebuild interrupted | Atomic write (rename) |

---

## Verification Tests After Fix

```python
# P0 tests must all pass
P0_SECURITY_TESTS = [
    "test_content_hash_covers_entire_file",
    "test_data_offset_boundary_validation",
    "test_symlink_chain_canonicalization",
    "test_dangerous_paths_complete_blacklist",
    "test_fingerprint_cryptographic_binding",
    "test_import_graph_integrity_check",
    "test_marshal_recursion_limit",
    "test_read_atomicity_verification",
]
```

---

## Next Actions

### Architect Must (Before Implementation)

1. **Update RFC-0006** to address 8 P0 issues
2. **Add Section 2.18 Security Invariants**
3. **Resubmit for review**

### QA Must (After RFC Update)

1. Re-audit updated RFC
2. Create P0 test cases
3. Integrate into CI blocking gate

---

**QA Leader Conclusion**: Block Implementation  
**Reason**: 8 S0 Critical security issues unresolved

---

**Document End**
