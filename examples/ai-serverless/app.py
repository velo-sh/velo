import os
import time
from model import embed

# Heavy native init handled in model.py

def handler(event, context):
    start_time = time.time()
    text = event.get("text", "hello velo")
    result = embed(text)
    
    return {
        "status": "success",
        "latency_ms": int((time.time() - start_time) * 1000),
        "data": result
    }

if __name__ == "__main__":
    # Local test
    print(handler({"text": "test prompt"}, None))
