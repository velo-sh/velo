import argparse
import os
import sys
import uvicorn
import signal
import traceback

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
        # Search for the existing shield instance in meta_path to avoid module name conflicts
        for finder in sys.meta_path:
            if finder.__class__.__name__ == "ImportShield":
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
        if args.port:
            run_kwargs["port"] = args.port
        
        if getattr(args, "proxy_headers", False):
            # SEC-P0-004: Unsafe proxy headers bypass protection
            # require explicit trust via environment or non-wildcard IPs
            trusted = os.environ.get("VELO_TRUSTED_PROXY") == "1"
            allowed_ips = os.environ.get("VELO_FORWARDED_ALLOW_IPS", "")
            
            if not (trusted or allowed_ips):
                print("FATAL: --proxy-headers requires VELO_TRUSTED_PROXY=1 or VELO_FORWARDED_ALLOW_IPS list.", file=sys.stderr)
                sys.exit(1)
            
            run_kwargs["proxy_headers"] = True
            run_kwargs["forwarded_allow_ips"] = allowed_ips if allowed_ips else "*"
            
        # 6. Execution
        uvicorn.run(**run_kwargs)
        
    except Exception as e:
        # Emergency logging for startup failures
        log_path = f"/tmp/worker_error_{os.getpid()}.log"
        try:
            # SEC-P0-005: Use secure permissions (0600) for emergency logs
            fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
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
