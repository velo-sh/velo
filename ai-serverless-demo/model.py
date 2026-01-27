"""
Model module - Simulates heavy AI model initialization.

We intentionally use time.sleep() to simulate the cost of loading
native extensions (NumPy, PyTorch, Transformers) without requiring
actual dependencies. This keeps the demo lightweight and reproducible.
"""

import os
import time

# Simulate native extension / model weight loading cost
# Real-world: torch import ~500ms, transformers ~1s, model.load() ~2s+
SIMULATED_INIT_COST_S = float(os.environ.get("MODEL_INIT_COST", "0.8"))
print(f"[model.py] Simulating model initialization ({SIMULATED_INIT_COST_S}s)...")
time.sleep(SIMULATED_INIT_COST_S)
print("[model.py] Model ready.")


def embed(texts: list[str]) -> list[list[float]]:
    """
    Simulate embedding generation.
    Returns dummy vectors for demo purposes.
    """
    # In production: return model.encode(texts).tolist()
    return [[0.1 * len(t), 0.2, 0.3] for t in texts]
