# Velo Compatibility Verification Plan (Tier 1-3)

This document outlines the strategy for verifying Velo's compatibility with the top 100 Python packages by running their native test suites under the Velo Zygote environment.

## 1. Objectives
- **Zero Regression**: Ensure Velo (Zygote) achieves 100% functional parity with CPython.
- **Environment Isolation**: Prevent host environment pollution and ensure reproducible test results.
- **Automated Parity Audit**: Provide a standardized way to compare `pytest` results between CPython and Velo.

## 2. Methodology

### 2.1 Tier-Based Strategy
Packages are categorized into three tiers based on complexity and impact:
- **Tier 1 (Blocker)**: High-impact frameworks (`Django`, `FastAPI`, `Celery`, `Click`, `attrs`). These must achieve parity for any Velo release.
- **Tier 2 (Core)**: Widely used libraries (`requests`, `pydantic`, `numpy`, `pandas`, `flask`).
- **Tier 3 (Extended)**: Remaining top 100 packages.

### 2.2 Execution Protocol
Each test run follows these steps:
1. **Source Acquisition**: Clone specific version of the package or use `pip install`.
2. **Environment Shielding**: 
   - Scrub host `PYTHONPATH` and virtual env paths.
   - Inject absolute project paths to avoid CWD confusion in forked workers.
   - Use a shared, clean virtual environment for all tests.
3. **Dual Baseline**:
   - Run tests with CPython to establish the ground truth (Pass/Skip/XFail counts).
   - Run tests with Velo Zygote with identical arguments and environment variables.
4. **Parity Comparison**: Compare `nodeid` level outcomes. Failures that exist in Velo but not in CPython are marked as **Regressions**.

### 2.3 Verdict Definitions
- ✅ **COMPATIBLE**: Velo matches CPython's pass rate (or any differences are documented `known_failures`).
- ❌ **REGRESSION**: Velo fails a test that passes in CPython.
- ❓ **DISCOVERY_FAILED**: Tests could not be collected in either runtime (usually due to setup issues).
- ⌛ **TIMEOUT**: Tests exceeded the allotted time limit.

## 3. Configuration (`compat.toml`)
Each project has a dedicated `compat.toml` specifying:
- `git_repo` and `git_ref`: Exact version to test.
- `test_dependencies`: Required libraries for running tests.
- `env`: Framework-specific variables (e.g., `DJANGO_SETTINGS_MODULE`).
- `known_failures`: Masked tests that are environment-sensitive.

## 4. Environment Isolation Details
- **Absolute Path Injection**: Velo workers explicitly `os.chdir()` to the project root and use absolute `sys.path` entries.
- **Pyproject Hiding**: `pyproject.toml` is temporarily renamed during Velo runs to prevent automatic `uv --frozen` triggers that might conflict with the manual test setup.
- **Shared Venv**: A single `.shared_venv` is used to store all installed test dependencies to speed up subsequent runs.
