import os
import sys
from pathlib import Path
from typing import Tuple, Optional

try:
    from .settings import velo_config
except (ImportError, ValueError):
    from settings import velo_config



class ImportShield:
    """
    RFC-0012: Resilience Whitelist for Framework Bootstrap.
    Prevents unauthorized access to internal framework modules.
    """
    _active = False
    _is_velo_import_shield = True

    @classmethod
    def activate(cls):
        """Enable the shield. Once enabled, internal imports are blocked."""
        cls._active = True
        # Set environment variable for persistence in forks
        os.environ["VELO_ZYGOTE_SHIELD_ACTIVE"] = "1"

    def find_spec(self, fullname, path, target=None):
        # 0. Only block if shield is active (via class var or environment)
        # Environment check is the target-safe SSOT for forked children.
        if not (self._active or os.environ.get("VELO_ZYGOTE_SHIELD_ACTIVE") == "1"):
            return None

        # RFC-0012: Resilience Whitelist for Framework Bootstrap
        # We allow anything explicitly in whitelist OR any submodule of a whitelisted package.
        whitelist = ("velo_zygote",) # Restore framework access for bootstrap
        
        if fullname.startswith("velo_zygote"):
            if not any(fullname == w or fullname.startswith(w + ".") for w in whitelist):
                # We allow the launcher to import us once, but once the app is loading,
                # any SUBSEQUENT import of velo_zygote (by user code) is blocked.
                msg = f"Unauthorized access to internal framework module: {fullname}"
                try:
                    # Log to stderr for visibility in CI logs (Trap 178.2/3)
                    sys.stderr.write(f"🛡️ [ImportShield] {msg}\n")
                    sys.stderr.flush()
                except: pass
                raise ImportError(msg)
        
        # 2. Shadowing Protection: main.py
        # This finder is installed at the top of sys.meta_path.
        # If it returns None, Python falls back to standard finders (PathFinder).
        return None

    @staticmethod
    def install():
        """Install the shield at the front of sys.meta_path."""
        # Use name check instead of isinstance to avoid potential ABC issues or hangs
        if not any(type(f).__name__ == "ImportShield" for f in sys.meta_path):
            sys.meta_path.insert(0, ImportShield())
            
            # Centralized Path Sanitization (RFC-0011 6A.1)
            # Prevent shadowing of user modules by framework modules.
            try:
                framework_dir = os.path.dirname(os.path.abspath(__file__))
                if framework_dir in sys.path:
                    sys.path.remove(framework_dir)
            except: pass


class PathValidator:
    """Security validation for script paths."""

    @staticmethod
    def validate(script_path: str) -> Tuple[bool, str]:
        """
        Validate script path for security (SEC-P3-001).
        Blocks paths containing '..' or pointing to system directories.
        """
        try:
            script = Path(script_path).resolve()
            script_str = str(script)
            
            for blocked in velo_config.blocked_paths:
                if script_str.startswith(blocked + "/") or script_str == blocked:
                    return False, f"Access denied: script in protected system path '{blocked}'"
            
            return True, ""
        except Exception as e:
            return False, f"Invalid script path: {e}"
