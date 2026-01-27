# Velo Compatibility Charter

> **"Compatibility is our lifeline."**

**Version**: 1.0  
**Author**: Velo Architect  
**Date**: 2026-01-27

---

## 1. Mission Statement

Velo is an **Instant Python Runtime** that accelerates Python execution without breaking compatibility. This charter defines the compatibility guarantees we make to our users.

---

## 2. Python Version Support

### 2.1 Supported Versions

| Version | Status | EOL Date |
|:---|:---|:---|
| Python 3.10 | ✅ Supported | Oct 2026 |
| Python 3.11 | ✅ Supported | Oct 2027 |
| Python 3.12 | ✅ Supported | Oct 2028 |
| Python 3.13 | 🔬 Testing | Oct 2029 |

### 2.2 Version Policy

- **Minimum Supported**: Python 3.10
- **Maximum Lag**: New Python minor versions supported within 90 days of CPython stable release
- **Deprecation**: 6 months notice before dropping a version

---

## 3. Zero Python Patch Principle

> **Velo SHALL NOT modify CPython source code.**

We wrap, we accelerate, we optimize—but we never patch Python itself.

### What This Means:
- ✅ COW fork for fast startup (external process model)
- ✅ Pre-loading modules before fork (CPython API compliant)
- ✅ MessagePack IPC (no interpreter modification)
- ❌ No custom bytecode
- ❌ No GIL modifications
- ❌ No PyObject layout assumptions

---

## 4. C-Extension Compatibility

### 4.1 Guarantee Level

| Category | Guarantee |
|:---|:---|
| **Pure Python** | 100% compatible |
| **Stable ABI Extensions** | 100% compatible |
| **Limited API Extensions** | 100% compatible |
| **Non-stable ABI (e.g. NumPy)** | Best-effort, tested in CI |

### 4.2 Tested Extensions Matrix

| Extension | Version | Status |
|:---|:---|:---|
| NumPy | 1.26+ | ✅ Verified |
| PyTorch | 2.0+ | ✅ Verified |
| Pandas | 2.0+ | ✅ Verified |
| uvloop | 0.19+ | ✅ Verified |
| orjson | 3.9+ | ✅ Verified |

---

## 5. Framework Compatibility

| Framework | Status | Notes |
|:---|:---|:---|
| FastAPI | ✅ Tier 1 | First-class support |
| Flask | ✅ Tier 1 | First-class support |
| Django | ✅ Tier 1 | First-class support |
| pytest | ✅ Tier 1 | First-class support |
| Celery | ✅ Tier 2 | Tested, community-supported |

---

## 6. Breaking Change Policy

### 6.1 Definition

A **breaking change** is any change that:
- Causes previously working code to fail
- Changes CLI behavior without deprecation
- Removes or modifies public API

### 6.2 Process

1. **Announce**: 2 release cycles (minimum 60 days) before breaking change
2. **Deprecate**: Add deprecation warnings in intermediate release
3. **Document**: Migration guide in release notes
4. **Execute**: Remove in next major version

### 6.3 Exceptions

Emergency security fixes may bypass this process with post-hoc documentation.

---

## 7. Performance Overhead Commitment

| Metric | Guarantee |
|:---|:---|
| Cold start overhead | < 50ms vs vanilla Python |
| Memory overhead | < 10% vs vanilla Python |
| CPU overhead (steady state) | < 2% vs vanilla Python |

**Violation Response**: If benchmarks show violation, freeze new features until resolved.

---

## 8. Compliance Verification

### 8.1 Continuous Integration

- **Compatibility Matrix**: Every PR runs against Python 3.10-3.13
- **Extension Tests**: NumPy, PyTorch, uvloop tested in CI
- **Performance Regression**: Benchmark suite with 10% threshold alerting

### 8.2 Reporting

Compatibility issues should be reported via GitHub Issues with label `compatibility`.

---

**Custodian**: Velo Architect  
**Review Cycle**: Quarterly
