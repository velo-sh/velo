# Velo User Manual (TITANIUM Grade)

> **Audience**: Application Developers / DevOps
> **Status**: **IMMUTABLE**

## 1. Core Concepts

### The Supervisor Model
Velo is not just a runner; it is a **Supervisor**. It owns the process lifecycle.
*   **Don't**: Run `python main.py`.
*   **Do**: Run `velo serve main:app`.

### The Zygote (Pre-Warming)
Velo uses a "Zygote" process to pre-load your application code.
*   **Benefit**: <50ms restart times.
*   **Constraint**: Your initialization code must be "Fork-Safe" (no open DB connections in global scope).

## 2. Configuration (`pyproject.toml`)

Velo is configured via `[tool.velo]`.

```toml
[tool.velo]
# Project Identity (Mandatory)
project_name = "my_app"

# Zygote Tunables
preload_modules = ["django", "numpy"]
memory_limit_mb = 512

# Watcher
debounce_ms = 300
```

## 3. Production Deployment

### Docker Integration
Velo assumes PID 1 responsibilities.
```dockerfile
CMD ["velo", "serve", "main:app", "--host", "0.0.0.0"]
```

### Signal Handling
Velo intercepts `SIGTERM` and performs a graceful shutdown of all workers within 10s.

---

**Last Updated**: 2026-01-06
