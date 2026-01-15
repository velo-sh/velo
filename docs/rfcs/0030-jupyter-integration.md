# RFC-0030: Velo Jupyter Kernel

**Status**: DRAFT
**Author**: Architect
**Date**: 2026-01-14
**Phase**: Phase 8.x

## Related Documents
- [RFC-0029: Velo Live](./0029-velo-live.md)
- [RFC-0019: Native Sovereignty](./0019-native-sovereignty.md)

---

## 1. Summary

This RFC specifies the **Velo Jupyter Kernel** implementation, enabling Velo's high-performance runtime to serve as an alternative backend for Jupyter notebooks.

| Component | Description |
|:---|:---|
| `velo-kernel` | Jupyter kernel implementing Jupyter Messaging Protocol |
| `kernel.json` | Kernel discovery specification |
| Integration | Zygote COW for cell-level isolation |

---

## 2. Motivation

Jupyter notebooks are the dominant interface for interactive Python development. Integrating Velo as a Jupyter kernel enables:

- **Performance**: Zygote-based execution for faster cell evaluation
- **Isolation**: COW-based cell isolation without full process restart
- **Compatibility**: Standard Jupyter protocol, works with existing notebooks

---

## 3. Architecture

### 3.1 Jupyter Protocol Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      JUPYTER KERNEL ARCHITECTURE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────┐      ┌────────────────┐      ┌─────────────────────────┐    │
│  │  Jupyter   │◀────▶│ Jupyter Server │◀────▶│     velo-kernel         │    │
│  │  Frontend  │ HTTP │                │ ZMQ  │                         │    │
│  └────────────┘      └────────────────┘      └─────────────────────────┘    │
│                                                       │                      │
│                                                       ▼                      │
│                                               ┌───────────────┐              │
│                                               │ Velo Runtime  │              │
│                                               │ (Zygote + COW)│              │
│                                               └───────────────┘              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Cell Execution with Zygote

```
┌─────────────────────────────────────────────────────────────────┐
│  Cell Execution Flow                                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Kernel starts → Zygote pre-warms (import common libraries)     │
│                                                                  │
│  Stateless Mode (isolated cells):                                │
│       Cell N → fork(Zygote) → exec(code) → output → exit()      │
│                                                                  │
│  Stateful Mode (preserves state):                                │
│       Cell 1 → exec in main process                             │
│       Cell 2 → checkpoint → fork → exec → merge state           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Implementation

### 4.1 Kernel Specification

```json
{
  "argv": ["velo", "jupyter", "--connection-file", "{connection_file}"],
  "display_name": "Velo",
  "language": "python",
  "metadata": {
    "debugger": true
  }
}
```

### 4.2 Message Types

| Message | Direction | Description |
|:---|:---|:---|
| `execute_request` | Client → Kernel | Execute cell code |
| `execute_reply` | Kernel → Client | Execution status |
| `stream` | Kernel → Client | stdout/stderr output |
| `display_data` | Kernel → Client | Rich output (plots, HTML) |
| `error` | Kernel → Client | Exception traceback |

### 4.3 ZeroMQ Sockets

| Socket | Purpose |
|:---|:---|
| Shell | Request/reply (execute, complete) |
| IOPub | Broadcast output to all clients |
| Stdin | User input prompts |
| Control | Shutdown, interrupt |
| Heartbeat | Liveness check |

---

## 5. Deployment Models

### 5.1 Local Installation

```bash
pip install velo velo-jupyter
jupyter kernelspec install --user velo
```

### 5.2 JupyterHub Integration

```python
# jupyterhub_config.py
c.Spawner.default_url = '/lab'
c.KernelSpecManager.ensure_native_kernel = False
c.KernelSpecManager.whitelist = {'velo'}
```

### 5.3 Container Deployment

```dockerfile
FROM velo/runtime:latest
RUN pip install jupyterlab
EXPOSE 8888
CMD ["jupyter", "lab", "--ip=0.0.0.0"]
```

---

## 6. Performance Considerations

| Aspect | ipykernel | velo-kernel |
|:---|:---|:---|
| Cell startup | ~50-100ms | ~1-5ms (COW fork) |
| Memory isolation | None | Full (per-cell fork) |
| State management | Global | Configurable |

---

## 7. Security Model

### 7.1 Cell Isolation

Each cell execution in isolated mode runs in a forked process:
- **Memory isolation**: COW prevents cross-cell data leakage
- **Resource limits**: cgroups for CPU/memory per cell
- **Timeout**: Configurable per-cell execution timeout

### 7.2 Multi-tenant Considerations

For shared deployments (JupyterHub):
- Container-per-user isolation
- Namespace separation
- Network policy enforcement

---

## 8. Quality Gates

| Gate | Requirement |
|:---|:---|
| **Gate A** | Full Jupyter Messaging Protocol compliance |
| **Gate B** | Output parity with ipykernel for standard notebooks |
| **Gate C** | Cell execution latency < 5ms (excluding user code) |
| **Gate D** | Memory overhead < 10MB per notebook session |

---

**Last Updated**: 2026-01-14
