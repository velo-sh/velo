import os
from pathlib import Path
from typing import List, Optional

# RFC-0012: Import generated constants (SSOT)
try:
    from .constants import *
except (ImportError, ValueError):
    from constants import *

class VeloConfig:
    """Unified Configuration for Velo (Python Parity)."""

    def __init__(self):
        # List of modules to preload
        self.preload = self._load_preload()
        # Max message size in bytes
        self.max_message_size = self._get_env_int("VELO_MAX_MESSAGE_SIZE", MAX_MESSAGE_SIZE)
        # Timeout for socket startup (seconds)
        self.socket_startup_timeout = self._get_env_int("VELO_SOCKET_STARTUP_TIMEOUT", SOCKET_STARTUP_TIMEOUT)
        # Host for TCP listeners
        self.host = os.environ.get("VELO_HOST", DEFAULT_HOST)
        # Port for TCP listeners
        self.port = self._get_env_int("VELO_PORT", DEFAULT_PORT)
        # Max bundle size in bytes
        self.max_bundle_size = self._get_env_int("VELO_MAX_BUNDLE_SIZE", 100 * 1024 * 1024)
        # Graceful shutdown timeout in seconds
        self.graceful_shutdown_timeout = self._get_env_int("VELO_GRACEFUL_SHUTDOWN_TIMEOUT", GRACEFUL_SHUTDOWN_TIMEOUT)

    def is_ci(self) -> bool:
        """Check if running in a CI environment (GitHub Actions)."""
        return os.environ.get("GITHUB_ACTIONS") == "true"

    def _load_preload(self) -> List[str]:
        val = os.environ.get("VELO_PRELOAD", "")
        if not val:
            return []
        return [s.strip() for s in val.split(",") if s.strip()]

    def _get_env_int(self, key: str, default: int) -> int:
        val = os.environ.get(key)
        if val is None:
            return default
        try:
            return int(val)
        except ValueError:
            return default

# Singleton instance for easy access
config = VeloConfig()
