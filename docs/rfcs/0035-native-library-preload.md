# RFC-0035: Native Library Preload Optimization (.so Pre-warming)

**Status**: EXECUTION_APPROVED (v2.4)
**Author**: Velo Architect
**Date**: 2026-01-22
**Phase**: Phase 15 (Native Preload Implementation)
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
> **INV-PRELOAD-001**: Native libraries MUST be fingerprint-verified (full binary hash or rolling header hash) before loading.
> **INV-PRELOAD-002**: Only libraries in trusted paths (site-packages, explicit whitelist) may be preloaded.
> **INV-PRELOAD-003**: Fingerprint mismatch MUST block preload and warn user.
> **INV-PRELOAD-004**: `preload.lock` MUST include runtime fingerprint (os, arch, python_version, libc_version, SOABI).
> **INV-PRELOAD-005**: Runtime mismatch (Current < Required) MUST block preload.
> **INV-PRELOAD-006**: Implementation MUST NOT require any modification to the user's Python source code (Drop-in Purity).
> **INV-PRELOAD-007**: **Silent Resilience (Mismatches)**: Preloading failure due to missing, mismatched, or stale fingerprints MUST NOT terminate the process; Velo MUST silently fallback to standard Python import.
> **INV-PRELOAD-008**: **The Death Pact (Vet-then-Load)**: To protect Zygote from `ld.so` state corruption, Velo MUST spawn a disposable "Vet" child process to attempt preloading. Only libraries that survive vetting are loaded into the main Zygote. Any segfault in the "Vet" phase is considered fatal to that specific library's preload but not to the main process.
> **INV-PRELOAD-009**: **Split-Stage Loading**: Velo MUST distinguish between **Native Dependencies** (preloaded before Python init) and **Extension Modules** (preloaded after Python init, before fork).
> **INV-PRELOAD-010**: **Portability**: Paths in `preload.lock` MUST be relative to the virtual environment root.

---

## 3. Architecture

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NativeLibFingerprint {
    /// Relative path to venv root
    pub relative_path: PathBuf,
    /// Parent package (e.g., "torch")
    pub package: String,
    /// ELF SONAME
    pub soname: String,
    /// Full BLAKE3 hash (Integrity)
    pub hash: String,
    /// Platform metadata
    pub platform: LibPlatform,
    /// Stage: Pre-Init vs Post-Init
    pub load_stage: LoadStage,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LibPlatform {
    pub os: String,
    pub arch: String,
    pub python_version: String,
    pub libc_type: String,
    pub libc_version: String,
    pub soabi: String,
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
  "generator": {
    "velo_version": "0.9.5",
    "git_commit": "3701969"
  },
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

### 3.4 Recursive Dependency Walker
To minimize manual configuration, Velo MUST implement a recursive `DT_NEEDED` walker:
1. User identifies a root library (e.g., `torch`).
2. Velo reads the ELF dynamic section for `DT_NEEDED` tags.
3. Velo auto-discovers and fingerprints all transitive dependencies (e.g., `libc10.so`, `libtorch_cpu.so`) located within the venv.

### 3.5 Path & Security Sanitization
- **RPATH Sanitization**: Velo MUST warn if a preloaded library contains `$ORIGIN` or `RPATH` pointing outside of the authorized `site-packages` or system directories.
- **Header vs Full Hash**: Defaults to rolling header hash for speed; `deep_verify: true` triggers full-file BLAKE3 verification.

To ensure the user's Python code remains untouched (`import torch` just works), we strictly separate Memory Mapping from Python Initialization.

```rust
// Revised Preload Logic: Risk Management via the "Death Pact" (Vet-then-Load)
// Stage 1: Native Dependencies (Pre-Python Init)
// Stage 2: Extension Modules (Post-Python Init)

fn preload_sequence_zygote(libs: &[NativeLibFingerprint]) {
    // 1. Spawn a "Vet" child process to experiment with the load
    match unsafe { fork() } {
        Ok(ForkResult::Child) => {
            for lib in libs {
                // RTLD_NOW ensures all relocations happen in the child for vetting
                let handle = unsafe { libc::dlopen(lib.path.as_ptr(), libc::RTLD_NOW | libc::RTLD_LOCAL) };
                if handle.is_null() { exit(1); }
            }
            exit(0); // All vetted!
        }
        Ok(ForkResult::Parent { child }) => {
            let status = waitpid(child, None);
            if status_was_success(status) {
                // 2. CHILD SURVIVED: Main process safely loads and relocates (True COW sharing)
                for lib in libs {
                    let flags = libc::RTLD_NOW | libc::RTLD_LOCAL;
                    let handle = unsafe { libc::dlopen(lib.path.as_ptr(), flags) };
                    std::mem::forget(handle); // Intentional Leak (Directive A)
                }
            } else {
                warn!("Vetting failed (Death Pact triggered). Falling back to standard Python import.");
            }
        }
        Err(_) => warn!("Failed to spawn Vet sandbox."),
    }
}
```

### 3.6 Configuration for Complex Libraries (Torch/NumPy)

To solve the Symbol Visibility issue, we provide a "Known Good" configuration preset in `pyproject.toml`.

```toml
[tool.velo.native_preload]
# Explicitly handle complex libraries to ensure compatibility
# Velo classifies these into Stage 1 (Native) and Stage 2 (Extension)
libraries = [
    # Phase 2: Python Extension (Loaded AFTER Python Init)
    { package = "torch", path = "lib/libtorch.so", stage = "extension" },
    # Phase 1: Native Dependency (Loaded BEFORE Python Init)
    { package = "numpy", path = "core/libopenblas.so", stage = "native" }
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

> [!NOTE]
> **System Dependency Blocking**: If a preloaded library (e.g., NumPy) depends on system-level libraries (e.g., `libopenblas.so` in `/usr/lib`), Velo's strict venv containment WILL block the preloading of those system dependencies. This is **by design** to ensure the preloading process remains hermetic and bound to the virtual environment's fingerprint.

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

### 4.3 Threat Model (Phase 6.7)

> [!IMPORTANT]
> This section documents the *explicit* security boundaries of Native Library Preload.

#### 4.3.1 Attack Scenarios COVERED ✅

| Attack | Mitigation | Invariant |
|--------|------------|-----------|
| **Path Traversal Side-Loading** | Path Integrity validates library is within trusted boundaries (venv, project, system) | INV-PRELOAD-002 |
| **Adversarial Staging** (`/tmp`, `/dev/shm`) | Blocked paths list rejects adversarial staging areas | INV-PRELOAD-002 |
| **Binary Tampering (Post-Install)** | BLAKE3 fingerprint in `preload.lock` detects file modification | INV-PRELOAD-001, 003 |
| **Platform Mismatch** | Runtime fingerprint (os/arch/libc/SOABI) blocks cross-platform loading | INV-PRELOAD-004, 005 |
| **Stale Configuration** | mtime + hash verification forces re-analysis after pip upgrades | INV-PRELOAD-003 |
| **ld.so State Corruption** | Death Pact (Vet-then-Load) sandboxes risky dlopen in child process | INV-PRELOAD-008 |
| **Symbol Pollution** | RTLD_LOCAL default isolates symbols; RTLD_GLOBAL requires opt-in | Section 4.2 |

#### 4.3.2 Attack Scenarios NOT COVERED ❌

> [!CAUTION]
> The following attacks are **out of scope** for Native Preload and require additional security layers.

| Attack | Why NOT Covered | Future Mitigation |
|--------|-----------------|-------------------|
| **Compromised Package Index** | Malicious `.so` uploaded to PyPI → installed into trusted `site-packages` → passes path check | Provenance Guard (PEP 740 attestations, Sigstore) |
| **Build Poisoning (Toolchain)** | Library compiled with malicious compiler flags → no toolchain attestation | SLSA Build Provenance verification |
| **Supply Chain Substitution** | Typosquatting attack installs `numppy` instead of `numpy` → library in trusted path | Package name verification against lockfile |
| **Unsigned Wheel Replacement** | Attacker with venv write access replaces `.so` file → new hash matches new malicious file | Code signing verification (macOS `codesign`, Linux sigstore) |
| **C Extension Backdoors** | Malicious code in extension's `_init` → executes on import | Source code auditing, sandbox isolation |

#### 4.3.3 Security Recommendations

**For Users:**
1. **Lock Pip Dependencies**: Use `pip freeze` or `uv lock` to pin exact versions
2. **Verify PyPI Hashes**: Install with `pip install --require-hashes`
3. **Enable Path Integrity**: Keep `path_integrity = "warn"` (default) or `"enforce"` for strict mode
4. **Regular Re-Analysis**: Run `velo preload analyze` after any pip install/upgrade

**For Operators:**
1. **Immutable Deployments**: Deploy locked venv images to prevent runtime tampering
2. **Monitor Zygote Logs**: Watch for `[VELO-PRELOAD-FAIL]` and `[VELO-PATH-INTEGRITY]` warnings
3. **Network Isolation**: Prevent runtime package installation in production

**For Future Velo Versions (P1 Roadmap):**
- `provenance` field in `preload.lock` for signature/attestation storage
- macOS `codesign --verify` for system libraries
- Optional Sigstore integration for Linux

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
| **Gate E** | **Sharing Validation**: `Shared_Clean` in `smaps_rollup` > 200MB (for Torch) |

---

## 10. Grand Council Review (2026-01-22)

**Verdict**: 🟡 **CONDITIONALLY APPROVED** (v2.0 Revision)

### Mandatory Remediation (P0)

| ID | Requirement | Rationale |
|:---|:---|:---|
| **REQ-REMED-001** | **Deep Verification Flag** | Add `deep_verify: bool` for full binary BLAKE3 hash. |
| **REQ-REMED-002** | **SOABI-Based Tracking** | Refactor `RuntimeFingerprint` to use `SOABI` and `libc_version`. |
| **REQ-REMED-003** | **Zygote Path Sanitization** | Explicitly clean `LD_LIBRARY_PATH` and sanitize environment before preload. |
| **REQ-REMED-004** | **Relative Path Schema** | Implement relative-to-venv addressing in `preload.lock`. |

### Addressed Issues (v1.0 -> v2.0)

| Issue | Resolution |
|:---|:---|
| Fingerprint requirement | ✅ INV-PRELOAD-001: Mandatory verification |
| RTLD_GLOBAL pollution | ✅ Defaults to LOCAL; GLOBAL requires opt-in |
| Untrusted path attack | ✅ INV-PRELOAD-002: Venv-bound containment |
| Version mismatch | ✅ `libc_version` (Current >= Required) |
| macOS dyld | ✅ Out of scope for v1.0 |
| Relocation sharing | ✅ INV-PRELOAD-008: Prefork Preload |

### Future Work (P2)

| Item | Description |
|:---|:---|
| `user` field | Track generator UID for multi-user shared environments. |
| Parallel preload | Use a thread pool for concurrent `dlopen` of multiple libraries. |
| Visibility Promotion | `GlobalOnImport` mode (Deferred Promotion). |

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

