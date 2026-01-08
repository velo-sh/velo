import argparse
import os
import sys
import uvicorn
import signal
import traceback
import tempfile

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
        # Search for the existing shield instance in meta_path
        # Use marker attribute check for robustness (getattr)
        for finder in sys.meta_path:
            if getattr(finder, "_is_velo_import_shield", False) or finder.__class__.__name__ == "ImportShield":
                finder.activate()
                os.environ["VELO_ZYGOTE_SHIELD_ACTIVE"] = "1"
                break

        # 4. Surgical Path Sanitization (RFC-0014)
        # Prevent the launcher's directory (velo_zygote/) from shadowing user modules (main.py)
        # by moving it to the end of sys.path.
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir in sys.path:
            sys.path.remove(script_dir)
            sys.path.append(script_dir)
        
        # Ensure CWD is at the front (Standard parity with CPython)
        if os.getcwd() not in sys.path:
            sys.path.insert(0, os.getcwd())

        # 5. Uvicorn Configuration
        run_kwargs = {
            "app": args.app,
            "log_level": "info",
        }
        
        if args.uds:
            run_kwargs["uds"] = args.uds
        if args.host:
            run_kwargs["host"] = args.host
        if args.port is not None:
            run_kwargs["port"] = args.port
        
        if getattr(args, "proxy_headers", False):
            # SEC-P0-004: Unsafe proxy headers bypass protection
            # Require explicit trust AND a non-empty allowlist.
            # RFC-0011/SEC: Never fallback to "*" for security.
            trusted = os.environ.get("VELO_TRUSTED_PROXY") == "1"
            allowed_ips = os.environ.get("VELO_FORWARDED_ALLOW_IPS", "")
            
            if not allowed_ips:
                print("FATAL: --proxy-headers requires VELO_FORWARDED_ALLOW_IPS list.", file=sys.stderr)
                sys.exit(1)
            
            if not trusted:
                print("FATAL: --proxy-headers requires VELO_TRUSTED_PROXY=1.", file=sys.stderr)
                sys.exit(1)
            
            run_kwargs["proxy_headers"] = True
            run_kwargs["forwarded_allow_ips"] = allowed_ips
            
        # 6. Execution
        uvicorn.run(**run_kwargs)
        
    except Exception as e:
        # Emergency logging for startup failures
        try:
            # SEC-P0-005: Use tempfile API for secure, restrictive (0600) log creation
            fd, _log_path = tempfile.mkstemp(prefix="worker_error_", suffix=".log", dir="/tmp")
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
