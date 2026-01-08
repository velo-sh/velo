# Handover: Developer (DEF-70-001 - BLAKE3 Harmonization)

> **Mission**: Migrate remaining SHA256 usage in `cache.rs` to BLAKE3.
> **Role**: Developer (ID-LOCK-002)
> **SOP**: [SOP-001-master-lifecycle.md](../../docs/architecture/SOP-001-master-lifecycle.md)
> **Defect**: [DEF-70-001](../qa/DEFECTS/DEF-70-001-blake3-harmonization.md)

## 1. Deliverables

### [MODIFY] `src/cache.rs`

#### Step 1: Remove SHA256 import
```diff
- use sha2::{Digest, Sha256};
```

#### Step 2: Update `compute_packages_hash()` (Line ~170-188)
```diff
- let hash = Sha256::digest(packages.join("\n").as_bytes());
- Ok(hex::encode(hash))
+ let hash = blake3::hash(packages.join("\n").as_bytes());
+ Ok(hash.to_hex().to_string())
```

#### Step 3: Update comments
- L34: `/// BLAKE3 hash of uv.lock (environment fingerprint)`
- L50: `/// BLAKE3 of sorted pip freeze output`

### [MODIFY] `Cargo.toml` (Optional)
If `sha2` is no longer used anywhere else:
```diff
- sha2 = "0.10"
```

## 2. Invariants (Architect's Red Lines)
1. **Hash Length**: BLAKE3 hex output is 64 characters (same as SHA256). Tests should pass without modification.
2. **No Keyed Mode**: For `packages_hash`, plain `blake3::hash()` is sufficient (not security-critical, just integrity).

## 3. Verification
```bash
cargo test cache::tests
cargo clippy -- -D warnings
```
