"""
HIO-004 Serverless Handler

Minimal handler focusing on import cost only.
No business logic, no I/O - pure import overhead measurement.

Dependencies represent real Python serverless workloads:
- FastAPI: Web framework
- Pydantic: Data validation
- SQLAlchemy: Database ORM
- NumPy: Numerical computing
"""

import os
import sys

# --- Heavy Imports (The "Import Tax") ---
# These imports represent real-world serverless function dependencies.
# In traditional serverless, this cost is paid on EVERY cold start.
# With Velo Zygote, this cost is paid ONCE and shared via CoW.
import fastapi
import numpy as np
import pydantic
import sqlalchemy


def handler(event: dict) -> dict:
    """
    Minimal serverless handler.

    Args:
        event: Request payload (dict-like)

    Returns:
        Response with status and metadata
    """
    return {
        "status": "ok",
        "size": len(str(event)),
        "python_version": sys.version.split()[0],
        "pid": os.getpid(),
    }


# Expose imported modules for introspection
LOADED_MODULES = {
    "fastapi": fastapi.__version__,
    "pydantic": pydantic.__version__,
    "sqlalchemy": sqlalchemy.__version__,
    "numpy": np.__version__,
}


if __name__ == "__main__":
    # Direct execution for testing
    import json

    result = handler({"test": "payload"})
    print(json.dumps(result, indent=2))
    print(f"\nLoaded modules: {LOADED_MODULES}")
