# RFC-0002: Phase 3 Zygote Mode

> **Status**: `Draft`  
> **Author**: Velo Core Team  
> **Created**: 2026-01-01  
> **Target Release**: Velo v0.3.0  
> **Discussion**: [GitHub Issues](https://github.com/velo-sh/velo/issues)

---

## 1. Executive Summary

### 1.1 Background

Phase 1.5 achieved **2-5% faster** startup than CPython through path caching and ABI detection. However, the fundamental bottleneck remains:

| Startup Phase | Time | Cacheable? |
|---------------|------|------------|
| Path resolution | ~10ms | ✅ Cached in Phase 1 |
| Module loading | ~200-400ms | ❌ Not cached |
| C-Extension init | ~50-100ms | ❌ Not cached |

**The real cost is module execution** - importing NumPy, loading Django's app registry, initializing FastAPI middleware. Path caching only addresses 3% of the problem.

### 1.2 Zygote Vision

**Zygote mode** pre-warms a Python interpreter with heavy libraries, then uses `fork()` + Copy-on-Write (COW) to instantly spawn workers:

```
┌─────────────────────────────────────────────────────────────┐
│                    Zygote Process                           │
│  - Pre-loaded: numpy, pandas, torch, fastapi, django        │
│  - Warm memory state                                        │
│  - Ready to fork                                            │
└──────────────────────┬──────────────────────────────────────┘
                       │ fork() + COW
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   ┌───────────┐ ┌───────────┐ ┌───────────┐
   │ Worker 1  │ │ Worker 2  │ │ Worker 3  │
   │  <5ms     │ │  <5ms     │ │  <5ms     │
   │  startup  │ │  startup  │ │  startup  │
   └───────────┘ └───────────┘ └───────────┘
```

### 1.3 Expected Impact

| Metric | Current (Phase 1.5) | Zygote Target |
|--------|---------------------|---------------|
| FastAPI cold start | 540ms | **< 50ms** |
| Django cold start | 400ms | **< 50ms** |
| Memory per worker | 100% | **~30%** (COW sharing) |

---

## 2. Technical Design

### 2.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      velo zygote                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   Spawner   │───▶│   Zygote    │───▶│   Workers   │     │
│  │   (Rust)    │    │  (Python)   │    │  (Python)   │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│        │                  │                  │              │
│        ▼                  ▼                  ▼              │
│  - Config loading   - Import heavy    - Handle requests     │
│  - Socket setup       libraries       - Execute scripts     │
│  - Process mgmt     - Wait for fork   - Exit when done      │
│                       signal                                │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Core Components

#### 2.2.1 Zygote Launcher (`velo zygote start`)

```rust
// src/zygote/launcher.rs
pub struct ZygoteLauncher {
    config: ZygoteConfig,
    zygote_pid: Option<u32>,
    socket_path: PathBuf,
}

impl ZygoteLauncher {
    /// Start the Zygote process with pre-loaded modules
    pub fn start(&mut self) -> Result<()> {
        // 1. Create Unix socket for IPC
        // 2. Spawn Python with zygote_main.py
        // 3. Wait for "READY" signal
    }
    
    /// Fork a new worker from the Zygote
    pub fn spawn_worker(&self, script: &Path) -> Result<WorkerHandle> {
        // 1. Send FORK command over socket
        // 2. Zygote forks and runs script
        // 3. Return handle to worker process
    }
}
```

#### 2.2.2 Zygote Process (Python)

```python
# velo_zygote/main.py
import os
import sys
import socket

def zygote_main(config_path: str):
    """Main entry point for Zygote process."""
    
    # 1. Load configuration
    config = load_config(config_path)
    
    # 2. Pre-import heavy modules
    for module in config.preload_modules:
        __import__(module)
    
    # 3. Signal ready
    notify_ready()
    
    # 4. Wait for fork commands
    while True:
        cmd = wait_for_command()
        if cmd.type == "FORK":
            if os.fork() == 0:
                # Child: run the script
                exec(cmd.script)
                sys.exit(0)
            # Parent: continue waiting
```

#### 2.2.3 IPC Protocol

```
┌─────────────────────────────────────────────────────────────┐
│                    Unix Socket Protocol                     │
├─────────────────────────────────────────────────────────────┤
│  Launcher → Zygote:                                         │
│    FORK <script_path> <args>                                │
│    SHUTDOWN                                                 │
│                                                             │
│  Zygote → Launcher:                                         │
│    READY                                                    │
│    FORKED <worker_pid>                                      │
│    ERROR <message>                                          │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 Configuration

```toml
# pyproject.toml
[tool.velo]
preload = ["numpy", "pandas", "fastapi", "sqlalchemy"]
idle_timeout = 300  # seconds (for Zygote daemon)

# Auto-detect from --profile data
[tool.velo.zygote]
threshold_ms = 50  # Pre-load modules that take > 50ms
```

### 2.4 CLI Commands

```bash
# Start Zygote daemon
velo zygote start

# Run script using Zygote (fast spawn)
velo run --zygote script.py

# Check Zygote status
velo zygote status

# Stop Zygote daemon
velo zygote stop

# Auto-configure from profile data
velo zygote auto-config
```

---

## 3. Platform Considerations

### 3.1 macOS Limitations

| Issue | Impact | Mitigation |
|-------|--------|------------|
| No `prctl(PR_SET_PDEATHSIG)` | Orphan workers | Use `kqueue` for parent death notification |
| SIP restricts fork | Some system modules | Test thoroughly, provide fallback |
| Sandbox restrictions | May block sockets | Use user-writable paths |

### 3.2 Linux Advantages

- Full `fork()` + COW support
- `prctl` for clean orphan handling
- cgroups for resource limiting

### 3.3 Windows Limitations

- No `fork()` - **Zygote not supported on Windows**
- Fall back to regular `velo run` mode

---

## 4. Implementation Phases

### 4.1 Phase 3.1: Basic Fork (2 weeks)

- [ ] Unix socket IPC setup
- [ ] Basic Zygote Python script
- [ ] `velo zygote start/stop`
- [ ] `velo run --zygote`
- [ ] Basic tests

### 4.2 Phase 3.2: Production Hardening (2 weeks)

- [ ] Worker lifecycle management
- [ ] Orphan process cleanup
- [ ] Graceful shutdown
- [ ] Log aggregation
- [ ] Error recovery

### 4.3 Phase 3.3: Auto-Configuration (1 week)

- [ ] Integration with `--profile` data
- [ ] `velo zygote auto-config` command
- [ ] `pyproject.toml [tool.velo]` generation

### 4.4 Phase 3.4: Optimization (1 week)

- [ ] Memory usage benchmarks
- [ ] COW effectiveness measurement
- [ ] Startup time benchmarks
- [ ] Documentation

---

## 5. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| fork() unsafe with threads | High | Critical | Ensure single-threaded pre-fork |
| Module side effects on import | Medium | High | Document known problematic modules |
| Socket permission issues | Low | Medium | Use user-writable temp directory |
| Memory not actually shared (COW broken) | Low | High | Benchmark and validate COW behavior |

---

## 6. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Cold start (FastAPI) | < 50ms | `time velo run --zygote` |
| Cold start (Django) | < 50ms | `time velo run --zygote` |
| Memory per worker | < 50% of standalone | `ps aux` comparison |
| Fork latency | < 5ms | IPC round-trip timing |

---

## 7. Design Decisions

### 7.1 Hybrid Daemon Mode ✅

**Decision**: Zygote operates in **Hybrid mode** - auto-starts on first `--zygote` request, exits after idle timeout.

| Mode | Behavior |
|------|----------|
| First run | Auto-start Zygote + pre-warm |
| Subsequent runs | Instant fork from existing Zygote |
| Idle | Auto-exit after `idle_timeout` (default: 5 min) |
| Explicit | `velo zygote start` for permanent daemon |

**Rationale**:
- Development: Use and forget, no memory waste
- CI/CD: Each job auto-starts, no setup needed
- Production: Explicit daemon mode available

### 7.2 Independent CLI Tool ✅

**Decision**: Phase 3 positions Velo as an **independent startup accelerator**, NOT integrated with uvicorn/gunicorn.

```bash
# Phase 3 approach
velo run --zygote my_script.py
velo run --zygote uvicorn main:app  # User manages uvicorn

# NOT: velo serve main:app --workers 4  (deferred to Phase 4)
```

**Rationale**:
- Minimize scope to validate Zygote feasibility
- Avoid framework coupling in MVP
- Users can still benefit by wrapping their server command

### 7.3 Windows Fallback ✅

**Decision**: On Windows, `--zygote` flag is **silently ignored** and falls back to normal `velo run`.

```rust
if cfg!(windows) && args.zygote {
    eprintln!("⚠️ Zygote not supported on Windows, using normal mode");
}
```

---

## 8. Future Roadmap

```
Phase 3.0: Zygote MVP (Current RFC)
├─ Hybrid daemon mode
├─ Independent CLI tool
└─ Goal: Prove <50ms cold start

Phase 3.5: Ecosystem Integration (Future)
├─ Velo as prefork manager
├─ Integration with uvicorn/gunicorn
└─ Goal: Simplify deployment

Phase 4: ASGI Server (Long-term)
├─ velo serve main:app --workers 4
├─ Built-in HTTP server with Zygote
└─ Goal: One-stop solution
```

---

## 9. Open Questions (Remaining)

1. **Module state handling**
   - Some modules (e.g., `random`, `ssl`) have global state
   - Need to document which modules are fork-safe

2. **GPU memory sharing**
   - Does COW work with CUDA/MPS memory?
   - May need special handling for torch/tensorflow

---

**Document End**
