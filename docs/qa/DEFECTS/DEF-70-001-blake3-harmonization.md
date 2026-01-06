# DEF-70-001: SHA256 Residual in `cache.rs` (BLAKE3 Harmonization)

> **Status**: 🟡 OPEN  
> **Severity**: P1 (Must fix - Crypto Standard Violation)  
> **Reporter**: Architect (ID-LOCK-001)  
> **Date**: 2026-01-07  
> **Target**: `src/cache.rs`

---

## 1. Problem Statement

The cryptography expert (Phase 6.0) mandated **BLAKE3** as the sole hashing algorithm for all security-relevant operations (P1-013, P1-014). However, `cache.rs` still uses SHA256 for computing the `packages_hash` field.

## 2. Affected Code

| File | Line | Current | Should Be |
| :--- | :--- | :--- | :--- |
| `src/cache.rs` | L10 | `use sha2::{Digest, Sha256};` | `// Remove or replace with blake3` |
| `src/cache.rs` | L34 | `/// SHA256 hash of uv.lock` | `/// BLAKE3 hash of uv.lock` |
| `src/cache.rs` | L50 | `/// SHA256 of sorted pip freeze` | `/// BLAKE3 of sorted pip freeze` |
| `src/cache.rs` | L187 | `Sha256::digest(...)` | `blake3::hash(...)` |

## 3. Rationale (Expert Opinion)

From [cryptography-expert-audit.md](../qa/PHASES/phase-6/reviews-6.0/cryptography-expert-audit.md):

> **P1-013**: BLAKE3's **Keyed Mode** MUST be used for all security bindings.
> **P1-014**: `machine_key` MUST be derived using BLAKE3 in **Derive Key Mode**.

**Why harmonize?**
1. **Performance**: BLAKE3 is ~6x faster than SHA256.
2. **Consistency**: Mixed algorithms increase maintenance burden.
3. **Security**: BLAKE3 is natively immune to length extension attacks.

## 4. Acceptance Criteria

1. `src/cache.rs` no longer imports `sha2` crate.
2. `compute_packages_hash()` uses `blake3::hash()`.
3. All comments updated to reflect BLAKE3 usage.
4. Existing tests pass (hash length assertion may change from 64 to 64 - no change for hex output).

## 5. Verification

```bash
cargo test cache::tests
grep -r "sha2" src/  # Should return no results in cache.rs
```
