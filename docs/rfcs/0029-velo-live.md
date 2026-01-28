# RFC-0029: Velo Vibe Engine (Instant Python Feedback)

**Status**: ✅ IMPLEMENTED
**Author**: Architect
**Date**: 2026-01-14
**Updated**: 2026-01-21
**Phase**: Phase 8

## Related Documents
- [RFC-0019: Native Sovereignty](./0019-native-sovereignty.md) (Zygote Architecture)
- [Zygote COW Vision](../architecture/zygote_cow_vision.md)

---

## 1. Summary

**Velo Live** delivers a **"What You See Is What You Get"** experience for Python development. Like hot-reload in web development, every code change triggers instant execution and feedback.

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
# Start vibe mode (real-time hot reload)
velo run --vibe app.py

# With specific preloads
velo run --vibe --preload "torch,pandas" app.py

# Custom WebSocket port
velo run --vibe --port 9191 app.py

# Alias: --live is equivalent to --vibe
velo run --live app.py
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

---

**Last Updated**: 2026-01-14
