# Velo 🚀

**Python is perfect for coding. Velo is perfect for running.**

The high-performance Python runtime for the AI era, built with Rust.

> 🚧 **Heavy Work In Progress.** Not ready for production. Expect breaking changes.

## Why Velo?

| Problem | Solution |
|---------|----------|
| Python cold start is slow | **11% faster** startup via path caching |
| Version mismatch issues | Single binary supports **Python 3.11, 3.12, 3.13+** |
| Dependency chaos | Auto-detects `uv` virtual environments |

## Architecture

Velo uses **process isolation** - it detects your project's Python and spawns it with optimized environment settings:

```
┌─────────────────────────────┐
│        Velo Binary          │
│  - Detect .venv/bin/python  │
│  - Cache sys.path (rkyv)    │
│  - Optimize PYTHONPATH      │
└──────────────┬──────────────┘
               │ subprocess
               ▼
┌─────────────────────────────┐
│    Your Project's Python    │
│    (3.11, 3.12, 3.13...)    │
└─────────────────────────────┘
```

## Quick Start

```bash
# Build
cargo build --release

# Run a Python script (uses .venv/bin/python automatically)
./target/release/velo run your_script.py

# First run: captures paths, slight overhead
# Second run: uses cache, 11% faster than CPython
```

## Benchmark Results

```
=== CPython ===
NumPy import: 64ms

=== Velo (first run, no cache) ===
NumPy import: 69ms  (+8%)

=== Velo (cached) ===
NumPy import: 57ms  (-11%) ✅
```

## How It Works

1. **Python Detection**: Finds `.venv/bin/python` or `VELO_PYTHON` env var
2. **Environment Fingerprinting**: Hash `uv.lock` to detect changes
3. **Path Caching**: Cache `sys.path` with zero-copy `rkyv` serialization
4. **Deferred Capture**: First run executes immediately, caches for next time

## Development

```bash
# Run tests
uv run run_tests.py

# Benchmark against real projects
python3 benchmark_projects.py --all -n 5
```

## Compatibility

- **Python**: 3.11, 3.12, 3.13+ (single binary)
- **Packages**: Full PyPI compatibility (NumPy, Pandas, FastAPI, Django, etc.)
- **Environment**: Works with `uv`-managed virtual environments

## Roadmap

- [x] Phase 1: Environment fingerprinting & path caching
- [x] Phase 1.5: Binary size optimization (363KB)
- [x] Phase 2: Process isolation (multi-Python support)
- [ ] Phase 3: Zygote mode (< 5ms cold start)
- [ ] Phase 4: Static analysis & bytecode optimization

## License

Apache-2.0