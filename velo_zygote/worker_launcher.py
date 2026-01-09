import argparse
import os
import sys
import uvicorn
import signal

def main():
    import io
    stderr_capture = io.StringIO()
    # Force stderr capture since parent provided None
    sys.stderr = stderr_capture
    
    # Ensure current working directory is in sys.path
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    # Was: debug_child.log writing logic removed
    """Velo Worker Launcher (Titanium Stabilized)"""
    # 1. Signal Hygiene
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGCHLD):
        try:
            signal.signal(sig, signal.SIG_DFL)
        except: pass

    # 2. Argument Parsing
    parser = argparse.ArgumentParser(description="Velo Worker Launcher")
    parser.add_argument("--app", required=True)
    parser.add_argument("--uds")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--proxy-headers", action="store_true")
    
    args = parser.parse_args()
    
    # 3. Uvicorn Configuration
    run_kwargs = {
        "app": args.app,
        "log_level": "info",
    }
    
    if args.uds:
        run_kwargs["uds"] = args.uds
    if args.host:
        run_kwargs["host"] = args.host
    # Force asyncio to debug fatal crash
    run_kwargs["loop"] = "asyncio"
    if args.port:
        run_kwargs["port"] = args.port
    if args.proxy_headers:
        run_kwargs["proxy_headers"] = True
        run_kwargs["forwarded_allow_ips"] = "*"
        
    # 4. Execution
    # 4. Execution
    try:
        uvicorn.run(**run_kwargs)
    except BaseException as e:
        import traceback
            # Was: debug_child.log writing logic removed
            pass
        raise

if __name__ == "__main__":
    main()
