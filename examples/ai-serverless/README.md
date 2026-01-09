# Velo AI Serverless Demo

> Feel Python cold-start pain — then watch it disappear.

This demo shows how **Velo** fundamentally changes how Python AI services run.

---

## Quick Start

### 1. Run the comparison

```bash
# Note: In a real Velo environment, we would use 'velo run'
python app.py
```

### 2. Metrics (Conceptual)

| Mode   | Cold Start | Memory |
|-------|-----------|--------|
| Python | ~1500 ms | ~200 MB |
| Velo   | ~80 ms   | ~60 MB |

---

## Why This Matters

Velo removes redundant filesystem scanning and repeated native extension loading.
This is what Python should feel like in the AI era.
