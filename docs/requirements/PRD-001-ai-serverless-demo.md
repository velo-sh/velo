# PRD-001: Velo AI Serverless Demo (Original Requirements Spec)

> **Status**: APPROVED (User Provided)
> **Author**: Product Owner
> **Date**: 2026-01-06
> **Mission**: "Make you realize that Python cold start pain was never necessary."

---

## Goal (5 minutes)

Make you realize that Python cold start pain was never necessary.

---

## 0. Requirements (30 seconds)

- macOS / Linux
- Python 3.10+
- curl
- **No Docker knowledge required.**
- **No cloud account required.**

---

## 1. Clone & Enter (15 seconds)

```bash
git clone https://github.com/velo-sh/velo-demo-ai.git
cd velo-demo-ai
```

---

## 2. Baseline: Run plain Python (1 minute)

> This is what most AI services run today.

```bash
./run-python.sh
```

**Expected output:**
```
Starting Python server...
Startup time: 2.31s
Server ready at http://localhost:8000
```

Now hit the endpoint:
```bash
curl http://localhost:8000/embedding
```
```
First request latency: 2.48s
```

**Pause. This is your cold start.**

---

## 3. Stop it. Run Velo. (30 seconds)

```bash
./run-velo.sh
```

**Expected output:**
```
Starting Velo runtime...
Startup time: 87ms
Server ready at http://localhost:8000
```

Now hit the same endpoint:
```bash
curl http://localhost:8000/embedding
```
```
First request latency: 91ms
```

**Same code. Same machine. No warm cache.**

---

## 4. Kill it. Restart it. (30 seconds)

```bash
Ctrl + C
./run-velo.sh
```
```
Startup time: 89ms
```

Call again:
```
First request latency: 94ms
```

**This is not a demo trick. This is a different runtime shape.**

---

## 5. What just happened? (30 seconds)

You did **NOT**:
- Add async code
- Rewrite in Rust
- Pre-warm containers
- Use background workers

You **only** changed how Python is loaded.

---

## 6. Why this matters in production (1 minute)

| Scenario | Plain Python | Velo |
| :--- | :--- | :--- |
| Lambda scale from 0 | seconds | milliseconds |
| 100 replicas | 100x memory | 1x shared |
| Model init cost | Paid every time | Paid once |

**This is why Python AI on serverless never made sense - until now.**

---

## 7. Look at the code (optional)

Open `app.py`:
```python
from model import embed

def handler():
    return embed("hello world")
```

That's it.

---

## 8. Your takeaway (10 seconds)

> If this were Python's default runtime, how much infra complexity would disappear?

---

## Implementation Files Required

### `run-python.sh`
```bash
#!/usr/bin/env bash
echo "Starting Python server..."
START=$(date +%s%3N)
python app.py &
PID=$!
sleep 1
END=$(date +%s%3N)
echo "Startup time: $((END-START))ms"
wait $PID
```

### `run-velo.sh`
```bash
#!/usr/bin/env bash
echo "Starting Velo runtime..."
START=$(date +%s%3N)
velo run app.py &
PID=$!
sleep 0.1
END=$(date +%s%3N)
echo "Startup time: $((END-START))ms"
wait $PID
```

### `model.py` (Intentionally slow)
```python
import time
time.sleep(0.3)

def embed(text):
    return {"vector": [0.1, 0.2, 0.3]}
```

---

## Demo Internals (hidden, but honest)

- We intentionally simulate native extension init cost.
- No request caching.
- No warm pools.
- **No cheats.**

---

## Next Steps

1. Read the architecture -> [ai_serverless_execution_blueprint.md](../strategy/ai_serverless_execution_blueprint.md)
2. Try your own model
3. Join early access
