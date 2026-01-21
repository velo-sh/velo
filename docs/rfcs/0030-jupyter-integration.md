# RFC-0030: Velo IDE Integration (Jupyter + VS Code)

**Status**: APPROVED
**Author**: Architect
**Date**: 2026-01-14 (Updated: 2026-01-21)
**Phase**: Phase 9

## Related Documents
- [RFC-0029: Velo Vibe Engine](./0029-velo-live.md)
- [RFC-0019: Native Sovereignty](./0019-native-sovereignty.md)
- [RFC-0028: pytest-velo](./0028-zygote-test-executor.md)

---

## 1. Summary

This RFC specifies **Velo IDE Integration**, bringing Velo's core capabilities to Jupyter and VS Code users:

### Core Capabilities

| Capability | Traditional Jupyter | With Velo |
|:---|:---|:---|
| **1. Instant Startup/Restart** | 2-5s cold start | **<100ms** (Zygote fork) |
| **2. Memory Density** | 500MB per kernel | **~20MB delta** (COW sharing) |

### Impact at Scale (100 Concurrent Kernels)

| Metric | Traditional | Velo | Improvement |
|:---|:---|:---|:---:|
| **Kernel startup** | 2-5s | <100ms | **20-50x** |
| **Total memory** | ~50GB | ~2.5GB | **20x** |

---

## 2. Architecture

### 2.1 High-Density Memory Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TRADITIONAL JUPYTERHUB (100 KERNELS)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Kernel 1: [Python + numpy + pandas + torch] = 500MB                        │
│  Kernel 2: [Python + numpy + pandas + torch] = 500MB                        │
│  ...                                                                         │
│  Kernel 100: [Python + numpy + pandas + torch] = 500MB                      │
│                                                                              │
│  TOTAL: 100 × 500MB = 50GB                                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                    VELO JUPYTERHUB (100 KERNELS)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  ZYGOTE (Shared Read-Only) = 500MB                                   │    │
│  │  [Python + numpy + pandas + torch]                                   │    │
│  │                                 ▼ COW fork()                         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  Kernel 1: [Private delta] = ~20MB                                          │
│  Kernel 2: [Private delta] = ~20MB                                          │
│  ...                                                                         │
│  Kernel 100: [Private delta] = ~20MB                                        │
│                                                                              │
│  TOTAL: 500MB (shared) + 100 × 20MB (private) = 2.5GB                       │
│  EFFICIENCY: 20x memory reduction                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Component Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         VELO JUPYTER STACK                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────┐                                                          │
│  │  JupyterHub    │  (Unmodified)                                           │
│  │  + Lab/Classic │                                                          │
│  └───────┬────────┘                                                          │
│          │                                                                   │
│          ▼                                                                   │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │  jupyterhub-velo-spawner                                            │     │
│  │  • Replaces DockerSpawner/KubernetesSpawner                        │     │
│  │  • Requests kernel from Velo Zygote                                │     │
│  │  • Returns ZMQ endpoints to Hub                                     │     │
│  └───────┬────────────────────────────────────────────────────────────┘     │
│          │                                                                   │
│          ▼ UDS/MessagePack                                                   │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │  Velo Zygote Server (Rust)                                          │     │
│  │  ┌──────────────────────────────────────────────────────────────┐  │     │
│  │  │  Pre-warmed Python + Scientific Stack                        │  │     │
│  │  │  [numpy, pandas, torch, sklearn, matplotlib, ...]            │  │     │
│  │  └──────────────────────────────────────────────────────────────┘  │     │
│  │                            │                                        │     │
│  │               fork() COW   ▼                                        │     │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │     │
│  │  │ Kernel 1     │  │ Kernel 2     │  │ Kernel 3     │  ...        │     │
│  │  │ (velo-kernel)│  │ (velo-kernel)│  │ (velo-kernel)│              │     │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Self-Contained Architecture (RFC-0018 Integration)

Velo embeds `uv` internally (RFC-0018 Integrated Custody), enabling zero-dependency Jupyter setup:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         VELO (SELF-CONTAINED)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  velo binary                                                                 │
│    ├── Embedded uv (RFC-0018)                                               │
│    ├── Zygote Engine                                                         │
│    ├── Jupyter Kernel Handler                                               │
│    └── ZMQ Protocol Implementation                                          │
│                                                                              │
│  velo jupyter install:                                                       │
│    1. Uses embedded uv to create/sync kernel environment                    │
│    2. Auto-installs ipykernel + dependencies                                │
│    3. Registers kernel.json                                                  │
│    4. Done. No external dependencies.                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Environment Detection Priority

| User Scenario | Behavior |
|:---|:---|
| Has `.venv` | Use existing environment |
| Has `pyproject.toml` | Embedded uv sync |
| Has `uv.lock` | Embedded uv resolves directly |
| Nothing | Embedded uv creates managed environment |

#### Compatibility Guarantee

| Standard Command | Velo Equivalent | 100% Compatible |
|:---|:---|:---:|
| `python -m ipykernel install` | `velo jupyter install` | ✅ |
| `jupyter kernelspec list` | Works unchanged | ✅ |
| `jupyter lab` | Discovers Velo kernel | ✅ |

---

### 2.4 Kernel Lifecycle

```
1. KERNEL REQUEST
   └── Hub → VeloSpawner.start()
       └── Spawner → Zygote: "FORK_KERNEL {user_id, preload}"

2. ZYGOTE FORK (~50ms)
   └── Zygote: fork() → child process
   └── Child: Initialize ZMQ sockets
   └── Child: Send ZMQ endpoints back to Spawner

3. KERNEL READY
   └── Spawner → Hub: {shell_port, iopub_port, ...}
   └── Hub → Frontend: Connect to kernel

4. CELL EXECUTION
   └── Frontend → Kernel (ZMQ Shell): execute_request
   └── Kernel: exec(code)
   └── Kernel → Frontend (ZMQ IOPub): stream, display_data

5. KERNEL SHUTDOWN
   └── Kernel: exit(0)
   └── Memory: Private pages freed, shared pages remain
```

---

## 3. Implementation

### 3.1 Design Philosophy: Wrap, Don't Reimplement

> [!IMPORTANT]
> **Key Insight**: ipykernel is pure Python running on CPython. Velo can directly boot it.
> This achieves 100% compatibility with zero protocol reimplementation.

```
Traditional Jupyter:
  python -m ipykernel_launcher -f connection.json
  └── Cold start: 2-5 seconds

Velo Jupyter:
  velo run -m ipykernel_launcher -f connection.json
  └── Zygote fork: <100ms
  └── COW memory sharing: 20x density
  └── 100% ipykernel compatibility
```

### 3.2 Compatibility Matrix

| ipykernel Feature | Velo Support | Notes |
|:---|:---:|:---|
| `execute_request` | ✅ | Via ipykernel |
| Magic commands (`%`, `%%`) | ✅ | Via IPython |
| Shell escapes (`!`) | ✅ | Via IPython |
| Tab completion | ✅ | Via ipykernel |
| Rich display (plots, HTML) | ✅ | Via ipykernel |
| ipywidgets | ✅ | Via ipykernel |
| Debugger | ✅ | Via ipykernel |

**Drop-in Score: 100%**

### 3.3 kernel.json

```json
{
  "argv": ["velo", "run", "-m", "ipykernel_launcher", "-f", "{connection_file}"],
  "display_name": "Velo Python",
  "language": "python",
  "metadata": { "debugger": true }
}
```

> [!NOTE]
> Uses `velo run` to boot ipykernel with Zygote acceleration.
> No custom kernel code needed.

### 3.4 JupyterHub Spawner (Optional)

For multi-user deployments, a custom spawner enables COW memory sharing:

```python
# jupyterhub_velo/spawner.py
from jupyterhub.spawner import LocalProcessSpawner

class VeloSpawner(LocalProcessSpawner):
    """Spawner that uses Velo Zygote for high-density kernel deployment."""
    
    def get_args(self):
        return ['run', '-m', 'ipykernel_launcher', '-f', self.connection_file]
    
    @property
    def cmd(self):
        return ['velo']
```

### 3.5 Zygote Preload Configuration

For maximum startup speed, preload common scientific stack:

```bash
# .velo/jupyter.toml
[zygote.preload]
modules = ["numpy", "pandas", "matplotlib", "torch", "sklearn"]
```

This ensures all heavy imports are in the Zygote, enabling <50ms kernel fork.

---

## 4. CLI Interface

> [!NOTE]
> All commands use Velo's embedded `uv` (RFC-0018). No external pip/uv installation required.

```bash
# Install Velo as Jupyter kernel (uses embedded uv internally)
velo jupyter install                          # Current project
velo jupyter install --sys-prefix             # System-wide
velo jupyter install --preload "torch,pandas" # With preload hints

# Verify installation (standard Jupyter command)
jupyter kernelspec list
# Available kernels:
#   velo    /Users/xxx/.local/share/jupyter/kernels/velo

# Launch kernel directly (for debugging)
velo jupyter kernel --connection-file /path/to/kernel.json

# Start Zygote server with Jupyter support
velo zygote start --jupyter --preload "numpy,pandas,torch"

# One-liner: launch JupyterLab with Velo kernel
velo jupyter lab
```

---

## 5. JupyterHub Configuration

### 5.1 Basic

```python
# jupyterhub_config.py
c.JupyterHub.spawner_class = 'jupyterhub_velo.VeloSpawner'
c.VeloSpawner.zygote_socket = '/var/run/velo-jupyter.sock'
c.VeloSpawner.preload_modules = ['numpy', 'pandas', 'matplotlib']
```

### 5.2 Kubernetes

```yaml
# Velo Zygote DaemonSet
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: velo-zygote
spec:
  template:
    spec:
      containers:
      - name: zygote
        image: velo/zygote:latest
        args: ["--jupyter", "--preload", "numpy,pandas,torch"]
```

---

## 6. Performance Targets

| Metric | Target | Test |
|:---|:---|:---|
| **Kernel startup** | <100ms | `test_kernel_startup_latency` |
| **Memory per kernel** | <30MB delta | `test_memory_delta` |
| **100 concurrent kernels** | <5GB total | `test_100_kernels_memory` |
| **Cell execution overhead** | <5ms | `test_cell_overhead` |

---

## 7. Security Model

### 7.1 Threat Mitigations

| Threat | Mitigation |
|:---|:---|
| **Cross-user data leak** | COW: Write triggers private copy |
| **Cross-user file access** | Per-kernel TMPDIR: `/tmp/velo-kernel-{pid}/` |
| **Socket hijacking** | Per-user socket: `/run/user/{uid}/velo-kernel-{pid}.sock` |
| **Resource exhaustion** | cgroups: CPU=1 core, Memory=2GB per kernel |
| **Privilege escalation** | namespaces: User namespace per kernel |

### 7.2 Isolation Paths (P1-002)

```
Kernel 1 (user: alice, pid: 1234):
  TMPDIR:  /tmp/velo-kernel-1234/
  Socket:  /run/user/1000/velo-kernel-1234.sock
  
Kernel 2 (user: bob, pid: 5678):
  TMPDIR:  /tmp/velo-kernel-5678/
  Socket:  /run/user/1001/velo-kernel-5678.sock
```

---

## 8. Quality Gates

| Gate | Requirement |
|:---|:---|
| **Gate A** | Jupyter Messaging Protocol compliant |
| **Gate B** | ipykernel feature parity for basic notebooks |
| **Gate C** | 100 kernels in <5GB memory |
| **Gate D** | Kernel startup <100ms |
| **Gate E** | JupyterHub spawner integration works |

---

## 9. Implementation Phases

| Phase | Scope | Duration |
|:---|:---|:---|
| **Phase 1** | velo-kernel MVP (ZMQ, execute_request) | 3 days |
| **Phase 2** | jupyterhub-velo-spawner | 2 days |
| **Phase 3** | High-density mode + memory benchmark | 2 days |
| **Phase 4** | Security (namespaces, cgroups) | 3 days |

### 9.1 Engineering Risk Notes (P0 Action Items)

> [!WARNING]
> The following details are critical for achieving true "Drop-in" compatibility.

#### 9.1.1 Signal Propagation

**Problem**: When user clicks "Stop" in Jupyter UI, SIGINT is sent to the parent process (`velo`).

**Requirement**: Velo MUST act as a transparent proxy and forward ALL signals (SIGINT, SIGTERM, SIGHUP) to the child process (`ipykernel`). Otherwise, users cannot stop infinite loops.

```rust
// Required in Velo process management
signal::forward_to_child(child_pid, &[SIGINT, SIGTERM, SIGHUP]);
```

#### 9.1.2 Connection File Permissions

**Problem**: Jupyter generates `kernel-xxx.json` in `/tmp` or Runtime directory.

**Requirement**: Forked child process MUST have read access to this file. If using Namespace isolation (RFC-0019), bind mount the path into the namespace.

```
/tmp/kernel-{uuid}.json → accessible to forked kernel
```

#### 9.1.3 File Descriptor Leak Prevention

**Requirement**: After Zygote fork, before exec'ing ipykernel, MUST close all unnecessary file descriptors (except ZMQ sockets and log pipes). This ensures a clean environment.

```rust
// Post-fork cleanup
for fd in 3..max_fd {
    if !preserved_fds.contains(&fd) {
        libc::close(fd);
    }
}
```

---

## 10. VS Code Integration

### 10.1 Unified Architecture

VS Code and Jupyter share the same integration approach:

```
                    ┌─────────────────────────┐
                    │     Velo Zygote         │
                    │  (Python + libs)        │
                    └───────────┬─────────────┘
                                │ fork() <100ms
            ┌───────────────────┼───────────────────┐
            ▼                   ▼                   ▼
    ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
    │ Jupyter Kernel│   │ VS Code Debug │   │ velo run      │
    │ (ipykernel)   │   │ (debugpy)     │   │               │
    └───────────────┘   └───────────────┘   └───────────────┘
```

### 10.2 Debug Configuration

> [!NOTE]
> VS Code's `debugpy` expects a Python interpreter path. Use a wrapper script or the run configuration below.

**Option A: Shell-based Debug (Recommended)**

```json
// .vscode/launch.json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Velo: Run Python",
      "type": "node-terminal",
      "request": "launch",
      "command": "velo run ${file}"
    }
  ]
}
```

**Option B: Python Debug with Velo Preload**

```json
// .vscode/launch.json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Debug (Velo-warmed)",
      "type": "debugpy",
      "request": "launch",
      "program": "${file}",
      "preLaunchTask": "velo-zygote-start"
    }
  ]
}
```

### 10.3 Run Configuration

```json
// .vscode/tasks.json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Velo Run",
      "type": "shell",
      "command": "velo run ${file}",
      "group": "test",
      "presentation": { "reveal": "always" }
    }
  ]
}
```

### 10.4 Value Proposition

| Scenario | Traditional | With Velo |
|:---|:---|:---|
| **Run Python** | 2-5s cold start | <100ms |
| **Debug Start** | 3-5s | <100ms |
| **Restart Debug** | 2-3s | <50ms |

### 10.5 Future: VS Code Extension

A dedicated Velo extension could provide:
- Automatic Zygote management
- Status bar indicator
- One-click preload configuration

---

## 11. Open Questions

| Question | Proposed Answer |
|:---|:---|
| **ipywidgets support?** | ✅ Via ipykernel |
| **VS Code Debugger?** | ✅ Via debugpy |
| **Other IDEs (PyCharm)?** | Future Phase |

---

**Last Updated**: 2026-01-21
