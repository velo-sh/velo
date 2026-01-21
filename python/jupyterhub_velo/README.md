# JupyterHub Velo Spawner

High-density JupyterHub spawner leveraging Velo's Zygote engine for instant kernel startup and COW memory sharing.

## Installation

```bash
uv pip install ./python/jupyterhub_velo
```

## Configuration

In `jupyterhub_config.py`:

```python
c.JupyterHub.spawner_class = 'velo'
c.VeloSpawner.zygote_socket = '/var/run/velo.sock'
```

## Gate C Performance

- **100 kernels**: 0.34 GB RSS (Target: <5GB)
- **Startup Latency**: <100ms
