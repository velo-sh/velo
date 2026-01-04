# Velo QA Standards

> Official QA standards and testing methodology for Velo

---

## Overview

This document defines the official QA methodology for Velo, including tiered testing, test categorization, and quality gates.

### Quick Reference

| Command | Description | Time |
|---------|-------------|------|
| `../../../scripts/qa-fast.sh 0` | Smoke tests | ~3s |
| `../../../scripts/qa-fast.sh 1` | Fast tests | ~15s |
| `../../../scripts/qa-fast.sh 2` | Standard | ~7min |
| `../../../scripts/qa-fast.sh 3` | Heavy/Brutal | ~5min |
| **Phase 6.0** | **L6 Optimizations** | **Uncompromising** |

---

## 1. Tiered Testing Strategy

### 1.1 Test Pyramid

```
          ┌─────────────────┐
          │   Tier 3: Heavy │  5min, 22 tests
          │   (Brutal/Chaos)│  Run: release only
          ├─────────────────┤
          │  Tier 2: Standard│  7min, ~110 tests
          │   (Full Suite)   │  Run: before merge
          ├─────────────────┤
          │  Tier 1: Fast    │  15s, 40 tests
          │ (Security/Error) │  Run: every commit
          ├─────────────────┤
          │  Tier 0: Smoke   │  3s, 5 tests
          │   (Binary/CLI)   │  Run: always
          └─────────────────┘
```

### 1.2 Tier Definitions

| Tier | Name | Time | What It Tests |
|------|------|------|---------------|
| **0** | Smoke | <5s | Binary exists, CLI help, basic commands |
| **1** | Fast | <30s | Security, error handling, CLI parsing |
| **2** | Standard | <10min | Server startup, HTTP, signals, integration |
| **3** | Heavy | ~5min | Resource exhaustion, chaos, stress tests |

### 1.3 Fail-Fast Rule

> **If Tier N fails, do NOT run Tier N+1.**

```
Tier 0 ──PASS──▶ Tier 1 ──PASS──▶ Tier 2 ──PASS──▶ Tier 3
   │                │                │                │
 FAIL             FAIL             FAIL             FAIL
   │                │                │                │
   ▼                ▼                ▼                ▼
 STOP            STOP             STOP            (optional)
```

---

## 2. Test Categories

### 2.1 Agent Classification

| Agent | Focus | Test Files |
|-------|-------|------------|
| **A** | Edge Cases | `test_phase*_agent_a_edge.py` |
| **B** | Stability | `test_phase*_agent_b_stability.py` |
| **C** | Security | `test_phase*_agent_c_security.py`, `test_bundle_config.py` |
| **D** | Destroyer | `test_phase*_agent_d_destroyer.py` |

### 2.2 Test ID Prefixes

| Prefix | Category | Priority |
|--------|----------|----------|
| `SMOKE-` | Smoke tests | BLOCKING |
| `FUNC-` | Functionality | BLOCKING |
| `SEC-` | Security | HIGH |
| `EDGE-` | Edge cases | MEDIUM |
| `CHAOS-` | Chaos/brutal | LOW |
| `PERF-` | Performance | MEDIUM |

### 2.3 Level Classification (L0-L5)

| Level | Description | When to Run |
|-------|-------------|-------------|
| L0 | Smoke - Does it start? | Always |
| L1 | Happy Path - Basic journey | Always |
| **L1-SEC** | **Security Invariants (P0-001 to P0-008)** | **Every Commit** |
| L5 | Integration - Zygote, frameworks | Before release |
| **L6** | **Static Graph (Phase 6.0)** | **Bilateral Audit** |
| **L6-AST** | **Hard vs Soft Dependency extraction** | **Build-Time Gate** |
| **L6-SCC** | **SCC Cyclic Handling (Tarjan's)** | **Correctness Gate** |
| **L6-STAT** | **Syscall Audit (0-stat Rule)** | **Performance Gate** |
| **L6-SEC** | **rkyv Security & Arch Binding** | **Security Gate** |

---

## 3. Final QA Verification (MANDATORY)

> ⚠️ **CRITICAL**: Before marking any Phase as "QA Passed", you MUST run the final verification script.

### 3.1 One-Click Final Script

每个 Phase 必须有一个最终验收脚本：

```bash
# Phase 4.0 Example
./scripts/qa_phase4_final.sh
```

### 3.2 Final Verification Checklist

| Step | Command | Required |
|------|---------|----------|
| 1 | `cargo build --release` | ✅ |
| 2 | Fix venv permissions | ✅ |
| 3 | Tier 0 (Smoke) | ✅ |
| 4 | Agent Tests (A/B/C) | ✅ |
| 5 | **Integration Tests** | ✅ |
| 6 | **Benchmark Tests** | ✅ |

### 3.3 Script Template

新 Phase 验收脚本必须包含：

```bash
#!/bin/bash
set -e

# 1. Build
cargo build --release

# 2. Fix permissions
chmod +x .venv/bin/python3

# 3. Tiered tests
uv run pytest -m tier0
uv run pytest tests/qa/test_phaseX*.py -v

# 4. Integration (MUST NOT SKIP)
uv run pytest tests/qa/test_phaseX_integration.py -v

# 5. Benchmarks (MUST NOT SKIP)
uv run python benchmark_projects.py --all
```

> **Rule**: 如果没有 Integration 和 Benchmark 测试通过，Phase 不能标记为 "QA Passed"。

---

## 4. CI Integration

### 4.1 Recommended Pipeline

```yaml
jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - run: ../../../scripts/qa-fast.sh 0
  
  fast:
    needs: smoke
    runs-on: ubuntu-latest
    steps:
      - run: ../../../scripts/qa-fast.sh 1
  
  standard:
    needs: fast
    runs-on: ubuntu-latest
    steps:
      - run: ../../../scripts/qa-fast.sh 2
  
  heavy:
    needs: standard
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - run: ../../../scripts/qa-fast.sh 3

  # MANDATORY: Benchmark as standalone job
  benchmark:
    needs: standard
    runs-on: ubuntu-latest
    steps:
      - run: uv run python benchmark_projects.py --all
```

### 4.2 PR Requirements

| Check | Required | Gate |
|-------|----------|------|
| Tier 0 (Smoke) | ✅ | Merge blocked |
| Tier 1 (Fast) | ✅ | Merge blocked |
| Tier 2 (Standard) | ✅ | Merge blocked |
| Tier 3 (Heavy) | ⚠️ | Main branch only |
| **Benchmark** | ✅ | Merge blocked |

---

## 4. Quality Gates

### 4.1 Definition of Done

Before marking a feature complete:

- [ ] Tier 0-2 tests pass (100%)
- [ ] No new BLOCKING defects
- [ ] Coverage meets phase target
- [ ] Documentation updated

### 4.2 Coverage Targets

| Phase | Target | Current |
|-------|--------|---------|
| Phase 1.5 | 60% | - |
| Phase 3 | 70% | - |
| Phase 3.5 | 70% | - |
| Phase 4+ | 80% | - |
| **Phase 6.0** | **85%** | - |

---

## 5. Defect Reporting

### 5.1 Severity Levels

| Severity | Description | Response |
|----------|-------------|----------|
| 🔴 CRITICAL | Core feature broken | Block release |
| 🟠 HIGH | Major functionality impacted | Fix before release |
| 🟡 MEDIUM | Non-critical issue | Schedule fix |
| 🟢 LOW | Minor/cosmetic | Backlog |

### 5.2 Defect ID Format

```
DEF-{phase}-{number}
Example: DEF-3.5-002
```

---

## 6. Test File Organization

```
tests/qa/
├── conftest.py                      # Shared fixtures
├── test_phase{X.Y}_{agent}_{focus}.py  # Agent tests
├── test_phase{X.Y}_comprehensive.py # L0-L5 hierarchy
├── test_phase{X.Y}_hardening.py     # Hardening tests
├── test_phase{X_Y}_leader_brutal.py # Tier 3 tests
└── test_phase{X.Y}_serve.py         # Feature tests
```

---

## 7. Test Environment Standards

### 7.1 The `isolated_env` Fixture

> **RULE**: Tests that run velo commands MUST use `isolated_env` fixture to ensure local/CI consistency.

```python
def test_uvicorn_missing_error(isolated_env):
    """Test behavior when uvicorn not installed."""
    env = isolated_env  # Clean venv, NO extra dependencies
    env.create_app("main.py", "app = None")
    
    result = env.run_velo("serve", "main:app")
    assert "Missing dependency" in result.stderr
```

### 7.2 Fixture API

| Method | Description |
|--------|-------------|
| `env.path` | Temporary directory path |
| `env.python` | Path to isolated Python |
| `env.velo` | Path to velo binary |
| `env.create_app(name, code)` | Create app file |
| `env.install(*packages)` | Install packages in isolated venv |
| `env.run_velo(*args)` | Run velo command |

### 7.3 Why Isolated Environment?

| Problem | Solution |
|---------|----------|
| Local has uvicorn, CI doesn't | `isolated_env` starts with NO dependencies |
| Tests pollute each other | Each test gets fresh venv |
| "Works on my machine" | Same behavior everywhere |

---

## 8. Running Tests

### 8.1 Quick Commands

```bash
# Smoke test (3s)
../../../scripts/qa-fast.sh 0

# Fast tests (15s)
../../../scripts/qa-fast.sh 1

# Full suite (7min)
../../../scripts/qa-fast.sh 2

# Brutal tests (5min, optional)
../../../scripts/qa-fast.sh 3
```

### 8.2 Specific Tests

```bash
# Run single test
uv run python -m pytest tests/qa/test_file.py::TestClass::test_name -v

# Run by marker
uv run python -m pytest -m "not slow" tests/qa/

# Run with coverage
uv run python -m pytest --cov=. tests/qa/
```

---

## 9. Related Documents

| Document | Purpose |
|----------|---------|
| **[QA-SOP.md](./QA-SOP.md)** | **Master QA Standard Operating Procedure (1200+ lines)** |
| [DEFINITION_OF_DONE.md](../../DEFINITION_OF_DONE.md) | Quality gate standards |
| [STANDARDS.md](../../STANDARDS.md) | Project naming conventions |
| [CHECKLIST-TEMPLATE.md](../TEMPLATES/CHECKLIST-TEMPLATE.md) | Manual checklist |
| [QA-REFLECTION-FIRST-PRINCIPLES.md](../ARCHIVE/QA-REFLECTION-FIRST-PRINCIPLES.md) | Testing lessons learned |

---

**Last Updated**: 2026-01-04

