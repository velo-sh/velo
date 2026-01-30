import time

from pydantic import BaseModel

# Generate heavy Import
print("[HIO] Loading heavy library imports...")
start = time.perf_counter()


# Generate Pydantic v2 model metadata mass production


class HeavyMetadata(BaseModel):
    name: str
    index: int
    data: dict


print("[HIO] Schema Locking: Generating 100 virtual schemas...")
models = [HeavyMetadata(name=f"Model{i}", index=i, data={"key": "val"}) for i in range(100)]

end = time.perf_counter()
print(f"[HIO] Execution Ready in {(end - start) * 1000:.2f}ms")
