#!/usr/bin/env python3
import importlib
import json
import os
import signal
import site
import socket
import struct
import sys
import traceback
from typing import Any, Union

PROTOCOL_VERSION = 1

# Configurable via VELO_ZYGOTE_MAX_POOL_SIZE env var (default: 100)
# Can be set in pyproject.toml [tool.velo] zygote_max_pool_size = N
def _get_max_pool_size() -> int:
    try:
        return int(os.environ.get("VELO_ZYGOTE_MAX_POOL_SIZE", "100"))
    except ValueError:
        return 100

MAX_POOL_SIZE = _get_max_pool_size()

# BUG-010: Dangerous environment variables that could enable code injection
# These are NEVER allowed to be set via Fork env overrides
DANGEROUS_ENV_VARS = frozenset([
    # Dynamic linker injection (Linux)
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT",
    # Dynamic linker injection (macOS)
    "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH",
    # Python path hijacking
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
    # Command hijacking
    "PATH",
])

# BUG-001: Default blocked path prefixes for script execution
# Additional paths come from velo_config.blocked_paths if available
DEFAULT_BLOCKED_PATHS = ["/usr", "/bin", "/sbin", "/etc", "/root", "/boot"]

def filter_dangerous_env(env: dict[str, str]) -> dict[str, str]:
    """BUG-010: Filter out dangerous environment variables that could enable injection."""
    filtered = {}
    blocked = []
    for k, v in env.items():
        if k in DANGEROUS_ENV_VARS:
            blocked.append(k)
        else:
            filtered[k] = v
    if blocked:
        sys.stderr.write(f"🛡️ [Security] Blocked dangerous env vars: {blocked}\n")
    return filtered

def validate_script_path(script_path: str) -> tuple[bool, str]:
    """
    BUG-001: Validate script path for security.
    - Blocks directory traversal (..)
    - Blocks execution from system directories
    - Resolves symlinks to prevent escape
    """
    try:
        # 1. Check for directory traversal
        path_parts = script_path.replace("\\", "/").split("/")
        if ".." in path_parts:
            return False, f"Security: Directory traversal detected in '{script_path}'"

        # 2. Resolve to real path (follows symlinks)
        real_path = os.path.realpath(os.path.abspath(script_path))

        # 3. Check against blocked paths
        blocked_paths = DEFAULT_BLOCKED_PATHS
        # Try to get additional blocked paths from velo_config if available
        try:
            from velo_zygote.settings import velo_config
            blocked_paths = velo_config.blocked_paths
        except (ImportError, Exception):
            pass

        for blocked in blocked_paths:
            if real_path.startswith(blocked + "/") or real_path == blocked:
                return False, f"Security: Script in protected system path '{blocked}'"

        return True, ""
    except Exception as e:
        return False, f"Security: Invalid script path: {e}"

def setup_site() -> None:
    """P0: Inject User Virtual Environment into sys.path (Tier 1 Mutation)."""
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        # 1. Add site-packages
        # Standard locations: lib/pythonX.Y/site-packages
        # We allow site.addsitedir to do the heavy lifting of .pth files
        lib_dir = os.path.join(venv, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
        if os.path.exists(lib_dir):
            site.addsitedir(lib_dir)

        # 2. Also try 'lib64' for some Linux distros
        lib64_dir = os.path.join(venv, "lib64", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
        if os.path.exists(lib64_dir):
            site.addsitedir(lib64_dir)

        # 3. Update sys.prefix to allow tools to detect they are "in" the venv
        sys.prefix = venv
        sys.exec_prefix = venv

class IdlePool:
    def __init__(self, target_size: int = 0) -> None:
        self.target_size = target_size
        self.pool: list[tuple[int, int]] = [] # List of (pid, pipe_write_fd)

    def get_count(self) -> int:
        self.pool = [p for p in self.pool if self._is_alive(p[0])]
        return len(self.pool)

    def _is_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def add(self, pid: int, pipe_write_fd: int) -> None:
        self.pool.append((pid, pipe_write_fd))

    def pop(self) -> tuple[Union[int, None], Union[int, None]]:
        while self.pool:
            pid, write_fd = self.pool.pop(0)
            if self._is_alive(pid):
                return pid, write_fd
            try:
                os.close(write_fd)
            except OSError:
                pass
        return None, None

    def shutdown(self) -> None:
        """Kill all workers in the pool."""
        while self.pool:
            pid, write_fd = self.pool.pop(0)
            try:
                os.kill(pid, signal.SIGTERM)
                os.close(write_fd)
            except OSError:
                pass

    def replenish(self, main_sock: Union[socket.socket, None] = None) -> None:
        """
        Refilled the pool to target_size.
        Refactored for P1: This is now called *after* the IPC response is sent,
        so we don't block the Supervisor from receiving the Ack.
        """
        current = self.get_count()
        # Limit replenishment batch size to avoid freezing the loop for too long
        # if the target size is huge (e.g. 100).
        batch_limit = 5
        spawned = 0

        while current < self.target_size and spawned < batch_limit:
            r_fd, w_fd = os.pipe()
            pid = os.fork()
            if pid == 0:
                # --- POOLED WORKER ---
                os.close(w_fd)
                if main_sock:
                    try:
                        main_sock.close()
                    except OSError:
                        pass
                # Reset signals in child
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                self._worker_loop(r_fd)
                sys.exit(0)
            else:
                os.close(r_fd)
                self.add(pid, w_fd)
                current += 1
                spawned += 1

    def _worker_loop(self, pipe_read_fd: int) -> None:
        try:
            header = os.read(pipe_read_fd, 4)
            if not header:
                return
            length = struct.unpack("<I", header)[0]
            payload = b""
            while len(payload) < length:
                chunk = os.read(pipe_read_fd, length - len(payload))
                if not chunk:
                    break
                payload += chunk
            msg = json.loads(payload.decode('utf-8'))
            execute_payload(msg)
        except Exception:
            traceback.print_exc()
        finally:
            os.close(pipe_read_fd)

def execute_payload(msg: dict[str, Any]) -> None:
    app_module = msg.get("module")
    script_path = msg.get("script_path")

    # BUG-010: Filter dangerous environment variables before applying
    env_overrides = msg.get("env", {})
    if env_overrides:
        safe_env = filter_dangerous_env(env_overrides)
        if safe_env:
            os.environ.update(safe_env)
            # Re-apply site packages if VIRTUAL_ENV changed (rare but possible in dynamic stacks)
            if "VIRTUAL_ENV" in safe_env:
                setup_site()

    if app_module:
        if ":" in app_module:
            mod_name, obj_name = app_module.split(":")
            mod = importlib.import_module(mod_name)
            getattr(mod, obj_name)
        else:
            importlib.import_module(app_module)
    elif script_path:
        # BUG-016: Validate script path exists before execution
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f"Script not found: {script_path}")

        # BUG-001: Validate script path for security (traversal, blocked paths)
        is_valid, error_msg = validate_script_path(script_path)
        if not is_valid:
            raise PermissionError(error_msg)

        # HO-004: Inject script directory into sys.path[0] for relative imports
        script_dir = os.path.dirname(os.path.abspath(script_path))
        if sys.path and sys.path[0] != script_dir:
            sys.path.insert(0, script_dir)

        # P0: Inject sys.argv so argparse works in the script
        # argv[0] should be the script path
        sys.argv = [script_path] + msg.get("args", [])

        with open(script_path, "rb") as f:
            code = compile(f.read(), script_path, "exec")
            exec(code, {"__name__": "__main__", "__file__": script_path})

IDLE_POOL = IdlePool()

def handle_shutdown(signum: int, frame: Any) -> None:
    """Graceful shutdown handler for Zygote process."""
    IDLE_POOL.shutdown()
    sys.exit(0)

def bootstrap() -> None:
    setup_site() # P0: Inject venv immediately

    socket_path = os.environ.get("VELO_ZYGOTE_SOCK")
    if not socket_path:
        sys.exit(1)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    # Linux abstract sockets: convert @ prefix to null byte (\0)
    # Rust uses @ as internal convention, Python needs actual null byte
    if socket_path.startswith("@"):
        socket_path = "\0" + socket_path[1:]
    sock.connect(socket_path)

    # RFC-0012 Phase 3: Perfect Signal Orchestration
    # Intercept termination to cleanup pooled workers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Send Ready
    payload = json.dumps({"type": "Ready"}).encode('utf-8')
    total_len = 1 + len(payload)
    sock.sendall(struct.pack("<I", total_len) + struct.pack("B", PROTOCOL_VERSION) + payload)

    while True:
        resp: dict[str, Any] = {}
        try:
            raw_len = sock.recv(4)
            if not raw_len:
                break
            total_len = struct.unpack("<I", raw_len)[0]
            v_buf = sock.recv(1)
            if not v_buf:
                break

            # BUG-012: Handle partial recv properly for truncated messages
            payload_len = total_len - 1
            payload_bytes = b""
            while len(payload_bytes) < payload_len:
                chunk = sock.recv(payload_len - len(payload_bytes))
                if not chunk:
                    raise ConnectionError("Connection closed during message receive")
                payload_bytes += chunk

            try:
                payload_str = payload_bytes.decode('utf-8')
                msg = json.loads(payload_str)
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                # BUG-012: Send error response for malformed JSON instead of crashing
                resp = {"type": "Error", "message": f"Invalid JSON payload: {e}"}
                p = json.dumps(resp).encode('utf-8')
                sock.sendall(struct.pack("<I", 1 + len(p)) + struct.pack("B", PROTOCOL_VERSION) + p)
                continue

            cmd = msg.get("type")
            should_replenish = False
            resp = {}

            if cmd == "Auth":
                resp = {"type": "Ack"}
            elif cmd == "Handshake":
                resp = {"type": "Handshake", "version": PROTOCOL_VERSION, "capabilities": ["v3-shim", "pool"]}
            elif cmd == "Status":
                # Check pool count but don't replenish here to keep Status fast
                resp = {
                    "type": "Status",
                    "pid": os.getpid(),
                    "preload": [],
                    "state": "READY",
                    "preload_done": True,
                    "pool_count": IDLE_POOL.get_count(),
                    "target_pool_size": IDLE_POOL.target_size
                }
                # If we are critically low, maybe we should replenish?
                # Let's rely on explicit ReplenishPool command or post-Fork replenishment.
            elif cmd == "ReplenishPool":
                # BUG-009/011: Validate pool size bounds
                target_count = msg.get("target_count", 0)
                if not isinstance(target_count, int) or target_count < 0:
                    resp = {"type": "Error", "message": f"Invalid target_count: {target_count}. Must be non-negative integer."}
                elif target_count > MAX_POOL_SIZE:
                    resp = {"type": "Error", "message": f"target_count {target_count} exceeds maximum allowed ({MAX_POOL_SIZE})"}
                else:
                    IDLE_POOL.target_size = target_count
                    # Mark for replenishment AFTER response
                    should_replenish = True
                    resp = {"type": "Ack"}
            elif cmd == "Fork":
                pid, pipe_fd = IDLE_POOL.pop()
                if pid is not None and pipe_fd is not None:
                    p = json.dumps(msg).encode('utf-8')
                    os.write(pipe_fd, struct.pack("<I", len(p)) + p)
                    os.close(pipe_fd)
                    resp = {"type": "Forked", "worker_pid": pid, "is_warm": True}
                    # Replenish after assignment
                    should_replenish = True
                else:
                    pid = os.fork()
                    if pid == 0:
                        sock.close()
                        execute_payload(msg)
                        sys.exit(0)
                    resp = {"type": "Forked", "worker_pid": pid, "is_warm": False}
            elif cmd == "Exit" or cmd == "Shutdown":
                break
            else:
                # BUG-015: Return error for unknown commands instead of silent Ack
                resp = {"type": "Error", "message": f"Unknown command type: {cmd}"}

            p = json.dumps(resp).encode('utf-8')
            sock.sendall(struct.pack("<I", 1 + len(p)) + struct.pack("B", PROTOCOL_VERSION) + p)

            # P1: Perform replenishment *after* sending response to unblock Supervisor
            if should_replenish:
                IDLE_POOL.replenish(main_sock=sock)

        except Exception:
            traceback.print_exc()
            break

    # Explicit cleanup on loop exit
    IDLE_POOL.shutdown()
    try:
        sock.close()
    except OSError:
        pass

if __name__ == "__main__":
    bootstrap()
