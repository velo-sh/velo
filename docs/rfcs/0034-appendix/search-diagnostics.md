# RFC-0034 Appendix: Search Diagnostics

> Detailed output format for native library search path diagnostics.

## Diagnostic Principles

1. **Success**: Always show which path was used
2. **Failure**: Show all searched paths with skip reasons
3. **Verbose**: Show full search process for debugging

---

## Search Order

| Priority | Path | Source |
|:---|:---|:---|
| 1 | `$VELO_LIB_PATH` | Velo-specific env var |
| 2 | Manifest `native_search_paths` | Bundle author specified |
| 3 | Active Python venv/conda | `$VIRTUAL_ENV/lib`, `$CONDA_PREFIX/lib` |
| 4 | `$LD_LIBRARY_PATH` | User-specified |
| 5 | `/etc/ld.so.conf.d/*.conf` | System config |
| 6 | `/lib/x86_64-linux-gnu/`, `/usr/lib/x86_64-linux-gnu/` | Distro standard |
| 7 | `/usr/local/lib/`, `/opt/cuda/lib64/` | Common install paths |

---

## Output Formats

### Normal Mode (default)

Show what's being used:
```
[velo] ✓ libtorch.so → /opt/cuda/lib64/libtorch.so.2.1.0
[velo] ✓ libcudnn.so → /opt/cuda/lib64/libcudnn.so.8.6.0
```

### Verbose Mode (`-v` or `VELO_DEBUG=1`)

Show full search process:
```
[velo] Searching libtorch.so (>= 2.0.0)
   [1] $VELO_LIB_PATH: not set
   [2] manifest paths: none specified
   [3] $CONDA_PREFIX/lib: /home/user/miniconda3/lib
       → not found
   [4] $LD_LIBRARY_PATH: /opt/cuda/lib64:/usr/local/lib
       → /opt/cuda/lib64/libtorch.so.2.1.0
       → version from SONAME: 2.1.0 ✓
   
[velo] ✓ Using /opt/cuda/lib64/libtorch.so.2.1.0
```

### Failure Mode

Show all searched locations with skip reasons:
```
❌ libtorch.so not found (>= 2.0.0)

   Searched 7 locations:
   [1] $VELO_LIB_PATH: not set
   [2] manifest paths: none specified
   [3] $CONDA_PREFIX/lib: directory does not exist
   [4] $LD_LIBRARY_PATH: not set
   [5] /usr/lib/x86_64-linux-gnu/libtorch.so.1.9.0
       → version 1.9.0 < required 2.0.0 (SKIP)
   [6] /usr/local/lib: file not found
   [7] /opt/cuda/lib64: file not found
   
   Fix: Either:
     1. Install PyTorch >= 2.0.0
     2. Set $VELO_LIB_PATH to your PyTorch installation
     3. Rebuild bundle: velo bundle build --include-native
```

---

## Special Cases

### Non-Standard Path Warning

```
[velo] ✓ libtorch.so → /tmp/libs/libtorch.so
   ⚠️ WARNING: Loaded from non-standard path (outside /usr, /opt)
```

### Version Mismatch Detail

```
[velo] Checking libtorch.so
   /usr/lib/libtorch.so.1.9.0
     → version from SONAME: 1.9.0
     → required: >= 2.0.0
     → SKIP (version too old)
```

---

## Version Detection Methods

Velo attempts to detect .so version via:

1. **SONAME**: `libtorch.so.2.1.0` → version `2.1.0`
2. **Symbol lookup**: Call `torch::version()` if available
3. **Companion file**: Read `libtorch.version` if exists

---

## Manifest Extension

Authors can specify custom search paths:

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

---

## See Also

- [Error Messages](./error-messages.md) - Complete error catalog
- [RFC-0034 Main](../0034-preload-bundle-distribution.md) - Bundle architecture
