import argparse
import os
import sys
import uvicorn
import signal
import traceback
import tempfile
import importlib

class UDSProxyMiddleware:
    """
    Titanium Fix: Ensures scope['client'] is not None on UDS connections.
    
    Uvicorn's ProxyHeadersMiddleware (and some frameworks) skip X-Forwarded-For 
    processing if the connection is via UDS because scope['client'] is None.
    
    This middleware simulates a localhost client if forwarding headers are present,
    thereby allowing downstream middlewares to correctly identify the real client.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and scope.get("client") is None:
            # Check for common proxy headers in scope headers (list of tuples)
            headers = scope.get("headers", [])
            has_proxy_headers = any(k.lower() in (b"x-forwarded-for", b"x-real-ip") for k, v in headers)
            
            if has_proxy_headers:
                # Inject a dummy local client to satisfy uvicorn/framework checks
                # format: (host, port)
                scope["client"] = ("127.0.0.1", 0)
        await self.app(scope, receive, send)

def main():
    try:
        # 1. Signal Hygiene
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

        # 2. Argument Parsing
        parser = argparse.ArgumentParser(description="Velo Worker Launcher")
        parser.add_argument("--app", required=True)
        parser.add_argument("--uds")
        parser.add_argument("--host")
        parser.add_argument("--port", type=int)
        parser.add_argument("--proxy-headers", action="store_true", dest="proxy_headers")
        args = parser.parse_args()
        
        # 3. ImportShield Activation (Titanium Isolation)
        # SSOT: Import directly from shield module (Phase 10.0)
        try:
            from .shield import ImportShield
            ImportShield.activate()
        except ImportError:
            # Fallback if running outside of package context (though unlikely for launcher)
            # Try to find it if it was installed by main.py (if invoked via main? No, launcher starts first)
            # Actually, launcher imports shield, shield sets env var.
            pass

        # 4. Surgical Path Sanitization (RFC-0014 - SSOT)
        # Prevent the launcher's directory from shadowing user modules
        
        # We need VeloPaths here, but it might not be imported yet if we do it early.
        # But we do it before uvicorn.run().
        # Actually, let's keep the import close to usage if possible, or top level.
        # Since we are inside main(), we can import here or assume top-level (later).
        # Let's import locally to avoid circular deps if any, though paths/constants are strictly low-level.
        try:
            from .paths import VeloPaths
            VeloPaths.sanitize_sys_path(__file__)
        except ImportError:
            # Fallback for direct invocation without package structure
            pass


        # 5. Uvicorn Configuration
        # Load app if we need to wrap it for UDS IP preservation
        app = args.app
        if args.uds and getattr(args, "proxy_headers", False):
            try:
                from uvicorn.config import Config
                config = Config(app=args.app)
                app = config.loaded_app
                app = UDSProxyMiddleware(app)
            except Exception as e:
                print(f"Warning: Could not wrap app for UDS IP preservation: {e}", file=sys.stderr)
                # Fallback to original app string
                app = args.app

        run_kwargs = {
            "app": app,
            "log_level": "info",
        }
        
        if args.uds:
            run_kwargs["uds"] = args.uds
        if args.host:
            run_kwargs["host"] = args.host
        if args.port is not None:
            run_kwargs["port"] = args.port
        
        # Load Configuration (SSOT)
        from .settings import VeloConfig
        from .paths import VeloPaths
        velo_config = VeloConfig.load_from_env()

        if getattr(args, "proxy_headers", False):
            # SEC-P0-004: Unsafe proxy headers bypass protection
            # Require explicit trust AND a non-empty allowlist.
            # RFC-0011/SEC: Never fallback to "*" for security.
            
            if not velo_config.forwarded_allow_ips:
                print("FATAL: --proxy-headers requires VELO_FORWARDED_ALLOW_IPS list.", file=sys.stderr)
                sys.exit(1)
            
            if not velo_config.trusted_proxy:
                print("FATAL: --proxy-headers requires VELO_TRUSTED_PROXY=1.", file=sys.stderr)
                sys.exit(1)
            
            run_kwargs["proxy_headers"] = True
            run_kwargs["forwarded_allow_ips"] = velo_config.forwarded_allow_ips
            
        # 6. Execution
        uvicorn.run(**run_kwargs)
        
    except Exception as e:
        # Emergency logging for startup failures
        try:
            # SEC-P0-005: Use tempfile API for secure, restrictive (0600) log creation
            fd, _log_path = tempfile.mkstemp(prefix="worker_error_", suffix=".log", dir=tempfile.gettempdir())
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(f"FATAL: {e}\n")
                traceback.print_exc(file=f)
        except Exception as log_exc:
            # Fallback to stderr if file logging fails
            print(f"FAILED TO WRITE EMERGENCY LOG: {log_exc}", file=sys.stderr)
            print(f"ORIGINAL ERROR: {e}", file=sys.stderr)
            traceback.print_exc()
            
        sys.exit(1)

if __name__ == "__main__":
    main()
