# Quick Start Guide (TITANIUM Edition)

> **Goal**: From Zero to TITANIUM in 5 Minutes.

## 1. Installation

```bash
# Install via Cargo (Recommended)
cargo install velo
```

## 2. The "Hello World" (FastAPI)

```python
# main.py
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "Velo"}
```

## 3. Running with Velo

```bash
# Dev Mode (Hot Reload + Zygote)
velo serve main:app

# Prod Mode (Stripped)
velo serve main:app --release
```

## 4. Troubleshooting (The Prosecutor)

If Velo refuses to start, it is likely protecting you.

*   **Error**: `InsecureLocation` -> You are running in `/tmp`. Move to a secure dir.
*   **Error**: `SocketCollision` -> Another project is running. Use `velo info` to see active sockets.
*   **Error**: `HashMismatch` -> Your `pyproject.toml` changed. Restart Velo.

---

**Last Updated**: 2026-01-06
