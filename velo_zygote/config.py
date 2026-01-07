import os
from pathlib import Path
from typing import List, Optional

# RFC-0012: Import generated constants (SSOT)
try:
    from .constants import *
except (ImportError, ValueError):
    from constants import *

# Default values (RFC-0012 local fallbacks)
DEFAULT_SOCKET_STARTUP_TIMEOUT = 5
DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT = 20
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

class VeloConfig:
    """Unified Configuration for Velo (Python Parity)."""

    def __init__(self):
        # Environment mode: dev, ci, prod
        self.env_mode = os.environ.get("VELO_ENV", "dev").lower()
        # List of modules to preload
        self.preload = self._load_preload()
        # Max message size in bytes
        # MAX_MESSAGE_SIZE is still in constants.py (compile-time)
        self.max_message_size = self._get_env_int("VELO_MAX_MESSAGE_SIZE", MAX_MESSAGE_SIZE)
        # Timeout for socket startup (seconds)
        self.socket_startup_timeout = self._get_env_int("VELO_SOCKET_STARTUP_TIMEOUT", DEFAULT_SOCKET_STARTUP_TIMEOUT)
        # Host for TCP listeners
        self.host = os.environ.get("VELO_HOST", DEFAULT_HOST)
        # Port for TCP listeners
        self.port = self._get_env_int("VELO_PORT", DEFAULT_PORT)
        # Max bundle size in bytes
        self.max_bundle_size = self._get_env_int("VELO_MAX_BUNDLE_SIZE", 1024 * 1024 * 1024)
        # Graceful shutdown timeout in seconds
        self.graceful_shutdown_timeout = self._get_env_int("VELO_GRACEFUL_SHUTDOWN_TIMEOUT", DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT)
        
        # Security: Config-driven boundary with profile parity
        self.security_trusted_prefixes = self._get_security_list("trusted_prefixes")
        self.security_env_whitelist = self._get_security_list("env_whitelist")
        
        # Security: HPC thread limit
        self.security_hpc_threads = self._get_env_int("VELO_SECURITY_HPC_THREADS", 1)

    def is_ci(self) -> bool:
        """Check if running in a CI environment (GitHub Actions)."""
        return os.environ.get("GITHUB_ACTIONS") == "true"

    def _load_preload(self) -> List[str]:
        return self._get_env_list("VELO_PRELOAD", [])

    def _get_env_list(self, key: str, default: List[str]) -> List[str]:
        val = os.environ.get(key, "")
        if not val:
            return default
        return [s.strip() for s in val.split(",") if s.strip()]

    def _get_env_int(self, key: str, default: int) -> int:
        val = os.environ.get(key)
        if val is None:
            return default
        try:
            return int(val)
        except ValueError:
            return default

    def _get_security_list(self, base_key: str) -> List[str]:
        """Load security list using hierarchical Platform x Environment resolution."""
        import sys
        env_key = f"VELO_SECURITY_{base_key.upper()}"
        env_val = os.environ.get(env_key)
        if env_val:
            return [s.strip() for s in env_val.split(",") if s.strip()]

        # Detect OS
        os_name = "macos" if sys.platform == "darwin" else "linux"
        suffix = base_key.upper()

        # Level 0: Global Base
        base_val = globals().get(f"SECURITY_BASE_{suffix}", "")

        # Level 1: OS Base (merge with global base)
        os_base_key = f"SECURITY_{os_name.upper()}_BASE_{suffix}"
        os_base_val = globals().get(os_base_key, "").replace("${BASE}", base_val)

        # Level 2: OS + Environment (merge with OS base)
        final_key = f"SECURITY_{os_name.upper()}_{self.env_mode.upper()}_{suffix}"
        fallback_key = f"SECURITY_{os_name.upper()}_DEV_{suffix}"
        
        profile_val = globals().get(final_key, globals().get(fallback_key, ""))
        final_val = profile_val.replace("${OS_BASE}", os_base_val)

        return [s.strip() for s in final_val.split(",") if s.strip()]

# Singleton instance for easy access
config = VeloConfig()
