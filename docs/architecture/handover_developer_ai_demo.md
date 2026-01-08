# Handover: Developer (Phase 7.1 - AI Serverless Demo)

> **Mission**: Set up the local AI Serverless Demo environment as defined by the marketing narrative.
> **Role**: Developer (ID-LOCK-002)
> **SOP**: [SOP-001-master-lifecycle.md](../../docs/architecture/SOP-001-master-lifecycle.md)

## 1. Deliverables

Create a new directory `demo/ai-serverless/` and populate it with the following files:

### 1.1 `demo/ai-serverless/model.py`
```python
import time
# Simulating the cost of loading heavy native extensions/tensors
time.sleep(0.3)

def embed(text):
    return {"vector": [0.1, 0.2, 0.3]}
```

### 1.2 `demo/ai-serverless/app.py`
```python
from model import embed

def handler():
    return embed("hello world")

if __name__ == "__main__":
    import json
    print(json.dumps(handler()))
```

### 1.3 `demo/ai-serverless/run-python.sh`
```bash
#!/usr/bin/env bash
echo "🐍 Starting Python server..."
START=$(date +%s%3N)
# Simulating a server startup or single invocation
python3 app.py &
PID=$!
sleep 1
END=$(date +%s%3N)
echo "⏱ Startup time: $((END-START))ms"
kill $PID
```

### 1.4 `demo/ai-serverless/run-velo.sh`
```bash
#!/usr/bin/env bash
echo "⚡ Starting Velo runtime..."
# Use the local build of velo
VELO_BIN="../../target/debug/velo"
START=$(date +%s%3N)
$VELO_BIN run app.py &
PID=$!
sleep 0.1
END=$(date +%s%3N)
echo "⏱ Startup time: $((END-START))ms"
kill $PID
```

## 2. Invariants
1. **No Cheats**: Do not use caches or pre-warmed pools.
2. **Path Integrity**: Ensure scripts are executable (`chmod +x`).

## 3. Verification
- Running `./run-velo.sh` should show a startup time significantly lower (<150ms) than `./run-python.sh` (>1000ms).
