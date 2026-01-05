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

import asyncio
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


def post_fork_reinit():
    """
    RFC-0011 6A.2: Reset Python state after fork from Zygote.
    
    This MUST be called immediately after fork() in the child process.
    Failure to call this can result in undefined behavior from inherited
    Zygote state (signal handlers, random seeds, SSL contexts, etc.)
    
    Execution order follows RFC-0011 6A.6 Supplemental Recommendations:
    1. Random Seed (cryptographic safety)
    2. SSL Context (regenerate if needed)
    3. Signal Handlers (reset to default)
    4. OpenMP/BLAS threads (restore for workers)
    """
    import random
    import resource

    # 1. FD Hygiene (RFC-0011 6A.1 / Architect Recommendation)
    # Whitelist-based cleanup of inherited file descriptors.
    # On Linux, we iterate /proc/self/fd for efficiency.
    try:
        keep_fds = {0, 1, 2}
        try:
            # Efficient Linux-specific cleanup
            current_fds = set(int(fd) for fd in os.listdir('/proc/self/fd'))
            for fd in current_fds:
                if fd not in keep_fds:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
        except (FileNotFoundError, PermissionError, OSError):
            # Fallback for macOS or restricted environments
            max_fd = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
            if max_fd == resource.RLIM_INFINITY:
                max_fd = 4096
            os.closerange(3, max_fd)
    except Exception as e:
        # Log to file since stderr might be closed or redirected
        LogUtils.debug_log(f"FD cleanup failed: {e}")

    # 2. Random Seed (cryptographic safety)
    # Fork inherits parent's random state - child must reseed
    random.seed()
    try:
        import secrets
        # Force secrets module to regenerate entropy pool
        _ = secrets.token_bytes(1)
    except ImportError:
        pass
    
    # 2. SSL Context (regenerate if needed)
    # Inherited SSL contexts may have shared state
    try:
        import ssl
        ssl._create_default_https_context = ssl.create_default_context
    except (ImportError, AttributeError):
        pass
    
    # 3. Signal Handlers (reset to default)
    # Zygote has custom handlers that must not affect workers
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    
    # Reset wakeup FD (uvloop/asyncio pollution)
    # If asyncio has installed a wakeup FD in Zygote, child must clear it
    try:
        signal.set_wakeup_fd(-1)
    except (ValueError, OSError):
        # Not set or not supported
        pass
    
    # 4. OpenMP/BLAS threads (restore for workers)
    # Zygote may have set OMP_NUM_THREADS=1 to avoid fork issues
    # Workers should use full CPU for NumPy/BLAS operations
    try:
        cpu_count = os.cpu_count() or 4
        os.environ['OMP_NUM_THREADS'] = str(cpu_count)
        os.environ['MKL_NUM_THREADS'] = str(cpu_count)
        os.environ['OPENBLAS_NUM_THREADS'] = str(cpu_count)
    except Exception:
        pass


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

            # 2. RFC-0011 6A.2: Full post-fork state reset
            # (signals, random seed, SSL context, OMP threads)
            post_fork_reinit()

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

    async def start(self):
        """Start the Zygote server using asyncio."""
        try:
            LogUtils.log(f"Starting Async ZygoteServer (PID: {os.getpid()})")
            self._setup_signals()
            self._preload_modules()
            
            # Architect Recommendation: Command Dispatcher mapping
            self._command_handlers = {
                "Fork": self._handle_fork_cmd,
                "WaitWorker": self._handle_wait_worker_cmd,
                "SignalWorker": self._handle_signal_worker_cmd,
                "WorkerStatus": self._handle_worker_status_cmd,
                "Shutdown": self._handle_shutdown_cmd,
            }
            
            await self._run_loop()
        except Exception:
            traceback.print_exc()
            sys.exit(1)

    def _setup_signals(self):
        # We don't use signal.signal for SIGCHLD with asyncio if possible,
        # but Zygote's child management is still mostly manual waitpid.
        # However, asyncio works better if we don't interfere too much.
        signal.signal(signal.SIGCHLD, self.worker_manager.reap_zombies)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
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

    async def _run_loop(self):
        path = Path(self.socket_path)
        if path.exists():
            if self._is_socket_in_use():
                raise RuntimeError(f"Socket {self.socket_path} in use")
            path.unlink()
            
        server = await asyncio.start_unix_server(
            self._handle_client, 
            path=self.socket_path
        )
        
        LogUtils.log("Zygote ready (async).")
        
        async with server:
            try:
                # Use wait_for to implement idle timeout
                await asyncio.wait_for(server.serve_forever(), timeout=self.idle_timeout)
            except (asyncio.TimeoutError, KeyboardInterrupt):
                LogUtils.log(f"Zygote shutting down (timeout or interrupt).")
            finally:
                await self._cleanup()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle individual client connection using asyncio Streams."""
        try:
            # 1. Send Ready
            await self._send_response(writer, {"type": "Ready"})
            
            while True:
                cmd = await self._recv_command(reader)
                if not cmd:
                    break
                
                # 2. Dispatch command (Finding B2)
                response = await self._dispatch_command(cmd)
                if response:
                    await self._send_response(writer, response)
                    if cmd.get("type") == "Shutdown":
                        # Signal the main loop to exit
                        asyncio.get_event_loop().stop()
                        break
        except Exception as e:
            LogUtils.debug_log(f"Client error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _dispatch_command(self, cmd: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Dispatcher Pattern: Maps type to handler."""
        cmd_type = cmd.get("type")
        handler = self._command_handlers.get(cmd_type)
        
        if handler:
            return await handler(cmd)
        else:
            return {"type": "Error", "message": f"Unknown command: {cmd_type}"}

    async def _handle_fork_cmd(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        return self._cmd_fork(cmd)

    async def _handle_wait_worker_cmd(self, cmd: Dict[str, Any]) -> Dict:
        return self._handle_wait_worker(
            cmd.get("worker_pid"), 
            cmd.get("timeout_secs")
        )

    async def _handle_signal_worker_cmd(self, cmd: Dict[str, Any]) -> Dict:
        return self._handle_signal_worker(
            cmd.get("worker_pid"), 
            cmd.get("signal")
        )

    async def _handle_worker_status_cmd(self, cmd: Dict[str, Any]) -> Dict:
        return self._handle_worker_status(cmd.get("worker_pid"))

    async def _handle_shutdown_cmd(self, cmd: Dict[str, Any]) -> Dict:
        return {"type": "Ack"}

    def _is_socket_in_use(self) -> bool:
        try:
            test = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            test.settimeout(0.5)
            test.connect(self.socket_path)
            test.close()
            return True
        except:
            return False

    def _handle_wait_worker(self, worker_pid: int, timeout_secs: Optional[int]) -> Dict:
        """Wait for worker (Now runs in async context, but waitpid is sync)."""
        if worker_pid not in self.workers:
            return {"type": "WorkerExited", "worker_pid": worker_pid, "exit_code": 0}
        
        try:
            start_time = time.time()
            while True:
                pid, status = os.waitpid(worker_pid, os.WNOHANG)
                if pid == worker_pid:
                    exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
                    self.workers.pop(worker_pid, None)
                    return {"type": "WorkerExited", "worker_pid": worker_pid, "exit_code": exit_code}
                
                if timeout_secs is not None and (time.time() - start_time) > timeout_secs:
                    return {"type": "Error", "message": "Wait timeout"}
                
                # In an async context, we should yield control
                # This is a blocking call, but the patch implies it's okay for now.
                # A more robust async solution would use loop.run_in_executor for os.waitpid
                # or asyncio.create_subprocess_exec with communicate().
                time.sleep(0.05) # Small sleep to prevent busy-waiting
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
        # Standardized Worker Module support (Architect recommendation)
        if not script_path and cmd.get("module_name"):
            # If no script path, we use module execution mode
            pass
        elif not script_path or not Path(script_path).exists():
             return {"type": "Error", "message": f"Script not found: {script_path}"}
        
        if script_path:
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
            try:
                pid, status = os.waitpid(worker_pid, 0)
                exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
                self.worker_manager.remove_worker(worker_pid)
                self.workers.pop(worker_pid, None)
            except ChildProcessError:
                exit_code = 0 
            
            return {"type": "Forked", "worker_pid": worker_pid, "exit_code": exit_code}


    async def _recv_command(self, reader: asyncio.StreamReader) -> Optional[Dict]:
        """Receive MessagePack message using async StreamReader."""
        try:
            len_data = await reader.readexactly(4)
            total_len = struct.unpack('<I', len_data)[0]
            
            if total_len > MAX_MESSAGE_SIZE or total_len < 1:
                LogUtils.debug_log(f"Message too large or too small: {total_len} bytes")
                return None
            
            version_data = await reader.readexactly(1)
            version = version_data[0]
            
            if version != PROTOCOL_VERSION:
                LogUtils.debug_log(f"Protocol version mismatch: got {version}, expected {PROTOCOL_VERSION}")
                return None
            
            payload_len = total_len - 1
            data = await reader.readexactly(payload_len)
            
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

    async def _send_response(self, writer: asyncio.StreamWriter, response: Dict):
        """Send MessagePack message using async StreamWriter."""
        try:
            payload = packer(response)
            # ADV-2: TRACE logging
            LogUtils.debug_log(f"[IPC SEND] {repr(response)}")
            
            total_len = 1 + len(payload)
            header = struct.pack('<I', total_len)
            version = bytes([PROTOCOL_VERSION])
            writer.write(header + version + payload)
            await writer.drain()
        except Exception as e:
            LogUtils.debug_log(f"Send error: {e}")

    async def _cleanup(self):
        LogUtils.log("Cleaning up...")
        self.worker_manager.cleanup_all()
        Path(self.socket_path).unlink(missing_ok=True)
        LogUtils.log("Shutdown complete.")


def zygote_main(socket_path: str, preload: List[str], idle_timeout: int = 300, worker_ttl: int = 3600):
    """Main entry point for Zygote process."""
    server = ZygoteServer(socket_path, preload, idle_timeout, worker_ttl)
    asyncio.run(server.start())




def check_cuda_initialized() -> bool:
    """
    RFC-0011 6A.3: Enhanced check for CUDA/ML library initialization.
    Architect Recommendation: Check library state instead of just sys.modules.
    """
    # 1. Check sys.modules for presence (low overhead)
    if 'torch' in sys.modules:
        try:
            import torch
            # Check if CUDA context is actually initialized
            if torch.cuda.is_initialized():
                return True
        except Exception:
            pass
            
    if 'tensorflow' in sys.modules:
        # TF usually initializes GPU eagerly if imported
        return True
        
    # 2. Check for loaded shared libraries (more robust)
    try:
        # Linux specific library check
        with open('/proc/self/maps', 'r') as f:
            content = f.read()
            if 'libcuda.so' in content or 'libcudart.so' in content:
                return True
    except (FileNotFoundError, OSError):
        pass

    return 'cuda' in sys.modules

if __name__ == "__main__":
    # RFC-0011 6A.3 HPC Pre-flight: Set OMP_NUM_THREADS=1
    # Prevents OpenMP from initializing thread pool in Zygote parent, which hangs on fork.
    # Workers verify this and restore it in post_fork_reinit.
    os.environ['OMP_NUM_THREADS'] = '1'

    import argparse
    
    parser = argparse.ArgumentParser(description="Velo Zygote Process")
    parser.add_argument("--socket", required=True, help="Unix socket path")
    parser.add_argument("--preload", nargs="*", default=[], help="Modules to pre-import")
    parser.add_argument("--timeout", type=int, default=300, help="Idle timeout in seconds (default: 300)")
    parser.add_argument("--worker-ttl", type=int, default=3600, help="Worker TTL in seconds (default: 3600)")
    
    args = parser.parse_args()

    # RFC-0011 6A.3: Warn if CUDA might be initialized by preloads
    if check_cuda_initialized():
        print("[velo-zygote] ⚠️  WARNING: CUDA/Torch/TensorFlow modules detected in Zygote start.", file=sys.stderr)
        print("[velo-zygote]    This is unsafe for forking. Ensure these are NOT imported before Zygote loop.", file=sys.stderr)

    zygote_main(args.socket, args.preload, args.timeout, args.worker_ttl)
