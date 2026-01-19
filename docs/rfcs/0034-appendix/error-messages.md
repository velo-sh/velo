# RFC-0034 Appendix: Error Messages

> Complete catalog of Velo Bundle error messages with semantic, actionable format.

## Error Message Format

All errors follow the pattern:
```
❌ [WHAT HAPPENED]

   Reason: [WHY IT HAPPENED]
   
   Fix: [WHAT TO DO NEXT]
```

---

## Platform & Compatibility Errors

### glibc Version Mismatch
```
❌ Cannot load libtorch.so

   Reason: Your system glibc (2.17) is older than required (2.31)
   
   Fix: Either:
     1. velo run --allow-fallback app.vpkg  (use system libtorch if available)
     2. Rebuild bundle for your platform: velo bundle build --platform linux-glibc2.17
```

### Missing Native Library
```
❌ Missing native library: libcudnn.so

   Reason: Bundle was built without --include-native
   
   Fix: Install CUDA toolkit, or rebuild:
     velo bundle build --include-native --output app.vpkg
```

### Missing Dependency Chain
```
❌ Cannot load libtorch.so

   Missing dependency: libcudart.so.12
   
   Reason: CUDA runtime not installed
   
   Fix: Install CUDA 12.x or use CPU-only bundle:
     velo bundle build --variant cpu --output app.vpkg
```

### Symbol Not Found
```
❌ Symbol not found in libtorch.so

   Missing: _ZN5torch4cuda11is_availableEv (torch::cuda::is_available)
   
   Reason: libtorch version mismatch (bundle: 2.1.0, linked: 2.0.0)
   
   Fix: Rebuild bundle with matching PyTorch version
```

---

## Cache & Storage Errors

### Disk Full
```
❌ Cache write failed

   Reason: Disk full at ~/.velo/so-cache/
   
   Fix: Free disk space or clean cache:
     velo cache clean
```

### Permission Denied
```
❌ Cannot create cache directory

   Reason: Permission denied at ~/.velo/so-cache/
   
   Fix: Check directory permissions or set custom cache path:
     export VELO_CACHE_DIR=/path/with/write/permission
```

### Cache Corruption
```
❌ Cache integrity check failed

   File: libtorch-a1b2c3d4.so
   Expected: a1b2c3d4e5f6...
   Actual:   x9y8z7w6v5u4...
   
   Reason: Cache file corrupted
   
   Fix: Clear cache and retry:
     velo cache clean && velo run app.vpkg
```

---

## Security Errors

### Signature Verification Failed
```
❌ Bundle signature verification failed

   Reason: Signature does not match manifest content
   
   This could mean:
     • Bundle was tampered with during transfer
     • Bundle was built with different signing key
   
   Fix: Re-download bundle from trusted source
     WARNING: Do not use --skip-verify unless you trust the source
```

---

## Resource Errors

### Insufficient Memory
```
❌ Failed to mmap vpkg

   Reason: Insufficient memory for 2.1GB bundle
   Available: 1.5GB
   
   Fix: Either:
     1. Close other applications to free memory
     2. Use streaming mode: velo run --stream app.vpkg
```

---

## See Also

- [Search Diagnostics](./search-diagnostics.md) - Native library search path output
- [RFC-0034 Main](../0034-preload-bundle-distribution.md) - Bundle architecture
