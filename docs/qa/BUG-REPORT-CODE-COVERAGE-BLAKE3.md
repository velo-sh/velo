# BUG Report: Code Coverage BLAKE3 Test Failures

**Date**: 2026-01-03  
**Severity**: Medium  
**Component**: Rust Unit Tests (`tests/loader_tests.rs`)  
**CI Job**: Code Coverage

## Summary

Two Rust security tests fail in the Code Coverage job due to a mismatch between test expectations and the actual H-1 Global Hash scheme implementation.

## Failing Tests

1. `security_tests::test_accepts_valid_blake3` (line 162)
2. `security_tests::test_accepts_valid_module_hash` (line 193)

## Root Cause

### Test Code (Incorrect)
```rust
let data = b"test data for hashing";
let correct_hash = blake3::hash(data);
let result = verify_blake3(data, correct_hash.as_bytes());
```

### Actual Implementation (`verify.rs`)
```rust
// H-1 Global Hash: Covers Identity Prefix + Content (skips hash field)
hasher.update(&data[0..20]);   // Identity Prefix
hasher.update(&data[52..]);    // Content after hash field
```

The tests use simple `blake3::hash(full_data)`, but `verify_blake3` implements RFC-0008 H-1 scheme with split hashing regions.

## Required Fix

Update tests to provide properly structured test data:
1. Create mock bundle data ≥52 bytes with correct header structure
2. Calculate hash using the H-1 scheme (hash [0..20] + [52..EOF])
3. Place computed hash in bytes [20..52]

## Impact

- ✅ All QA tests pass (L0-L5, Tier 0-2)
- ❌ Code Coverage job fails
- No production impact
