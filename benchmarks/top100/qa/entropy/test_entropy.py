import uuid
import sys

# Generate UUID. In a forked environment without reseed, this might repeat.
# However, Python's uuid module usually handles fork (using usage counters or urandom).
# But checking it explicitly is good. The runner should run this multiple times (runs=3)
# and we can visually verify or programmically verify if we collected results.
# For single run, we just check it generates *something*.
u = uuid.uuid4()
print(f"UUID: {u}")
