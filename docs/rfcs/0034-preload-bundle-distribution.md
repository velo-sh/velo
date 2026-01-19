# RFC-0034: Velo Bundle (Application Packaging & Distribution)

**Status**: DRAFT
**Author**: Velo Architect
**Date**: 2026-01-19
**Phase**: Phase 15 (Future)
**Scope**: Packaging, Distribution, Deployment

> **Note**: This RFC focuses on **source/software distribution** (static packaging).
> For runtime optimization (native library pre-loading), see RFC-0035.

---

## 1. Executive Summary

This RFC proposes **Velo Bundle**, a system for packaging Python applications with all dependencies and assets into a single distributable file (`.vbundle`). This is a **source distribution format**, not a runtime image.

| Aspect | Description |
|:---|:---|
| **Scope** | Source code + dependencies + assets |
| **Format** | Single `.vbundle` archive (tar.zst) |
| **Runtime** | Zygote pre-warming happens at deployment, not in bundle |
| **Target** | Clean machines with Velo installed |

---

## 2. Core Invariants

> [!IMPORTANT]
> **INV-BUNDLE-001**: Bundle contains only static assets (source, deps, configs).
> **INV-BUNDLE-002**: Runtime optimization (preload.lock, Zygote) is NOT part of bundle.
> **INV-BUNDLE-003**: Bundle MAY be signed; verification is opt-in (v1.0), mandatory in enterprise mode (future).
> **INV-BUNDLE-004**: Bundle is platform-tagged but runtime verification is deployment-time concern.

## 2. Motivation

### 2.1 The Serverless Cold Start Problem
Current serverless Python deployments suffer from:
1. **Dependency Installation**: `pip install` on every cold start
2. **Import Overhead**: Heavy frameworks (PyTorch, TensorFlow) take 2-5s to import
3. **Model Loading**: AI models require additional I/O from storage

### 2.2 The Velo Opportunity
Velo's Zygote architecture already solves import overhead via COW fork. The next step is to make this **portable and distributable**.

---

## 3. Architecture

### 3.1 Scope Separation

```
┌─────────────────────────────────────────────────────────────┐
│              RFC-0034 (This RFC)    │    RFC-0035           │
│              STATIC / BUILD-TIME    │    RUNTIME            │
├─────────────────────────────────────┼───────────────────────┤
│  .vbundle file                      │   preload.lock        │
│  ├── source code                    │   native lib dlopen   │
│  ├── site-packages/                 │   Zygote pre-warming  │
│  ├── assets (.safetensors)          │   fingerprint verify  │
│  └── manifest.json                  │   runtime checks      │
└─────────────────────────────────────┴───────────────────────┘
```

### 3.2 Bundle Format (`.vbundle`)

**File Format**: tar.zst (tar archive with Zstandard compression)

```
app.vbundle (tar.zst)
├── manifest.json           # Metadata + signature
├── src/                    # Application source code
├── site-packages/          # Pre-installed dependencies (wheels)
├── assets/                 # Static assets (models, configs)
│   ├── model.safetensors
│   └── config.json
└── pyproject.toml          # Project definition
```

### 3.3 Manifest Format

```json
{
  "bundle_version": "1.0",
  "name": "my-app",
  "version": "0.1.0",
  "build_platform": {
    "os": "linux",
    "arch": "x86_64",
    "python_version": "3.11.6"
  },
  "entrypoint": "app:main",
  "preload_hint": ["torch", "transformers"],
  "files": {
    "src/main.py": "sha256:abc123...",
    "site-packages/torch/...": "sha256:def456..."
  },
  "signature": "ed25519:..."
}
```

> **Note**: `preload_hint` is advisory only. Actual preload.lock is generated at deployment time (RFC-0035).

### 3.4 Deployment Lifecycle

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────────────────────┐
│ velo bundle │────▶│  .vbundle   │────▶│ velo deploy (or velo run)       │
│   build     │     │   (ship)    │     │                                 │
└─────────────┘     └─────────────┘     │  1. Verify signature            │
      │                                 │  2. Extract to isolated dir     │
      ▼                                 │  3. Generate preload.lock (0035)│
  Static packaging                      │  4. Start Zygote + pre-warm     │
  (no runtime state)                    └─────────────────────────────────┘
```

---

## 4. CLI Interface

```bash
# Build a bundle from pyproject.toml
velo bundle build --preload "torch,transformers" --output app.vbundle

# Build with model assets (Memory Gravity)
velo bundle build --include model.safetensors --output app.vbundle

# Run from bundle
velo bundle run app.vbundle

# Deploy to serverless (future)
velo bundle deploy app.vbundle --target aws-lambda
```

---

## 5. Security Model

### 5.1 Tiered Signing Strategy

> **Industry Context**: Most package ecosystems (npm, PyPI) don't enforce signing. Sigstore is the emerging standard for keyless signing.

| Phase | Strategy | Mechanism |
|:---|:---|:---|
| **v1.0** | Trust source | No signing; trust local build or known registry |
| **v1.x** | Optional signing | Ed25519, manual key management, `--sign` flag |
| **Future** | Sigstore integration | OIDC keyless signing, Rekor transparency log |

### 5.2 v1.0 Behavior (No Mandatory Signing)

```bash
# Build (no signing by default)
velo bundle build --output app.vbundle

# Run (no verification by default)
velo bundle run app.vbundle

# Optional: Build with signing
velo bundle build --sign --key ~/.velo/signing.key --output app.vbundle

# Optional: Verify before run
velo bundle run --verify --trust ~/.velo/trusted-keys/ app.vbundle
```

### 5.3 Future: Sigstore Integration

```bash
# Keyless signing via GitHub OIDC
velo bundle build --sign-sigstore --output app.vbundle

# Verify with transparency log
velo bundle verify app.vbundle --sigstore
# Checks: signature + Rekor log entry + certificate identity
```

### 5.4 Extraction Safety

```rust
// Extract to isolated, user-owned directory
fn extract_bundle(bundle: &Path) -> Result<PathBuf> {
    let extract_dir = dirs::data_local_dir()
        .join("velo")
        .join("bundles")
        .join(bundle_hash);
    
    // Never extract to /tmp or world-writable locations
    ensure!(!extract_dir.starts_with("/tmp"));
    
    Ok(extract_dir)
}
```

---

## 6. Integration with Existing Features

| Feature | Integration |
|:---|:---|
| **Memory Gravity (RFC-0015)** | Bundle includes `.safetensors` as SHM-ready assets |
| **vtest (RFC-0028)** | Test with pre-bundled fixtures for consistent environment |
| **Kinetic (RFC-0013)** | Bundle includes pre-warmed Zygote socket binding |

---

## 7. Competitive Analysis

| Tool | Cold Start | Distribution | Velo Advantage |
|:---|:---|:---|:---|
| **Docker** | ~2s (layer extract) | Container registry | No container runtime needed |
| **Lambda Layers** | ~1s | AWS-specific | Platform agnostic |
| **PyInstaller** | ~500ms | Single binary | + COW fork + SHM sharing |
| **Velo Bundle** | **< 50ms** | `.vbundle` file | Full Zygote ecosystem |

---

## 8. Implementation Phases

### Phase 1: Core Bundle Format
- [ ] Define `.vbundle` file format specification
- [ ] Implement `velo bundle build` command
- [ ] Implement `velo bundle run` command

### Phase 2: Asset Integration
- [ ] Support `--include` for static assets
- [ ] Memory Gravity asset embedding (`.safetensors`)

### Phase 3: Distribution
- [ ] Bundle signing and verification
- [ ] Registry protocol (future: `velo bundle push/pull`)

---

## 9. Quality Gates

| Gate | Requirement |
|:---|:---|
| **Gate A** | Bundle runs on clean machine with only Velo installed |
| **Gate B** | Cold start from bundle < 100ms |
| **Gate C** | Memory Gravity assets load via SHM, not file I/O |
| **Gate D** | Bundle signature verification before execution |

---

## 10. Open Questions

1. **Multi-Python Support**: How to handle multiple Python versions in same bundle?
2. **Update Strategy**: How to patch a deployed bundle without full rebuild?
3. **Size Optimization**: How to minimize bundle size while preserving all dependencies?

---

## 11. Grand Council Review (2026-01-19)

**Verdict**: 🟢 **APPROVED**

### Addressed Issues

| Issue | Resolution |
|:---|:---|
| Scope separation | ✅ INV-BUNDLE-001/002: Static only, runtime in RFC-0035 |
| Signing strategy | ✅ Tiered: v1.0 opt-in → Future Sigstore |
| Extraction safety | ✅ Isolated user directory, no /tmp |
| Platform tagging | ✅ manifest.build_platform |

### P2 Future Considerations

| Item | Description |
|:---|:---|
| Lock file | Include uv.lock for audit purposes |
| XDG support | Honor XDG_DATA_HOME on Linux |
| Large bundle | Consider streaming/incremental extract for >2GB bundles |

---

**Custodian**: Velo Architect
**Last Updated**: 2026-01-19

