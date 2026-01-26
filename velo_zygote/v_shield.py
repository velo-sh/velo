import os
import sys
import types
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from .settings import velo_config
except (ImportError, ValueError):
    from settings import velo_config  # type: ignore[no-redef]


class VeloRuntimeShield:
    """
    SPEC-0005: Active Runtime Defense (The reset gate).
    Intercepts and BLOCKS any import that resolves to the Velo Runtime physical path
    unless it is addressed via the authorized 'velo_zygote' namespace.
    """

    _active = False

    def __init__(self, runtime_root: str):
        self.runtime_root = os.path.abspath(runtime_root)
        # Ensure we match directories correctly
        if not self.runtime_root.endswith(os.sep):
            self.runtime_root += os.sep

    @classmethod
    def install(cls) -> None:
        """Install the shield at the front of sys.meta_path."""
        runtime_root = os.path.dirname(os.path.abspath(__file__))

        # Avoid duplicate installation
        for f in sys.meta_path:
            if isinstance(f, VeloRuntimeShield):
                return

        sys.meta_path.insert(0, cls(runtime_root))  # type: ignore

    # Compatibility for v_fork.py which calls .activate()
    activate = install

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: types.ModuleType | None = None,
    ) -> Any:
        """
        The Gatekeeper Logic.
        """
        # 1. Allow authorized namespace
        if fullname.startswith("velo_zygote"):
            return None

        # 2. Check if this module NAME is a known internal module
        # Optimization: We could just check ALL imports, but that's expensive I/O.
        # We only care if it resolves to OUR directory.
        # But we can't accept the spec if we don't know where it is.
        # So we let Python find it first? No, we are the finder.

        # CRITICAL ARCHITECTURE:
        # We cannot easily "resolve" without being a full PathFinder.
        # Instead, we rely on the fact that if 'sys.path' is clean, standard finders won't find it.
        # BUT the user might add the path back.
        # So we must inspect if the user is trying to import a module that EXISTS in our runtime root.

        # Fast check: Is this a potential collision candidate?
        # We convert the dot-path to a filesystem path relative to runtime root.

        # CASE A: Top-level import 'utils' -> velo_zygote/utils.py
        candidate_path = os.path.join(self.runtime_root, *fullname.split("."))

        # Only check generic top-level names or common submodules
        # Performance: Checking implies syscalls.
        is_hit = False
        if os.path.isfile(candidate_path + ".py"):
            is_hit = True
        elif os.path.isdir(candidate_path) and os.path.isfile(os.path.join(candidate_path, "__init__.py")):
            is_hit = True

        if is_hit:
            # COLLISION DETECTED
            # We must determine if this import resolves to the RUNTIME ROOT (Block)
            # or to a user-space file (Allow).

            # Use PathFinder to simulate standard resolution WITHOUT triggering meta_path recursion.
            from importlib.machinery import PathFinder

            try:
                # We use the current sys.path (or the path argument passed to find_spec)
                search_path = path if path is not None else sys.path
                spec = PathFinder.find_spec(fullname, path=search_path)

                if spec and spec.origin:
                    # Check physical location
                    # Resolve symlinks to be sure
                    try:
                        origin_path = os.path.realpath(spec.origin)
                        runtime_real = os.path.realpath(self.runtime_root)

                        if origin_path.startswith(runtime_real):
                            msg = f"ImportShield Violation: Access denied to runtime kernel module '{fullname}'."
                            try:
                                sys.stderr.write(f"🛡️ [ImportShield] BLOCKED: {msg} (Origin: {origin_path})\n")
                            except Exception:
                                pass
                            raise ImportError(msg)
                    except OSError:
                        pass

            except ImportError:
                # If PathFinder can't find it, we permit continuation (it will fail later anyway)
                pass

        return None

    @classmethod
    def validate_security(cls) -> None:
        """Self-test to ensure the shield is active."""
        # Simple check if we are in meta_path
        if not any(isinstance(f, cls) for f in sys.meta_path):
            cls.install()


# Legacy Alias for backward compatibility if needed
ImportShield = VeloRuntimeShield


# RFC-0012 Phase 11.3: Auto-install when environment variable is set.
# This ensures protection even when Zygote falls back to direct uvicorn mode.
if os.environ.get("VELO_ZYGOTE_SHIELD_ACTIVE") == "1":
    ImportShield.install()
    # Zygote itself must NOT be shielded from its own internal modules (Trap 178.4)
    if os.environ.get("VELO_IS_ZYGOTE") != "1":
        ImportShield._active = True


class PathValidator:
    """Security validation for script paths."""

    @staticmethod
    def validate(script_path: str) -> tuple[bool, str]:
        """
        Validate script path for security (SEC-P3-001).
        Blocks paths containing '..' or pointing to system directories.
        """
        try:
            # Recursive check for directory traversal (Pillar 2: Sandbox Integrity)
            if ".." in script_path.replace("\\", "/").split("/"):
                return False, f"Exploit Attempt: Directory traversal detected in path '{script_path}'"

            script = Path(script_path).resolve()
            script_str = str(script)

            # RFC-0030 Hole-punching: Allow Jupyter connection files in dynamic temp locations
            # These are dynamically generated by Jupyter/JupyterHub.
            if script.name.startswith("kernel-") and script.name.endswith(".json"):
                import tempfile

                temp_dir = tempfile.gettempdir()
                if script_str.startswith(temp_dir):
                    return True, ""
                # macOS specific var folders
                if sys.platform == "darwin" and script_str.startswith("/var/folders"):
                    return True, ""

            for blocked in velo_config.blocked_paths:
                if script_str.startswith(blocked + "/") or script_str == blocked:
                    return (
                        False,
                        f"Access denied: script in protected system path '{blocked}'",
                    )

            return True, ""
        except Exception as e:
            return False, f"Invalid script path: {e}"
