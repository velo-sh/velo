import argparse
import os
import sys
import uvicorn
import signal

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
            run_kwargs["proxy_headers"] = True
            run_kwargs["forwarded_allow_ips"] = "*"
            
        # 6. Execution
        uvicorn.run(**run_kwargs)
    except Exception as e:
        # Emergency logging for startup failures
        try:
            with open(f"/tmp/worker_error_{os.getpid()}.log", "w") as f:
                f.write(f"FATAL: {e}\n")
                import traceback
                traceback.print_exc(file=f)
        except: pass
        sys.exit(1)

if __name__ == "__main__":
    main()
