# Velo AI Serverless Demo

> Feel Python cold-start pain — then watch it disappear.

This demo shows how **Velo** fundamentally changes how Python AI services run.

Same Python code.
Same workload.
Three runtimes.
Radically different behavior.

---

## What This Demo Proves (In 5 Minutes)

If you’ve built AI services in Python, you already know:
- Cold starts take seconds
- Memory usage explodes
- Scaling hurts
- Docker often makes things worse

This demo lets you experience the difference, not just read about it.

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/velo-sh/velo
cd velo/ai-serverless-demo
```

### 2. Run the full comparison

```bash
bash scripts/measure.sh
```

That's it.

---

## What You Will See

The script runs the same application three times:

1. Baseline Python
2. Dockerized Python
3. Velo Runtime

Each run prints:
- Cold-start time (ms)
- RSS memory usage

### Example Output (varies by machine)

| Mode   | Cold Start | Memory |
|-------|-----------|--------|
| Python | ~1500 ms | ~200 MB |
| Docker | ~2000 ms | ~200 MB |
| Velo | ~80 ms | ~60 MB |

---

## Why This Matters

Python does not have to be slow.

Velo removes:
- redundant filesystem scanning
- repeated native extension loading
- container overhead

This is what Python should feel like in the AI era.

---

## Learn More

- [Velo Repository](https://github.com/velo-sh/velo)

> Python is perfect for coding.
> Velo is perfect for running.
