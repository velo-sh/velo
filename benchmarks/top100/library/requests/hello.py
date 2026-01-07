import sys
import time
import requests

print(f"Requests version: {requests.__version__}")
print(f"Is requests in sys.modules? {'requests' in sys.modules}")
if 'requests' in sys.modules:
    print(f"Requests module object: {sys.modules['requests']}")
    print(f"Requests file: {getattr(sys.modules['requests'], '__file__', 'N/A')}")

t0 = time.perf_counter()
import requests
t1 = time.perf_counter()
print(f"Import time: {(t1-t0)*1000:.2f}ms")
