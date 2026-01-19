# RFC-0035: Native Library Preload Optimization (.so Pre-warming)

**Status**: DRAFT
**Author**: Velo Architect
**Date**: 2026-01-19
**Phase**: Phase 15 (Future)
**Scope**: Performance, Startup Optimization

> **Note**: This RFC focuses on **native library pre-loading**. For application packaging, see RFC-0034.

---

## 1. Executive Summary

This RFC proposes **Preload Optimization**, a mechanism to pre-load native shared libraries (`.so`/`.dylib`) before Python startup, reducing import latency for heavy native extensions.

| Metric | Standard Import | Preload Optimized |
|:---|:---|:---|
| PyTorch import | ~2-3s | **< 500ms** |
| NumPy import | ~200ms | **< 50ms** |
| Native extension load | dlopen on-demand | Pre-mapped in memory |

---

## 2. Motivation

### 2.1 The Native Extension Bottleneck
Heavy Python packages rely on native libraries:
- **PyTorch**: `libtorch.so`, `libcudnn.so` (~500MB+)
- **NumPy**: `libopenblas.so`, `libmkl.so`
- **TensorFlow**: `libtensorflow.so`

These libraries are loaded via `dlopen()` during Python import, causing:
1. **Disk I/O**: Reading large binaries from storage
2. **Symbol Resolution**: Dynamic linker overhead
3. **Memory Mapping**: Page fault storms on first access

### 2.2 The Velo Opportunity
Velo can pre-load these libraries before Python starts, so imports find them already memory-resident.

---

## 3. Architecture

### 3.1 Preload Strategy

```
┌─────────────────────────────────────────────────────────────┐
│                    Velo Preload Flow                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Startup                                                  │
│     └── Rust Host reads preload config                      │
│                                                              │
│  2. Pre-map Phase (before Python)                            │
│     ├── dlopen("libtorch.so", RTLD_NOW | RTLD_GLOBAL)       │
│     ├── dlopen("libopenblas.so", ...)                       │
│     └── Touch pages (prefault) to avoid later page faults   │
│                                                              │
│  3. Python Import                                            │
│     └── Libraries already in memory → near-instant import   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Configuration

```toml
# pyproject.toml
[tool.velo.preload]
libraries = [
    "libtorch.so",
    "libtorch_cpu.so",
    "libopenblas.so",
]
# Auto-detect from installed packages
auto_detect = true
```

### 3.3 CLI Interface

```bash
# Analyze and generate preload config
velo preload analyze

# Run with explicit preload
velo run --preload "libtorch.so,libopenblas.so" main.py

# Apply to serve
velo serve --preload-auto main:app
```

---

## 4. Technical Implementation

### 4.1 Rust Host Pre-loading

```rust
// src/preload/mod.rs
use libloading::Library;

pub fn preload_libraries(libs: &[String]) -> Result<Vec<Library>> {
    libs.iter()
        .map(|lib_path| {
            // RTLD_NOW: Resolve all symbols immediately
            // RTLD_GLOBAL: Make symbols available to subsequently loaded libs
            unsafe { Library::new(lib_path) }
        })
        .collect()
}
```

### 4.2 Page Prefaulting

```rust
// Touch all pages to avoid page faults during Python import
fn prefault_library(lib: &Library) {
    // madvise(MADV_WILLNEED) or manual read
}
```

### 4.3 Auto-Detection

```python
# velo preload analyze
# Scans site-packages for .so files and generates config
```

---

## 5. Integration with Existing Features

| Feature | Integration |
|:---|:---|
| **Zygote (RFC-0019)** | Preload happens before Zygote pre-warming |
| **Memory Gravity (RFC-0015)** | Preloaded libs shared via COW across workers |
| **Bundle (RFC-0034)** | Bundle can include preload config for deployment |

---

## 6. Implementation Phases

### Phase 1: Manual Preload
- [ ] Implement `--preload` CLI flag
- [ ] Support explicit library list

### Phase 2: Auto-Detection
- [ ] Scan site-packages for native extensions
- [ ] Generate recommended preload config

### Phase 3: Integration
- [ ] Integrate with Zygote pre-warming
- [ ] Add preload config to Bundle format

---

## 7. Quality Gates

| Gate | Requirement |
|:---|:---|
| **Gate A** | PyTorch import < 500ms with preload |
| **Gate B** | No symbol resolution errors (RTLD_GLOBAL correctness) |
| **Gate C** | Memory overhead < 5% vs on-demand loading |

---

## 8. Open Questions

1. **Symbol Conflicts**: How to handle libraries with conflicting symbols?
2. **Version Mismatch**: Pre-loaded .so vs Python package version sync?
3. **macOS/Windows**: dylib/dll handling differences?

---

## 9. Grand Council Review (2026-01-19)

**Verdict**: 🔶 **CONDITIONAL APPROVAL** (Linux-first)

### P0 Blocker (macOS)
- **dyld semantic mismatch**: macOS uses two-level namespace; RTLD_GLOBAL behaves differently
- **Resolution**: macOS support OUT OF SCOPE for v1.0; requires separate RFC

### P1 Issues (Must Fix)
| Issue | Recommendation |
|:---|:---|
| RTLD_GLOBAL symbol pollution | Default to RTLD_LOCAL; GLOBAL only via opt-in |
| Version mismatch | Add `velo preload verify` command |
| Extension module flag mismatch | Match flags that Python would use |

### Approval Conditions
1. Linux-first implementation
2. Default to RTLD_LOCAL
3. Ship `velo preload analyze` with version hash tracking

---

**Custodian**: Velo Architect
**Last Updated**: 2026-01-19

