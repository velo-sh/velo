import os
import sys

def _normalize_environment():
    """
    Ensure critical environment variables are set and normalized.
    RFC-0012: SSOT for environment configuration.
    """
    if "VELO_ENV" not in os.environ:
        # 🟢 Fallback to 'dev' with explicit logging for auditability
        os.environ["VELO_ENV"] = "dev"
        sys.stderr.write("[BOOTSTRAP-INFO] VELO_ENV missing, normalized to 'dev' for discovery/tests.\n")
        sys.stderr.flush()
    else:
        # Standardize to lowercase
        os.environ["VELO_ENV"] = os.environ["VELO_ENV"].lower()

def initialize():
    """
    Standardize the Velo Python environment.
    This must be called at the very beginning of any entry point.
    
    Rule 1: Explicit Bootstrap
    Rule 3: Boot-Validation
    """
    # 1. Environment Normalization (Phase 11.1)
    _normalize_environment()

    # 2. Normalize sys.path
    # SCRIPT_DIR is the directory of this file (velo_zygote/)
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    # PKG_ROOT is the directory containing velo_zygote/
    _pkg_root = os.path.dirname(_script_dir)
    
    # Ensure package root is in sys.path
    if _pkg_root not in sys.path:
        sys.path.insert(0, _pkg_root)
    
    # Ensure CWD is at the front (Standard parity with CPython)
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    # 3. Pre-flight Integrity Check (Fail-Fast)
    try:
        from velo_zygote import integrity
        integrity.validate_runtime()
    except Exception as e:
        # Rule 2: Fail-Loud Principle
        sys.stderr.write(f"\n\033[91m🚨 VELO BOOTSTRAP FAILURE: {e}\033[0m\n")
        sys.stderr.flush()
        if isinstance(e, ImportError):
            sys.stderr.write(f"DEBUG info: sys.path={sys.path}\n")
            sys.stderr.write(f"DEBUG info: __file__={__file__}\n")
            sys.stderr.flush()
        sys.exit(1)

    # 3. ImportShield and other initialization can be triggered here if needed
    # but usually we want to keep bootstrap minimal and let the entry point decide.
