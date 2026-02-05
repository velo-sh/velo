import urllib3

# Official usage: Instantiate PoolManager
# This measures the cost of setting up the connection pool infrastructure
# without actually making a network request.
http = urllib3.PoolManager()

print(f"Urllib3 PoolManager created. Version: {urllib3.__version__}")
