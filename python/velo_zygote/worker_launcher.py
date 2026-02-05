# --- Velo Bootstrap (CRITICAL: MUST BE FIRST) ---
import os
import sys
from typing import Any


# DEF-72-C02: Surgical sys.path sanitization to prevent shadowing
# During 'python -m', sys.path[0] is the current directory.
# We MUST remove it before pre-importing critical libraries.
def _sovereign_import(name: str) -> Any:
    _original_path = sys.path.copy()
    _cwd = os.getcwd()
    sys.path = [p for p in sys.path if p and p != _cwd and p != "." and p != ""]
    try:
        return __import__(name)
    finally:
        sys.path = _original_path


# Pre-import msgpack to protect against local shadowing
msgpack = _sovereign_import("msgpack")

# Ensure velo_zygote is in path
_pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

# DEF-003: Runtime Isolation (SPEC-0005)
# Remove the script's directory from sys.path to prevent namespace collision
# (e.g. user 'main.py' vs 'velo_zygote/main.py')
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir in sys.path:
    sys.path.remove(_script_dir)

# Standard bootstrap
try:
    from velo_zygote import bootstrap

    bootstrap.initialize()
except ImportError:
    pass
# ----------------------------------------------

import argparse
import inspect
import signal
import tempfile
import time
import traceback
from types import FrameType
from typing import Any

_T0 = time.perf_counter()
# RFC-0012: Use system temp dir instead of hardcoded /tmp
_PROF_LOG_PATH = os.path.join(tempfile.gettempdir(), "worker_prof.log")
_PROF_STATS_PATH = os.path.join(tempfile.gettempdir(), "worker.prof_log")


def _prof_log(msg: str) -> None:
    with open(_PROF_LOG_PATH, "a") as f:
        f.write(f"[{time.perf_counter()}] {msg}\n")


_prof_log(f"[PROF] Import Start: {_T0}")

import uvicorn

_T1 = time.perf_counter()
_prof_log(f"[PROF] Uvicorn Imported: +{(_T1 - _T0) * 1000:.2f}ms")

from velo_zygote.paths import VeloPaths
from velo_zygote.v_shield import ImportShield

_T2 = time.perf_counter()
_prof_log(f"[PROF] Velo Framework Imported: +{(_T2 - _T1) * 1000:.2f}ms")

if hasattr(uvicorn, "Server") and hasattr(uvicorn.Server, "install_signal_handlers"):
    _original_install_signal_handlers = uvicorn.Server.install_signal_handlers

    def _install_signal_handlers_with_marker(self: uvicorn.Server) -> None:
        _original_install_signal_handlers(self)
        previous = signal.getsignal(signal.SIGTERM)

        def _sigterm_marker(sig: int, frame: FrameType | None) -> None:
            print("CHILD_RECEIVED_SIGTERM", flush=True)
            if callable(previous):
                previous(sig, frame)
            elif previous == signal.SIG_DFL:
                raise SystemExit(0)

        signal.signal(signal.SIGTERM, _sigterm_marker)

    uvicorn.Server.install_signal_handlers = _install_signal_handlers_with_marker


class UDSProxyMiddleware:
    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        current_client = scope.get("client")
        is_client_missing = current_client is None or (
            isinstance(current_client, (list, tuple)) and len(current_client) > 0 and current_client[0] is None
        )
        if scope["type"] in ("http", "websocket") and is_client_missing:
            headers = scope.get("headers", [])
            has_proxy_headers = False
            client_host = "127.0.0.1"

            # RFC-0011 §6A.4: Recover client IP from X-Forwarded-For injected by Rust Proxy
            # Standard ASGI headers are (lowercase_bytes, bytes)
            for h_name, h_val in headers:
                name_lower = h_name.lower()
                if name_lower == b"x-forwarded-for":
                    try:
                        client_host = h_val.decode().split(",")[0].strip()
                        has_proxy_headers = True
                    except Exception:
                        pass
                elif name_lower == b"x-real-ip":
                    try:
                        client_host = h_val.decode().strip()
                        has_proxy_headers = True
                    except Exception:
                        pass
                elif name_lower == b"x-forwarded-proto":
                    try:
                        scope["scheme"] = h_val.decode().strip()
                    except Exception:
                        pass

            if has_proxy_headers:
                # RFC-0011: scope['client'] MUST be a tuple of (host, port)
                scope["client"] = (client_host, 0)

        result = self.app(scope, receive, send)
        if inspect.isawaitable(result):
            await result


def _enforce_ghost_mode() -> None:
    """
    SPEC-0005: Ghost Mode Isolation.
    Purge any internal Velo modules from sys.modules that leaked into the top-level namespace.
    """
    import os
    import sys

    # Identify the physical location of the runtime
    runtime_root = os.path.dirname(os.path.abspath(__file__))

    # Identify modules to purge
    to_purge = []

    # We must iterate over a copy of keys
    for name, module in list(sys.modules.items()):
        # If the module names starts with 'velo_zygote', it's namespaced correctly. Keep it.
        if name.startswith("velo_zygote"):
            continue

        # If the module has no file attribute, we skipped it (built-ins)
        if not hasattr(module, "__file__") or not module.__file__:
            continue

        # Check if the module resides inside our runtime root
        # e.g. /path/to/velo_zygote/utils.py imported as 'utils'
        try:
            mod_path = os.path.abspath(module.__file__)
            if mod_path.startswith(runtime_root):
                # LEAK DETECTED!
                # This is an internal module masquerading as a top-level one.
                to_purge.append(name)
        except Exception:
            continue

    # Purge them
    for name in to_purge:
        if name in sys.modules:
            del sys.modules[name]

    # Also ensure the runtime root is NOT in sys.path
    if runtime_root in sys.path:
        sys.path.remove(runtime_root)

    # SPEC-0005: Install Active Import Shield
    # This prevents re-importing internal modules even if sys.path is tampered with.
    try:
        from velo_zygote.v_shield import VeloRuntimeShield

        VeloRuntimeShield.install()
    except ImportError:
        pass


def _wrap_app_with_middleware(app_path: str) -> Any:
    """
    Wrap the ASGI app with UDS Proxy Middleware (Trusted).
    """
    import importlib
    import sys

    # SPEC-0005: Enforce Ghost Mode before loading user code
    _enforce_ghost_mode()

    module_name, attr_name = app_path.rsplit(":", 1)

    # DEF-003: Runtime Isolation (SPEC-0005)
    # If 'main' is already loaded (e.g. from Velo Runtime), we MUST unload it
    # so that import_module('main') searches sys.path for the user's app.
    # Note: _enforce_ghost_mode handles generic leaks, but we check 'main' explicitly as a fail-safe
    if module_name == "main" and "main" in sys.modules:
        del sys.modules["main"]

    module = importlib.import_module(module_name)
    app = getattr(module, attr_name)
    return UDSProxyMiddleware(app)


def main() -> None:
    try:

        def _graceful_exit(sig: int, frame: FrameType | None) -> None:
            raise SystemExit(0)

        # Respect app-level SIGTERM handlers for graceful shutdown.
        # Keep SIGINT fast-exit for interactive use.
        signal.signal(signal.SIGINT, _graceful_exit)
        parser = argparse.ArgumentParser(description="Velo Worker Launcher")
        parser.add_argument("--app", required=True)
        parser.add_argument("--uds")
        parser.add_argument("--host")
        parser.add_argument("--port", type=int)
        parser.add_argument("--proxy-headers", action="store_true", dest="proxy_headers")
        parser.add_argument("--rsgi", action="store_true")
        _T3 = time.perf_counter()
        args = parser.parse_args()
        _T4 = time.perf_counter()
        _prof_log(f"[PROF] Args Parsed: +{(_T4 - _T3) * 1000:.2f}ms")

        if args.rsgi:
            from velo_zygote.v_rsgi import run_rsgi

            ImportShield.activate()
            VeloPaths.sanitize_sys_path(__file__)
            run_rsgi(args.app, args.uds)
        else:
            ImportShield.activate()
            VeloPaths.sanitize_sys_path(__file__)
            _T5 = time.perf_counter()
            _prof_log(f"[PROF] Pre-Run Hygiene: +{(_T5 - _T4) * 1000:.2f}ms")

            config_kwargs = {
                "app": args.app,
                "loop": "auto",
                "http": "auto",
                "lifespan": "on",
                "proxy_headers": True,  # RFC-0011: FORCED for L7 proxy header trust
                "log_config": None,
            }
            if args.uds:
                config_kwargs["uds"] = args.uds
            else:
                config_kwargs["host"] = args.host or "127.0.0.1"
                config_kwargs["port"] = args.port or 8000

            _T6 = time.perf_counter()
            _prof_log(f"[PROF] Entering uvicorn execution: +{(_T6 - _T5) * 1000:.2f}ms")

            import cProfile
            import pstats

            profiler = cProfile.Profile()
            profiler.enable()
            try:
                # Injected by v_fork.py under __VELO_WARM_SERVER__
                warmed_server = globals().get("__VELO_WARM_SERVER__")
                warmed_config = globals().get("__VELO_WARM_CONFIG__")

                if warmed_config is not None:
                    _prof_log("[PROF] Using Deep-Warmed uvicorn Config.")
                    # STB-SOCKET-004: Patch config with this worker's socket path
                    # We MUST patch BEFORE creating a new Server, not after.
                    if args.uds:
                        warmed_config.uds = args.uds
                        warmed_config.host = None
                        warmed_config.port = None
                        # RFC-0011 GOLD-013: Force proxy_headers for UDS
                        warmed_config.proxy_headers = True
                    else:
                        warmed_config.uds = None
                        warmed_config.host = args.host or "127.0.0.1"
                        warmed_config.port = args.port or 8000

                    # RFC-0011 GOLD-013: Wrap app with UDSProxyMiddleware for scope['client'] population
                    # This is required because uvicorn's proxy_headers doesn't work for UDS connections
                    if args.uds and warmed_config.loaded_app is not None:
                        warmed_config.loaded_app = UDSProxyMiddleware(warmed_config.loaded_app)

                    # Recreate Server with patched config (socket binding is determined at run time)
                    server = uvicorn.Server(warmed_config)
                    server.run()
                elif warmed_server is not None:
                    # Legacy fallback: patch server.config directly (may not work for UDS)
                    _prof_log("[PROF] Using Deep-Warmed uvicorn Server (legacy).")
                    if args.uds:
                        warmed_server.config.uds = args.uds
                        # RFC-0011 GOLD-013: Wrap for UDS
                        if warmed_server.config.loaded_app is not None:
                            warmed_server.config.loaded_app = UDSProxyMiddleware(warmed_server.config.loaded_app)
                    else:
                        warmed_server.config.host = args.host or "127.0.0.1"
                        warmed_server.config.port = args.port or 8000
                    warmed_server.run()
                else:
                    _prof_log("[PROF] warmed_server is None, falling back to uvicorn.run()")
                    # RFC-0011 GOLD-013: Wrap app for UDS fallback
                    try:
                        if args.uds:
                            config_kwargs["app"] = _wrap_app_with_middleware(args.app)
                    except (ImportError, AttributeError, ValueError) as e:
                        # FATAL: App cannot be loaded. Do not retry uvicorn.run() as it will just hang or fail again.
                        sys.stderr.write(f"FATAL: Application load failed: {e}\n")
                        sys.exit(1)

                    uvicorn.run(**config_kwargs)
            except (SystemExit, KeyboardInterrupt):
                raise
            except Exception as e:
                _prof_log(f"[PROF] Execution Error: {e}")
                # If we've already failed to load the app once, another attempt is futile if it's an import error
                uvicorn.run(**config_kwargs)
            finally:
                profiler.disable()
                with open(_PROF_STATS_PATH, "w") as f:
                    ps = pstats.Stats(profiler, stream=f).sort_stats("cumulative")
                    ps.print_stats()

    except Exception as e:
        sys.stderr.write(f"FATAL WORKER CRASH: {e}\n")
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
