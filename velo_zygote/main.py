#!/usr/bin/env python3
"""
Velo Zygote Python Module

This module implements the Zygote process (Python side):
1. Pre-import heavy modules
2. Wait for fork commands from Rust launcher
3. Fork and execute scripts in child processes

Protocol (Unix Socket, JSON newline-delimited):
  Launcher → Zygote:
    {"type": "Fork", "script_path": "/path/to/script.py", "args": [...]}
    {"type": "Shutdown"}
  
  Zygote → Launcher:
    {"type": "Ready"}
    {"type": "Forked", "worker_pid": 12345}
    {"type": "Error", "message": "..."}
"""

import json
import os
import socket
import sys
from pathlib import Path
from typing import List, Optional


def log(msg: str) -> None:
    """Log message with Zygote prefix."""
    print(f"[velo-zygote] {msg}", file=sys.stderr, flush=True)


def preload_modules(modules: List[str]) -> None:
    """Pre-import specified modules to warm the interpreter."""
    for module in modules:
        try:
            __import__(module)
            log(f"Pre-loaded: {module}")
        except ImportError as e:
            log(f"Warning: Failed to pre-load {module}: {e}")


def create_socket(socket_path: str) -> socket.socket:
    """Create and bind Unix socket."""
    # Remove existing socket if present
    path = Path(socket_path)
    if path.exists():
        path.unlink()
    
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(socket_path)
    sock.listen(1)
    return sock


def send_response(conn: socket.socket, response: dict) -> None:
    """Send JSON response over socket."""
    msg = json.dumps(response) + "\n"
    conn.sendall(msg.encode("utf-8"))


def recv_command(conn: socket.socket) -> Optional[dict]:
    """Receive JSON command from socket."""
    data = b""
    while b"\n" not in data:
        chunk = conn.recv(1024)
        if not chunk:
            return None
        data += chunk
    
    line = data.decode("utf-8").strip()
    return json.loads(line)


def handle_fork(script_path: str, args: List[str]) -> int:
    """Fork and execute script in child process."""
    pid = os.fork()
    
    if pid == 0:
        # Child process
        try:
            # Set up sys.argv
            sys.argv = [script_path] + args
            
            # Execute the script
            with open(script_path, "rb") as f:
                code = compile(f.read(), script_path, "exec")
                exec(code, {"__name__": "__main__", "__file__": script_path})
            
            sys.exit(0)
        except Exception as e:
            print(f"Error executing {script_path}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Parent process
        return pid


def zygote_main(socket_path: str, preload: Optional[List[str]] = None) -> None:
    """Main entry point for Zygote process."""
    log(f"Starting Zygote (PID: {os.getpid()})")
    log(f"Socket: {socket_path}")
    
    # Pre-import heavy modules
    if preload:
        log(f"Pre-loading modules: {', '.join(preload)}")
        preload_modules(preload)
    
    # Create socket
    sock = create_socket(socket_path)
    log("Zygote ready, waiting for connections...")
    
    while True:
        try:
            conn, _ = sock.accept()
            
            # Signal ready on new connection
            send_response(conn, {"type": "Ready"})
            
            # Handle commands
            while True:
                cmd = recv_command(conn)
                if cmd is None:
                    break
                
                cmd_type = cmd.get("type")
                
                if cmd_type == "Fork":
                    script_path = cmd.get("script_path", "")
                    args = cmd.get("args", [])
                    
                    if not script_path or not Path(script_path).exists():
                        send_response(conn, {
                            "type": "Error",
                            "message": f"Script not found: {script_path}"
                        })
                        continue
                    
                    worker_pid = handle_fork(script_path, args)
                    send_response(conn, {
                        "type": "Forked",
                        "worker_pid": worker_pid
                    })
                    log(f"Forked worker PID: {worker_pid}")
                
                elif cmd_type == "Shutdown":
                    log("Received shutdown command")
                    conn.close()
                    sock.close()
                    Path(socket_path).unlink(missing_ok=True)
                    log("Zygote shutdown complete")
                    return
                
                else:
                    send_response(conn, {
                        "type": "Error",
                        "message": f"Unknown command: {cmd_type}"
                    })
            
            conn.close()
        
        except KeyboardInterrupt:
            log("Interrupted, shutting down...")
            break
        except Exception as e:
            log(f"Error: {e}")
    
    sock.close()
    Path(socket_path).unlink(missing_ok=True)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Velo Zygote Process")
    parser.add_argument("--socket", required=True, help="Unix socket path")
    parser.add_argument("--preload", nargs="*", default=[], help="Modules to pre-import")
    
    args = parser.parse_args()
    zygote_main(args.socket, args.preload)
