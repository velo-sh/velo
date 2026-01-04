# RFC-0006 Security Fix Recommendations

> **From**: QA Leader  
> **To**: Architect  
> **Date**: 2026-01-03  
> **Priority**: BLOCKING

---

## Executive Summary

RFC-0006 Phase 5.0 Fast Loader has **8 P0 security issues** that must be fixed before implementation.

This document provides specific code-level fix proposals.

---

# P0-001: content_hash Must Cover Entire File

## Problem

```rust
// Current RFC design (WRONG)
let computed = sha256(&bundle[data_offset..]);  // Only verifies data
```

## Attack

Attacker modifies header `module_count = 99999`, causing out-of-bounds read.

## Fix Proposal

```rust
// Option A: Hash covers entire file (Recommended)
struct BundleHeader {
    magic: [u8; 4],
    version: u32,
    // ...
    file_hash: [u8; 32],  // SHA-256 of entire file EXCLUDING this field
}

fn verify_bundle(path: &Path) -> Result<()> {
    let data = fs::read(path)?;
    
    // file_hash field at fixed offset (e.g., bytes 64-95)
    let hash_offset = 64;
    let expected = &data[hash_offset..hash_offset + 32];
    
    // Skip file_hash field itself when calculating
    let mut hasher = Sha256::new();
    hasher.update(&data[..hash_offset]);
    hasher.update(&data[hash_offset + 32..]);
    let computed = hasher.finalize();
    
    if computed.as_slice() != expected {
        return Err(Error::IntegrityFailed);
    }
    Ok(())
}
```

---

# P0-002: data_offset Must Validate Boundary

## Problem

```rust
// Current RFC design (WRONG)
let module_data = &bundle[data_offset..];  // data_offset from header
```

## Attack

Set `data_offset = 0`, treating "VELO" magic as bytecode.

## Fix Proposal

```rust
const MIN_HEADER_SIZE: usize = 128;  // Header minimum size

fn parse_bundle(data: &[u8]) -> Result<Bundle> {
    let header = parse_header(data)?;
    
    // Boundary check
    if header.data_offset < MIN_HEADER_SIZE as u64 {
        return Err(Error::InvalidDataOffset(
            format!("data_offset {} < minimum {}", header.data_offset, MIN_HEADER_SIZE)
        ));
    }
    
    if header.data_offset > data.len() as u64 {
        return Err(Error::InvalidDataOffset(
            format!("data_offset {} > file size {}", header.data_offset, data.len())
        ));
    }
    
    // Safe access
    let module_data = &data[header.data_offset as usize..];
    // ...
}
```

---

# P0-003: Symlink Must Use Three-Layer Check

## Problem

```rust
// Current RFC design (WRONG)
if path.starts_with("/tmp") {
    return Err(InsecureLocation);
}
```

## Attack

```bash
ln -s /tmp/evil.veloc ~/.velo/cache/bundle.veloc
# path = ~/.velo/cache/bundle.veloc, doesn't start with /tmp, bypasses check
```

## Fix Proposal

```rust
use std::fs;
use std::path::Path;

fn validate_path_security(path: &Path) -> Result<()> {
    // === Three-layer check ===
    
    // Layer 1: Raw path check
    if is_dangerous_path(path) {
        return Err(Error::InsecureLocation("raw path in dangerous location"));
    }
    
    // Layer 2: Read symlink target
    if let Ok(link_target) = fs::read_link(path) {
        if is_dangerous_path(&link_target) {
            return Err(Error::InsecureLocation("symlink points to dangerous location"));
        }
    }
    
    // Layer 3: Full canonicalization (resolve all symlinks)
    let canonical = fs::canonicalize(path)?;
    if is_dangerous_path(&canonical) {
        return Err(Error::InsecureLocation("canonical path in dangerous location"));
    }
    
    // Layer 4 (Optional): Check symlink chain depth
    let mut current = path.to_path_buf();
    for depth in 0..32 {  // Max 32 layers
        match fs::read_link(&current) {
            Ok(target) => current = target,
            Err(_) => break,  // Not a symlink
        }
        if depth >= 31 {
            return Err(Error::SymlinkLoopDetected);
        }
    }
    
    Ok(())
}

fn is_dangerous_path(path: &Path) -> bool {
    let dangerous = [
        "/tmp",
        "/var/tmp",
        "/dev/shm",
        "/run/user",
    ];
    
    // Use component matching, not starts_with
    for d in &dangerous {
        if path.starts_with(d) {
            let path_str = path.as_os_str().to_str().unwrap_or("");
            let after = &path_str[d.len()..];
            if after.is_empty() || after.starts_with('/') {
                return true;
            }
        }
    }
    
    // Check TMPDIR environment variable
    if let Ok(tmpdir) = std::env::var("TMPDIR") {
        if path.starts_with(&tmpdir) {
            return true;
        }
    }
    
    false
}
```

---

# P0-004: Complete Dangerous Path Blacklist

## Problem

Only checks `/tmp`, misses other writable directories.

## Fix Proposal

```rust
/// Dangerous path blacklist + dynamic detection
fn is_world_writable_location(path: &Path) -> Result<bool> {
    // Static blacklist
    let blacklist = [
        "/tmp",
        "/var/tmp",
        "/dev/shm",
        "/run/user",
        "/private/tmp",      // macOS
        "/private/var/tmp",  // macOS
    ];
    
    let canonical = fs::canonicalize(path)?;
    
    for blocked in &blacklist {
        if canonical.starts_with(blocked) {
            return Ok(true);
        }
    }
    
    // Dynamic detection: Is parent directory world-writable?
    if let Some(parent) = canonical.parent() {
        let meta = fs::metadata(parent)?;
        let mode = meta.permissions().mode();
        
        // Check other-write bit
        if mode & 0o002 != 0 {
            return Ok(true);
        }
        
        // Check sticky bit (like /tmp has sticky but still dangerous)
        if mode & 0o1000 != 0 && mode & 0o002 != 0 {
            return Ok(true);
        }
    }
    
    Ok(false)
}
```

---

# P0-005: Fingerprint Cryptographic Binding

## Problem

Fingerprint can be forged, attacker replaces bundle but keeps old fingerprint.

## Fix Proposal

```rust
use hmac::{Hmac, Mac};
use sha2::Sha256;

type HmacSha256 = Hmac<Sha256>;

/// Fingerprint = HMAC(machine_key, env_state || bundle_hash)
fn compute_fingerprint(
    env_state: &EnvState,
    bundle_hash: &[u8; 32],
) -> [u8; 32] {
    // Use machine-specific key (generated and stored on first run)
    let machine_key = get_or_create_machine_key();
    
    let mut mac = HmacSha256::new_from_slice(&machine_key)
        .expect("HMAC accepts any key size");
    
    // Bind environment state
    mac.update(env_state.python_version.as_bytes());
    mac.update(env_state.abi_tag.as_bytes());
    mac.update(&env_state.sys_path_hash);
    
    // Bind bundle content
    mac.update(bundle_hash);
    
    let result = mac.finalize();
    let mut fp = [0u8; 32];
    fp.copy_from_slice(&result.into_bytes()[..32]);
    fp
}
```

---

# P0-006: Import Graph Integrity

## Problem

`import_graph.json` loaded from file without integrity verification.

## Fix Proposal

```rust
/// import_graph hash included in fingerprint calculation
fn compute_env_fingerprint(project: &Path) -> Result<[u8; 32]> {
    let mut hasher = Sha256::new();
    
    // 1. Python version
    hasher.update(get_python_version()?.as_bytes());
    
    // 2. ABI tag
    hasher.update(get_abi_tag()?.as_bytes());
    
    // 3. pyproject.toml (locks dependencies)
    let pyproject = fs::read(project.join("pyproject.toml"))?;
    hasher.update(&pyproject);
    
    // 4. uv.lock (locks versions)
    let lock = fs::read(project.join("uv.lock"))?;
    hasher.update(&lock);
    
    // 5. import_graph.json (if exists)
    if let Ok(graph) = fs::read(project.join(".velo/cache/import_graph.json")) {
        hasher.update(&graph);
    }
    
    let result = hasher.finalize();
    let mut fp = [0u8; 32];
    fp.copy_from_slice(&result);
    Ok(fp)
}
```

---

# P0-007: Marshal Recursion Limit

## Problem

Deeply nested code objects may cause stack overflow.

## Fix Proposal

```python
# Python side
import sys
import marshal

# Set recursion limit before loading
_original_limit = sys.getrecursionlimit()

def safe_marshal_loads(data: bytes) -> object:
    """Safe wrapper for marshal.loads with recursion protection"""
    # Temporarily lower recursion limit
    sys.setrecursionlimit(500)  # Enough for normal code, blocks malicious depth
    try:
        return marshal.loads(data)
    except RecursionError:
        raise ValueError("Malformed bytecode: excessive nesting depth")
    finally:
        sys.setrecursionlimit(_original_limit)
```

---

# P0-008: Read Atomicity Guarantee

## Problem

`fs::read()` for large files may involve multiple syscalls, file replaced during read.

## Fix Proposal

```rust
use std::fs::File;
use std::os::unix::io::AsRawFd;

fn atomic_read_bundle(path: &Path) -> Result<Vec<u8>> {
    let file = File::open(path)?;
    
    // Get shared lock (blocks writes but allows other reads)
    flock(file.as_raw_fd(), FlockArg::LockShared)?;
    
    // Read to memory
    let mut data = Vec::new();
    file.read_to_end(&mut data)?;
    
    // Double-check: read beginning again to confirm unchanged
    let mut check = [0u8; 64];
    file.seek(SeekFrom::Start(0))?;
    file.read_exact(&mut check)?;
    
    if &data[..64] != &check {
        return Err(Error::FileModifiedDuringRead);
    }
    
    // Lock auto-releases when file scope ends
    Ok(data)
}

// Using nix crate
use nix::fcntl::{flock, FlockArg};
```

---

## RFC Update Checklist

Architect please add the following to RFC-0006:

### New Section 2.18 Security Invariants

```markdown
## 2.18 Security Invariants

The following security properties MUST be maintained:

1. **Hash Coverage**: `file_hash` covers the entire bundle file
2. **Offset Validation**: `data_offset >= MIN_HEADER_SIZE`
3. **Path Resolution**: Three-layer check (raw + symlink + canonical)
4. **Fingerprint Binding**: HMAC(machine_key, env_state || bundle_hash)
5. **Recursion Limit**: marshal.loads() depth < 500
6. **Read Atomicity**: flock() or double-check strategy
```

### Update Section 3 Implementation Plan

- [ ] Add security unit tests (at least 3 tests per P0 issue)
- [ ] Add fuzzing targets (fuzz header parsing)
- [ ] Add CI security check gate

---

**QA Leader Sign-off**: Fix recommendations complete  
**Expected Outcome**: Re-audit after fixes, implementation may proceed after passing

---

**Document End**
