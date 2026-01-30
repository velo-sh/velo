import os
import time

# Simulation/Reality Toggle
USE_REAL_LIBS = os.environ.get("VELO_REAL_AI", "0") == "1"

if USE_REAL_LIBS:
    try:
        print("[model.py] Loading real AI libraries (torch, numpy)...")
        # import numpy as np
        # import torch
        model_ready = True
    except ImportError:
        print("[model.py] Real libraries not found, falling back to simulation.")
        USE_REAL_LIBS = False

if not USE_REAL_LIBS:
    # Simulate native extension / model weight loading cost
    # Real-world: torch import ~500ms, transformers ~1s, model.load() ~2s+
    SIMULATED_INIT_COST_S = float(os.environ.get("MODEL_INIT_COST", "0.8"))
    print(f"[model.py] Simulating model initialization ({SIMULATED_INIT_COST_S}s)...")
    time.sleep(SIMULATED_INIT_COST_S)
    print("[model.py] Simulation ready.")


def embed(texts: list[str]) -> list[list[float]]:
    """
    Simulate or execute embedding generation.
    """
    if USE_REAL_LIBS:
        # In a real demo, we'd use a small model like 'all-MiniLM-L6-v2'
        # For simplicity, we just use numpy to show it's loaded
        import numpy as np
        return [[float(x) for x in np.random.rand(3)] for _ in texts]

    # Fallback to dummy vectors
    return [[0.1 * len(t), 0.2, 0.3] for t in texts]
