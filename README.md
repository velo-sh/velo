# Velo 🚀

**Python is perfect for coding. Velo is perfect for running.**

The high-performance Python runtime for the AI era, built with Rust.

> 🚧 **Heavy Work In Progress.** Not ready for production. Expect breaking changes.

## Why Velo?

| Problem | Solution |
|---------|----------|
| Python cold start is slow | **3-9% faster** startup via env fingerprinting & path caching |
| Dependency chaos | Auto-detects `uv` virtual environments |
| Heavy memory footprint | Zygote + Copy-on-Write (coming soon) |

## Benchmark Results

Tested against real-world project simulations (60-80+ imports):

| Project | CPython | Velo | Speedup |
|---------|---------|------|---------|
| FastAPI (60+ imports) | 529ms | 484ms | **8% faster** ✅ |
| Django (70+ imports) | 393ms | 371ms | **5% faster** ✅ |
| Data Science (80+ imports) | 793ms | 770ms | **3% faster** ✅ |

## Quick Start

```bash
# Build
cargo build --release

# Run a Python script
./target/release/velo run your_script.py

# Run the test suite
uv run run_tests.py
```

## Benchmarking

```bash
# Simple benchmark (lightweight tests)
uv run bench.py --mode all

# Real-world project benchmark (FastAPI, Django, etc.)
python3 benchmark_projects.py --all -n 5
python3 benchmark_projects.py -p fastapi -n 10
```

## How It Works

1. **Environment Fingerprinting**: Hash `uv.lock` to detect environment changes
2. **Path Caching**: Cache `sys.path` with zero-copy `rkyv` serialization
3. **Pre-init Injection**: Set `PYTHONPATH` before Python initializes
4. **Venv Auto-detection**: Automatically find `.venv/lib/python*/site-packages`

## Compatibility

Velo is **not** a new language. It runs standard Python code:
- CPython 3.11+
- PyPI packages (NumPy, Pandas, FastAPI, Django, etc.)
- Works with `uv`-managed virtual environments

## Roadmap

- [x] Phase 1: Environment fingerprinting & path caching
- [x] Phase 1.5: Binary size optimization (348KB)
- [ ] Phase 2: JIT compilation
- [ ] Phase 3: Zygote mode (< 5ms cold start)
- [ ] Phase 4: Single-binary packaging

## License

Apache-2.0