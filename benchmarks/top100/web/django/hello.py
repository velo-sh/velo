import sys
import os
print(f"Executable: {sys.executable}")
print(f"Prefix: {sys.prefix}")
print(f"Path: {sys.path}")
try:
    import django
    print(f"Django: {django.__version__}")
except ImportError as e:
    print(f"ImportError: {e}")
    sys.exit(1)