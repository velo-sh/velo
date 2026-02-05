import os
import sys

# Import EnvProfile for self-describing environment
try:
    from .env_profile import ENV_PROFILE
except (ImportError, ValueError):
    from env_profile import ENV_PROFILE  # type: ignore[no-redef]

# RFC-0035 Phase 6: Dunder Namespace Isolation
import types

__velo__ = types.ModuleType("__velo__")
__velo__.ENV_PROFILE = ENV_PROFILE  # type: ignore[attr-defined]
sys.modules["__velo__"] = __velo__


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


def _get_pss_kb() -> int:
    """Get Proportional Set Size in KB (Linux only)."""
    if sys.platform != "linux":
        return 0
    try:
        with open("/proc/self/smaps_rollup", "rb") as f:
            for line in f:
                if line.startswith(b"Pss:"):
                    return int(line.split()[1])
    except Exception:
        pass
    return 0


def _log_memory_metrics(label: str) -> None:
    """Log memory metrics via LOP (Log Origin Protocol)."""
    try:
        import resource
        import time

        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On macOS, ru_maxrss is in bytes; on Linux, it's in KB.
        if sys.platform == "darwin":
            rss_kb //= 1024

        pss_kb = _get_pss_kb()

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        msg = f"[{timestamp}] [ZYGOTE] INFO [VELO-MEM-METRIC] {label}: RSS={rss_kb}KB"
        if pss_kb > 0:
            efficiency = (1.0 - (pss_kb / rss_kb)) * 100 if rss_kb > 0 else 0
            msg += f", PSS={pss_kb}KB, COW-Efficiency={efficiency:.1f}%"

        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _v_native_preload(target_stage: str) -> None:
    """
    RFC-0035: Native Library Preload (Stage 1 & 2).
    Uses 'velo preload check' for Death Pact vetting before ctypes.CDLL.
    Aligns with SPEC-0006 LOP logging.
    """
    lock_json = os.environ.get("VELO_RUNTIME_PRELOAD_LOCK")
    if not lock_json:
        return

    try:
        import ctypes
        import json
        import subprocess
        import time

        lock_data = json.loads(lock_json)
        fingerprints = lock_data.get("fingerprints", [])

        # Map target_stage string to internal enum
        # PreInit maps to 'pre-init', PostInit maps to 'post-init' in the lock file usually?
        # Let's check native_fingerprint.rs: PreInit, PostInit.
        # serde usually serializes enums as strings "PreInit", "PostInit" or similar.
        # Actually in preload.rs: LoadStage::PreInit is used.

        for fp in fingerprints:
            lib_path = fp.get("relative_path")
            soname = fp.get("soname")
            fp_stage = fp.get("load_stage")

            # SPEC-0007: Stage-Gated Loading
            if fp_stage != target_stage:
                continue

            # 1. Rust-based "Death Pact" Vetting (INV-PRELOAD-008)
            try:
                velo_exe = os.environ.get("VELO_RUNTIME_EXE_PATH", "velo")
                is_critical = any(x in soname.lower() for x in ["libtorch", "libtensorflow", "libpython"])

                cmd = [
                    velo_exe,
                    "preload",
                    "check",
                    "--path",
                    lib_path,
                    "--expected-hash",
                    fp.get("hash", ""),
                    "--expected-mtime",
                    str(fp.get("mtime", 0)),
                ]
                if is_critical:
                    cmd.append("--global")

                subprocess.run(cmd, capture_output=True, text=True, check=True)
            except subprocess.CalledProcessError as e:
                # SPEC-0006: LOP Logging
                timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
                sys.stderr.write(
                    f"[{timestamp}] [ZYGOTE] ERROR [VELO-PRELOAD-FAIL] Integrity/Vetting failed for {soname}: {e.stderr}\n"
                )

                # RFC-0035 §1.1 / §4.2: Environmental Guardrail
                # If strict mode is on, or if this is an environment where we MUST trust the lock
                if os.environ.get("VELO_NATIVE_PRELOAD_STRICT") == "1":
                    sys.stderr.write("🚨 VELO_NATIVE_PRELOAD_STRICT is enabled. Aborting execution for security.\n")
                    os._exit(1)

                continue

            # 2. Process-local Load
            try:
                mode = ctypes.RTLD_GLOBAL if is_critical else ctypes.RTLD_LOCAL
                ctypes.CDLL(lib_path, mode=mode)

                # SPEC-0006: LOP Logging (Optional for success)
                # timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
                # sys.stderr.write(f"[{timestamp}] [ZYGOTE] INFO [VELO-PRELOAD-OK] Preloaded {soname}\n")
            except Exception as e:
                timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
                sys.stderr.write(f"[{timestamp}] [ZYGOTE] WARN [VELO-PRELOAD-ERR] Load failed for {soname}: {e}\n")

    except Exception as e:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        sys.stderr.write(f"[{timestamp}] [ZYGOTE] ERROR [VELO-PRELOAD-CRIT] Bootstrap failed: {e}\n")


# Expose internal hooks to the isolated namespace
__velo__.native_preload = _v_native_preload  # type: ignore[attr-defined]
__velo__.log_memory = _log_memory_metrics  # type: ignore[attr-defined]


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
    # Aligned with SPEC-0007: This is the PreInit stage.
    _v_native_preload("PreInit")
    _log_memory_metrics("After PreInit")

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
