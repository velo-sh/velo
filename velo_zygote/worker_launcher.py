# --- Velo Bootstrap (CRITICAL: MUST BE FIRST) ---
import sys
import os

# DEF-72-C02: Surgical sys.path sanitization to prevent shadowing
# During 'python -m', sys.path[0] is the current directory.
# We MUST remove it before pre-importing critical libraries.
def _sovereign_import(name):
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
import traceback
from typing import Any, Dict

from velo_zygote.utils import LogUtils

class UDSProxyMiddleware:
    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        current_client = scope.get("client")
        is_client_missing = current_client is None or (isinstance(current_client, (list, tuple)) and len(current_client) > 0 and current_client[0] is None)
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
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        parser = argparse.ArgumentParser(description="Velo Worker Launcher")
        parser.add_argument("--app", required=True)
        parser.add_argument("--uds")
        parser.add_argument("--host")
        parser.add_argument("--port", type=int)
        parser.add_argument("--proxy-headers", action="store_true", dest="proxy_headers")
        parser.add_argument("--rsgi", action="store_true")
        args = parser.parse_args()

        from velo_zygote.shield import ImportShield
        from velo_zygote.paths import VeloPaths
        from velo_zygote.settings import VeloConfig
        from velo_zygote import integrity
        
        if args.rsgi:
            from velo_zygote.rsgi import run_rsgi
            ImportShield.activate()
            VeloPaths.sanitize_sys_path(__file__)
            run_rsgi(args.app, args.uds)
        else:
            uvicorn = _sovereign_import("uvicorn")
            ImportShield.activate()
            VeloPaths.sanitize_sys_path(__file__)
            
            config_kwargs = {
                "app": args.app,
                "loop": "auto",
                "http": "auto",
                "lifespan": "on",
                "proxy_headers": getattr(args, "proxy_headers", False),
            }
            if args.uds:
                config_kwargs["uds"] = args.uds
            else:
                config_kwargs["host"] = args.host or "127.0.0.1"
                config_kwargs["port"] = args.port or 8000
            uvicorn.run(**config_kwargs)

    except Exception as e:
        sys.stderr.write(f"FATAL WORKER CRASH: {e}\n")
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
