"""
Velo Integrity Protocol (Pre-Flight Checks)
"""
import sys
import platform
from typing import List

try:
    from . import constants
except ImportError:
    # Fallback for direct execution
    import constants

class IntegrityError(Exception):
    """Raised when the runtime environment is corrupt or misconfigured."""
    pass

REQUIRED_CONSTANTS = [
    "PROTOCOL_VERSION",
    "SOCKET_PATH_LIMIT",
    "MAX_MESSAGE_SIZE",
    "DEFAULT_BLOCKED_PATHS",
    # Platform specific checks handled dynamically
]

REQUIRED_CONSTANTS_LINUX = [
    "PATH_LINUX_FD_DIR",
    "PATH_LINUX_BASE_SOCKET_PARENT",
]

REQUIRED_CONSTANTS_MACOS = [
    "PATH_MACOS_FD_DIR",
    "PATH_MACOS_BASE_SOCKET_PARENT",
]

def check_constants():
    """Verify that constants.py contains all necessary configuration."""
    missing = []
    
    # Check Base
    for key in REQUIRED_CONSTANTS:
        if not hasattr(constants, key):
            missing.append(key)

    # Check Platform Specifics
    system = platform.system()
    if system == "Linux":
        for key in REQUIRED_CONSTANTS_LINUX:
            if not hasattr(constants, key):
                missing.append(key)
    elif system == "Darwin":
        for key in REQUIRED_CONSTANTS_MACOS:
            if not hasattr(constants, key):
                missing.append(key)

    if missing:
        raise IntegrityError(f"Missing Critical Constants: {', '.join(missing)}. "
                             "Your 'constants.py' is likely out of sync with 'build.rs'. "
                             "Please run 'cargo build' to regenerate it.")

    # Check Logic
    if not constants.DEFAULT_BLOCKED_PATHS:
        # Empty list is dangerous (regression risk)
        raise IntegrityError("DEFAULT_BLOCKED_PATHS is empty! Security regression detected.")

def validate_runtime():
    """
    Run all pre-flight checks.
    Raises IntegrityError if any check fails.
    """
    try:
        check_constants()
        # Future: check_permissions(), check_dependencies()
    except IntegrityError:
        raise
    except Exception as e:
        raise IntegrityError(f"Integrity Check Failed Unexpectedly: {e}")
