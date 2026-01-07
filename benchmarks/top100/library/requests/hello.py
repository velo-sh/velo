import requests
import sys

# Official usage: Import and check version
# We explicitly avoid making network requests (requests.get) to keep it a startup benchmark.
print(f"Requests version: {requests.__version__}")
