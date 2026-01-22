# RFC-0035: Native Library Preload Optimization (.so Pre-warming)

**Status**: DRAFT
**Author**: Velo Architect
**Date**: 2026-01-19
**Phase**: Phase 15 (Future)
**Scope**: Performance, Startup Optimization, Security

> **Note**: This RFC focuses on **native library pre-loading**. For application packaging, see RFC-0034.
> **Prerequisite**: Extends existing `EnvironmentFingerprint` system from `src/custody/fingerprint.rs`.

---

## 1. Executive Summary

This RFC proposes **Native Library Preload**, extending Velo's existing fingerprint-verified preload system to include `.so`/`.dylib` files. Libraries are pre-loaded before Python startup, verified against stored fingerprints, and shared across workers via COW.

| Metric | Standard Import | Preload Optimized |
|:---|:---|:---|
| PyTorch import | ~2-3s | **< 500ms** |
| NumPy import | ~200ms | **< 50ms** |
| Native extension load | dlopen on-demand | Pre-mapped + fingerprint-verified |

---

## 2. Core Invariants

> [!IMPORTANT]
> **INV-PRELOAD-001**: Native libraries MUST be fingerprint-verified before loading.
> **INV-PRELOAD-002**: Only libraries in trusted paths (site-packages, explicit whitelist) may be preloaded.
> **INV-PRELOAD-003**: Fingerprint mismatch MUST block preload and warn user.
> **INV-PRELOAD-004**: preload.lock MUST include runtime fingerprint (os, arch, python_version).
> **INV-PRELOAD-005**: Runtime mismatch MUST block preload with clear error.
> **INV-PRELOAD-006**: Implementation MUST NOT require any modification to the user's Python source code (Drop-in Purity).
> **INV-PRELOAD-007**: **Silent Resilience (Mismatches)**: Preloading failure due to missing, mismatched, or stale fingerprints MUST NOT terminate the process; Velo MUST silently fallback to standard Python import.
> **INV-PRELOAD-008**: **Invisible Fatalities**: Velo acknowledges that native library static initializers (C/C++ `__attribute__((constructor))`) can cause fatal segfaults during `dlopen`. To mitigate this, Velo MUST isolate the preload sequence in a Zygote sub-process (Crash Containment).
> **INV-PRELOAD-009**: **Deferred Visibility Promotion**: Velo MUST support `GlobalOnImport` mode, where libraries are preloaded with `RTLD_LOCAL` and promoted to `RTLD_GLOBAL` only upon the first standard Python `import`.

---

## 3. Architecture

### 3.1 Fingerprint-First Design

Native library preload extends the existing `EnvironmentFingerprint` system:

```rust
// src/custody/fingerprint.rs (EXTENSION)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NativeLibFingerprint {
    /// Absolute path to the library (canonicalized)
    pub path: PathBuf,
    /// Parent package (e.g., "torch" for libtorch.so)
    pub package: String,
    /// ELF SONAME (e.g., "libtorch.so.2.1.0") - handles symlinks
    pub soname: Option<String>,
    /// Fast check: mtime of file
    pub mtime: u64,
    /// Authority: BLAKE3 hash of ELF/Mach-O header (first 4KB)
    pub header_hash: String,
    /// Platform metadata
    pub platform: LibPlatform,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LibPlatform {
    pub os: String,        // "linux" | "darwin"
    pub arch: String,      // "x86_64" | "aarch64"
    pub libc_type: String, // "glibc" | "musl"
    pub elf_osabi: Option<u8>,  // ELF OS/ABI byte
}
```

### 3.2 Verification Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Preload Verification Flow                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Load preload.lock                                        │
│     └── Contains NativeLibFingerprint for each library      │
│                                                              │
│  2. Fast Path: mtime check                                   │
│     ├── mtime unchanged → Trust cached fingerprint          │
│     └── mtime changed → Recompute header_hash               │
│                                                              │
│  3. Runtime Check (INV-PRELOAD-004/005)                      │
│     ├── Check os/arch match current environment             │
│     └── Mismatch → BLOCK + ERROR (wrong platform)           │
│                                                              │
│  4. Library Verify                                           │
│     ├── Hash match → Proceed to security check              │
│     └── Hash mismatch → BLOCK + WARN (stale config)         │
│                                                              │
│  5. Security Check                                           │
│     ├── Path in site-packages OR whitelist → OK             │
│     └── Path in /tmp or untrusted → REJECT                  │
│                                                              │
│  6. Load                                                     │
│     └── dlopen(path, RTLD_NOW | RTLD_LOCAL)                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 Configuration

```toml
# pyproject.toml
[tool.velo.native_preload]
# Package::library format (auto-resolves path from site-packages)
libraries = [
    "torch::libtorch.so",
    "torch::libtorch_cpu.so",
    "numpy.core::libopenblas.so",
]

# Auto-detect from installed packages
auto_detect = true

# Verification strictness
verify_mode = "mtime+hash"  # "mtime" (fast) | "hash" (strict) | "mtime+hash" (default)

# Symbol visibility (P1 Council Fix)
rtld_mode = "local"  # "local" (default, safe) | "global" (opt-in, risk)
```

### 3.4 Lock File

```json
// .velo/preload.lock
{
  "version": 1,
  "generated_at": 1705678900,
  "runtime_fingerprint": {
    "os": "linux",
    "arch": "x86_64",
    "libc_type": "glibc",
    "libc_version": "2.31",
    "python_version": "3.11.6",
    "venv_path": "/path/to/venv"
  },
  "libraries": [
    {
      "path": "/path/to/venv/lib/python3.11/site-packages/torch/lib/libtorch.so",
      "package": "torch",
      "soname": "libtorch.so.2.1.0",
      "mtime": 1705678800,
      "header_hash": "abc123def456...",
      "platform": { "os": "linux", "arch": "x86_64", "libc_type": "glibc", "elf_osabi": 0 }
    }
  ]
}

### 3.5 "Drop-in" Guarantee Implementation

To ensure the user's Python code remains untouched (`import torch` just works), we strictly separate Memory Mapping from Python Initialization.

```rust
// Core logic ensuring Drop-in Compatibility & Crash Containment
fn preload_library_isolated(lib: &NativeLibFingerprint) -> PreloadResult {
    // 1. VERIFY: Check hashes/paths (Safe Fallback if fails)
    if let Err(e) = verify_fingerprint(lib) {
        warn!("Skipping preload for {}: {}", lib.package, e);
        return PreloadResult::Skipped; 
    }

    // 2. ISOLATE: Fork a temporary zygote-child to perform the dlopen
    // This protects the main Zygote from "Bad Library" static initializers.
    match unsafe { fork() } {
        Ok(ForkResult::Child) => {
            // Perform actual dlopen
            let flags = match lib.rtld_mode.as_str() {
                "global" => libc::RTLD_NOW | libc::RTLD_GLOBAL,
                _ => libc::RTLD_NOW | libc::RTLD_LOCAL,
            };
            let handle = unsafe { libc::dlopen(lib.path.as_ptr(), flags) };
            if handle.is_null() { exit(1); }
            
            // Keep child alive if success, or exit gracefully
            exit(0); 
        }
        Ok(ForkResult::Parent { child }) => {
            // Monitor for Segfault (SIGSEGV) or success
            let status = waitpid(child, None);
            if status_was_segfault(status) {
                error!("CRITICAL: Library {} caused a segfault in initializer. Disabling preload.", lib.package);
                return PreloadResult::FatalCrash; 
            }
            // If child exited 0, the main process can now safely dlopen the same inode
            // knowing that the initializer has been "vetted" in the sub-process.
            unsafe { libc::dlopen(lib.path.as_ptr(), libc::RTLD_NOW | libc::RTLD_LOCAL) };
        }
        Err(_) => return PreloadResult::Failed,
    }
    
    PreloadResult::Success
}
```

### 3.6 Configuration for Complex Libraries (Torch/NumPy)

To solve the Symbol Visibility issue, we provide a "Known Good" configuration preset in `pyproject.toml`.

```toml
[tool.velo.native_preload]
# Explicitly handle complex libraries to ensure compatibility
libraries = [
    # PyTorch requires GLOBAL symbols for its plugins
    { package = "torch", path = "lib/libtorch.so", mode = "global" },
    # Standard libs are fine with LOCAL (safer)
    { package = "numpy", path = "core/libopenblas.so", mode = "local" }
]
```
```

---

## 4. Security Model

### 4.1 Venv-Bound Path Validation (P0)

> **Design Principle**: preload.lock is **bound to the specific venv** that generated it. All library paths must be within that venv.

```rust
/// Security Model: Strict Venv-Bound Validation
/// No "trusted prefixes" logic - just strict path containment

const BLOCKED_PREFIXES: &[&str] = &[
    "/tmp/",
    "/var/tmp/",
    "/dev/shm/",
];

fn validate_library_path(lib_path: &Path, venv_root: &Path) -> Result<()> {
    // 1. Canonicalize both paths (resolve symlinks, normalize)
    let lib_canonical = lib_path.canonicalize()
        .map_err(|_| Error::PathNotFound(lib_path))?;
    let venv_canonical = venv_root.canonicalize()
        .map_err(|_| Error::VenvNotFound(venv_root))?;
    
    // 2. Block dangerous paths (defense in depth)
    for blocked in BLOCKED_PREFIXES {
        if lib_canonical.starts_with(blocked) {
            return Err(Error::BlockedPath(lib_canonical));
        }
    }
    
    // 3. Strict containment: library must be within venv (bytes comparison)
    if !lib_canonical.starts_with(&venv_canonical) {
        return Err(Error::PathOutsideVenv {
            lib: lib_canonical,
            venv: venv_canonical,
        });
    }
    
    Ok(())
}
```

**Why this is the best approach**:
| Aspect | Benefit |
|:---|:---|
| **Security** | No "contains string" vulnerabilities |
| **Simplicity** | Zero configuration, no trusted prefixes to maintain |
| **Reproducibility** | Lock is bound to exact venv, regenerate if venv changes |

### 4.2 Symbol Visibility (P1 Council Fix)

| Mode | RTLD Flags | Use Case | Risk |
|:---|:---|:---|:---|
| `local` (default) | `RTLD_NOW \| RTLD_LOCAL` | Most libraries | Low - isolated symbols |
| `global` (opt-in) | `RTLD_NOW \| RTLD_GLOBAL` | Interdependent libs (CUDA) | High - symbol pollution |

---

## 5. CLI Interface

```bash
# Analyze project and generate preload.lock
velo preload analyze

# Verify current preload.lock against installed libraries
velo preload verify
# Output: ✅ All 3 libraries verified
# Output: ⚠️ libtorch.so hash mismatch (pip upgraded torch?)

# Run with preload
velo run main.py  # Uses preload.lock automatically

# Explicit override
velo run --preload "torch::libtorch.so" main.py
```

---

## 6. Integration with Existing Features

| Feature | Integration |
|:---|:---|
| **EnvironmentFingerprint** | NativeLibFingerprint stored alongside pyproject/lock hash |
| **Zygote (RFC-0019)** | Preload happens before Zygote pre-warming |
| **Memory Gravity (RFC-0015)** | Preloaded libs shared via COW across workers |
| **Bundle (RFC-0034)** | Bundle includes preload.lock for reproducible deploys |

---

## 7. Platform Support

| Platform | Status | Notes |
|:---|:---|:---|
| **Linux x86_64** | ✅ Primary | Full support |
| **Linux aarch64** | ✅ Supported | Full support |
| **macOS** | ❌ v1.0 Out of Scope | dyld two-level namespace incompatible |
| **Windows** | ❌ Future | LoadLibrary semantics differ |

---

## 8. Implementation Phases

### Phase 1: Fingerprint Infrastructure
- [ ] Extend `NativeLibFingerprint` struct
- [ ] Implement header-only BLAKE3 hashing
- [ ] Generate `preload.lock` format

### Phase 2: Verification & Loading
- [ ] Implement mtime fast-path
- [ ] Implement trusted path validation
- [ ] Implement `dlopen` with RTLD_LOCAL default

### Phase 3: CLI & Integration
- [ ] `velo preload analyze` command
- [ ] `velo preload verify` command
- [ ] Automatic preload on `velo run/serve`

---

## 9. Quality Gates

| Gate | Requirement |
|:---|:---|
| **Gate A** | PyTorch import < 500ms with preload |
| **Gate B** | Fingerprint mismatch blocks preload with clear error |
| **Gate C** | Untrusted path (/tmp) is rejected |
| **Gate D** | No symbol resolution errors with RTLD_LOCAL |

---

## 10. Grand Council Review (2026-01-22)

**Verdict**: 🟡 **CONDITIONALLY APPROVED** (v2.0 Revision)

### Mandatory Remediation (P0)

| ID | Requirement | Rationale |
|:---|:---|:---|
| **REQ-REMED-001** | **Deep Verification Flag** | Add `deep_verify: bool` for full binary BLAKE3 hash to prevent deep patching attacks in high-security zones. |
| **REQ-REMED-002** | **SOABI-Based Tracking** | Refactor `RuntimeFingerprint` to use `sys.config.get_config_var('SOABI')` for robust ABI compatibility tracking. |
| **REQ-REMED-003** | **Parallel Loading Protocol** | IPC protocol MUST support batching `PRELOAD_LIB` requests for concurrent `dlopen` via a thread pool in Zygote. |
| **REQ-REMED-004** | **Symbol Boundary Audit** | Explicit requirement to verify `dlopen(RTLD_LOCAL)` doesn't break `torch.cuda` symbol dependencies. |

### Addressed Issues (v1.0 -> v2.0)

| Issue | Resolution |
|:---|:---|
| Fingerprint requirement | ✅ INV-PRELOAD-001: Mandatory verification |
| RTLD_GLOBAL pollution | ✅ Default to RTLD_LOCAL |
| Untrusted path attack | ✅ Trusted path validation |
| Version mismatch | ✅ `velo preload verify` command |
| macOS dyld | ✅ Out of scope for v1.0 |
| Runtime fingerprint | ✅ REQ-REMED-002: SOABI-based check |

### Future Work (P2)

| Item | Description |
|:---|:---|
| `user` field | Track generator UID for multi-user shared environments. |
| Parallel preload | Implementation of Parallel Loading Protocol (REQ-REMED-003). |

---

## 11. Final Engineering Directives

### Directive A: The "Double-Load" Optimization
**Rule**: To maintain the optimization for the process lifetime, the implementation MUST NOT call `dlclose` on preloaded handles. The handle MUST intentionally leak so that the OS reference count remains >= 1, allowing Python to reuse the existing mapping upon its standard `import`.

### Directive B: The "Global" Allowlist Presets
**Rule**: By default, Velo MUST promote the following libraries to `RTLD_GLOBAL` visibility:
- `libtorch.so`
- `libtensorflow.so`
- `libpython*.so`
- *All others default to `RTLD_LOCAL` (Safety First).*

---

**Custodian**: Velo Architect
**Last Updated**: 2026-01-22

