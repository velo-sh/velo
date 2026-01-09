"""
Velo Path Logic (RFC-0012)

Centralized path resolution for Velo components, matching src/common/paths.rs.
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

# RFC-0012: Import generated constants (SSOT)
try:
    from .constants import *
except (ImportError, ValueError):
    from constants import *

class VeloPaths:
    """Centralized Path Resolver for Velo (Python Parity)."""

    # Standard Filenames (RFC-0012)
    PYPROJECT_TOML = "pyproject.toml"
    UV_LOCK = "uv.lock"
    REQUIREMENTS_TXT = "requirements.txt"
    SITE_CUSTOMIZE = "sitecustomize.py"
    VELO_LOADER = "velo_loader.py"
    VELO_CACHE_DIR = ".velo_cache"
    VELO_PROFILE_JSON = "velo_profile.json"

    @staticmethod
    def _expand_placeholders(path_str: str) -> str:
        """Expand placeholders to match Rust implementation."""
        result = path_str
        
        if "${HOME}" in result:
            result = result.replace("${HOME}", os.environ.get("HOME", "/tmp"))
            
        if "${XDG_RUNTIME_DIR}" in result:
            xdg = os.environ.get("XDG_RUNTIME_DIR")
            if xdg:
                result = result.replace("${XDG_RUNTIME_DIR}", xdg)
            else:
                # Fallback to /tmp if XDG_RUNTIME_DIR not set (matching Rust)
                result = result.replace("${XDG_RUNTIME_DIR}", "/tmp")
                
        if "${TMPDIR}" in result:
            result = result.replace("${TMPDIR}", tempfile.gettempdir())
            
        if "${UID}" in result:
            result = result.replace("${UID}", str(os.getuid()))
            
        return result

    @staticmethod
    def _get_path_config(key: str) -> Optional[str]:
        """Get path config from constants by name (e.g. PATH_MACOS_DEV_SOCKET_PARENT)."""
        # We look up in the global scope of this module (where constants are imported)
        return globals().get(key.upper())

    @staticmethod
    def socket_dir() -> Path:
        """Get the canonical socket directory using hierarchical path resolution."""
        # 1. Check for environment override
        override = os.environ.get("VELO_SOCKET_DIR")
        if override:
            return Path(override)

        # 2. Determine OS and Environment
        os_name = "macos" if sys.platform == "darwin" else "linux"
        env_mode = os.environ.get("VELO_ENV", "dev").lower()
        
        # 3. Resolve using Matrix
        # Try specific env first (e.g. PATH_MACOS_CI_SOCKET_PARENT)
        env_key = f"PATH_{os_name}_{env_mode}_SOCKET_PARENT"
        base_key = f"PATH_{os_name}_BASE_SOCKET_PARENT"
        
        parent_path = VeloPaths._get_path_config(env_key)
        if not parent_path:
            parent_path = VeloPaths._get_path_config(base_key)
            
        if not parent_path:
            parent_path = "/tmp" # Ultimate backup

        # 4. Expand Placeholders
        expanded_parent = VeloPaths._expand_placeholders(parent_path)
        
        # 5. Append Dir Name
        dir_name = VeloPaths._expand_placeholders(PATH_SOCKET_DIR_NAME)
        
        socket_path = Path(expanded_parent) / dir_name
        
        # 6. Check Length Limit
        # (Rust logic: if path too long, fallback to /tmp)
        if len(str(socket_path)) + 30 <= SOCKET_PATH_LIMIT:
             return socket_path
             
        # Fallback
        return Path("/tmp") / dir_name

    @staticmethod
    def zygote_socket() -> Path:
        """Get the full Zygote socket path."""
        if os.environ.get("VELO_ZYGOTE_SOCKET"):
            path_str = os.environ["VELO_ZYGOTE_SOCKET"]
            if len(path_str) <= SOCKET_PATH_LIMIT:
                return Path(path_str)
            else:
                print(f"⚠️ WARNING: VELO_ZYGOTE_SOCKET is too long. Falling back to default.", file=sys.stderr)
            
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
            
        # Use SSOT constants
        os_name = "macos" if sys.platform == "darwin" else "linux"
        base_key = f"PATH_{os_name.upper()}_BASE_LOG_PARENT"
        
        parent_tmpl = VeloPaths._get_path_config(base_key) or "${HOME}"
        expanded_parent = VeloPaths._expand_placeholders(parent_tmpl)
        
        return Path(expanded_parent) / PATH_LOG_DIR_RELATIVE / "zygote.log"

    @staticmethod
    def worker_log() -> Path:
        """Get the log path for the Worker."""
        # Use SSOT constants parity with zygote_log
        os_name = "macos" if sys.platform == "darwin" else "linux"
        base_key = f"PATH_{os_name.upper()}_BASE_LOG_PARENT"
        
        parent_tmpl = VeloPaths._get_path_config(base_key) or "${HOME}"
        expanded_parent = VeloPaths._expand_placeholders(parent_tmpl)
        
        return Path(expanded_parent) / PATH_LOG_DIR_RELATIVE / "worker.log"

    @staticmethod
    def project_file(project_root: Path, file_name: str) -> Path:
        """Get a project-relative file path."""
        return project_root / file_name

    @classmethod
    def pyproject(cls, project_root: Path) -> Path:
        """Canonical path to pyproject.toml."""
        return cls.project_file(project_root, PYPROJECT_TOML)

    @staticmethod
    def sanitize_sys_path(script_file: str):
        """
        Surgical Path Sanitization (RFC-0014).
        
        1. Prevent the script's directory from shadowing user modules by moving it to the end.
        2. Ensure CWD is at the front (Standard parity with CPython).
        """
        script_dir = os.path.dirname(os.path.abspath(script_file))
        if script_dir in sys.path:
            sys.path.remove(script_dir)
            sys.path.append(script_dir)
        
        if os.getcwd() not in sys.path:
            sys.path.insert(0, os.getcwd())

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
        # Verify
        try:
             mode = path.stat().st_mode & 0o777
             if mode != 0o700:
                 # Attempt to fix it
                 path.chmod(0o700)
        except: pass
             
        return True
    except Exception as e:
        print(f"Failed to ensure socket dir: {e}", file=sys.stderr)
        return False
