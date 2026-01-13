import os
import sys

# Import EnvProfile for self-describing environment
try:
    from .env_profile import ENV_PROFILE
except (ImportError, ValueError):
    from env_profile import ENV_PROFILE


def _normalize_environment():
    """
    Ensure critical environment variables are set and normalized.
    RFC-0012: SSOT for environment configuration.
    """
    if "VELO_ENV" not in os.environ:
        # SSOT: Use EnvProfile to auto-detect context (e.g. CI, Production)
        # instead of blindly defaulting to 'dev'.
        try:
            from .env_profile import EnvProfile, RunContext
        except (ImportError, ValueError):
            from env_profile import EnvProfile, RunContext

        profile = EnvProfile.detect()

        # Map RunContext back to VELO_ENV convention
        if profile.run_context == RunContext.CI:
            os.environ["VELO_ENV"] = "ci"
        elif profile.run_context == RunContext.PRODUCTION:
            os.environ["VELO_ENV"] = "prod"
        else:
            # 🟢 Default to 'dev' only if no other context detected
            os.environ["VELO_ENV"] = "dev"

    # Standardize to lowercase
    os.environ["VELO_ENV"] = os.environ["VELO_ENV"].lower()


def _log_banner():
    """
    Display a diagnostic startup banner according to the Velo Service Pattern.
    Standardized service header for transparency.
    """
    try:
        from velo_zygote import constants

        # RFC-0012: Rely on normalized environment (SSOT)
        env = os.environ["VELO_ENV"]
        hash_scm = getattr(constants, "BUILD_SCM_HASH", "unknown")
        proto = getattr(constants, "PROTOCOL_VERSION", "unknown")

        # Identity Matrix (Rule 2: Fail-Loud/Transparency)
        banner = [
            f"\n\033[1m[Velo Zygote Bootstrap]\033[0m",
            f"  • PID:      {os.getpid()}",
            f"  • ENV:      {ENV_PROFILE.describe()}",
            f"  • BUILD:    {hash_scm} (v{proto})",
            f"  • ROOT:     {os.path.dirname(os.path.abspath(__file__))}",
            f"  • CWD:      {os.getcwd()}\n",
        ]
        sys.stderr.write("\n".join(banner))
        sys.stderr.flush()
    except Exception as e:
        # Don't let banner failure crash the service
        sys.stderr.write(f"[BOOTSTRAP-WARN] Failed to display banner: {e}\n")


def initialize():
    """
    Standardize the Velo Python environment.
    This must be called at the very beginning of any entry point.

    Rule 1: Explicit Bootstrap
    Rule 3: Boot-Validation
    """
    # 0. Pre-import critical dependencies before sys.path is modified
    # This prevents DEF-72-C02: Dependency Shadowing (e.g. user msgpack.py)
    try:
        import msgpack  # type: ignore
    except ImportError:
        pass

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

    # 4. Success Banner (Transparency)
    _log_banner()

    # 3. ImportShield and other initialization can be triggered here if needed
    # but usually we want to keep bootstrap minimal and let the entry point decide.
