# Pytest Velo 🚀

*Hyper-fast, isolated testing powered by Zygote technology.*

---

**Pytest Velo** is a high-performance pytest plugin that leverages **Zygote COW (Copy-On-Write) forks** to accelerate your test suite. It turns the "bottleneck" of process-level isolation into a near-instant operation.

**Key Features**:
* ⚡ **Ultra Fast**: Reduces per-test startup overhead from ~200ms down to **~1ms**.
* 🛡️ **Industrial Isolation**: Every test gets its own fresh PID, `TMPDIR`, and environment variables.
* 🔌 **Drop-in Support**: Use your existing tests, markers, and fixtures without modification.
* 📦 **Preloading**: Pre-warm heavy modules (FastAPI, PyTorch, etc.) once in the Zygote to avoid redundant imports.

---

## ⚡ Quick Start

### 1. Installation

```bash
uv pip install pytest-velo
# or
pip install pytest-velo
```

### 2. Run with Turbo

Simply add the `--velo` flag to your usual pytest command:

```bash
pytest --velo
```

That's it. You've just saved minutes of wall-clock time.

---

## 🧐 Why?

In a standard test suite, if you have 1,000 tests and want process-level isolation (the safest way to test), you usually have two choices:
1. **The Slow Way**: Spawn 1,000 subprocesses. Total time: **~3-5 minutes**.
2. **The Risky Way**: Run everything in one process. Total time: **30 seconds**, but tests might pollute each other.

**Velo provides the third way**: Forking from a pre-warmed Zygote.
Total time: **~6 seconds** with **100% isolation**.

---

## 🔥 Advanced: Preloading

If your application has a heavy startup cost (e.g., loading a large AI model or a complex web framework), you can "bake" those modules into the Zygote.

```bash
pytest --velo --velo-preload="fastapi,torch,numpy"
```

The Zygote will import these once, and every subsequent test fork will inherit them via **Copy-on-Write** memory, making imports effectively free.

---

## 🛡️ Safety & Reliability

Pytest Velo is built with "Safety-First" principles (RFC-0028 P0 requirements):

* **Single-threaded Parent**: Velo ensures the parent process is single-threaded before forking to prevent GIL deadlocks.
* **FD Hygiene**: File descriptors are handled carefully to prevent corruption between workers.
* **Cleanup Control**: Automatic cleanup of worker directories (`/tmp/velo-worker-*`) after every test.

---

## 📊 Performance Benchmark

Actual measured results on a standard project:

| Metric | Standard Pytest | Pytest Velo | Improvement |
| :--- | :--- | :--- | :--- |
| **Startup Overhead** | ~210 ms | **< 2 ms** | **100x** 🚀 |
| **1000 Isolated Tests**| ~210 seconds | **~6 seconds** | **35x** |

---

## 🛠 Configuration

You can configure Velo via your `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "--velo --velo-preload=my_app"
```

Now every `pytest` run is a Velo run by default.

---

*“Velo is like having a warm engine that never needs to restart.”*
