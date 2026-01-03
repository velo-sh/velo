# High-Fidelity Security Blueprint (Phase 5.x)

This document provides the **exact logic** required to resolve the "Security RED" state. The Developer role MUST follow these blueprints verbatim to satisfy the prosecutor tests.

---

## 🏗️ Rust Blueprint: `verify.rs` (H-1 & H-5)

### 1. Read Atomicity (H-5)
```rust
use std::fs::File;
use fs2::FileExt; // Ensure fs2 is in Cargo.toml

pub fn load_and_verify(path: &Path, limit: Option<u64>) -> Result<VerifiedBundle> {
    let file = File::open(path)?;
    file.lock_shared()?; // REQUIRED: Atomic lock before size check or read

    let effective_limit = limit.unwrap_or(security::DEFAULT_MAX_BUNDLE_SIZE);
    security::validate_all(path, effective_limit)?; // validate size while locked

    let mut data = Vec::with_capacity(file.metadata()?.len() as usize);
    file.read_to_end(&mut data)?; // Read while locked
    // ...
}
```

### 2. Global Hash Coverage (H-1)
```rust
// Requirement: Hash [0..20] Identity + [52..EOF] Content
let mut hasher = blake3::Hasher::new();
hasher.update(&data[0..20]);    // Magic, Version, HashAlgo, Offsets
hasher.update(&data[52..]);     // Data + Index (Skips Content Hash field)
let actual = hasher.finalize();

if actual.as_bytes() != expected_hash {
    return Err(LoaderError::BundleCorrupted { ... });
}
```

---

## 🏗️ Python Blueprint: `velo_loader.py` (H-4)

### 3. Recursive Marshal protection (H-4)
```python
import sys
import marshal

MARSHAL_RECURSION_LIMIT = 500

def safe_marshal_loads(data):
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(MARSHAL_RECURSION_LIMIT)
    try:
        return marshal.loads(data)
    finally:
        sys.setrecursionlimit(old_limit)
```

---

## 🏗️ Rust Blueprint: `cache.rs` (H-6)

### 4. Keyed Cryptographic Binding (H-6)
```rust
// Use blake3::keyed_hash with a machine-specific key
// Fingerprint = blake3::keyed_hash(MACHINE_KEY, uv_lock_content)
pub fn compute_fingerprint(project_dir: &Path) -> Option<String> {
    let lock_file = project_dir.join("uv.lock");
    let content = fs::read(&lock_file).ok()?;
    
    // MACHINE_KEY should be locally derived (e.g., from machine-id)
    let key = get_machine_key(); 
    let hash = blake3::keyed_hash(&key, &content);
    Some(hash.to_hex().to_string())
}
```

---
*Verified by Architect (ID-LOCK-001)*
