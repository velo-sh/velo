# Handover: Developer (Phase 7.1 - AI Serverless Demo)

> **Mission**: Deliver the **Sensory Shock** of Velo performance.
> **Role**: Developer (ID-LOCK-002)
> **SOP**: [SOP-001-master-lifecycle.md](../../docs/architecture/SOP-001-master-lifecycle.md)

## 1. The Strategy: "Instant AI"
The goal is to prove that Python cold start is an architectural choice, not a language limitation.

### 1.1 Mandatory Deliverables
Create the `demo/ai-serverless/` directory with the following **Brand-Aligned** files:

#### `model.py` (The Weight Simulation)
Must simulate the 0.3s delay of a native model initialization. In "Velo mode", this init cost should be eliminated via Zygote pre-warming.
```python
import time
import os

# ARCHITECT'S MANDATE: 
# Simulation of heavy native init. Must sleep for 300ms in baseline.
time.sleep(0.3)

def embed(text):
    return {
        "vector": [0.1, 0.2, 0.3],
        "debug": {"pid": os.getpid(), "addr": hex(id(text))}
    }
```

#### `app.py` (The Handler)
A simple JSON API that returns the embedding and the memory address (Proof of Zero-Copy).

#### `run-python.sh` & `run-velo.sh`
Benchmark scripts that measure the time from **invoking the binary** to the **first response**. 
- **P0 Requirement**: Velo startup MUST be < 100ms.
- **P0 Requirement**: Output must calculate the "Velo Advantage" (X times faster).

## 2. TITANIUM Invariants (The Red Lines)
1. **H-26 (PID Namespace)**: `run-velo.sh` must verify all spawned workers share the Host's PID namespace via `ps -o ppid`.
2. **H-34 (Density Proof)**: You must provide a `verify-density.py` script that proves 10 concurrent requests use < 1.1x total RSS memory vs a single request.
3. **No Cheats**: No pre-warmed container pools or external caching. Validates the **Runtime Shape** only.

## 3. Verification Criteria
- [ ] `./run-python.sh` cold start > 2.0s.
- [ ] `./run-velo.sh` cold start < 100ms.
- [ ] `verify-density.py` shows flat-line memory scaling.
- [ ] Output uses ANSI colors for the "Wow" effect.
