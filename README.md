# Velo 🚀

**Python is perfect for coding. Velo is perfect for running.**

The high-performance Python runtime for the AI era, built with Rust.

> 🚧 **Heavy Work In Progress.** Not ready for production. Expect breaking changes.

## Why Velo?

| Problem | Solution |
|---------|----------|
| Python cold start is slow (~seconds) | Sub-millisecond startup via env fingerprinting |
| Dependency chaos, bloated Docker images | Single-binary packaging (coming soon) |
| Source code exposed | Bytecode encryption (coming soon) |
| Heavy memory footprint | Zygote + Copy-on-Write for serverless density |

## Quick Start

```bash
# Install
cargo install --path .

# Run the demo script
velo run tests/corpus/hello.py
```

## Development

```bash
# Run tests (requires uv)
uv run run_tests.py
```

## Compatibility

Velo is **not** a new language. It runs standard Python code and maintains full compatibility with:
- CPython 3.11+
- PyPI packages (NumPy, Torch, etc.)

## License

Apache-2.0