import sys
import time
import importlib

# Ensure we measure a fresh import
if "requests" in sys.modules:
    del sys.modules["requests"]

t0 = time.perf_counter()
requests = importlib.import_module("requests")
t1 = time.perf_counter()

print(f"Requests version: {requests.__version__}")
print(f"Is requests in sys.modules? {'requests' in sys.modules}")
if "requests" in sys.modules:
    print(f"Requests module object: {sys.modules['requests']}")
    print(f"Requests file: {getattr(sys.modules['requests'], '__file__', 'N/A')}")

print(f"Import time: {(t1-t0)*1000:.2f}ms")
