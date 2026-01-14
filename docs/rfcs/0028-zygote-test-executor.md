# RFC-0028: pytest-velo Plugin (Zygote-Accelerated Testing)

**Status**: DRAFT
**Author**: Architect
**Date**: 2026-01-14 (Updated: 2026-01-15)
**Phase**: Phase 8.x

## Related Documents
- [RFC-0019: Native Sovereignty](./0019-native-sovereignty.md) (Zygote Architecture)
- [RFC-0018: Integrated Custody](./0018-integrated-custody.md) (Environment Management)

---

## 1. Summary

**pytest-velo** is a pytest plugin that accelerates test execution by using Zygote COW forks instead of standard process spawning. It is a **drop-in enhancement** that requires no changes to existing tests.

| Metric | Standard pytest | pytest-velo |
|:---|:---|:---|
| **Per-worker startup** | 500ms - 2s | **~1ms** |
| **1000 tests** | 30+ min | **~30 sec** |
| **Memory per worker** | Full copy | **COW delta** |

---

## 2. Design Philosophy

> **Don't replace pytest, accelerate it.**

Instead of reimplementing pytest's collection, fixtures, and reporting, we hook into pytest's existing plugin system to replace only the slow part: **process spawning**.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PYTEST-VELO ARCHITECTURE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  pytest tests/ --velo                                                        │
│       │                                                                      │
│       ├── pytest collection (unchanged)                                      │
│       ├── pytest fixtures (unchanged)                                        │
│       ├── pytest reporting (unchanged)                                       │
│       │                                                                      │
│       └── [VELO HOOK] Test execution                                         │
│                 │                                                            │
│                 └── Instead of: subprocess.Popen() or os.fork()              │
│                     Use: Zygote fork() with pre-warmed Python                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Hook Points

| pytest Hook | Velo Override |
|:---|:---|
| `pytest_runtest_protocol` | Fork from Zygote per test |
| `pytest_configure` | Start Zygote, preload modules |
| `pytest_unconfigure` | Shutdown Zygote |

### 3.2 Integration with pytest-xdist

```
┌─────────────────────────────────────────────────────────────────┐
│  pytest-xdist + pytest-velo                                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Standard xdist:                                                 │
│       master → spawn worker 1 (load Python + deps)               │
│             → spawn worker 2 (load Python + deps)                │
│             → spawn worker N (load Python + deps)                │
│                                                                  │
│  With pytest-velo:                                               │
│       master → Zygote (pre-warm Python + deps once)              │
│             → fork worker 1 (COW, ~1ms)                          │
│             → fork worker 2 (COW, ~1ms)                          │
│             → fork worker N (COW, ~1ms)                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Implementation

### 4.1 Plugin Entry Point

```python
# pytest_velo/plugin.py

import pytest
from velo_zygote.fork import ForkHandler

_zygote = None

def pytest_addoption(parser):
    parser.addoption("--velo", action="store_true", help="Use Velo Zygote for fast forking")
    parser.addoption("--velo-preload", default="", help="Modules to preload")

def pytest_configure(config):
    global _zygote
    if config.option.velo:
        from velo_zygote.main import ZygoteServer
        preload = config.option.velo_preload.split(",") if config.option.velo_preload else []
        _zygote = ZygoteServer(preload=preload)
        _zygote.start_background()

def pytest_unconfigure(config):
    global _zygote
    if _zygote:
        _zygote.shutdown()

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    if item.config.option.velo and _zygote:
        return run_in_zygote_fork(item, _zygote)
    return None  # fallback to default
```

### 4.2 Fork Execution

```python
def run_in_zygote_fork(item, zygote):
    """Execute a single test in a Zygote fork."""
    # 1. Fork from Zygote
    pid = zygote.fork()
    
    if pid == 0:
        # Child: run the test
        try:
            item.runtest()
            os._exit(0)
        except:
            os._exit(1)
    else:
        # Parent: wait for result
        _, status = os.waitpid(pid, 0)
        return status == 0
```

---

## 5. Interface

```bash
# Install
pip install pytest-velo

# Basic usage (drop-in)
pytest tests/ --velo

# With preloading
pytest tests/ --velo --velo-preload=torch,pandas

# Combined with xdist
pytest tests/ -n 8 --velo
```

### 5.1 Configuration (pytest.ini)

```ini
[pytest]
addopts = --velo --velo-preload=torch,pandas,myapp
```

---

## 6. Compatibility

| Feature | Supported |
|:---|:---|
| pytest fixtures | ✅ |
| pytest markers | ✅ |
| pytest-xdist | ✅ |
| pytest-cov | ⚠️ Requires coverage fork support |
| pytest-asyncio | ✅ |

---

## 7. Performance Targets

| Metric | Target |
|:---|:---|
| Fork latency | < 2ms |
| Compatibility | 100% pytest feature parity |
| Memory overhead | < 2MB per concurrent test |

---

## 8. Quality Gates

| Gate | Requirement |
|:---|:---|
| **Gate A** | All pytest features work unchanged |
| **Gate B** | pytest-xdist integration functional |
| **Gate C** | Fork latency < 2ms |
| **Gate D** | Standard pytest test suite passes with --velo |

---

## 9. Implementation Effort

| Component | Effort |
|:---|:---|
| Plugin skeleton | 0.5 day |
| Zygote integration | 0.5 day |
| xdist compatibility | 0.5 day |
| Testing & polish | 0.5 day |
| **Total** | **~2 days** |

---

## 10. Rust/Python Division of Labor

**Principle**: Python maintains pytest compatibility; Rust handles performance-critical operations.

### 10.1 Responsibility Matrix

| Layer | Python (pytest) | Rust (velo) |
|:---|:---|:---|
| **Test Discovery** | ✅ pytest --collect | - |
| **Fixtures** | ✅ pytest fixtures | - |
| **Assertions** | ✅ pytest/assert | - |
| **Reporting** | ✅ pytest hooks | - |
| **Fork/Spawn** | - | ✅ libc::fork() |
| **Worker Pool** | - | ✅ Tokio tasks |
| **IPC** | - | ✅ UDS + MessagePack |
| **Output Capture** | - | ✅ Async I/O |
| **Result Aggregation** | - | ✅ Lock-free queue |

### 10.2 Rust Coordinator

```rust
// src/test/coordinator.rs
pub struct TestCoordinator {
    zygote: ZygoteHandle,
    workers: Vec<WorkerHandle>,
    results: mpsc::Receiver<TestResult>,
}

impl TestCoordinator {
    pub fn spawn_workers(&mut self, n: usize) -> Result<()>;
    pub fn dispatch(&self, test_id: &str) -> Result<()>;
    pub fn aggregate(&self) -> TestReport;
}
```

### 10.3 Python Plugin (Thin Wrapper)

```python
# pytest_velo/plugin.py
import velo  # PyO3 bindings

@pytest.hookimpl
def pytest_runtest_protocol(item):
    # All heavy work delegated to Rust
    return velo.run_test(item.nodeid)
```

### 10.4 Performance Impact

| Operation | Python | Rust | Speedup |
|:---|:---|:---|:---|
| Fork | ~5ms | ~1ms | 5x |
| IPC | ~2ms | ~0.1ms | 20x |
| Aggregate (1000 tests) | ~100ms | ~5ms | 20x |

---

## 11. Framework Ecosystem Strategy

### 11.1 Python Test Framework Market

| Framework | Market Share | Use Case |
|:---|:---|:---|
| **pytest** | ~70% | Universal standard |
| **unittest** | ~20% | Standard library, enterprise |
| **hypothesis** | Growing | Property-based testing |
| **Django TestCase** | Niche | Django projects |
| **nose2/behave** | <5% | Legacy/BDD |

### 11.2 Support Priority

| Phase | Framework | Strategy |
|:---|:---|:---|
| **P0** | pytest | Native plugin |
| **P1** | unittest | Auto-compatible (pytest runs unittest) |
| **P2** | Django | Django TestCase optimization |
| **P3** | Others | Community contributions |

### 11.3 Coverage via pytest

pytest can natively run:
- ✅ pytest tests
- ✅ unittest.TestCase
- ✅ nose-style tests

**Result**: Supporting pytest covers ~90% of Python testing.

---

**Last Updated**: 2026-01-15
