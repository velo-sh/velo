"""
Velo Path Logic (RFC-0012)

Centralized path resolution for Velo components, matching src/common/paths.rs.
"""

import os
import sys
import tempfile
from pathlib import Path

# RFC-0012: Import generated constants (SSOT)
try:
    from .constants import *
except (ImportError, ValueError):
    from constants import *

class VeloPaths:
    """Centralized Path Resolver for Velo (Python Parity)."""

    @staticmethod
    def socket_dir() -> Path:
        """Get the canonical socket directory."""
        uid = os.getuid()
        dir_name = f"velo-{uid}"
        
        # RFC-0012: Prioritize /tmp for short paths
        short_path = Path("/tmp") / dir_name
        
        # Check path length safety (AF_UNIX limit)
        test_socket = short_path / f"z-v{PROTOCOL_VERSION}.s"
        if len(str(test_socket)) <= SOCKET_PATH_LIMIT:
            return short_path
            
        # Fallback to XDG_RUNTIME_DIR
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if xdg:
            return Path(xdg) / "velo"
            
        return Path(tempfile.gettempdir()) / dir_name

    @staticmethod
    def zygote_socket() -> Path:
        """Get the full Zygote socket path."""
        if os.environ.get("VELO_ZYGOTE_SOCKET"):
            return Path(os.environ["VELO_ZYGOTE_SOCKET"])
            
        directory = VeloPaths.socket_dir()
        ensure_socket_dir(directory)
        return directory / f"velo-zygote-v{PROTOCOL_VERSION:02x}.sock"

    @staticmethod
    def worker_socket(worker_id: int) -> Path:
        """Generate a standardized worker socket path."""
        directory = VeloPaths.socket_dir()
        ensure_socket_dir(directory)
        return directory / f"w-{worker_id}.s"

    @staticmethod
    def zygote_log() -> Path:
        """Get the log path for the Zygote."""
        if os.environ.get("VELO_ZYGOTE_LOG"):
            return Path(os.environ["VELO_ZYGOTE_LOG"])
            
        home = os.environ.get("HOME", "/tmp")
        return Path(home) / ".local" / "state" / "velo" / "zygote.log"

    @staticmethod
    def project_file(project_root: Path, file_name: str) -> Path:
        """Get a project-relative file path."""
        return project_root / file_name

    @classmethod
    def pyproject(cls, project_root: Path) -> Path:
        """Canonical path to pyproject.toml."""
        return cls.project_file(project_root, PYPROJECT_TOML)

    @classmethod
    def uv_lock(cls, project_root: Path) -> Path:
        """Canonical path to uv.lock."""
        return cls.project_file(project_root, UV_LOCK)

def get_socket_dir() -> Path:
    """Legacy wrapper."""
    return VeloPaths.socket_dir()

def get_socket_path() -> Path:
    """Legacy wrapper."""
    return VeloPaths.zygote_socket()

def ensure_socket_dir(path: Path) -> bool:
    """Ensure socket directory exists with 0700 permissions."""
    try:
        if not path.exists():
            old_mask = os.umask(0o077)
            try:
                path.mkdir(parents=True, exist_ok=True)
            finally:
                os.umask(old_mask)
        
        path.chmod(0o700)
        mode = path.stat().st_mode & 0o777
        if mode != 0o700:
             print(f"⚠️ SECURITY: Socket dir has insecure permissions: {oct(mode)}", file=sys.stderr)
        return True
    except Exception as e:
        print(f"Failed to ensure socket dir: {e}", file=sys.stderr)
        return False
