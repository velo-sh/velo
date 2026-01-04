# Phase 1.5 Environment Detection - QA Test Matrix

> **Related RFC**: [RFC-0001](../rfcs/0001-phase-1.5-env-detection.md)  
> **Target Release**: v0.2.0

---

## 1. Test Environment Setup

### Prerequisites

```bash
# Install multiple Python versions (macOS example)
brew install python@3.11 python@3.12 python@3.13

# Or use pyenv
pyenv install 3.11.5 3.12.0 3.13.0

# Build Velo in release mode
cargo build --release
```

### Test Project Setup

```bash
# Create a test project
mkdir -p /tmp/velo-qa-test && cd /tmp/velo-qa-test
uv init
uv add numpy pandas fastapi
```

---

## 2. Functional Test Matrix

### 2.1 ABI Compatibility Tests

| ID | Scenario | Steps | Expected Result | Pass/Fail |
|----|----------|-------|-----------------|-----------|
| ABI-001 | First run cache creation | 1. Delete `.velo_cache/`<br>2. Run `velo run test.py` | Cache created, script runs | ☐ |
| ABI-002 | Cache hit on same Python | 1. Run `velo run test.py` again | Uses cache, no rebuild message | ☐ |
| ABI-003 | Python version switch | 1. Use py3.11, run<br>2. Switch to py3.12<br>3. Run again | Shows "ABI Mismatch", rebuilds cache | ☐ |
| ABI-004 | Minor version change | 1. Use py3.11.5<br>2. Switch to py3.11.6<br>3. Run | Should NOT rebuild (same ABI) | ☐ |

### 2.2 Environment Integrity Tests

| ID | Scenario | Steps | Expected Result | Pass/Fail |
|----|----------|-------|-----------------|-----------|
| ENV-001 | Clean uv environment | 1. `uv sync`<br>2. Run velo | No warnings | ☐ |
| ENV-002 | Pip pollution | 1. `pip install requests-oauthlib`<br>2. Run velo | Shows "Environment Drift" warning | ☐ |
| ENV-003 | uv.lock change | 1. Run velo<br>2. `uv add httpx`<br>3. Run velo | Cache invalidated, rebuilds | ☐ |

### 2.3 Startup Profiling Tests (`--profile`)

| ID | Scenario | Steps | Expected Result | Pass/Fail |
|----|----------|-------|-----------------|-----------|
| PRF-001 | Basic profiling | `velo run --profile test.py` | Displays timing breakdown table | ☐ |
| PRF-002 | Heavy imports | Profile script with numpy/pandas | Shows import times > 10ms | ☐ |
| PRF-003 | Suggestions | Profile heavy imports | Displays optimization suggestions | ☐ |

### 2.4 System Info Tests (`velo info`)

| ID | Scenario | Steps | Expected Result | Pass/Fail |
|----|----------|-------|-----------------|-----------|
| INF-001 | Basic info | `velo info` | Shows Python version, ABI, cache status | ☐ |
| INF-002 | No cache | Delete cache, run `velo info` | Shows "Cache: Not found" | ☐ |
| INF-003 | No venv | In non-venv directory, run `velo info` | Shows appropriate error/warning | ☐ |

---

## 3. Error Handling Tests

| ID | Scenario | Steps | Expected Result | Pass/Fail |
|----|----------|-------|-----------------|-----------|
| ERR-001 | Corrupted cache | 1. Write garbage to `.velo_cache/env.rkyv`<br>2. Run velo | Gracefully recovers, rebuilds cache | ☐ |
| ERR-002 | Missing Python | 1. Set `VELO_PYTHON=/nonexistent`<br>2. Run | Clear error message | ☐ |
| ERR-003 | No uv.lock | In dir without uv.lock, run | Works without fingerprinting | ☐ |
| ERR-004 | Permission denied | Make cache dir read-only, run | Warning, continues without cache | ☐ |

---

## 4. Platform Compatibility Matrix

### 4.1 Operating Systems

| OS | Version | Python | Status | Notes |
|----|---------|--------|--------|-------|
| macOS | 14.x (ARM) | 3.11, 3.12, 3.13 | ☐ | Primary dev platform |
| macOS | 14.x (Intel) | 3.11, 3.12 | ☐ | Rosetta compat |
| Ubuntu | 22.04 LTS | 3.11, 3.12 | ☐ | CI platform |
| Ubuntu | 24.04 LTS | 3.12, 3.13 | ☐ | Newer LTS |
| Windows | 11 | 3.11, 3.12 | ☐ | Path separator issues |

### 4.2 Python Installations

| Method | Tested | Notes |
|--------|--------|-------|
| System Python | ☐ | /usr/bin/python3 |
| Homebrew | ☐ | /opt/homebrew/bin/python3 |
| pyenv | ☐ | ~/.pyenv/shims/python |
| uv-managed | ☐ | .venv/bin/python |
| Conda | ☐ | May have conflicts |

---

## 5. Performance Benchmarks

| Metric | Baseline (CPython) | Target (Velo cached) | Actual | Pass/Fail |
|--------|-------------------|----------------------|--------|-----------|
| NumPy import | ~64ms | < 60ms | ☐ | ☐ |
| FastAPI startup | ~527ms | < 550ms | ☐ | ☐ |
| Django startup | ~415ms | < 420ms | ☐ | ☐ |
| Cache load time | N/A | < 1ms | ☐ | ☐ |

---

## 6. Test Execution

### 6.1 Manual Execution Checklist

```bash
# Before testing
cargo build --release
cd /tmp/velo-qa-test

# Run each test scenario
# Record results in this document
```

### 6.2 Quick Smoke Test

```bash
#!/bin/bash
# scripts/qa-smoke.sh

set -e

echo "=== Velo QA Smoke Test ==="

# Build
cargo build --release

# Create test project
TEST_DIR=$(mktemp -d)
cd "$TEST_DIR"
uv init
uv add numpy

# Test 1: Basic run
echo "Test 1: Basic run..."
echo 'import numpy; print("OK")' > test.py
./target/release/velo run test.py

# Test 2: Cache hit
echo "Test 2: Cache hit..."
./target/release/velo run test.py

# Test 3: velo info
echo "Test 3: velo info..."
./target/release/velo info

# Cleanup
rm -rf "$TEST_DIR"

echo "=== All smoke tests passed ==="
```

---

## 7. Defect Reporting

When reporting issues, include:

1. **Environment**
   - OS and version
   - Python version and installation method
   - Velo version (`velo --version`)

2. **Reproduction Steps**
   - Minimal script to reproduce
   - Exact commands run

3. **Actual vs Expected**
   - What happened
   - What should have happened

4. **Logs**
   - Full terminal output
   - Contents of `.velo_cache/` if relevant

---

## 8. Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| QA Lead | | | |
| Dev Lead | | | |
| Architect | | | |

---

**Document End**
