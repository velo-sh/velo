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

This RFC proposes **Velo Bundle**, a system for packaging Python applications with all dependencies and assets into a single distributable file (`.vpkg`). This is a **source distribution format**, not a runtime image.

| Aspect | Description |
|:---|:---|
| **Scope** | Source code + dependencies + assets |
| **Format** | Single `.vpkg` archive (tar.zst) |
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
│  .vpkg file                      │   preload.lock        │
│  ├── source code                    │   native lib dlopen   │
│  ├── site-packages/                 │   Zygote pre-warming  │
│  ├── assets (.safetensors)          │   fingerprint verify  │
│  └── manifest.json                  │   runtime checks      │
└─────────────────────────────────────┴───────────────────────┘
```

### 3.2 Bundle Format (`.vpkg`)

**File Format**: Uncompressed tar with index (mmap-friendly)

> **Design Principle**: `.vpkg` is directly runnable without extraction. Only `.so` files require caching.

#### 3.2.1 Two-Layer Distribution Model

```
Distribution:                              Runtime:
app.vpkg.zst ──decompress once──▶ app.vpkg ──▶ velo run app.vpkg
 (compressed)                    (mmap-ready)     (one-click)
```

| Layer | Format | Purpose |
|:---|:---|:---|
| **Distribution** | `.vpkg.zst` | Compressed for transfer (optional) |
| **Runtime** | `.vpkg` | Uncompressed, mmap-friendly, directly runnable |

#### 3.2.1.1 Compressed Format Handling

> **Behavior**: Velo auto-detects `.vpkg.zst` and extracts to cache before running.

| Input | Behavior |
|:---|:---|
| `velo run app.vpkg` | Direct mmap, no extraction |
| `velo run app.vpkg.zst` | Auto-extract to cache → run |
| `velo bundle extract app.vpkg.zst` | Explicit extract to user-specified path |

**Auto-Extraction Cache**:
```
~/.velo/bundles/{content-hash}/app.vpkg
```

**CLI Examples**:
```bash
# Compressed: auto-extract to cache
velo run app.vpkg.zst
# → Extracts to ~/.velo/bundles/abc123/app.vpkg
# → Subsequent runs use cached extraction

# Flat: direct run
velo run app.vpkg

# Explicit extract (user control)
velo bundle extract app.vpkg.zst -o ./app.vpkg

# Remote download (auto-cache)
velo run https://registry.example.com/app.vpkg.zst
# → Downloads + extracts to ~/.velo/bundles/{hash}/
```

**Cache Behavior**:
| Scenario | Action |
|:---|:---|
| First run | Extract → cache → run |
| Subsequent run | Use cached extraction |
| Bundle updated (new hash) | Extract new version |
| `velo cache clean` | Remove all cached extractions |

#### 3.2.1.2 Compression Design Decision

> **Council Decision (2026-01-19)**: Whole-file compression over internal file compression.

| Approach | Description | Chosen |
|:---|:---|:---|
| **Whole-file** | `vpkg (flat) → zstd → .vpkg.zst` | ✅ Yes |
| **Internal** | `[file1.zst, file2.zst, ...] → tar` | ❌ No |

**Rationale**:
| Factor | Whole-file | Internal |
|:---|:---|:---|
| Compression ratio | ✅ ~70% (cross-file dedup) | ~68% |
| Decompression speed | ✅ ~0.8s (stream) | ~1.2s (multi) |
| Standard tools | ✅ `zstd -d`, `tar` | ❌ Custom only |
| Implementation | ✅ ~50 lines | ~200 lines |
| Audit-friendly | ✅ Transparent | ❌ Opaque |
| Build disk space | ⚠️ 2x (flat + compressed) | ✅ 1x (stream) |

> **Trade-off**: Build requires ~2x disk space temporarily (flat vpkg + compressed vpkg.zst).
> For large bundles (>10GB), use streaming build: `velo bundle build --stream`

**Streaming Build (Future Optimization)**:

```
Standard (2-pass):
  files → tar → app.vpkg (disk) → zstd → app.vpkg.zst (disk)
  Disk: 2x bundle size

Streaming (1-pass):
  files → tar → zstd (pipe) → app.vpkg.zst (disk only)
  Disk: 1x bundle size
```

| Mode | CLI | Output | Disk Space |
|:---|:---|:---|:---|
| Standard | `velo bundle build` | .vpkg | 1x |
| Compressed | `velo bundle build --compress` | .vpkg + .vpkg.zst | 2x |
| Stream | `velo bundle build --stream` | .vpkg.zst only | 1x |

> **Note**: Streaming mode only outputs `.vpkg.zst`. Flat `.vpkg` is generated on target via extraction.

#### 3.2.2 vpkg Internal Structure

```
app.vpkg (uncompressed tar with offset index)
├── __velo_manifest__.json    # Metadata + file offset table
├── src/                      # Application source code
├── site-packages/            # Pre-installed dependencies
│   ├── torch/__init__.py     # ← mmap direct read
│   └── torch/lib/            # ← .so cached to ~/.velo/so-cache/
├── assets/                   # Static assets
│   ├── model.safetensors
│   └── config.json
└── pyproject.toml
```

#### 3.2.3 Runtime File Access Strategy

| File Type | Access Method | Cache? |
|:---|:---|:---|
| `.py` | mmap from vpkg | ❌ No |
| `.pyc` | mmap from vpkg | ❌ No |
| `.json/.toml` | mmap from vpkg | ❌ No |
| `.safetensors` | mmap from vpkg (SHM) | ❌ No |
| **`.so/.pyd`** | Extract to cache, dlopen | ✅ Yes |

#### 3.2.4 .so Caching Strategy (Content-Addressable)

> **Design**: .so files cached with blake3 hash in filename for deduplication.

```
Manifest:
{
  "site-packages/torch/lib/libtorch.so": {
    "offset": 5120,
    "size": 524288000,
    "blake3": "a1b2c3d4e5f6..."
  }
}

Cache path (content-addressable):
~/.velo/so-cache/libtorch-a1b2c3d4e5f6.so

dlopen:
dlopen("~/.velo/so-cache/libtorch-a1b2c3d4e5f6.so")
```

**Benefits**:
| Aspect | Traditional | Content-Addressable |
|:---|:---|:---|
| Deduplication | ❌ Same .so stored per bundle | ✅ Shared across bundles |
| Cache size | Large | ✅ Minimal |
| Lookup | Directory scan | ✅ Direct path construction |
| Cleanup | Complex | ✅ Simple LRU |

**Why blake3?**
- 10x faster than SHA256
- Collision-resistant
- 16-char prefix sufficient for uniqueness

#### 3.2.5 UV Comparison: Cache Key Strategy

> **Reference**: UV (Astral) uses version-based keys; Velo uses content hash for stricter guarantees.

| Aspect | UV | Velo |
|:---|:---|:---|
| Cache key | `{name}-{version}-{platform}` | `{basename}-{blake3}` |
| Precision | ⚠️ Same version may differ | ✅ Exact content match |
| Reproducibility | May vary | ✅ 100% reproducible |
| Complexity | Low | Medium |

**Decision**: Content hash for Velo provides stronger reproducibility guarantees aligned with Zygote's security model.

#### 3.2.6 Hardlink Strategy (Learned from UV)

> UV uses hardlinks for deduplication. Velo adopts the same approach.

```
First extraction:
  vpkg → extract .so → save to cache → hardlink count = 1

Second vpkg (same .so):
  check cache exists (blake3 match) → skip extraction → hardlink count = 2

dlopen:
  dlopen("~/.velo/so-cache/libtorch-{hash}.so")  // shared file
```

**Link Modes** (configurable via `VELO_LINK_MODE`):
| Mode | Behavior | Use Case |
|:---|:---|:---|
| `hardlink` (default) | Create hardlink to cache | Same filesystem |
| `copy` | Copy file | Cross-filesystem |
| `reflink` | CoW clone (btrfs/APFS) | Best performance |

#### 3.2.7 .so Handling Matrix

> **Problem**: .so compatibility depends on bundle inclusion and system availability.

**Scenario Matrix**:

| Bundle .so | System .so | Platform Match | Action |
|:---|:---|:---|:---|
| ❌ None | ✅ Exists | ✅ Match | Use system .so |
| ❌ None | ✅ Exists | ❌ Mismatch | Error: version mismatch |
| ❌ None | ❌ None | - | Error: missing dependency |
| ✅ Included | ❌ None | ✅ Match | Use bundle .so |
| ✅ Included | ❌ None | ❌ Mismatch | Error: platform incompatible |
| ✅ Included | ✅ Exists | ✅ Match | Priority: bundle (default) or system |
| ✅ Included | ✅ Exists | ❌ Mismatch | Fallback to system .so |

**Resolution Flow**:

```
                    ┌─────────────────────┐
                    │ Bundle includes .so? │
                    └──────────┬──────────┘
               yes ┌───────────┴───────────┐ no
                   ▼                       ▼
          ┌────────────────┐    ┌────────────────────┐
          │ Platform match?│    │ System .so exists? │
          └───────┬────────┘    └─────────┬──────────┘
       yes ┌──────┴──────┐ no        yes  │  no
           ▼             ▼                ▼    ▼
    ┌─────────────┐  ┌──────────────┐  ┌──────┐ ┌───────┐
    │ Use bundle  │  │ Fallback sys │  │ Use  │ │ Error │
    └─────────────┘  └──────┬───────┘  │ sys  │ └───────┘
                      exists│ none     └──────┘
                           ▼    ▼
                     ┌──────┐ ┌───────────────────┐
                     │ Use  │ │ Error: incompatible│
                     └──────┘ └───────────────────┘
```

**Configuration Options**:

| Option | Default | Values | Description |
|:---|:---|:---|:---|
| `VELO_SO_PRIORITY` | `bundle` | bundle / system / skip-if-exists | Which .so to use when both exist |
| `VELO_SO_FALLBACK` | **`false`** | true / false | Fallback to system on platform mismatch |
| `VELO_SO_STRICT` | `false` | true / false | Fail if platform doesn't match exactly |

> [!IMPORTANT]
> **Council Decision (2026-01-19)**: `VELO_SO_FALLBACK` defaults to `false` for security.
> - Fallback bypasses bundle signature verification
> - When fallback is used, a **warning is logged**
> - Use `--allow-fallback` CLI flag to explicitly enable

**CLI Interface**:
```bash
# Default: bundle only, fail on platform mismatch
velo run app.vpkg

# Explicit fallback permission
velo run --allow-fallback app.vpkg
```

**Priority Modes**:
- `bundle`: Always use bundled .so (isolation, reproducibility) ✅ **Recommended**
- `system`: Prefer system .so (smaller cache, faster startup)
- `skip-if-exists`: Skip extraction if system has compatible version


**Manifest Extension**:

```json
{
  "native_search_paths": [
    "$CONDA_PREFIX/lib",
    "/opt/cuda/lib64",
    "/usr/local/lib"
  ],
  "native_requirements": {
    "libtorch.so": { "min_version": "2.0.0", "symbols": ["_ZN5torch..."] },
    "libcudnn.so": { "optional": true, "min_version": "8.0.0" }
  }
}
```

**Version Detection**:
```bash
# Velo attempts to detect version via:
1. SONAME: libtorch.so.2.1.0
2. Symbol lookup: torch::version()
3. Companion file: libtorch.version
```

**Search Diagnostic Output**:

> For detailed output formats, see [Appendix: Search Diagnostics](./0034-appendix/search-diagnostics.md)

| Mode | Output |
|:---|:---|
| Normal | `✓ libtorch.so → /opt/cuda/lib64/libtorch.so.2.1.0` |
| Verbose (`-v`) | Full search process with all paths checked |
| Failure | All searched locations + skip reasons + fix suggestions |

#### 3.2.8 Startup Logging (Debug Support)

> **Principle**: Log key information at startup to facilitate debugging.

**Standard Output (always)**:
```
[velo] Loading app.vpkg (v0.1.0, linux-x86_64)
[velo] .so cache: ~/.velo/so-cache/
[velo] .so priority: bundle
```

**Verbose Mode (`VELO_DEBUG=1` or `-v`)**:
```
[velo] Manifest: 127 files, 3 native libs
[velo] libtorch-a1b2c3d4.so: cached ✓
[velo] libcudnn-e5f6g7h8.so: extracting...
[velo] Platform: linux-x86_64-glibc2.31
[velo] mmap vpkg: 2.1GB → 0.3ms
[velo] Zygote pre-warm: torch, transformers
```

**Error Output (semantic, actionable)**:

> **Principle**: Error messages tell user **what happened**, **why**, and **what to do next**.
> For complete error catalog, see [Appendix: Error Messages](./0034-appendix/error-messages.md)

| Category | Example Error |
|:---|:---|
| Platform | `❌ Cannot load libtorch.so` (glibc mismatch, missing deps) |
| Cache | `❌ Cache write failed` (disk full, permission denied) |
| Security | `❌ Bundle signature verification failed` |
| Resource | `❌ Failed to mmap vpkg` (insufficient memory) |

#### 3.2.9 Cache Management CLI

> For complete CLI reference, see [Appendix: CLI Examples](./0034-appendix/cli-examples.md)

| Command | Description |
|:---|:---|
| `velo cache info` | Show cache status |
| `velo cache clean` | Clean all cache |
| `velo cache prune --max-age 30d` | Remove old entries |
| `velo bundle warm app.vpkg` | Pre-warm cache |

#### 3.2.10 Concurrency Safety

> When multiple processes extract the same .so simultaneously, use file locking.

```rust
let lock = FileLock::exclusive(&cache_path.with_extension("lock"))?;
if !cache_path.exists() {
    extract_so(vpkg, &cache_path)?;
}
drop(lock);
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
    "src/main.py": { "offset": 4096, "size": 1024, "sha256": "abc123..." },
    "site-packages/torch/lib/libtorch.so": { "offset": 5120, "size": 524288000, "sha256": "def456...", "type": "native" }
  },
  "signature": "ed25519:..."
}
```

> **Key fields**:
> - `offset`: Byte offset in vpkg for mmap access
> - `type: "native"`: Marks .so files that require cache extraction

### 3.4 Deployment Lifecycle

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────────────────────┐
│ velo bundle │────▶│  .vpkg      │────▶│ velo run app.vpkg               │
│   build     │     │ (ship/run)  │     │                                 │
└─────────────┘     └─────────────┘     │  1. Verify signature (optional) │
      │                                 │  2. mmap vpkg file              │
      ▼                                 │  3. Extract .so to cache        │
  Preload-ordered                       │  4. Start Zygote + pre-warm     │
  uncompressed tar                      └─────────────────────────────────┘
  (no runtime state)                    └─────────────────────────────────┘
```

---

## 4. CLI Interface

> For complete CLI reference, see [Appendix: CLI Examples](./0034-appendix/cli-examples.md)

| Command | Description |
|:---|:---|
| `velo bundle build` | Build bundle from project |
| `velo bundle run` | Run bundle directly |
| `velo bundle deploy` | Deploy to serverless (future) |

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
velo bundle build --output app.vpkg

# Run (no verification by default)
velo bundle run app.vpkg

# Optional: Build with signing
velo bundle build --sign --key ~/.velo/signing.key --output app.vpkg

# Optional: Verify before run
velo bundle run --verify --trust ~/.velo/trusted-keys/ app.vpkg
```

### 5.3 Future: Sigstore Integration

```bash
# Keyless signing via GitHub OIDC
velo bundle build --sign-sigstore --output app.vpkg

# Verify with transparency log
velo bundle verify app.vpkg --sigstore
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
| **Velo Bundle** | **< 50ms** | `.vpkg` file | Full Zygote ecosystem |

---

## 8. Performance Optimizations

### 8.1 Preload-Friendly File Layout (P1)

> **Priority**: P1 (Council Approved 2026-01-19)
> **Goal**: File physical order in bundle = import order → Maximize page cache hits

#### 8.1.1 Performance Impact

| Scenario | Random Layout | Preload Layout | Improvement |
|:---|:---|:---|:---|
| PyTorch bundle (500MB .so) | ~3.2s | ~1.8s | **45%** |
| HDD sequential vs random | 5 MB/s | 150 MB/s | **30x** |
| NVMe sequential vs random | 300 MB/s | 3500 MB/s | **12x** |

> **Council Verdict**: Low cost (~1 day), high benefit (45% latency reduction)

#### 8.1.2 Physical Layout

```
app.vpkg physical layout:
├── [HOT ZONE] ────────────────────────
│   ├── torch/lib/libtorch.so          # First import
│   ├── torch/lib/libtorch_cpu.so      # Sequential read
│   ├── torch/__init__.py
│   ├── numpy/core/multiarray.so
├── [WARM ZONE] ────────────────────────
│   ├── app/main.py
│   ├── app/config.json
├── [COLD ZONE] ────────────────────────
│   └── tests/, docs/, etc.
```

#### 8.1.3 Implementation

```rust
// Build-time: sort files by preload_hint
let files = collect_files(project_dir);
let sorted = sort_by_preload_order(files, preload_hint);
create_tar_zst(sorted)?;

// Runtime: mmap + sequential hint
let mmap = unsafe { MmapOptions::new().map(&file)? };
madvise(mmap.as_ptr(), mmap.len(), MADV_SEQUENTIAL);
```

#### 8.1.4 Manifest Field

```json
{
  "layout": "preload_optimized",
  "preload_order": ["torch", "numpy", "transformers", "app"]
}
```

#### 8.1.5 Known Pitfalls (Council Review 2026-01-19)

| # | Issue | Severity | Mitigation |
|:---|:---|:---|:---|
| 1 | tar is stream format, not random-access | Medium | Extract-first or consider squashfs |
| 2 | zstd streaming prevents seeking | Medium | Accept sequential-only optimization |
| 3 | User import order unpredictable | Low | Hot zone for top N packages |
| 4 | Network FS breaks prefetch (NFS/EBS) | Low | Document as local-SSD optimized |
| 5 | Docker overlay2 adds indirection | Low | Best-effort optimization |

#### 8.1.6 Why Compression Still Benefits from Layout

> **Key Insight**: Compression preserves logical file order. Decompression restores the original layout.

```
Build-time:
[File A] [File B] [File C] ...  (preload order)
    ↓ zstd compress
[zstd frame 1] [zstd frame 2] [zstd frame 3]

Runtime:
[zstd frame 1] [zstd frame 2] [zstd frame 3]
    ↓ decompress (sequential I/O)
[File A] [File B] [File C] ...  ← Original order restored!
```

**Benefits at Each Layer**:
| Layer | Benefit |
|:---|:---|
| Disk I/O | Sequential read → kernel readahead effective |
| CPU | Decompression has good cache locality |
| Post-extract | Files laid out in preload order → mmap prefetch works |

**No Degradation Guarantee**: Even in Docker/NFS scenarios, preload ordering doesn't make things worse—just less effective.

#### 8.1.7 Format Alternatives (Future Consideration)

| Format | Random Access | Security | Cross-Platform |
|:---|:---|:---|:---|
| **tar.zst** (current) | ❌ Stream-only | ✅ Audited | ✅ Yes |
| **squashfs** | ✅ Block-level | ✅ Kernel-audited | ❌ Linux-only |
| **zip (stored)** | ✅ O(1) seek | ✅ Audited | ✅ Yes |
| **Private + Zstd** (v2.0) | ✅ Seekable blocks | ⚠️ Needs audit | ✅ Yes |

#### 8.1.8 Private Format + Zstd: Loading Speed Advantages (v2.0 Candidate)

> **When to invest**: If loading speed is the top priority, private format provides significant advantages.

**1. Seekable Zstd (Block Compression + Index Table)**

```
Standard tar.zst:
[====== single zstd stream ======]
   ↓ load libtorch.so (in middle)
   Must decompress from start ❌ slow

Private format + Seekable Zstd:
[block1][block2][block3]...[index table]
   ↓ load libtorch.so
   Query index → seek to block N → decompress only that block ✅ fast
```

**2. File-Level Parallel Decompression**

```
Standard: [decompress file1] → [file2] → [file3]  (serial)
Private:  [decompress file1]
          [decompress file2]   (parallel, multi-core)
          [decompress file3]
```
Speed improvement: **2-4x** on multi-core CPUs

**3. Prefetch Hints in Index**

```json
{
  "libtorch.so": { "offset": 1024, "size": "500MB", "prefetch_priority": 0 },
  "numpy.so": { "offset": "502MB", "size": "20MB", "prefetch_priority": 1 }
}
```
Result: Hottest files available first, **reduce time-to-first-import**

**4. Memory-Mapped Decompression (Zero-Copy Path)**

```
Standard: decompress → write to disk → mmap disk file
Private:  mmap compressed block → decompress to memory directly

Benefit: Skip disk write roundtrip
```

**Performance Estimate**:

| Scenario | Standard tar.zst | Private Format |
|:---|:---|:---|
| Load 500MB .so from middle | ~3s | ~0.5s (direct seek) |
| Decompress 1GB bundle (4-core) | ~2s | ~0.7s |
| Time to first import | After full extract | After hot zone extract |

> **Decision**: Keep tar.zst for v1.0 (simplicity, compatibility).
> Private format is a v2.0 candidate when loading speed becomes blocking.

### 8.2 Optional Native Library Bundling

> **Goal**: Drop-in, one-click deployment for homogeneous environments

| Mode | Description | Use Case |
|:---|:---|:---|
| **portable** (default) | Python only, .so installed on target | Cross-platform distribution |
| **self-contained** | Python + .so bundled | Same-platform one-click deploy |

**CLI Interface**:
```bash
# Default: portable (no native libs)
velo bundle build --output app.vpkg

# Self-contained: include native libraries
velo bundle build --include-native --output app.vpkg

# Cross-platform build (future)
velo bundle build --include-native --platform linux-x86_64 --output app.vpkg
```

**Manifest Extension**:
```json
{
  "native_mode": "self-contained",
  "native_libs": [
    {
      "path": "lib/libtorch.so",
      "platform": "linux-x86_64-glibc2.31",
      "sha256": "abc123..."
    }
  ]
}
```

> **Note**: Self-contained mode requires platform match at runtime (via RFC-0035 fingerprint check).

---

## 9. Implementation Phases

### Phase 1: Core Bundle Format
- [ ] Define `.vpkg` file format specification
- [ ] Implement `velo bundle build` command
- [ ] Implement `velo bundle run` command

### Phase 2: Asset & Native Integration
- [ ] Support `--include` for static assets
- [ ] Memory Gravity asset embedding (`.safetensors`)
- [ ] `--include-native` for self-contained mode
- [ ] Preload-friendly file ordering

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

