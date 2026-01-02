# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.5] - 2026-01-02

### Added

- **`velo serve` command**: Serve ASGI/WSGI apps with Zygote pre-warming
  - Syntax: `velo serve main:app --workers 4 --reload`
  - Framework auto-detection (FastAPI, Django, Flask, Starlette)
  - Wraps uvicorn with automatic Zygote integration
  - `--host`, `--port`, `--workers`, `--reload`, `--no-zygote` options
- **Worker pool management**: Health checks and graceful shutdown
- **RFC-0003**: Phase 3.5 Ecosystem Integration documentation

## [0.2.0] - 2026-01-01

### Added

- **`velo info` command**: Display system information including hardware, Python environment, and cache status
- **`velo run --profile`**: Startup profiling with import time breakdown and optimization suggestions
- **ABI detection**: Automatic Python ABI fingerprinting to prevent C-extension compatibility issues
- **Cache version management**: Automatic cache invalidation when Velo or Python version changes
- **Environment integrity checking**: Detection of packages installed outside of `uv`

### Changed

- Cache structure upgraded to v2 with ABI metadata
- Improved benchmark results: FastAPI 2% faster, Django 5% faster

### Fixed

- ABI detection no longer spawns Python subprocess on every cache hit (major performance fix)

## [0.1.0] - 2025-12-15

### Added

- Initial release
- `velo run` command for running Python scripts
- Environment fingerprinting via `uv.lock` hash
- Path caching with `rkyv` zero-copy serialization
- Process isolation supporting Python 3.11, 3.12, 3.13+
- Automatic `.venv` detection
