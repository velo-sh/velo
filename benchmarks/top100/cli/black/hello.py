import sys
from black import patched_main
import re

# Workaround for Velo missing feature: cannot pass args to script
# We emulate the official bin/black entry point logic but hardcode args.

if __name__ == "__main__":
    # Simulate "black --version"
    sys.argv = ["black", "--version"]
    try:
        patched_main()
    except SystemExit:
        pass
