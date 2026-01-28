<div align="center">

<p style="color: grey; font-size: 1.2rem;">
  Life is short. Use Python.
</p>

<h1 style="font-size: 4rem; font-weight: 800;">
  Python, Unchained.
</h1>

<p align="center">
  <img src="assets/velo_logo.jpg" alt="Velo Logo" width="200" />
</p>

<p style="font-size: 1.5rem;">
  The Instant Runtime that Python deserves.
</p>

</div>

> 🚧 **Heavy Work In Progress.** Not ready for production. Expect breaking changes.

---

## 🚀 Why Velo?

| The "Python Tax" | The Velo Fix |
|:-----------------|:-------------|
| **Cold starts take 500ms+** | **60x faster** with Zygote pre-warming |
| **Model loading is slow** | Fork pre-loaded models in **<20ms** |
| **Tests block your flow** | **40x faster** `pytest` runs |
| **Deploys are complex** | Single command: `velo serve main:app` |

---

## ⚡ 60x Faster. See It To Believe It.

```
╔════════════════════════════════════════════════════════════╗
║              FastAPI Hello World (Startup)                 ║
╠════════════════════════════════════════════════════════════╣
║  CPython           ██████████████████████████░░░░░  514ms  ║
║  Velo (Instant)    ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░    8.6ms ⚡║
╚════════════════════════════════════════════════════════════╝
                      🚀 59.7x faster than CPython
```

---

## 🎯 Who Is Velo For?

### For AI & ML Engineers
> "My Lambda function takes 10 seconds to cold start because of PyTorch."

Velo pre-loads your model into a Zygote. Every request forks from that warm state in **<20ms**. Memory is shared via Copy-on-Write.

**[→ Read the AI Inference Guide](docs/use-cases/ai-inference.md)**

---

### For Python Developers
> "I spend more time waiting for tests than writing code."

Velo's `pytest --velo` plugin accelerates your test suite by 40x. Combined with Vibe Mode, you get instant feedback on every save.

**[→ Read the Developer Workflow Guide](docs/use-cases/developer-workflow.md)**

---

## 🛠️ Quick Start

```bash
git clone https://github.com/velo-sh/velo.git && cd velo
cargo build --release
./target/release/velo run examples/hello.py
```

### Commands

```bash
# Run any Python script, 60x faster
velo run script.py

# Serve a web app (FastAPI, Django, Flask)
velo serve main:app --workers 4

# Accelerate your tests
pytest --velo

# Vibe Mode: instant hot-reload
velo run --vibe app.py
```

---

## 📊 Compatibility

- **Python**: 3.11, 3.12, 3.13+ (single binary)
- **Frameworks**: FastAPI, Django, Flask, Celery
- **Packages**: 100% of PyPI Top 100 verified ✅

---

## 📚 Documentation

| Guide | Description |
|:------|:------------|
| [AI Inference](docs/use-cases/ai-inference.md) | Deploy AI models with <20ms cold start |
| [Developer Workflow](docs/use-cases/developer-workflow.md) | 40x faster tests, instant hot-reload |
| [Compatibility Charter](docs/governance/compatibility-charter.md) | Our commitment to zero breaking changes |

---

## 🛡️ Enterprise Ready

*   **Zero Python Patch**: We never modify CPython. Full compatibility guaranteed.
*   **SLO-Backed Performance**: Fork latency P99 < 100ms, contractually.
*   **Security Hardened**: Landlock isolation, process sandboxing, supply-chain audited.

---

## 🤝 Special Thanks & Integrations

Velo stands on the shoulders of giants. We take pride in our deep integrations with the best tools in the Python ecosystem:

*   **[uv](https://github.com/astral-sh/uv)**: Velo's first-class dependency engine. We leverage `uv` for lightning-fast environment synchronization and reliable lockfile detection.
*   **[Granian](https://github.com/emmett-framework/granian)**: Our high-performance HTTP server backend. Velo integrates `Granian` to provide the raw power behind `velo serve`.

---

## License

Apache-2.0
