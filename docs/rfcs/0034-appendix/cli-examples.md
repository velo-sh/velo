# RFC-0034 Appendix: CLI Examples

> Complete CLI reference for Velo Bundle commands.

## Quick Reference

| Command | Description |
|:---|:---|
| `velo bundle build` | Build a bundle from project |
| `velo bundle run` | Run a bundle directly |
| `velo bundle warm` | Pre-warm cache for cold start |
| `velo cache info` | Show cache status |
| `velo cache clean` | Clean all cache |
| `velo cache prune` | Remove old cache entries |

---

## Build Commands

### Basic Build
```bash
# Build from pyproject.toml
velo bundle build --output app.vpkg

# Build with preload hints
velo bundle build --preload "torch,transformers" --output app.vpkg

# Build with model assets (Memory Gravity)
velo bundle build --include model.safetensors --output app.vpkg
```

### Native Library Options
```bash
# Default: portable (no native libs)
velo bundle build --output app.vpkg

# Self-contained: include native libraries
velo bundle build --include-native --output app.vpkg

# Cross-platform build (future)
velo bundle build --include-native --platform linux-x86_64 --output app.vpkg

# CPU-only variant (no CUDA)
velo bundle build --variant cpu --output app.vpkg
```

### Platform-Specific Builds
```bash
# Rebuild for older glibc
velo bundle build --platform linux-glibc2.17 --output app.vpkg
```

---

## Run Commands

### Basic Run
```bash
# Run bundle directly
velo bundle run app.vpkg

# Run with verbose output
velo bundle run -v app.vpkg

# Run with debug logging
VELO_DEBUG=1 velo bundle run app.vpkg
```

### Fallback Options
```bash
# Default: bundle only, fail on platform mismatch
velo run app.vpkg

# Explicit fallback permission
velo run --allow-fallback app.vpkg

# Use streaming mode (low memory)
velo run --stream app.vpkg
```

---

## Cache Commands

```bash
# View cache status
velo cache info
# Output: 1.2GB used, 15 .so files, oldest: 30 days

# Clean all cache
velo cache clean

# Prune old entries
velo cache prune --max-age 30d

# Pre-warm cache (for cold start scenarios)
velo bundle warm app.vpkg
```

---

## Security Commands

### Signing (v1.x Optional)
```bash
# Build with signing
velo bundle build --sign --key ~/.velo/signing.key --output app.vpkg

# Verify before run
velo bundle run --verify --trust ~/.velo/trusted-keys/ app.vpkg
```

### Sigstore (Future)
```bash
# Keyless signing via GitHub OIDC
velo bundle build --sign-sigstore --output app.vpkg

# Verify with transparency log
velo bundle verify app.vpkg --sigstore
# Checks: signature + Rekor log entry + certificate identity
```

---

## Deployment Commands (Future)

```bash
# Deploy to serverless
velo bundle deploy app.vpkg --target aws-lambda

# Deploy with environment
velo bundle deploy app.vpkg --env production --target gcp-cloud-run
```

---

## Environment Variables

| Variable | Default | Description |
|:---|:---|:---|
| `VELO_CACHE_DIR` | `~/.velo/so-cache/` | Custom cache directory |
| `VELO_LIB_PATH` | (none) | Additional .so search path |
| `VELO_SO_PRIORITY` | `bundle` | bundle / system / skip-if-exists |
| `VELO_SO_FALLBACK` | `false` | Allow system .so fallback |
| `VELO_SO_STRICT` | `false` | Fail on exact platform mismatch |
| `VELO_LINK_MODE` | `hardlink` | hardlink / copy / reflink |
| `VELO_DEBUG` | (none) | Enable verbose logging |

---

## See Also

- [Error Messages](./error-messages.md) - Complete error catalog
- [Search Diagnostics](./search-diagnostics.md) - Native library search output
- [RFC-0034 Main](../0034-preload-bundle-distribution.md) - Bundle architecture
