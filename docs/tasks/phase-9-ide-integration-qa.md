# Phase 9: IDE Integration - QA Task List

**RFC**: [RFC-0030](../rfcs/0030-jupyter-integration.md)
**Branch**: `phase-9/ide-integration`

---

## Quality Gates (from RFC-0030)

| Gate | Requirement | Test File |
|:---|:---|:---|
| **Gate A** | Jupyter Messaging Protocol compliant | `test_jmp_compliance.py` |
| **Gate B** | ipykernel feature parity | `test_feature_parity.py` |
| **Gate C** | 100 kernels in <5GB memory | `test_100_kernels_memory.py` |
| **Gate D** | Kernel startup <100ms | `test_startup_latency.py` |
| **Gate E** | JupyterHub spawner works | `test_jupyterhub_e2e.py` |

---

## Test Cases

### Tier 0: Smoke Tests

- [ ] `test_jupyter_kernelspec_list` - Velo kernel appears in list
- [ ] `test_jupyter_kernel_start` - Kernel starts without error
- [ ] `test_jupyter_cell_execute` - Basic cell execution works

### Tier 1: Functional Tests

- [ ] `test_magic_commands` - `%timeit`, `%matplotlib` work
- [ ] `test_shell_escape` - `!ls`, `!pip` work
- [ ] `test_rich_display` - Plots render correctly
- [ ] `test_tab_completion` - Tab completion works
- [ ] `test_shift_tab_docs` - Shift+Tab shows docs
- [ ] `test_ipywidgets` - Basic widget works
- [ ] `test_debugger` - Debugger can pause execution

### Tier 2: Performance Tests

- [ ] `test_kernel_startup_latency` - <100ms startup
- [ ] `test_cell_overhead` - <5ms overhead per cell
- [ ] `test_memory_delta` - <30MB per kernel
- [ ] `test_100_kernels_memory` - 100 kernels < 5GB total

### Tier 3: Security Tests

- [ ] `test_cross_user_isolation` - User A cannot see User B data
- [ ] `test_tmpdir_isolation` - Each kernel has separate TMPDIR
- [ ] `test_socket_permissions` - Socket only accessible by owner
- [ ] `test_cgroup_limits` - Resource limits enforced

### Tier 4: Adversarial Tests

- [ ] `test_signal_stop_loop` - SIGINT stops infinite loop
- [ ] `test_fd_leak` - No FD leak after 100 restarts
- [ ] `test_zombie_reaping` - No zombie processes

### Tier 5: JupyterHub Integration

- [ ] `test_jupyterhub_spawn` - VeloSpawner works
- [ ] `test_jupyterhub_multi_user` - 10 users concurrent
- [ ] `test_jupyterhub_restart` - Kernel restart works

### Tier 6: VS Code Integration

- [ ] `test_vscode_run` - `velo run` works from VS Code
- [ ] `test_vscode_debug` - Debug configuration works

---

## Bug Template

```markdown
## DEF-09-XXX: [Title]

**Severity**: P0/P1/P2
**Component**: Jupyter/JupyterHub/VS Code
**Found In**: Phase 9 / Gate X

### Description
[What happened]

### Steps to Reproduce
1. ...
2. ...

### Expected Behavior
[What should happen]

### Actual Behavior
[What actually happened]

### Evidence
[Logs, screenshots]
```

---

**Last Updated**: 2026-01-21
