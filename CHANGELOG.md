# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Zygote Stabilization (TITANIUM)**: 151x startup speedup on macOS
  - Process group isolation via `os.setsid()` for signal hygiene
  - Single Source of Truth (SSOT) lifecycle management via Rust supervisor
  - Slot-based stable UDS paths for race-free worker spawns
  - macOS kernel sandbox (`sandbox-exec`) enabled by default

### Known Issues

| Issue | Risk | Workaround |
|-------|------|------------|
| **macOS Orphan Processes** | 🟡 Medium | If supervisor is `SIGKILL`ed, workers may orphan. Use `pkill -f velo` for cleanup. |
| **`sandbox-exec` Deprecation** | 🟡 Medium | Apple may remove in future macOS. Will gracefully degrade to non-sandboxed mode. |
| **Reduced Debuggability** | 🟢 Low | Workers in separate session. Use `ps -o sid,pid,pgid,cmd` to discover worker PIDs. |
| **Uvicorn Signal Handling** | 🟢 Low | Workers rely on POSIX `SIGTERM`. Pin uvicorn version if issues arise. |

## [0.6.2] - 2026-01-06

### Added

- **Zygote Worker Integration (RFC-0011)**: L7 Proxy + COW-shared workers
  - Composition Architecture: Velo orchestrates worker lifecycle, uvicorn handles ASGI
  - Worker cold start reduced from ~200ms to ~10ms via Zygote fork
  - Memory sharing via COW (Copy-on-Write) optimization
  - Least-Connections load balancer with atomic counters
  - Abstract Namespace Sockets on Linux (`@velo-worker-N`)

### Changed

- Rust L7 Proxy replaces direct TCP for worker communication
- UDS (Unix Domain Sockets) for all worker IPC

### Security

- FD Hygiene: `FD_CLOEXEC` on all non-essential file descriptors before fork
- Signal State Reset: Full `post_fork` cleanup to prevent uvloop pollution
- Hop-by-Hop Header Stripping: `Connection`, `Transfer-Encoding`, `Te`, `Keep-Alive`
- Mandatory proxy headers: `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Port`

## [0.6.1] - 2026-01-04

### Added

- **`velo serve` (RFC-0010)**: Zero-config ASGI/WSGI server wrapper
  - Auto-detection: FastAPI, Django, Flask, Starlette
  - Instant restart (<50ms hot reload)
  - Gunicorn support for WSGI apps
  - Health check endpoints (`--health`)
  - Graceful shutdown with configurable timeout
  - Platform-specific optimizations (macOS FSEvents, Linux inotify)
- **`velo analyze --graph`**: Static import graph visualization with savings report
- **MessagePack IPC (OPT-0010-001)**: 20% message size reduction, 3-5x faster serialization
  - Protocol version 0x01 with length-prefix framing
  - Pure Python fallback via vendored u-msgpack-python
  - TRACE-level debugging for IPC messages
- **15 Expert Reviews**: Comprehensive RFC-0010 review (Platform, Security, QA, DX, Docs, Performance, Accessibility, Legal)

### Changed

- IPC protocol upgraded from JSON to MessagePack
- Zygote communication uses versioned protocol framing

### Security

- Command injection prevention for app arguments
- Path traversal protection in auto-discovery
- PID file TOCTOU race condition prevention
- DoS protection via message size limits (1MB max)

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
