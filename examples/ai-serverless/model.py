import time
import os

# Emulate heavy initialization (e.g., model weights loading)
# We perform actual CPU work to demonstrate Zygote's ability to save computational resources.
# In Velo mode, this CPU cost is paid ONCE by the Zygote, then shared via CoW.
import hashlib
for _ in range(500000):
   _ = hashlib.sha256(b"loading_weights_simulation").hexdigest()

def embed(text):
    return {
        "vector": [0.1, 0.2, 0.3],
        "debug": {
            "pid": os.getpid(), 
            "addr": hex(id(text)),
            "velo_mode": os.environ.get("VELO_MODE", "false")
        }
    }
