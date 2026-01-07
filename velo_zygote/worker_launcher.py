#!/usr/bin/env python3
"""
Velo Standardized Worker Launcher (Phase 3A)
Architect recommendation: Move from dynamic scripts to preset modules.
"""
import sys
import os
import argparse
import uvicorn

def main():
    parser = argparse.ArgumentParser(description="Velo Standardized Worker")
    parser.add_argument("--app", required=True, help="ASGI app import path (module:app)")
    parser.add_argument("--uds", help="Unix Domain Socket path")
    parser.add_argument("--host", help="TCP Host (if not using UDS)")
    parser.add_argument("--port", type=int, help="TCP Port (if not using UDS)")
    parser.add_argument("--proxy-headers", action="store_true", help="Enable X-Forwarded-* headers")
    
    # Parse args
    args = parser.parse_args()
    
    # Add current working directory to path for app imports
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    
    run_kwargs = {
        "app": args.app,
        "log_level": "info",
    }
    
    if args.uds:
        run_kwargs["uds"] = args.uds
    else:
        run_kwargs["host"] = args.host or "127.0.0.1"
        run_kwargs["port"] = args.port or 8000
    
    if args.proxy_headers:
        run_kwargs["proxy_headers"] = True
        run_kwargs["forwarded_allow_ips"] = "*"
        
    # Execute uvicorn
    try:
        print(f"[WORKER] Launching uvicorn for {args.app}")
        uvicorn.run(**run_kwargs)
        print("[WORKER] uvicorn.run finished normally")
    except Exception as e:
        import traceback
        with open("/tmp/worker_launch_error.log", "a") as f:
            f.write(f"PID {os.getpid()}: CRASH: {e}\n")
            f.write(traceback.format_exc())
            f.write("\n")
        print(f"[WORKER] CRASH: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
