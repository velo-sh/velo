"""
Velo Path Logic (RFC-0012)

Centralized path resolution for Velo components, matching src/common/paths.rs.
"""

import os
import sys
import tempfile
from pathlib import Path

SOCKET_PATH_LIMIT = 104
PROTOCOL_VERSION = 1

def get_socket_dir() -> Path:
    """Get the canonical socket directory.
    
    Priority:
    1. XDG_RUNTIME_DIR/velo
    2. TMPDIR/velo-{uid}
    3. /tmp/velo-{uid}
    """
    uid = os.getuid()
    
    # 1. Try XDG_RUNTIME_DIR
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "velo"
        
    # 2. Try TMPDIR
    # Note: we use strict velo-{uid} naming without project hash (RFC-0012)
    dir_name = f"velo-{uid}"
    user_dir = Path(tempfile.gettempdir()) / dir_name
    
    # Check path length safety
    test_socket = user_dir / f"z-v{PROTOCOL_VERSION}.s"
    if len(str(test_socket)) <= SOCKET_PATH_LIMIT:
        return user_dir
        
    # 3. Fallback to /tmp
    return Path("/tmp") / dir_name

def get_socket_path() -> Path:
    """Get the full socket path."""
    if os.environ.get("VELO_ZYGOTE_SOCKET"):
        return Path(os.environ["VELO_ZYGOTE_SOCKET"])
        
    directory = get_socket_dir()
    return directory / f"velo-zygote-v{PROTOCOL_VERSION:02x}.sock"

def ensure_socket_dir(path: Path) -> bool:
    """Ensure socket directory exists with 0700 permissions."""
    try:
        if not path.exists():
            # Use strict umask for creation
            old_mask = os.umask(0o077)
            try:
                path.mkdir(parents=True, exist_ok=True)
            finally:
                os.umask(old_mask)
        
        # Enforce 0700
        path.chmod(0o700)
        
        # Verify
        mode = path.stat().st_mode & 0o777
        if mode != 0o700:
             print(f"⚠️ SECURITY: Socket dir has insecure permissions: {oct(mode)}", file=sys.stderr)
             
        return True
    except Exception as e:
        print(f"Failed to ensure socket dir: {e}", file=sys.stderr)
        return False
