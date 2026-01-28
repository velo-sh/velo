import os

# Check if POLLUTED env var exists (it shouldn't)
val = os.environ.get("POLLUTED_ENV")
print(f"FOO is {val}")

# Set it (should not leak to next run)
os.environ["POLLUTED_ENV"] = "DIRTY"
