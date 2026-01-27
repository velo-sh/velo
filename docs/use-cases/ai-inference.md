# Velo for AI Inference

> **Deploy AI models with <20ms cold start. Run 100 workers with the memory cost of 1.**

---

## The Problem

AI inference in serverless environments suffers from catastrophic cold starts:

| Scenario | Traditional Cold Start | With Velo |
|:---------|:----------------------|:----------|
| PyTorch import | ~3,000ms | **<50ms** |
| Hugging Face Transformers | ~5,000ms | **<80ms** |
| Load 7B LLM | ~15,000ms | **<200ms** (pre-warmed) |

---

## The Velo Solution: Zygote Pre-Warming

```
┌─────────────────────────────┐
│     Zygote (Pre-Warmed)     │
│  - Python VM initialized    │
│  - torch loaded             │
│  - model.pth in GPU memory  │
└──────────────┬──────────────┘
               │ fork() <20ms
    ┌──────────┼──────────┐
    ▼          ▼          ▼
 Worker 1   Worker 2   Worker 3
```

*   **Copy-on-Write Memory**: Workers share the parent's memory pages.
*   **Instant Fork**: The `fork()` syscall is microseconds.

---

## Quick Start

```bash
# Start the Zygote Daemon
velo zygote start

# Serve Your Model
velo serve main:app --workers 4
```

---

## Benchmarks

| Runtime | PyTorch Cold Start | Memory (8 workers) |
|:--------|:-------------------|:-------------------|
| Native Python | 3,200ms | 16 GB |
| Docker | 4,500ms | 18 GB |
| **Velo** | **48ms** | **2.5 GB** ⚡ |
