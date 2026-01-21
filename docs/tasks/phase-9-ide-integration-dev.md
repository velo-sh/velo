# Phase 9: IDE Integration - Developer Task List

**RFC**: [RFC-0030](../rfcs/0030-jupyter-integration.md)
**Branch**: `phase-9/ide-integration`
**Estimated Duration**: 10 days

---

## Phase 1: Jupyter Kernel MVP (3 days)

### Day 1: kernel.json + CLI

- [ ] Implement `velo jupyter install` command
  - [ ] Use embedded uv to sync ipykernel dependency
  - [ ] Write kernel.json to `~/.local/share/jupyter/kernels/velo/`
  - [ ] Support `--sys-prefix` and `--preload` flags
- [ ] Test: `jupyter kernelspec list` shows "velo"

### Day 2: Zygote Integration

- [ ] Implement `velo run -m ipykernel_launcher -f {file}` path
- [ ] Ensure signal forwarding (SIGINT/SIGTERM/SIGHUP) to child
- [ ] Implement FD cleanup with allow-list approach
- [ ] Test: Jupyter can start Velo kernel

### Day 3: Connection File Handling

- [ ] Ensure forked child can read `/tmp/kernel-xxx.json`
- [ ] Implement namespace bind mount if needed
- [ ] Test: Full Jupyter notebook execution

---

## Phase 2: JupyterHub Spawner (2 days)

### Day 4: VeloSpawner

- [ ] Create `jupyterhub-velo-spawner` Python package
- [ ] Implement `VeloSpawner(LocalProcessSpawner)`
- [ ] Test: JupyterHub spawns Velo kernels

### Day 5: Preload Configuration

- [ ] Implement `.velo/jupyter.toml` preload config
- [ ] Support per-user preload profiles
- [ ] Test: Preloaded libraries are in Zygote

---

## Phase 3: High-Density Mode (2 days)

### Day 6: Memory Benchmark

- [ ] Implement `test_100_kernels_memory` benchmark
- [ ] Verify 20x memory reduction (100 kernels < 5GB)
- [ ] Document actual numbers

### Day 7: Startup Latency

- [ ] Implement `test_kernel_startup_latency`
- [ ] Verify <100ms startup time
- [ ] Profile and optimize if needed

---

## Phase 4: VS Code Integration (1 day)

### Day 8: Configuration Files

- [ ] Create example `.vscode/launch.json`
- [ ] Create example `.vscode/tasks.json`
- [ ] Test: VS Code can run Python via Velo
- [ ] Document in README

---

## Phase 5: Security Hardening (2 days)

### Day 9: Isolation

- [ ] Implement per-kernel TMPDIR
- [ ] Implement per-user socket paths
- [ ] Implement cgroups limits (CPU=1, Memory=2GB)

### Day 10: Namespace Isolation

- [ ] Implement user namespace per kernel (if needed)
- [ ] Security audit
- [ ] Final integration test

---

## P0 Engineering Notes (Must Read)

> [!WARNING]
> See RFC-0030 Section 9.1 for critical implementation details:
> - Signal Propagation
> - Connection File Permissions
> - FD Leak Prevention (allow-list approach)

---

**Last Updated**: 2026-01-21
