# Velo

> **Python is perfect for coding.  
> Velo is perfect for running.**

Velo is a **high-performance runtime for the AI era**.  
It preserves the Python ecosystem you already use, while fundamentally rethinking how Python applications *start*, *scale*, and *consume memory* in production.

Velo is not a framework.  ```bash
git clone https://github.com/velo-sh/velo.git && cd velo
cargo build --release
./target/release/velo run examples/hello.py
```

## Benchmark Results

![Velo Benchmark](./assets/benchmark_v3.png)

### 🧬 Velo Instant Mode (v0.6.0) - **60x Faster!**

```
╔══════════════════════════════════════════════════════════╗
║              FastAPI Hello World (Startup)               ║
╠══════════════════════════════════════════════════════════╣
║  CPython           ██████████████████████████░░░░  514ms ║
║  Velo (Cold)       █░░░░░░░░░░░░░░░░░░░░░░░░░░░░   17.7ms║
║  Velo (Instant)    ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░    8.6ms⚡║
╚══════════════════════════════════════════════════════════╝
                     🚀 59.7x faster than CPython
```

### Warm Start Benchmarks

| Project | CPython | Velo (Instant) | Speedup |
|---------|---------|---------------|---------|
| **Simple Script** | 22ms | **8.6ms** | **2.5x** 🔥 |
| **Heavy Imports** | 514ms | **8.8ms** | **58.4x** 🔥 |
| **FastAPI** | 606ms | **15ms** | **40.4x** 🔥 |

> **Note**: Speedups come from preloading dependencies (pydantic, django, numpy, etc.) into the **Velo background runner**.

## See It in Action (HIO Program 🚀)

**Velo High-Inertia Optimization (HIO)** 专门狩猎“三巨头”，展示 Python 性能在重型初始化场景下的飞跃。

### 🎯 [Django (The Heavyweight)](./examples/django-heavy/README.md)
解决了 Django 测试中 App Registry 加载和 DB Setup 慢的问题。**利用 COW 共享内存，加速测试循环。**

### 🎯 [LangChain / LlamaIndex (The AI Glue)](./examples/langchain-fast/README.md)
消灭 AI 开发中的 `import` 等待。**Zygote 预加载重型 AI 库，启动即运行。**

### 🎯 [FastAPI + SQLAlchemy (Modern Stack)](./examples/fastapi-instant/README.md)
演示“瞬时回滚”。**利用进程销毁实现状态重置，无需繁琐的数据库清理。**

---

👉 **[AI Serverless Demo](./examples/ai-serverless/README.md)**  
感受冷启动从秒级缩短到毫秒级的震撼体验。

---

## Why Velo Exists

Python won the AI ecosystem — but its runtime model did not evolve with it.

Today’s Python production stack suffers from:

- Slow cold starts (seconds, not milliseconds)
- Massive memory duplication across processes
- Heavy Docker images and poor density
- Serverless platforms that punish Python workloads

These problems are not caused by Python *code*.  
They are caused by Python’s **runtime assumptions**.

Velo fixes that.

---

## What Velo Does (In One Sentence)

**Velo turns Python into a serverless- and AI-native runtime by eliminating redundant startup work and enabling OS-level memory sharing.**

---

## Core Capabilities

### ⚡ Sub-millisecond Startup
- Environment fingerprinting
- Cached import graphs
- Zero redundant filesystem scans

### 🧠 Memory Sharing by Design
- Zygote-based process model
- Copy-on-write memory semantics
- One model loaded, many instances served

### 📦 Industrial Delivery
- Single-binary packaging (roadmap)
- Zero-extraction execution
- Source sealing for commercial distribution

### ☁️ Serverless-First Architecture
- Designed for scale-to-zero
- Optimized for high fan-out AI inference
- No Docker required

---

## See It in Action (5 Minutes)

The fastest way to understand Velo is to *feel* the difference.

👉 **AI Serverless Demo**

This demo runs the same Python AI service in three modes:

1. Baseline Python  
2. Dockerized Python  
3. Velo Runtime  

You will see:
- Cold-start latency collapse from seconds to milliseconds
- Memory usage drop dramatically
- Why Python does not have to behave this way

➡️ [**ai-serverless-demo/README.md**](./ai-serverless-demo/README.md)

---

## Architecture Overview

Velo works *with* CPython, not against it.

- Rust-based host runtime
- Full CPython C-API compatibility
- Zero changes to user code
- Progressive enhancement from tooling → runtime → cloud

Think of Velo as:
> **The Bun of Python — evolving toward the Vercel of AI.**

---

## Who Is This For?

- AI teams deploying Python inference services
- Companies struggling with Python cold starts
- Engineers hitting memory limits with model-heavy workloads
- Anyone who loves Python but hates its runtime behavior in production

---

## Project Status

Velo is under active development.

Current focus:
- AI serverless runtime
- Memory sharing primitives
- Fast loader infrastructure

The project follows a staged roadmap from tooling to full cloud runtime.

---

## Roadmap (High Level)

- Phase 6.x — Fast loader & runtime primitives
- Phase 7.x — AI serverless runtime
- Phase 8.x — Single-binary packaging & hybrid engine
- Phase 9.x — Velo Cloud (Python AI serverless platform)

---

## Get Involved

- ⭐ Star the repo if this resonates
- 🧪 Try the AI Serverless Demo
- 💬 Open issues for real production pain
- 🤝 Reach out if you’re building serious AI infrastructure

---

> **Python won AI.  
> Velo makes it production-grade.**
