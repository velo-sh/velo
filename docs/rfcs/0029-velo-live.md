# RFC-0029: Velo Live (Instant Python Feedback)

**Status**: PROVISIONALLY APPROVED (Architect Review 2026-01-20)
**Author**: Architect
**Date**: 2026-01-14
**Phase**: Phase 8.x

## Related Documents
- [RFC-0019: Native Sovereignty](./0019-native-sovereignty.md) (Zygote Architecture)
- [Zygote COW Vision](../architecture/zygote_cow_vision.md)

---

## 1. Summary

**Velo Live** delivers a **"What You See Is What You Get"** experience for Python development. Like hot-reload in web development, every code change triggers instant execution and feedback.

### 1.1 The Vibe Engine (Velo + Vibe-Coding)

To support the AI-driven **"Vibe-Coding"** movement, Velo establishes the **Vibe Engine**. 
- **Definition**: Vibe-coding requires a zero-latency feedback loop where the developer's "vibe" (intent) is manifested and verified instantly. 
- **The Prerequisite**: True vibe-coding is impossible with 2-second reload times. Velo's sub-10ms Miracle Fork provides the only industrial-grade infrastructure that can keep up with AI-speed iteration.
- **Sovereign Alias**: The `velo` CLI will expose **`vibe`** as the primary entry point for live development.

| Metric | Traditional | Velo Live |
|:---|:---|:---|
| Save-to-result | 500ms - 5s | **< 10ms** |
| State isolation | ❌ Polluted | ✅ Clean fork |
| Heavy imports | Every time | Once (Zygote) |

---

## 2. Motivation

Current Python development pain points:
- **Slow feedback**: `python app.py` reloads everything on each run
- **REPL pollution**: Interactive sessions accumulate stale state
- **Jupyter limits**: Good for notebooks, poor for app development

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        VELO LIVE ARCHITECTURE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────┐        ┌──────────────────────────────┐         │
│  │   IDE (VS Code)        │        │   Live Preview Panel         │         │
│  │   ┌────────────────┐   │        │   ┌──────────────────────┐   │         │
│  │   │ def predict(): │   │        │   │ Output: [0.95, 0.03] │   │         │
│  │   │   return model │◀──┼────────┼──▶│ Time: 3ms            │   │         │
│  │   └────────────────┘   │        │   │ Vars: x=5, y=10      │   │         │
│  └────────────────────────┘        │   └──────────────────────┘   │         │
│                                    └──────────────────────────────┘         │
│                                                                              │
│  Execution Flow (on each save):                                             │
│                                                                              │
│  ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐               │
│  │ File    │────▶│ Zygote  │────▶│ fork()  │────▶│ Execute │               │
│  │ Change  │     │ (warm)  │     │ (~1ms)  │     │ + Output│               │
│  └─────────┘     └─────────┘     └─────────┘     └────┬────┘               │
│                                                       │                     │
│                                                       ▼                     │
│                                                  ┌─────────┐               │
│                                                  │ exit()  │               │
│                                                  │ (clean) │               │
│                                                  └─────────┘               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Interface

```bash
# Start live mode
velo live app.py

# With specific preloads
velo live --preload "torch,pandas" app.py

# Watch specific function
velo live app.py::predict

### 4.1 CLI Ergonomics (The Triple-Tier Strategy)

To provide the shortest path to "Flow" while maintaining CLI consistency, Velo implements a tiered access model:

1.  **Sovereign Command (`vibe`)**: A standalone binary alias for the ultimate shorthand.
    *   `vibe app.py` -> Instant execution.
    *   `vibe test` -> Instant TDD.
2.  **Explicit Flag (`--vibe` / `--live`)**: A toggle for existing core commands.
    *   `velo run --vibe app.py`
    *   `velo serve --live app:app`
3.  **Formal Command (`velo vibe`)**: The rooted command structure for long-term stability.
    *   `velo vibe serve app:app`
    *   `velo vibe test`

- **`--auto-reload`**: Passive alias for `--vibe`, provided for compatibility with legacy uvicorn/flask workflows.
```

---

## 5. Features

### 5.1 Instant Execution

| Trigger | Action |
|:---|:---|
| File save | Fork + exec entire file |
| Ctrl+Enter | Fork + exec current selection |
| Function change | Fork + exec single function |

### 5.2 Clean State Guarantee

```
Edit 1 → fork() → execute → exit() → [clean]
Edit 2 → fork() → execute → exit() → [clean]
         ↑
         └── Each run starts from identical Zygote state
```

### 5.3 Variable Watch

```python
# app.py
x = compute_something()
# velo:watch x

# Preview panel shows:
# x = {'result': 42, 'time': 0.003}

### 5.4 Process Lifecycle Management (v_live Hardening)

To maintain **TITANIUM** reliability during high-frequency edit loops, the `v_live` engine must implement the following lifecycle protections:

1.  **Debounce Mechanism**: A minimum 50ms stable-state delay is required before triggering a new Zygote fork.
2.  **Greedy Reaper (TITANIUM)**: The Master process MUST implement a greedy reaper loop: `while waitpid(-1, &status, WNOHANG) > 0` to clean up all terminated workers in a single cycle.
3.  **Self-Healing Watcher**: The `v_live` monitor MUST survive Python `SyntaxError` and runtime crashes in the child worker, remaining active to watch for fixed code.
4.  **Pipe-Fence Logic**: To prevent log interleaving (SPEC-0006), the Master MUST ensure the active UDS/Pipe of the previous worker is fully drained and closed before binding the new worker's stream.
5.  **Orphan Prevention**: All live workers MUST be spawned with `PR_SET_PDEATHSIG` (Linux) or equivalent kernel-level supervision.
6.  **Exit Hygiene (SPEC-0006)**: Workers MUST exit via `os._exit()` to bypass genotype `atexit` hooks.
7.  **Resource Caps**: Hard limits on CPU/Memory per session.
```

---

## 6. Performance Targets

| Metric | Target |
|:---|:---|
| Fork latency | < 2ms |
| Total save-to-output | < 10ms |
| Memory per fork | COW, ~1MB delta |

---

## 7. IDE Integration

| IDE | Integration Method |
|:---|:---|
| **VS Code** | Extension + Side Panel |
| **PyCharm** | Plugin + Tool Window |
| **Neovim** | LSP + Floating Window |

---

## 8. Quality Gates

| Gate | Requirement |
|:---|:---|
| **Gate A** | Each execution is isolated (no state leak) |
| **Gate B** | stdout/stderr captured to preview panel |
| **Gate C** | Errors shown inline with line numbers |
| **Gate D** | Works with pytest for instant test feedback |

---

## 9. Comparison

| Tool | Latency | Isolation | IDE Integration |
|:---|:---|:---|:---|
| Python REPL | Instant | ❌ | ❌ |
| Jupyter | ~100ms | ⚠️ Cell | ⚠️ Limited |
| pytest-watch | ~500ms | ✅ | ❌ |
| **Velo Live** | **~10ms** | **✅** | **✅** |

---

## 10. Full-Stack Live Development

**Vision**: Combine backend Velo Live with frontend HMR for **sub-100ms full-stack feedback**.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FULL-STACK LIVE ARCHITECTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐       │
│  │  VS Code   │───▶│ Velo Live  │───▶│ WebSocket  │───▶│  Browser   │       │
│  │  (Python)  │    │ (Backend)  │    │   Push     │    │ (Frontend) │       │
│  └────────────┘    └────────────┘    └────────────┘    └────────────┘       │
│        │                 │                                   │               │
│   Edit Python        fork()                           Auto Refresh          │
│        │              ~10ms                                  │               │
│        └─────────────────────────────────────────────────────┘               │
│                              │                                               │
│                    Total Latency: < 60ms                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 10.1 Server Mode

```bash
# Start live server (FastAPI/Flask)
velo live serve app:app

# With frontend dev server integration
velo live serve app:app --notify-url http://localhost:5173/__velo_reload
```

### 10.2 Execution Flow

| Step | Action | Latency |
|:---|:---|:---|
| 1 | Python file saved | 0ms |
| 2 | Velo fork + reload module | ~10ms |
| 3 | WebSocket notify browser | ~5ms |
| 4 | Frontend HMR / refresh | ~30-50ms |
| **Total** | **Backend change visible in browser** | **< 60ms** |

### 10.3 Integration with Frontend Tools

| Frontend | Integration |
|:---|:---|
| **Vite** | Plugin + WebSocket bridge |
| **Next.js** | Custom dev server middleware |
| **React (CRA)** | Proxy + reload signal |

### 10.4 Competitive Advantage

| Stack | Backend Reload | Total Latency |
|:---|:---|:---|
| Next.js + uvicorn | ~2s | ~2s |
| Next.js + FastAPI (--reload) | ~500ms | ~550ms |
| **Vite + Velo Live** | **~10ms** | **~60ms** |

### 10.5 Native WebSocket Gateway

To achieve the <60ms target, Velo will implement a native **WebSocket Gateway** written in Rust (`src/v_live/gateway.rs`). 

- **Zygote workers push results to a locked-free queue in the Rust master via MessagePack (Internal SSoT).
- **IDE/Browser Binding**: The Master process hosts a WebSocket server that broadcasts results as **JSON Strings**.
- **Performance Tier (Future Work)**: Binary MessagePack egress is deferred to future optimizations to prioritize initial stability and zero-friction integration.
- **Native Serialization (TITANIUM)**: Payload extraction from Worker results handled via native Rust logic to minimize bridge latency.
- **Protocol Limits (SPEC-0007)**: WebSocket frames are capped at **5MB**.

---

**Last Updated**: 2026-01-14
