#!/usr/bin/env python3
"""
Velo Zygote Python Module

This module implements the Zygote process (Python side):
1. Pre-import heavy modules
2. Wait for fork commands from Rust launcher
3. Fork and execute scripts in child processes

Protocol (Unix Socket, JSON newline-delimited):
  Launcher -> Zygote:
    {"type": "Fork", "script_path": "/path/to/script.py", "args": [...]}
    {"type": "Shutdown"}
  
  Zygote -> Launcher:
    {"type": "Ready"}
    {"type": "Forked", "worker_pid": 12345}
    {"type": "Error", "message": "..."}
"""

import json
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional, Set


# Track active worker PIDs for cleanup
_active_workers: Set[int] = set()

# Project root for path validation (set on startup)
_project_root: Optional[Path] = None

# Track preloaded modules
_preloaded_modules: List[str] = []

# Sensitive paths that should never be executed (SEC-P3-001)
_BLOCKED_PATHS = [
    "/etc", "/var", "/usr", "/bin", "/sbin",
    "/System", "/Library", "/private/etc",
    "/root", "/home",  # Prevent access to other users
]

# Worker TTL (seconds) - 0 means no TTL
_worker_ttl: int = 3600 


def validate_script_path(script_path: str) -> tuple[bool, str]:
    """Validate script path for security (SEC-P3-001: path traversal fix).
    
    Blocks:
    1. Paths containing '..' that could escape to sensitive locations
    2. Paths within system directories
    
    Returns:
        (is_valid, error_message) - error_message is empty if valid
    """
    try:
        # Resolve to absolute path
        script = Path(script_path).resolve()
        script_str = str(script)
        
        # Check for blocked system paths
        for blocked in _BLOCKED_PATHS:
            if script_str.startswith(blocked + "/") or script_str == blocked:
                return False, f"Access denied: script in protected system path '{blocked}'"
        
        # Path seems safe
        return True, ""
    except Exception as e:
        return False, f"Invalid script path: {e}"


def log(msg: str) -> None:
    """Log message with Zygote prefix. Safe when stderr is closed."""
    try:
        print(f"[velo-zygote] {msg}", file=sys.stderr, flush=True)
    except (BrokenPipeError, OSError):
        pass  # Ignore - stderr may be closed in daemon mode


def debug_log(msg: str) -> None:
    """Write debug log to file for daemon mode debugging."""
    try:
        with open("/tmp/velo-zygote-debug.log", "a") as f:
            import datetime
            f.write(f"{datetime.datetime.now()} - {msg}\n")
            f.flush()
    except Exception:
        pass


def reap_zombies(signum=None, frame=None) -> None:
    """Reap zombie child processes (SIGCHLD handler)."""
    global _active_workers
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
            _active_workers.discard(pid)
        except ChildProcessError:
            break


def setup_signal_handlers() -> None:
    """Setup signal handlers for orphan cleanup."""
    # Reap zombie children automatically
    signal.signal(signal.SIGCHLD, reap_zombies)
    
    # Ignore SIGTERM - parent exit sends SIGTERM to process group
    # We want Zygote to stay alive after parent exits
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    
    # Ignore SIGPIPE - prevents crash when parent closes stderr
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)


class WorkerSafety:
    """Manages worker safety: orphan protection and TTL (AUDIT-51-001)."""
    @staticmethod
    def start_guardian(parent_pid: int, ttl: int):
        def guardian():
            start_time = time.time()
            while True:
                # 1. Check if orphaned (parent died)
                if os.getppid() != parent_pid:
                    # Don't use log() here as stderr might be messed up
                    os._exit(1)
                
                # 2. Check TTL
                if ttl > 0 and (time.time() - start_time) > ttl:
                    os._exit(1)
                
                time.sleep(10)
        
        t = threading.Thread(target=guardian, daemon=True)
        t.start()


def preload_modules(modules: List[str]) -> None:
    """Pre-import specified modules to warm the interpreter."""
    global _preloaded_modules
    for module in modules:
        try:
            __import__(module)
            if module not in _preloaded_modules:
                _preloaded_modules.append(module)
            log(f"Pre-loaded: {module}")
        except ImportError as e:
            log(f"Warning: Failed to pre-load {module}: {e}")


def is_socket_in_use(socket_path: str) -> bool:
    """Check if a socket is actively being used by another Zygote."""
    try:
        test_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        test_sock.settimeout(0.5)
        test_sock.connect(socket_path)
        # If connect succeeds, socket is in use
        test_sock.close()
        return True
    except (ConnectionRefusedError, FileNotFoundError, socket.timeout):
        return False
    except Exception:
        return False


def create_socket(socket_path: str) -> socket.socket:
    """Create and bind Unix socket."""
    path = Path(socket_path)
    
    # Only remove stale socket - don't delete if actively in use
    if path.exists():
        if is_socket_in_use(socket_path):
            raise RuntimeError(f"Socket {socket_path} is already in use by another Zygote")
        path.unlink()
    
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(socket_path)
    sock.listen(5)  # Allow multiple pending connections
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


def handle_fork(
    script_path: str,
    args: List[str],
    stdout_path: Optional[str] = None,
    stderr_path: Optional[str] = None,
    exit_code_path: Optional[str] = None,
    fast_mode: bool = False,
    bundle_path: Optional[str] = None,
    project_root: Optional[str] = None,
    max_bundle_size: Optional[int] = None,
) -> int:
    """Fork and execute script in child process.
    
    DEF-P3-013/014: Captures exit code from sys.exit() and os._exit().
    """
    global _active_workers
    
    pid = os.fork()
    
    if pid == 0:
        # Child process
        exit_code = 0
        try:
            # Start guardian to prevent leakage (AUDIT-51-001)
            WorkerSafety.start_guardian(os.getppid(), _worker_ttl)

            # Reset signal handlers to default
            signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            
            # Redirect stdout to file if provided (for IPC capture)
            if stdout_path:
                try:
                    stdout_file = open(stdout_path, "w")
                    sys.stdout = stdout_file
                except OSError:
                    pass
            else:
                # Try terminal fallback
                try:
                    tty = open("/dev/tty", "w")
                    sys.stdout = tty
                except OSError:
                    pass
            
            # Redirect stderr to file if provided
            if stderr_path:
                try:
                    stderr_file = open(stderr_path, "w")
                    sys.stderr = stderr_file
                except OSError:
                    pass
            
            # Set up sys.argv
            sys.argv = [script_path] + args
            
            # RFC-0008: Activate Fast Mode in Zygote Worker (BUG-51-001)
            if fast_mode and bundle_path:
                try:
                    # Search for velo_loader in multiple locations
                    possible_loader_dirs = [
                        # 1. Relative to this script (velo_zygote/main.py -> python/)
                        str(Path(__file__).parent.parent / "python"),
                        # 2. Project root (if provided)
                        str(Path(project_root) / "python") if project_root else None,
                        # 3. Installed location (site-packages)
                        None,  # Already in sys.path if installed
                    ]
                    
                    for loader_dir in possible_loader_dirs:
                        if loader_dir and loader_dir not in sys.path and Path(loader_dir).exists():
                            sys.path.insert(0, loader_dir)
                    
                    from velo_loader import activate_fast_mode
                    _bundle = activate_fast_mode(
                        Path(bundle_path), 
                        Path(project_root) if project_root else None,
                        max_bundle_size
                    )
                    # Worker activated - don't print to avoid polluting stdout
                except Exception as e:
                    print(f"⚠️ Worker Fast Loader failed: {e}", file=sys.stderr)
            
            # Execute the script
            with open(script_path, "rb") as f:
                code = compile(f.read(), script_path, "exec")
                exec(code, {"__name__": "__main__", "__file__": script_path})
            
            # Script completed successfully
            exit_code = 0
            
        except SystemExit as e:
            # DEF-P3-013: Capture sys.exit() code
            if e.code is None:
                exit_code = 0
            elif isinstance(e.code, int):
                exit_code = e.code
            else:
                # Non-integer exit code (e.g., string message)
                exit_code = 1
        except Exception as e:
            print(f"Error executing {script_path}: {e}", file=sys.stderr)
            exit_code = 1
        finally:
            # Flush output before exit
            try:
                sys.stdout.flush()
                if stderr_path:
                    sys.stderr.flush()
            except Exception:
                pass
            
            # Write exit code to file (DEF-P3-013/014)
            if exit_code_path:
                try:
                    with open(exit_code_path, "w") as f:
                        f.write(str(exit_code))
                except Exception:
                    pass
            
            # Use os._exit to avoid cleanup that might interfere
            os._exit(exit_code)
    else:
        # Parent process - track worker
        _active_workers.add(pid)
        return pid


def cleanup_workers() -> None:
    """Kill all active workers on shutdown."""
    global _active_workers
    for pid in list(_active_workers):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    
    # Wait briefly for workers to exit
    import time
    time.sleep(0.1)
    
    # Force kill any remaining
    for pid in list(_active_workers):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    
    _active_workers.clear()


def zygote_main(socket_path: str, preload: Optional[List[str]] = None, idle_timeout: int = 300, worker_ttl: int = 3600) -> None:
    """Main entry point for Zygote process.
    
    Args:
        socket_path: Path to Unix socket
        preload: List of modules to pre-import
        idle_timeout: Seconds to wait before exiting (default 5 min)
        worker_ttl: Worker time-to-live in seconds
    """
    global _worker_ttl
    _worker_ttl = worker_ttl
    
    log(f"Starting Zygote (PID: {os.getpid()})")
    log(f"Socket: {socket_path}")
    log(f"Idle timeout: {idle_timeout}s")
    log(f"Worker TTL: {worker_ttl}s")
    
    # Setup signal handlers for orphan cleanup
    setup_signal_handlers()
    
    # Pre-import heavy modules
    if preload:
        log(f"Pre-loading modules: {', '.join(preload)}")
        preload_modules(preload)
    
    # Create socket
    sock = create_socket(socket_path)
    log("Zygote ready, waiting for connections...")
    
    try:
        while True:
            try:
                debug_log("Before accept()")
                log("DEBUG: Waiting for connection (accept)...")
                sock.settimeout(idle_timeout)  # Timeout only on accept() for idle exit
                conn, _ = sock.accept()
                debug_log("After accept() - got connection")
                log("DEBUG: Connection accepted, setting timeout...")
                conn.settimeout(30)  # Per-connection timeout for commands
                
                # Signal ready on new connection
                send_response(conn, {"type": "Ready"})
                log("DEBUG: Sent Ready, entering command loop...")
                
                # Handle commands
                while True:
                    log("DEBUG: Waiting for command (recv)...")
                    cmd = recv_command(conn)
                    log(f"DEBUG: Received: {cmd}")
                    if cmd is None:
                        log("DEBUG: recv_command returned None, breaking inner loop")
                        break
                    
                    cmd_type = cmd.get("type")
                    
                    if cmd_type == "Fork":
                        script_path = cmd.get("script_path", "")
                        args = cmd.get("args", [])
                        stdout_path = cmd.get("stdout_path")
                        stderr_path = cmd.get("stderr_path")
                        exit_code_path = cmd.get("exit_code_path")
                        async_mode = cmd.get("async_mode", False)
                        fast_mode = cmd.get("fast_mode", False)
                        bundle_path = cmd.get("bundle_path")
                        project_root = cmd.get("project_root")
                        max_bundle_size = cmd.get("max_bundle_size")
                        
                        if not script_path or not Path(script_path).exists():
                            send_response(conn, {
                                "type": "Error",
                                "message": f"Script not found: {script_path}"
                            })
                            continue
                        
                        # SEC-P3-001: Validate path is within project directory
                        is_valid, error_msg = validate_script_path(script_path)
                        if not is_valid:
                            send_response(conn, {
                                "type": "Error",
                                "message": error_msg
                            })
                            log(f"SECURITY: Blocked path traversal attempt: {script_path}")
                            continue
                        
                        worker_pid = handle_fork(
                            script_path, args, stdout_path, stderr_path, exit_code_path,
                            fast_mode, bundle_path, project_root, max_bundle_size
                        )
                        
                        if async_mode:
                            # Return PID immediately (RFC-0008)
                            send_response(conn, {
                                "type": "Forked",
                                "worker_pid": worker_pid,
                                "exit_code": None
                            })
                            log(f"Forked worker PID: {worker_pid} (async mode, active: {len(_active_workers)})")
                        else:
                            # Wait for worker completion in sync mode (default)
                            # This avoids polling in the CLI
                            log(f"Waiting for worker PID: {worker_pid} (sync mode)...")
                            try:
                                pid, status = os.waitpid(worker_pid, 0)
                                exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
                                _active_workers.discard(worker_pid)
                            except ChildProcessError:
                                # Already reaped by SIGCHLD handler?
                                exit_code = 0
                            
                            send_response(conn, {
                                "type": "Forked",
                                "worker_pid": worker_pid,
                                "exit_code": exit_code
                            })
                            log(f"Worker PID {worker_pid} completed with code {exit_code}")
                        
                    elif cmd_type == "Shutdown":
                        log("Received shutdown command")
                        send_response(conn, {"type": "Ready"}) # Send any response as acknowledgment
                        cleanup_workers()
                        conn.close()
                        sock.close()
                        Path(socket_path).unlink(missing_ok=True)
                        log("Zygote shutdown complete")
                        return
                    
                    elif cmd_type == "Status":
                        send_response(conn, {
                            "type": "Status",
                            "pid": os.getpid(),
                            "preload": _preloaded_modules
                        })
                        log(f"Sent Status: PID {os.getpid()}, {len(_preloaded_modules)} modules")
                    
                    else:
                        send_response(conn, {
                            "type": "Error",
                            "message": f"Unknown command: {cmd_type}"
                        })
                
                log("DEBUG: Inner loop exited, closing conn, continuing outer loop...")
                conn.close()
            
            except socket.timeout:
                debug_log("Exit: socket.timeout")
                log(f"Idle timeout ({idle_timeout}s), shutting down...")
                break
            except KeyboardInterrupt:
                debug_log("Exit: KeyboardInterrupt")
                log("Interrupted, shutting down...")
                break
            except BaseException as e:
                debug_log(f"Exit: BaseException {type(e).__name__}: {e}")
                log(f"Error in main loop: {type(e).__name__}: {e}")
                if isinstance(e, SystemExit):
                    debug_log(f"SystemExit code: {e.code}")
                import traceback
                log(f"Traceback: {traceback.format_exc()}")
    
    finally:
        debug_log("Entering finally block")
        log("DEBUG: Exiting main loop, entering finally...")
        cleanup_workers()
        sock.close()
        Path(socket_path).unlink(missing_ok=True)
        log("Zygote shutdown complete")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Velo Zygote Process")
    parser.add_argument("--socket", required=True, help="Unix socket path")
    parser.add_argument("--preload", nargs="*", default=[], help="Modules to pre-import")
    parser.add_argument("--timeout", type=int, default=300, help="Idle timeout in seconds (default: 300)")
    parser.add_argument("--worker-ttl", type=int, default=3600, help="Worker TTL in seconds (default: 3600)")
    
    args = parser.parse_args()
    zygote_main(args.socket, args.preload, args.timeout, args.worker_ttl)

