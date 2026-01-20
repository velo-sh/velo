# Velo Examples & High-Inertia Optimization (HIO)

The **High-Inertia Optimization (HIO)** program targets the "Big Three" performance bottlenecks in modern Python production stacks: heavy frameworks, deep validation schemas, and database initialization.

> These examples prioritize **reproducibility and architectural clarity**
> over full production dependency stacks.
> Real-world variants are provided separately for advanced validation.

## 🚀 The HIO Benchmark Suite

| ID | Project | Bottleneck Solved | Velo Speedup |
| :--- | :--- | :--- | :--- |
| **HIO-001** | **[Django Heavyweight](./django-heavy)** | App Registry & DB Setup | **~600x** (0.6s → <1ms) |
| **HIO-002** | **[LangChain Fast-path](./langchain-fast)** | Schema Gen & Imports | **~16x** (1.17s → 0.07s) |
| **HIO-003** | **[FastAPI Instant](./fastapi-instant)** | Test State Rollback | **~16x** (5s → 0.31s) |
| **HIO-004** | **[Serverless Instant](./serverless-instant)** | Cold Start Latency | **~450x** (0.45s → <1ms) |
| **HIO-005** | **[CLI Accelerator](./cli-fast)** | TTFL (Time To First Logic) | **~40x** (0.04s → <1ms) |

---

## 📂 Demo Overviews

### 1. [Django Heavyweight (HIO-001)](./django-heavy)
**The Problem:** Django's `setup()` is notoriously slow, scanning every installed app and model before running a single test.
**The Fix:** Velo initializes the App Registry *once* in the Zygote. Workers fork from this "ready" state, bypassing the scan entirely.
- **Key Tech:** Copy-on-Write (CoW) memory sharing for model definitions.

### 2. [LangChain / Pydantic (HIO-002)](./langchain-fast)
**The Problem:** Modern AI stacks spend seconds generating complex Pydantic v2 schemas and importing heavy libraries like `numpy` or `transformers`.
**The Fix:** Pre-warm the validation graph in the parent process. Workers wake up with all schemas compiled and ready.
- **Key Tech:** Zero-overhead simulation of heavy imports.

### 3. [FastAPI "Instant" (HIO-003)](./fastapi-instant)
**The Problem:** Integration tests usually require slow `TRUNCATE` operations or transaction rollbacks to clean the database between runs.
**The Fix:** Use process destruction as the rollback mechanism. Each test runs in a fresh fork; when it dies, the state "snaps back" instantly.
- **Key Tech:** Kernel-level state reset via `fork()`.

### 4. [Serverless Instant (HIO-004)](./serverless-instant)
**The Problem:** Python serverless functions pay full interpreter and import costs on every cold start.
**The Fix:** Velo's Zygote pre-warms the runtime once. Workers fork instantly, bypassing interpreter and import overhead.
- **Key Tech:** fork() + Copy-On-Write memory sharing.

### 5. [CLI Accelerator (HIO-005)](./cli-fast)
**The Problem:** Python CLI tools (like `pip`, `uv`, `aws-cli`) pay a heavy "import tax" on every invocation, making short commands feel sluggish.
**The Fix:** Velo's Zygote pre-loads the interpreter and heavy dependencies. CLI commands fork instantly with near-zero startup latency (TTFL < 1ms).
- **Key Tech:** Zygote pre-warming + instant fork for CLI responsiveness.

---

## 🏃‍♂️ How to Run

### Prerequisites

Install [uv](https://github.com/astral-sh/uv) package manager:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or via Homebrew (macOS)
brew install uv
```

### Run Any Demo

All demos support a standardized CLI for comparison:

```bash
# General Syntax
./examples/<demo-name>/run_hio.sh --compare --runs=20
```

**Examples:**
```bash
# HIO-001: Django startup speedup
./examples/django-heavy/run_hio.sh --compare --runs=20

# HIO-002: Pydantic schema generation
./examples/langchain-fast/run_hio.sh --compare --runs=20

# HIO-003: FastAPI environment reset
./examples/fastapi-instant/run_hio.sh --compare --resets=20

# HIO-004: Serverless cold start
./examples/serverless-instant/run_hio.sh --compare --runs=20

# HIO-005: CLI accelerator (recommended first!)
./examples/cli-fast/run_hio.sh --compare --runs=20
```
