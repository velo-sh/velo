# RFC-0030: Velo Jupyter Integration (High-Density Kernel Architecture)

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

This RFC specifies **Velo Jupyter Integration**, bringing Velo's core capabilities to Jupyter users:

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

### 3.1 velo-kernel (Python Package)

```python
# velo_jupyter/kernel.py
from ipykernel.kernelbase import Kernel

class VeloKernel(Kernel):
    implementation = 'Velo'
    implementation_version = '1.0'
    language = 'python'
    language_version = '3.11'
    language_info = {
        'name': 'python',
        'mimetype': 'text/x-python',
        'file_extension': '.py',
    }
    banner = "Velo Kernel - High-Density Python Runtime"

    def do_execute(self, code, silent, store_history=True, 
                   user_expressions=None, allow_stdin=False):
        exec(compile(code, '<cell>', 'exec'), self.user_ns)
        return {'status': 'ok', 'execution_count': self.execution_count}
```

### 3.2 jupyterhub-velo-spawner (Python Package)

```python
# jupyterhub_velo/spawner.py
from jupyterhub.spawner import Spawner

class VeloSpawner(Spawner):
    """Spawner that creates kernels via Velo Zygote COW fork."""
    
    async def start(self):
        socket = await self._connect_to_zygote()
        await socket.send_msgpack({
            'cmd': 'FORK_KERNEL',
            'user': self.user.name,
            'preload': self.preload_modules,
        })
        response = await socket.recv_msgpack()
        return (response['ip'], response['port'])
    
    async def stop(self):
        pass  # Kernel handles cleanup via SIGTERM
```

### 3.3 Zygote Kernel Fork Handler (Rust)

```rust
// src/zygote/jupyter.rs

pub struct JupyterKernelFork {
    user_id: String,
    connection_file: PathBuf,
    zmq_ports: ZmqPorts,
}

impl JupyterKernelFork {
    pub fn spawn(zygote: &ZygoteHandle, request: &KernelRequest) -> Result<Self> {
        let pid = zygote.fork()?;
        
        if pid == 0 {
            Self::child_init(request)?;
        }
        
        Ok(Self { ... })
    }
    
    fn child_init(request: &KernelRequest) -> Result<()> {
        let context = zmq::Context::new();
        let shell = context.socket(zmq::ROUTER)?;
        let iopub = context.socket(zmq::PUB)?;
        
        velo_kernel_main_loop(shell, iopub);
        Ok(())
    }
}
```

### 3.4 kernel.json

```json
{
  "argv": ["velo", "jupyter", "kernel", "--connection-file", "{connection_file}"],
  "display_name": "Velo (Python)",
  "language": "python",
  "metadata": { "debugger": true },
  "env": { "VELO_JUPYTER_MODE": "1" }
}
```

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

| Threat | Mitigation |
|:---|:---|
| **Cross-user data leak** | COW: Write triggers private copy |
| **Resource exhaustion** | cgroups: CPU/memory limits per kernel |
| **Privilege escalation** | namespaces: User namespace per kernel |

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

---

## 10. Open Questions

| Question | Proposed Answer |
|:---|:---|
| **ipywidgets support?** | Phase 2 |
| **Debugger support?** | Phase 3 (low priority) |
| **JupyterLab extensions?** | Compatible (run in browser) |

---

**Last Updated**: 2026-01-21
