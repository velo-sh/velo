#!/usr/bin/env python3
"""
Velo Worker Runner - Simplified ASGI Worker
Version: 4.2 (Security Enhanced)
"""

import os
import sys
import socket
import asyncio
import signal
from typing import Any

# Critical environment variables (minimum cleanup list)
_CRITICAL_ENV_VARS = ['LD_PRELOAD', 'DYLD_INSERT_LIBRARIES', 'PYTHONSTARTUP']

def run_worker_with_shared_port(
    app_path: str, 
    host: str, 
    port: int,
    log_level: str = "info"
) -> None:
    """Run ASGI worker with SO_REUSEPORT
    
    Args:
        app_path: ASGI app path in format "module:app"
        host: Host to bind
        port: Port to bind
        log_level: Uvicorn log level
    """
    
    # 0. Minimum security cleanup (only critical vars)
    for var in _CRITICAL_ENV_VARS:
        os.environ.pop(var, None)
    
    # 1. Create new event loop (required after fork)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # 2. Create SO_REUSEPORT socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind((host, port))
    sock.listen(1024)
    sock.set_inheritable(True)
    
    try:
        # 3. Load ASGI app
        app = _load_asgi_app(app_path)
        
        # 4. Configure uvicorn
        from uvicorn import Config, Server
        
        config = Config(
            app=app,
            fd=sock.fileno(),
            loop="asyncio",
            log_level=log_level,
        )
        
        server = Server(config)
        
        # 5. Drop privileges (if running as root)
        _drop_privileges_if_root()
        
        # 6. Run server
        try:
            loop.run_until_complete(server.serve())
        except KeyboardInterrupt:
            pass
        finally:
            loop.close()
    finally:
        # Always clean up socket on error
        sock.close()


def _drop_privileges_if_root() -> None:
    """Drop privileges (if currently root)
    
    Security best practice: avoid running worker as root
    """
    if os.getuid() != 0:
        return  # Not root, no need to drop privileges
    
    try:
        import pwd
        nobody = pwd.getpwnam('nobody')
        
        # Set gid first, then uid (order matters!)
        os.setgid(nobody.pw_gid)
        os.setuid(nobody.pw_uid)
        
        # Verify privilege drop succeeded
        if os.getuid() == 0 or os.getgid() == 0:
            raise RuntimeError("Failed to drop root privileges")
            
    except Exception as e:
        # Privilege drop failure is a critical security issue, must exit
        print(f"CRITICAL: Failed to drop privileges: {e}", file=sys.stderr)
        sys.exit(1)


def _load_asgi_app(app_path: str) -> Any:
    """Load ASGI application
    
    Args:
        app_path: App path in format "module:app"
        
    Returns:
        ASGI application object
        
    Raises:
        ValueError: Invalid app path format
        SystemExit: Failed to load app
    """
    if ':' not in app_path:
        raise ValueError(f"Invalid app path format: {app_path}")
    
    module_name, app_name = app_path.split(':', 1)
    
    try:
        module = __import__(module_name, fromlist=[app_name])
        app = getattr(module, app_name)
        return app
    except (ImportError, AttributeError) as e:
        print(f"ERROR: Failed to load app '{app_path}': {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"UNEXPECTED ERROR loading app: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: worker_runner.py <app:path> <host> <port>")
        sys.exit(1)
    
    run_worker_with_shared_port(sys.argv[1], sys.argv[2], int(sys.argv[3]))
