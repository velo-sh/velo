# --- Velo Bootstrap (CRITICAL: MUST BE FIRST) ---
import os
import sys


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

# Standard bootstrap
try:
    from velo_zygote import bootstrap

    bootstrap.initialize()
except ImportError:
    pass
# ----------------------------------------------

import argparse
import signal
import time
import traceback
from types import FrameType
from typing import Any

_T0 = time.perf_counter()


def _prof_log(msg: str) -> None:
    with open("/tmp/worker_prof.log", "a") as f:
        f.write(f"[{time.perf_counter()}] {msg}\n")


_prof_log(f"[PROF] Import Start: {_T0}")

import uvicorn

_T1 = time.perf_counter()
_prof_log(f"[PROF] Uvicorn Imported: +{(_T1 - _T0) * 1000:.2f}ms")

from velo_zygote.paths import VeloPaths
from velo_zygote.v_shield import ImportShield

_T2 = time.perf_counter()
_prof_log(f"[PROF] Velo Framework Imported: +{(_T2 - _T1) * 1000:.2f}ms")


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
            has_proxy_headers = any(k.lower() in (b"x-forwarded-for", b"x-real-ip") for k, v in headers)
            if has_proxy_headers:
                client_host = "127.0.0.1"
                for h_name, h_val in headers:
                    if h_name.lower() == b"x-forwarded-for":
                        client_host = h_val.decode().split(",")[0].strip()
                        break
                    if h_name.lower() == b"x-real-ip":
                        client_host = h_val.decode().strip()
                        break
                scope["client"] = [client_host, 0]
        await self.app(scope, receive, send)


def main() -> None:
    try:

        def _graceful_exit(sig: int, frame: FrameType | None) -> None:
            raise SystemExit(0)

        signal.signal(signal.SIGINT, _graceful_exit)
        signal.signal(signal.SIGTERM, _graceful_exit)
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
                "proxy_headers": getattr(args, "proxy_headers", False),
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
                    else:
                        warmed_config.uds = None
                        warmed_config.host = args.host or "127.0.0.1"
                        warmed_config.port = args.port or 8000
                    
                    # Recreate Server with patched config (socket binding is determined at run time)
                    server = uvicorn.Server(warmed_config)
                    server.run()
                elif warmed_server is not None:
                    # Legacy fallback: patch server.config directly (may not work for UDS)
                    _prof_log("[PROF] Using Deep-Warmed uvicorn Server (legacy).")
                    if args.uds:
                        warmed_server.config.uds = args.uds
                    else:
                        warmed_server.config.host = args.host or "127.0.0.1"
                        warmed_server.config.port = args.port or 8000
                    warmed_server.run()
                else:
                    _prof_log("[PROF] warmed_server is None, falling back to uvicorn.run()")
                    uvicorn.run(**config_kwargs)
            except Exception as e:
                _prof_log(f"[PROF] Execution Error: {e}")
                uvicorn.run(**config_kwargs)
            finally:
                profiler.disable()
                with open("/tmp/worker.prof_log", "w") as f:
                    ps = pstats.Stats(profiler, stream=f).sort_stats("cumulative")
                    ps.print_stats()

    except Exception as e:
        sys.stderr.write(f"FATAL WORKER CRASH: {e}\n")
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
