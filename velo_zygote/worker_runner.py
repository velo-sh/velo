#!/usr/bin/env python3
"""
Velo Worker Runner - Simplified ASGI Worker
Version: 4.2 (Security Enhanced)
"""

import os
import sys
import json
import socket
import asyncio
import signal
from typing import Any

# 最危险的环境变量（最小清理列表）
_CRITICAL_ENV_VARS = ['LD_PRELOAD', 'DYLD_INSERT_LIBRARIES', 'PYTHONSTARTUP']

def run_worker_with_shared_port(
    app_path: str, 
    host: str, 
    port: int,
    log_level: str = "info"
) -> None:
    """运行 ASGI worker with SO_REUSEPORT
    
    Args:
        app_path: ASGI app path in format "module:app"
        host: Host to bind
        port: Port to bind
        log_level: Uvicorn log level
    """
    
    # 0. 最小安全清理（只清理最关键的）
    for var in _CRITICAL_ENV_VARS:
        os.environ.pop(var, None)
    
    # 1. 创建新 event loop (fork 后必须)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # 2. 创建 SO_REUSEPORT socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind((host, port))
    sock.listen(1024)
    sock.set_inheritable(True)
    
    # 3. 加载 ASGI app
    app = _load_asgi_app(app_path)
    
    # 4. 配置 uvicorn
    from uvicorn import Config, Server
    
    config = Config(
        app=app,
        fd=sock.fileno(),
        loop="asyncio",
        log_level=log_level,
    )
    
    server = Server(config)
    
    # 5. 权限下降（如果以 root 运行）
    _drop_privileges_if_root()
    
    # 6. 运行
    try:
        loop.run_until_complete(server.serve())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


def _drop_privileges_if_root() -> None:
    """降低权限（如果当前是 root）
    
    安全最佳实践：避免以 root 身份运行 worker
    """
    if os.getuid() != 0:
        return  # 不是 root，无需降权
    
    try:
        import pwd
        nobody = pwd.getpwnam('nobody')
        
        # 先设置 gid，再设置 uid（顺序重要！）
        os.setgid(nobody.pw_gid)
        os.setuid(nobody.pw_uid)
        
        # 验证降权成功
        if os.getuid() == 0 or os.getgid() == 0:
            raise RuntimeError("Failed to drop root privileges")
            
    except Exception as e:
        # 降权失败是严重安全问题，必须退出
        print(f"CRITICAL: Failed to drop privileges: {e}", file=sys.stderr)
        sys.exit(1)


def _load_asgi_app(app_path: str) -> Any:
    """加载 ASGI 应用
    
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
