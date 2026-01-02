# Phase 3.5 Tiered Testing Guide

> Efficient QA testing with fail-fast strategy

---

## Overview

Tests are organized into 4 tiers for efficiency:

| Tier | Name | Time | Tests | Purpose |
|------|------|------|-------|---------|
| 0 | Smoke | ~3s | 5 | Binary exists, CLI works |
| 1 | Fast | ~15s | 40 | Security, error handling |
| 2 | Standard | ~7min | 110 | Full test suite (no brutal) |
| 3 | Heavy | ~5min | 22 | Brutal/chaos stress tests |

---

## Usage

```bash
# Quick smoke test (run first!)
./scripts/qa-fast.sh 0

# Fast security/error tests
./scripts/qa-fast.sh 1

# Full standard suite
./scripts/qa-fast.sh 2

# Heavy brutal tests (run last, optional)
./scripts/qa-fast.sh 3
```

---

## Fail-Fast Strategy

```
Tier 0 (3s)     Tier 1 (15s)     Tier 2 (7min)     Tier 3 (5min)
    │               │                 │                 │
    ▼               ▼                 ▼                 ▼
┌───────┐       ┌───────┐         ┌───────┐         ┌───────┐
│ Smoke │──OK──▶│ Fast  │───OK───▶│ Full  │───OK───▶│ Heavy │
└───────┘       └───────┘         └───────┘         └───────┘
    │               │                 │                 │
  FAIL            FAIL              FAIL              FAIL
    │               │                 │                 │
    ▼               ▼                 ▼                 ▼
  STOP            STOP              STOP            (optional)
```

**Rule**: Never run higher tiers if lower tiers fail.

---

## Tier Details

### Tier 0: Smoke Tests (3s)
- Binary exists and is executable
- `--help` works
- `serve` command recognized
- Dependency check shows correct message

**When to run**: Always. Before any other tests.

### Tier 1: Fast Tests (15s)
- Security: Shell injection, path traversal, info leaks
- Error handling: Invalid module, missing app, syntax errors
- CLI promises: Help mentions port/workers
- Hardening: Edge cases in CLI parsing

**When to run**: After Tier 0, for quick verification.

### Tier 2: Standard Tests (7min)
- All Agent A/B/C/D tests
- Server startup tests (may skip if uvicorn not in customer venv)
- Signal handling
- Framework detection
- Comprehensive L0-L5 tests

**When to run**: For full verification before release.

### Tier 3: Heavy Tests (5min)
- Resource exhaustion (FD, memory, fork bombs)
- Chaos attacks (concurrent, race conditions)
- Injection stress tests
- Crash attempts (null bytes, unicode bombs)

**When to run**: Before release, in isolated environment.

---

## CI Integration

```yaml
# .github/workflows/qa.yml
jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - run: ./scripts/qa-fast.sh 0
  
  fast:
    needs: smoke
    runs-on: ubuntu-latest
    steps:
      - run: ./scripts/qa-fast.sh 1
  
  standard:
    needs: fast
    runs-on: ubuntu-latest
    steps:
      - run: ./scripts/qa-fast.sh 2
  
  heavy:
    needs: standard
    runs-on: ubuntu-latest
    # Only on main branch
    if: github.ref == 'refs/heads/main'
    steps:
      - run: ./scripts/qa-fast.sh 3
```

---

## Test Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Tier 0+1 | < 20s | 17s |
| Full suite | < 15min | ~12min |
| Pass rate | 100% | 100% (with skips) |
| Skip rate | < 30% | 22 tests (uvicorn dep) |
