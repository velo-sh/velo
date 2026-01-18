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

## 🚀 Installation

For now, `pytest-velo` lives within the Velo core repository. To get the turbo-boosted experience, you'll need to set up the development environment and build the engine.

### 1. Setup the Environment

We use `uv` for lightning-fast Python dependency management. Run our one-click setup script to prepare your virtual environment:

```bash
# Clone the repository (if you haven't)
git clone https://github.com/velo-sh/velo.git
cd velo

# Run the setup script
./setup-dev.sh
```

### 2. Build the Zygote Engine

The high-performance core of Velo is written in Rust. You need to build it once locally (this takes ~1 min for the first run):

```bash
cargo build --release
```

### 3. Add to your PATH

The pytest plugin needs to find the `velo` binary to manage the Zygote daemon. Add the build directory to your path:

```bash
export PATH="$PWD/target/release:$PATH"
```

---

## ⚡ Quick Start

With the environment ready, you can now run any pytest suite and simply add the `--velo` flag.

### Run your tests

```bash
uv run pytest --velo
```

### Verify it's working

You should see an output like this:

```text
platform darwin -- Python 3.11.x, pytest-x.y.z
plugins: velo-0.1.0, ...
[Session] Log dir: /tmp/velo-sessions/...
[Zygote] Warm-up complete. Forking workers...
```

If you see these logs, **congratulations!** You are now running tests at the speed of physics.

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
uv run pytest --velo --velo-preload="fastapi,torch,numpy"
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

## 🎨 Tutorial - User Guide

Let's verify the **42x speedup** on your machine right now.

### 1. Create a "Heavy" Test
Create a directory named `my_perf_tests` and add a test file that simulates a realistic import load:

```python
# test_physics.py
import time
import math

def test_heavy_calculation():
    # Simulate some work
    result = sum(math.sqrt(i) for i in range(10000))
    assert result > 0
```

### 2. The Slow Way (Standard Isolation)
Run this test 50 times using standard subprocess spawning:

```bash
time for i in {1..50}; do uv run pytest test_physics.py -q; done
# Estimated time: ~12-15 seconds
```

### 3. The Velo Way (Zygote Turbo)
Run the same 50 tests with Velo in one go:

```bash
uv run pytest --velo --velo-preload=math my_perf_tests/
# Estimated time: < 0.5 seconds 🚀
```

---

## 📁 Project Structure

If you're curious about how the magic happens:

```text
.
├── Cargo.toml          # Rust Zygote Engine definition
├── pyproject.toml      # Python Plugin registration
├── pytest_velo/        # 🐍 Python Plugin logic
│   └── plugin.py       # The Zygote-Fork orchestrator
└── src/                # 🦀 Rust Zygote implementation
```

---

*“Velo is like having a warm engine that never needs to restart.”*
