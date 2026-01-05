#!/usr/bin/env python3
"""
Velo Zygote Python Module (Refactored Phase 6.2)

This module implements the Zygote process (Python side) using an Object-Oriented architecture.
It eliminates global mutable state and encapsulates process management.

Protocol: MessagePack with length prefix + version byte (ADV-1)
  - 4-byte little-endian length (includes version + payload)
  - 1-byte protocol version (0x01)
  - MessagePack payload

Architecture:
  ZygoteServer: Main service responding to socket commands.
  WorkerManager: Manages child process lifecycle and reaping.
  ForkHandler: Handles the complexity of forking and environment setup.
"""

import os
import signal
import socket
import struct
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import List, Optional, Set, Dict, Any, Tuple

# ============================================================================
# Protocol Constants (ADV-1 + DEF-61-004)
# ============================================================================
PROTOCOL_VERSION = 0x01
MAX_MESSAGE_SIZE = 1024 * 1024  # 1MB security limit


# ============================================================================
# Socket Path Functions (DEF-61-004: Protocol Socket Isolation)
# ============================================================================

# Red Line #1: Path length limit with 4-byte margin from 108 Unix limit
SOCKET_PATH_LIMIT = 104

def get_socket_dir() -> Path:
    """Get the user-isolated socket directory.
    
    DEF-61-004: Uses XDG_RUNTIME_DIR or falls back to /tmp/velo-{uid}
    Directory has 0700 permissions for security.
    
    Red Line #1: Path Length Circuit Breaker
    Unix sockets have a 108-character path limit. We use 104 as the threshold
    to leave margin for the socket filename. If exceeded, fallback to /tmp.
    """
    uid = os.getuid()
    
    # 1. Try XDG_RUNTIME_DIR (preferred on Linux)
    xdg_dir = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_dir:
        dir_path = Path(xdg_dir) / "velo"
        test_path = dir_path / "velo-zygote-v01.sock"
        if len(str(test_path)) <= SOCKET_PATH_LIMIT and ensure_socket_dir(dir_path):
            return dir_path
    
    # 2. Try user-isolated temp directory
    import tempfile
    user_dir = Path(tempfile.gettempdir()) / f"velo-{uid}"
    test_path = user_dir / "velo-zygote-v01.sock"
    # Red Line #1: Check path length BEFORE ensuring directory
    if len(str(test_path)) <= SOCKET_PATH_LIMIT and ensure_socket_dir(user_dir):
        return user_dir
    
    # 3. Fallback to /tmp (for macOS with long $TMPDIR paths)
    # Red Line #1: /tmp fallback when path too long
    if len(str(test_path)) > SOCKET_PATH_LIMIT:
        print(f"⚠️ $TMPDIR path too long (>{SOCKET_PATH_LIMIT} chars), falling back to /tmp", file=sys.stderr)
    fallback_dir = Path("/tmp") / f"velo-{uid}"
    ensure_socket_dir(fallback_dir)
    return fallback_dir


def ensure_socket_dir(dir_path: Path) -> bool:
    """Ensure socket directory exists with 0700 permissions.
    
    Red Line #2 & #6: Double Permission Verification
    After setting permissions, we MUST verify the mode is exactly 0700.
    If umask interferes and permissions are wrong, we log a warning.
    """
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        # Set 0700 permissions (owner only)
        os.chmod(dir_path, 0o700)
        
        # Red Line #2/#6: Double verification - confirm mode is 0700
        actual_mode = os.stat(dir_path).st_mode & 0o777
        if actual_mode != 0o700:
            print(
                f"⚠️ SECURITY: Socket dir has insecure permissions: {oct(actual_mode)} (expected 0700)",
                file=sys.stderr
            )
            # Continue but warn - umask may have interfered
        
        return True
    except (OSError, PermissionError):
        return False


def get_versioned_socket_path() -> Path:
    """Get the versioned socket path for this protocol version.
    
    DEF-61-004: Format: {socket_dir}/velo-zygote-v{PROTOCOL_VERSION:02x}.sock
    """
    return get_socket_dir() / f"velo-zygote-v{PROTOCOL_VERSION:02x}.sock"

# ============================================================================
# MessagePack Import with Pure Python Fallback (ADV-3)
# ============================================================================
_USING_PURE_PYTHON_MSGPACK = False

try:
    # 1. Try high-performance C extension first
    import msgpack
    packer = lambda msg: msgpack.packb(msg, use_bin_type=True)
    unpacker = lambda data: msgpack.unpackb(data, raw=False)

except (ImportError, OSError) as e:
    # 2. Fallback to vendored Pure Python implementation
    _fallback_loaded = False
    
    # Search paths for vendored umsgpack.py
    _search_paths = [
        # Relative to this file: velo_zygote/main.py -> python/velo/_vendor
        Path(__file__).parent.parent / "python" / "velo" / "_vendor",
        # If running from project root
        Path.cwd() / "python" / "velo" / "_vendor",
        # If installed as package
        Path(__file__).parent / "_vendor",
    ]
    
    for _vendor_path in _search_paths:
        if (_vendor_path / "umsgpack.py").exists():
            if str(_vendor_path) not in sys.path:
                sys.path.insert(0, str(_vendor_path))
            try:
                import umsgpack
                
                sys.stderr.write("[Velo] ⚠️  Warning: fast 'msgpack' extension failed to load.\n")
                sys.stderr.write("[Velo]    Falling back to pure Python implementation (slower IPC).\n")
                sys.stderr.write("[Velo]    Run: pip install msgpack  (requires C compiler)\n")
                sys.stderr.flush()
                
                packer = lambda msg: umsgpack.packb(msg)
                unpacker = lambda data: umsgpack.unpackb(data)
                _USING_PURE_PYTHON_MSGPACK = True
                _fallback_loaded = True
                break
            except ImportError:
                continue
    
    if not _fallback_loaded:
        sys.stderr.write(f"[Velo] ❌ Error: msgpack not available and fallback failed.\n")
        sys.stderr.write(f"[Velo]    Original error: {e}\n")
        sys.stderr.write(f"[Velo]    Searched: {[str(p) for p in _search_paths]}\n")
        sys.stderr.write(f"[Velo]    Run: pip install msgpack\n")
        sys.exit(1)


# Sensitive paths that should never be executed (SEC-P3-001)
_BLOCKED_PATHS = [
    "/etc", "/var", "/usr", "/bin", "/sbin",
    "/System", "/Library", "/private/etc",
    "/root", "/home",
]


class LogUtils:
    """Utilities for safe logging in a daemonized process."""
    
    @staticmethod
    def log(msg: str) -> None:
        """Log message with Zygote prefix."""
        try:
            print(f"[velo-zygote] {msg}", file=sys.stderr, flush=True)
        except (BrokenPipeError, OSError):
            pass

    @staticmethod
    def debug_log(msg: str) -> None:
        """Write debug log to file for daemon mode debugging."""
        try:
            with open("/tmp/velo-zygote-debug.log", "a") as f:
                import datetime
                f.write(f"{datetime.datetime.now()} - {msg}\n")
                f.flush()
        except Exception:
            pass


class PathValidator:
    """Security validation for script paths."""

    @staticmethod
    def validate(script_path: str) -> Tuple[bool, str]:
        """
        Validate script path for security (SEC-P3-001).
        Blocks paths containing '..' or pointing to system directories.
        """
        try:
            script = Path(script_path).resolve()
            script_str = str(script)
            
            for blocked in _BLOCKED_PATHS:
                if script_str.startswith(blocked + "/") or script_str == blocked:
                    return False, f"Access denied: script in protected system path '{blocked}'"
            
            return True, ""
        except Exception as e:
            return False, f"Invalid script path: {e}"


class WorkerManager:
    """Manages child worker processes and reaping."""

    def __init__(self, worker_ttl: int = 3600):
        self._active_workers: Set[int] = set()
        self._worker_ttl = worker_ttl
        self._lock = threading.Lock()

    def add_worker(self, pid: int):
        with self._lock:
            self._active_workers.add(pid)

    def remove_worker(self, pid: int):
        with self._lock:
            self._active_workers.discard(pid)

    def reap_zombies(self, signum, frame):
        """SIGCHLD handler to reap dead children."""
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
                self.remove_worker(pid)
            except ChildProcessError:
                break

    def cleanup_all(self):
        """Kill all workers on shutdown."""
        with self._lock:
            pids = list(self._active_workers)
        
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        
        time.sleep(0.1)
        
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        
        with self._lock:
            self._active_workers.clear()

    @staticmethod
    def start_guardian(parent_pid: int, ttl: int):
        """Child process guardian to prevent orphans (AUDIT-51-001)."""
        def guardian():
            start_time = time.time()
            while True:
                if os.getppid() != parent_pid:
                    os._exit(1)
                if ttl > 0 and (time.time() - start_time) > ttl:
                    os._exit(1)
                time.sleep(10)
        
        t = threading.Thread(target=guardian, daemon=True)
        t.start()


class ForkHandler:
    """Handles the forking logic and child process environment setup."""

    @staticmethod
    def handle_fork(
        cmd: Dict[str, Any],
        worker_manager: WorkerManager,
        preloaded_modules: List[str]
    ) -> int:
        """
        Fork and execute script.
        Returns worker PID (parent) or exits (child).
        """
        script_path = cmd.get("script_path", "")
        args = cmd.get("args", [])
        stdout_path = cmd.get("stdout_path")
        stderr_path = cmd.get("stderr_path")
        exit_code_path = cmd.get("exit_code_path")
        fast_mode = cmd.get("fast_mode", False)
        bundle_path = cmd.get("bundle_path")
        project_root = cmd.get("project_root")
        max_bundle_size = cmd.get("max_bundle_size")

        pid = os.fork()

        if pid == 0:
            # Child Process
            ForkHandler._child_process(
                script_path, args, stdout_path, stderr_path, exit_code_path,
                fast_mode, bundle_path, project_root, max_bundle_size,
                worker_manager._worker_ttl
            )
            return 0 # Should not be reached
        else:
            # Parent Process
            worker_manager.add_worker(pid)
            return pid

    @staticmethod
    def _child_process(
        script_path: str, args: List[str], stdout_path: Optional[str],
        stderr_path: Optional[str], exit_code_path: Optional[str],
        fast_mode: bool, bundle_path: Optional[str], project_root: Optional[str],
        max_bundle_size: Optional[int], worker_ttl: int
    ):
        exit_code = 0
        try:
            # 1. Start Guardian
            WorkerManager.start_guardian(os.getppid(), worker_ttl)

            # 2. Reset Signals
            signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)

            # 3. I/O Redirection
            ForkHandler._redirect_io(stdout_path, stderr_path)

            # 4. Setup Sys Args
            sys.argv = [script_path] + args

            # 5. Fast Mode Activation
            if fast_mode and bundle_path:
                ForkHandler._activate_fast_mode(bundle_path, project_root, max_bundle_size)

            # 6. Execute Script
            with open(script_path, "rb") as f:
                code = compile(f.read(), script_path, "exec")
                exec(code, {"__name__": "__main__", "__file__": script_path})
            
            exit_code = 0

        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        except Exception as e:
            print(f"Error executing {script_path}: {e}", file=sys.stderr)
            exit_code = 1
        finally:
            ForkHandler._cleanup_child(stdout_path, stderr_path, exit_code_path, exit_code)
            os._exit(exit_code)

    @staticmethod
    def _redirect_io(stdout_path: Optional[str], stderr_path: Optional[str]):
        if stdout_path:
            try:
                sys.stdout = open(stdout_path, "w")
            except OSError: pass
        else:
            try:
                sys.stdout = open("/dev/tty", "w")
            except OSError: pass

        if stderr_path:
            try:
                sys.stderr = open(stderr_path, "w")
            except OSError: pass

    @staticmethod
    def _activate_fast_mode(bundle_path: str, project_root: Optional[str], max_size: Optional[int]):
        try:
            # Search for velo_loader
            possible_loader_dirs = [
                str(Path(__file__).parent.parent / "python"),
                str(Path(project_root) / "python") if project_root else None,
            ]
            for loader_dir in possible_loader_dirs:
                if loader_dir and loader_dir not in sys.path and Path(loader_dir).exists():
                    sys.path.insert(0, loader_dir)

            from velo_loader import activate_fast_mode
            activate_fast_mode(
                Path(bundle_path), 
                Path(project_root) if project_root else None,
                max_size
            )
        except Exception as e:
            print(f"⚠️ Worker Fast Loader failed: {e}", file=sys.stderr)

    @staticmethod
    def _cleanup_child(stdout_path, stderr_path, exit_code_path, exit_code):
        try:
            sys.stdout.flush()
            if stderr_path: sys.stderr.flush()
        except: pass

        if exit_code_path:
            try:
                with open(exit_code_path, "w") as f:
                    f.write(str(exit_code))
            except: pass


class ZygoteServer:
    """Main Zygote Service."""

    def __init__(self, socket_path: str, preload: List[str] = None, idle_timeout: int = 300, worker_ttl: int = 3600):
        self.socket_path = socket_path
        self.idle_timeout = idle_timeout
        self.worker_manager = WorkerManager(worker_ttl)
        self.preload = preload or []
        self._preloaded_modules: List[str] = []
        self.workers: Dict[int, Tuple[float, Any]] = {}  # pid -> (start_time, process)

    def start(self):
        try:
            LogUtils.log(f"Starting ZygoteServer (PID: {os.getpid()})")
            self._setup_signals()
            self._preload_modules()
            self._run_loop()
        except Exception:
            traceback.print_exc()
            sys.exit(1)

    def _setup_signals(self):
        signal.signal(signal.SIGCHLD, self.worker_manager.reap_zombies)
        signal.signal(signal.SIGTERM, signal.SIG_IGN) # Ignore SIGTERM, let parent kill via socket or SIGKILL
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    def _preload_modules(self):
        for module in self.preload:
            try:
                __import__(module)
                if module not in self._preloaded_modules:
                    self._preloaded_modules.append(module)
                LogUtils.log(f"Pre-loaded: {module}")
            except ImportError as e:
                LogUtils.log(f"Warning: Failed to pre-load {module}: {e}")

    def _create_socket(self) -> socket.socket:
        path = Path(self.socket_path)
        if path.exists():
             # Basic stale checking
            if self._is_socket_in_use():
                raise RuntimeError(f"Socket {self.socket_path} in use")
            path.unlink()
        
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(self.socket_path)
        sock.listen(5)
        return sock

    def _is_socket_in_use(self) -> bool:
        try:
            test = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            test.settimeout(0.5)
            test.connect(self.socket_path)
            test.close()
            return True
        except:
            return False

    def _run_loop(self):
        sock = self._create_socket()
        LogUtils.log("Zygote ready.")
        
        try:
            while True:
                try:
                    sock.settimeout(self.idle_timeout)
                    conn, _ = sock.accept()
                    conn.settimeout(30)
                    self._handle_connection(conn)
                except socket.timeout:
                    LogUtils.log(f"Idle timeout ({self.idle_timeout}s).")
                    break
        except KeyboardInterrupt:
            LogUtils.log("Interrupted.")
        finally:
            self._cleanup(sock)

    def _handle_connection(self, conn: socket.socket):
        try:
            self._send_response(conn, {"type": "Ready"})
            while True:
                cmd = self._recv_command(conn)
                if not cmd: break
                
                response = self._process_command(cmd)
                if response:
                    self._send_response(conn, response)
                    if cmd.get("type") == "Shutdown":
                        raise KeyboardInterrupt # Trigger graceful shutdown
        except Exception as e:
            LogUtils.debug_log(f"Connection error: {e}")
        finally:
            conn.close()

    def _process_command(self, cmd: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        cmd_type = cmd.get("type")

        if cmd_type == "Fork":
            return self._cmd_fork(cmd)
        elif cmd_type == "Status":
            return {
                "type": "Status",
                "pid": os.getpid(),
                "preload": self._preloaded_modules
            }
        elif cmd_type == "WaitWorker":
            worker_pid = cmd.get("worker_pid")
            timeout_secs = cmd.get("timeout_secs")
            return self._handle_wait_worker(worker_pid, timeout_secs)
        elif cmd_type == "SignalWorker":
            worker_pid = cmd.get("worker_pid")
            signal_num = cmd.get("signal")
            return self._handle_signal_worker(worker_pid, signal_num)
        elif cmd_type == "WorkerStatus":
            worker_pid = cmd.get("worker_pid")
            return self._handle_worker_status(worker_pid)
        elif cmd_type == "Shutdown":
             return {"type": "Ack"}
        else:
            return {"type": "Error", "message": f"Unknown command: {cmd_type}"}

    def _handle_wait_worker(self, worker_pid: int, timeout_secs: Optional[int]) -> Dict:
        """Wait for a worker to exit (Optimized for CI stability)"""
        if worker_pid not in self.workers:
            # Check if it's already reaped by SIGCHLD handler
            return {"type": "WorkerExited", "worker_pid": worker_pid, "exit_code": 0}
        
        try:
            start_time = time.time()
            while True:
                # Check if process is dead
                pid, status = os.waitpid(worker_pid, os.WNOHANG)
                if pid == worker_pid:
                    exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
                    self.workers.pop(worker_pid, None)
                    return {"type": "WorkerExited", "worker_pid": worker_pid, "exit_code": exit_code}
                
                # Check for timeout
                if timeout_secs is not None and (time.time() - start_time) > timeout_secs:
                    return {"type": "Error", "message": "Wait timeout"}
                
                # Sleep briefly to avoid busy waiting
                time.sleep(0.05)
        except ChildProcessError:
            self.workers.pop(worker_pid, None)
            return {"type": "WorkerExited", "worker_pid": worker_pid, "exit_code": 0}
        except Exception as e:
            return {"type": "Error", "message": f"Wait failed: {e}"}

    def _handle_signal_worker(self, worker_pid: int, signal_num: int) -> Dict:
        """Send signal to a worker"""
        if worker_pid not in self.workers:
            return {"type": "Error", "message": f"Worker {worker_pid} not found"}
        
        try:
            os.kill(worker_pid, signal_num)
            return {"type": "Ack"}
        except ProcessLookupError:
            self.workers.pop(worker_pid, None)
            return {"type": "Error", "message": "Process not found"}

    def _handle_worker_status(self, worker_pid: int) -> Dict:
        """Query worker status"""
        if worker_pid not in self.workers:
            return {
                "type": "WorkerInfo",
                "worker_pid": worker_pid,
                "is_running": False,
                "uptime_secs": 0
            }
        
        start_time, _ = self.workers[worker_pid]
        try:
            os.kill(worker_pid, 0)
            is_running = True
        except ProcessLookupError:
            is_running = False
            self.workers.pop(worker_pid, None)
        
        uptime = int(time.time() - start_time) if is_running else 0
        return {
            "type": "WorkerInfo",
            "worker_pid": worker_pid,
            "is_running": is_running,
            "uptime_secs": uptime
        }


    def _cmd_fork(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        script_path = cmd.get("script_path", "")
        if not script_path or not Path(script_path).exists():
             return {"type": "Error", "message": f"Script not found: {script_path}"}
        
        valid, err = PathValidator.validate(script_path)
        if not valid:
            LogUtils.log(f"SECURITY BLOCK: {err}")
            return {"type": "Error", "message": err}

        worker_pid = ForkHandler.handle_fork(cmd, self.worker_manager, self._preloaded_modules)
        async_mode = cmd.get("async_mode", False)

        # Track the worker
        self.workers[worker_pid] = (time.time(), None)

        if async_mode:
            LogUtils.log(f"Forked worker PID: {worker_pid} (async)")
            return {"type": "Forked", "worker_pid": worker_pid, "exit_code": None}
        else:
            LogUtils.log(f"Waiting for worker PID: {worker_pid} (sync)")
            # Sync wait
            try:
                pid, status = os.waitpid(worker_pid, 0)
                exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
                self.worker_manager.remove_worker(worker_pid)
                self.workers.pop(worker_pid, None)
            except ChildProcessError:
                exit_code = 0 
            
            return {"type": "Forked", "worker_pid": worker_pid, "exit_code": exit_code}


    def _recv_command(self, conn: socket.socket) -> Optional[Dict]:
        """Receive MessagePack message with length prefix and version byte (ADV-1)."""
        try:
            # Read 4-byte length prefix (includes version + payload)
            len_data = conn.recv(4)
            if len(len_data) < 4:
                return None
            total_len = struct.unpack('<I', len_data)[0]
            
            # Security: Max message size
            if total_len > MAX_MESSAGE_SIZE:
                LogUtils.log(f"Message too large: {total_len} bytes")
                return None
            
            # Need at least version byte
            if total_len < 1:
                LogUtils.log("Message too small to contain version byte")
                return None
            
            # Read version byte (ADV-1)
            version_data = conn.recv(1)
            if len(version_data) < 1:
                return None
            version = version_data[0]
            
            if version != PROTOCOL_VERSION:
                LogUtils.log(f"Protocol version mismatch: got {version}, expected {PROTOCOL_VERSION}")
                return None
            
            # Read payload (total_len - 1 for version byte)
            payload_len = total_len - 1
            data = b""
            while len(data) < payload_len:
                chunk = conn.recv(min(4096, payload_len - len(data)))
                if not chunk:
                    return None
                data += chunk
            
            # Unpack with rmp_serde compatibility
            raw_result = unpacker(data)
            
            # ADV-2: TRACE logging
            LogUtils.debug_log(f"[IPC RECV] {repr(raw_result)}")
            
            return self._smart_unpack(raw_result)
        except Exception as e:
            LogUtils.debug_log(f"Recv error: {e}")
            return None

    def _smart_unpack(self, result: Any) -> Dict:
        """Normalize rmp_serde output to dict format.
        
        rmp_serde serializes internally tagged enums as flat tuples:
        - ['Ready'] (unit variant)
        - ['Fork', script_path, args, async_mode, ...] (struct variant as tuple)
        - {'type': 'Ready'} (dict - already correct format)
        """
        # If already a dict with type, return as-is
        if isinstance(result, dict):
            return result
        
        # If it's a list/tuple from rmp_serde
        if isinstance(result, (list, tuple)) and len(result) >= 1:
            type_name = str(result[0])
            
            # Unit variant: ['Ready'], ['Shutdown'], ['Status'], ['Ack']
            if len(result) == 1:
                return {"type": type_name}
            
            # Fork variant has 11 positional fields (after type name):
            # script_path, args, async_mode, stdout_path, stderr_path, 
            # exit_code_path, fast_mode, bundle_path, project_root, max_bundle_size
            if type_name == "Fork" and len(result) >= 2:
                return {
                    "type": "Fork",
                    "script_path": result[1] if len(result) > 1 else "",
                    "args": result[2] if len(result) > 2 else [],
                    "async_mode": result[3] if len(result) > 3 else False,
                    "stdout_path": result[4] if len(result) > 4 else None,
                    "stderr_path": result[5] if len(result) > 5 else None,
                    "exit_code_path": result[6] if len(result) > 6 else None,
                    "fast_mode": result[7] if len(result) > 7 else False,
                    "bundle_path": result[8] if len(result) > 8 else None,
                    "project_root": result[9] if len(result) > 9 else None,
                    "max_bundle_size": result[10] if len(result) > 10 else None,
                }
            
            # Forked response: ['Forked', worker_pid, exit_code]
            if type_name == "Forked" and len(result) >= 2:
                return {
                    "type": "Forked",
                    "worker_pid": result[1] if len(result) > 1 else 0,
                    "exit_code": result[2] if len(result) > 2 else None,
                }
            
            # Status response: ['Status', pid, preload]  
            if type_name == "Status" and len(result) >= 2:
                return {
                    "type": "Status",
                    "pid": result[1] if len(result) > 1 else 0,
                    "preload": result[2] if len(result) > 2 else [],
                }
            
            # Error response: ['Error', message]
            if type_name == "Error" and len(result) >= 2:
                return {
                    "type": "Error",
                    "message": str(result[1]) if len(result) > 1 else "",
                }
            
            # Fallback for unknown variants with fields
            return {"type": type_name}
        
        # If it's a string, treat as type name
        if isinstance(result, str):
            return {"type": result}
        
        # Fallback: wrap in dict
        return {"type": str(result)}

    def _send_response(self, conn: socket.socket, resp: Dict):
        """Send MessagePack message with length prefix and version byte (ADV-1)."""
        payload = packer(resp)  # Uses global packer for fallback support
        
        # ADV-2: TRACE logging
        LogUtils.debug_log(f"[IPC SEND] {repr(resp)}")
        
        # Length includes version byte + payload
        total_len = 1 + len(payload)
        header = struct.pack('<I', total_len)
        version = bytes([PROTOCOL_VERSION])
        conn.sendall(header + version + payload)

    def _cleanup(self, sock: socket.socket):
        LogUtils.log("Cleaning up...")
        self.worker_manager.cleanup_all()
        sock.close()
        Path(self.socket_path).unlink(missing_ok=True)
        LogUtils.log("Shutdown complete.")


def zygote_main(socket_path: str, preload: List[str], idle_timeout: int = 300, worker_ttl: int = 3600):
    """Main entry point for Zygote process."""
    server = ZygoteServer(socket_path, preload, idle_timeout, worker_ttl)
    server.start()



if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Velo Zygote Process")
    parser.add_argument("--socket", required=True, help="Unix socket path")
    parser.add_argument("--preload", nargs="*", default=[], help="Modules to pre-import")
    parser.add_argument("--timeout", type=int, default=300, help="Idle timeout in seconds (default: 300)")
    parser.add_argument("--worker-ttl", type=int, default=3600, help="Worker TTL in seconds (default: 3600)")
    
    args = parser.parse_args()
    zygote_main(args.socket, args.preload, args.timeout, args.worker_ttl)
