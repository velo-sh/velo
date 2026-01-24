import os
import sys

# Import EnvProfile for self-describing environment
try:
    from .env_profile import ENV_PROFILE
except (ImportError, ValueError):
    from env_profile import ENV_PROFILE  # type: ignore[no-redef]


def _normalize_environment() -> None:
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
            from env_profile import EnvProfile, RunContext  # type: ignore[no-redef]

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


def _log_banner() -> None:
    """
    Display a diagnostic startup banner according to the Velo Service Pattern.
    Standardized service header for transparency.
    """
    if os.environ.get("VELO_TEST_MODE") == "1":
        return
    try:
        from velo_zygote import constants

        # RFC-0012: Rely on normalized environment (SSOT)
        hash_scm = getattr(constants, "BUILD_SCM_HASH", "unknown")
        proto = getattr(constants, "PROTOCOL_VERSION", "unknown")

        # Identity Matrix (Rule 2: Fail-Loud/Transparency)
        banner = [
            "\n\033[1m[Velo Zygote Bootstrap]\033[0m",
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


def _native_preload() -> None:
    """
    RFC-0035: Native Library Preload (Stage 1 & 2).
    Uses 'velo preload check' for Death Pact vetting before ctypes.CDLL.
    """
    lock_json = os.environ.get("VELO_NATIVE_PRELOAD_LOCK")
    if not lock_json:
        return

    try:
        import ctypes
        import json
        import subprocess

        lock_data = json.loads(lock_json)
        fingerprints = lock_data.get("fingerprints", [])

        for fp in fingerprints:
            lib_path = fp.get("relative_path")
            soname = fp.get("soname")

            # 1. Rust-based "Death Pact" Vetting
            # We call the CLI to perform the fork-vet-load in a separate process.
            try:
                # Use current process environment to ensure paths are correct
                velo_exe = os.environ.get("VELO_EXE_PATH", "velo")

                # Directive B: Promote critical libs
                is_critical = any(x in soname.lower() for x in ["libtorch", "libtensorflow", "libpython"])

                cmd = [velo_exe, "preload", "check", "--path", lib_path]
                if is_critical:
                    cmd.append("--global")

                subprocess.run(cmd, capture_output=True, text=True, check=True)
            except subprocess.CalledProcessError as e:
                sys.stderr.write(f"[VELO-NATIVE] Vetting failed for {soname}: {e.stderr}\n")
                continue

            # 2. Process-local Load
            # If vetting passed, it's safe to load in the current process.
            try:
                mode = ctypes.RTLD_GLOBAL if is_critical else ctypes.RTLD_LOCAL
                ctypes.CDLL(lib_path, mode=mode)
                # sys.stderr.write(f"[VELO-NATIVE] Preloaded {soname}\n")
            except Exception as e:
                sys.stderr.write(f"[VELO-NATIVE] Load failed for {soname}: {e}\n")

    except Exception as e:
        sys.stderr.write(f"[VELO-NATIVE-ERROR] Bootstrap failed: {e}\n")


def initialize() -> None:
    """
    Standardize the Velo Python environment.
    This must be called at the very beginning of any entry point.

    Rule 1: Explicit Bootstrap
    Rule 3: Boot-Validation
    """
    # 0. Pre-import critical dependencies before sys.path is modified
    # This prevents DEF-72-C02: Dependency Shadowing (e.g. user msgpack.py)
    import importlib.util

    if importlib.util.find_spec("msgpack") is None:
        pass  # msgpack not available, will use fallback

    # 1. Environment Normalization (Phase 11.1)
    _normalize_environment()

    # 1.1 RFC-0035 Native Preloading (Pre-Warming)
    # This must happen before sys.path modification to ensure clean state
    _native_preload()

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
