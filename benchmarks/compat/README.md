# Velo Compatibility Suite

This directory contains compatibility test configurations and runners for 100+ popular Python packages. These tests are designed to verify Velo's compatibility and stability across various types of Python libraries (CLI, Web, Library).

## 📋 Requirements

- **Velo**: Ensure the `velo` executable is in your PATH or compiled in `target/release/velo`.
- **Python**: 3.11+
- **uv**: For fast environment setup (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

## 🚀 Quick Start

### 1. Initialize Test Environment

First, run the setup script to build the shared virtual environment (`.shared_venv`) and install base dependencies:

```bash
cd benchmarks/compat
python3 setup_shared_env.py
```

### 2. Run Tests

Use the `_runner/compat_runner.py` script to execute tests.

**Run a single package:**
```bash
# Example: Run tests for the 'flask' package
python3 _runner/compat_runner.py --package flask
```

**Run a specific category:**
```bash
# Run all web packages (e.g., flask, django, fastapi)
python3 _runner/compat_runner.py --category web
```

**Run all tests:**
```bash
python3 _runner/compat_runner.py --all
```

## 📂 Directory Structure

```text
benchmarks/compat/
├── cli/                # CLI tools (e.g., black, mypy)
├── library/            # General libraries (e.g., numpy, requests)
├── web/                # Web frameworks (e.g., flask, django)
├── _runner/            # Core test runner scripts
├── setup_shared_env.py # Environment setup script
├── COMPAT_REPORT.md    # Final compatibility report
└── ...
```

## 📊 Viewing Results

- **Single Run**: After a run completes, a summary is printed to the console, and temporary reports (`compat_results_<name>.json` and `COMPAT_REPORT_<name>.md`) are generated (ignored by `.gitignore`).
- **Full Report**: Refer to `COMPAT_REPORT.md` in the root of this directory for the latest compatibility status of all packages.

## 🛠️ Adding New Tests

1. Create a new directory under `cli/`, `library/`, or `web/` (named after the package).
2. Create a `compat.toml` file in that directory to configure the test source and arguments. Refer to existing configurations (e.g., `library/requests/compat.toml`).
