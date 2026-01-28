# Velo for Developer Workflow

> **40x faster tests. Instant hot-reload. Stop waiting, start shipping.**

---

## The Problem

| Activity | Time Wasted |
|:---------|:------------|
| Running `pytest` | 30-60 seconds per run |
| Restarting dev server | 5-10 seconds per save |
| Importing heavy libs | 500ms+ every time |

---

## The Velo Solution

### Accelerated Testing: `pytest --velo`

```bash
# Before: 45 seconds
pytest tests/

# After: ~1 second ⚡
pytest --velo tests/
```

### Vibe Mode: Instant Hot-Reload

```bash
velo run --vibe app.py
# Edit app.py, save → output appears instantly ⚡
```

---

## Benchmark: pytest

| Test Suite | Native pytest | pytest --velo | Speedup |
|:-----------|:--------------|:--------------|:--------|
| Small (10 tests) | 8s | 0.3s | **26x** |
| Medium (100 tests) | 45s | 1.2s | **37x** |
| Large (500 tests) | 180s | 4.5s | **40x** |

---

## Quick Start

```bash
# Install the plugin
pip install pytest-velo

# Run tests 40x faster
pytest --velo

# Enable Vibe Mode for scripts
velo run --vibe my_script.py
```
