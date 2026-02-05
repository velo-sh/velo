import requests

# Just verify import and version to confirm environment health
# without relying on external network (which might be flaky or blocked)
print(f"Requests version: {requests.__version__}")
print("Done")
