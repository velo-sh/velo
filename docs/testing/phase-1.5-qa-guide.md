# Phase 1.5 QA Test Guide

Testing guide for RFC-0001 Environment Detection features.

---

## Quick Start

```bash
# One-click test (recommended)
./scripts/test-phase1.5.sh
```

---

## Manual Testing

### 1. Unit Tests
```bash
cargo test              # All 28 tests
cargo test python_info  # ABI detection
cargo test profile      # Profiling
cargo test hardware     # Hardware detection
cargo test cache        # Cache + integrity
```

### 2. Week 1: ABI Detection
```bash
# Check Python ABI info
./target/release/velo info

# Expected: Version + ABI tag displayed
```

**ABI Mismatch Test** (requires pyenv):
```bash
pyenv local 3.11 && velo run test.py  # Create cache
pyenv local 3.12 && velo run test.py  # Should warn: "⚠️ ABI Mismatch..."
```

### 3. Week 2: `--profile`
```bash
./target/release/velo run --profile bench.py

# Expected: Import timing table with slowest modules
```

### 4. Week 3: `velo info`
```bash
./target/release/velo info

# Expected:
# ▸ Hardware (CPU, Cores, Memory, Arch)
# ▸ Python Environment (Path, Version, ABI)
# ▸ Cache Status (Location, Fingerprint, Status)
```

### 5. Week 4: Environment Integrity
```bash
pip install some-package  # Outside uv
velo run test.py          # Should warn: "⚠️ Environment Drift..."
```

---

## Performance Gates (DoD)

| Metric | Requirement | Check Command |
|--------|-------------|---------------|
| Binary size | < 500KB | `ls -lh target/release/velo` |
| Cache load | < 1ms | `--profile` output |
| Cached run | ≤ CPython + 5% | `python bench.py` |

---

## Acceptance Checklist

- [ ] All 28 unit tests pass
- [ ] Clippy clean
- [ ] `velo info` displays all sections
- [ ] `--profile` shows timing breakdown
- [ ] Binary < 500KB
- [ ] No regressions in `velo run`
