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
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10MB


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


class ZygoteTransport:
    """Layer 1: Transport Layer - Handles asyncio-based MessagePack IO."""
    
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.peer_capabilities: List[str] = []

    async def recv(self) -> Optional[Dict]:
        """Receive length-prefixed MessagePack message."""
        try:
            len_data = await self.reader.readexactly(4)
            total_len = struct.unpack('<I', len_data)[0]
            
            if total_len > MAX_MESSAGE_SIZE or total_len < 1:
                return None
            
            version_data = await self.reader.readexactly(1)
            if version_data[0] != PROTOCOL_VERSION:
                return None
            
            payload_len = total_len - 1
            data = await self.reader.readexactly(payload_len)
            return unpacker(data)
        except Exception as e:
            LogUtils.debug_log(f"Transport Recv Error: {e}")
            return None

    async def send(self, msg: Dict):
        """Send length-prefixed MessagePack message."""
        try:
            payload = packer(msg)
            total_len = 1 + len(payload)
            header = struct.pack('<I', total_len)
            version = bytes([PROTOCOL_VERSION])
            self.writer.write(header + version + payload)
            await self.writer.drain()
        except Exception as e:
            LogUtils.debug_log(f"Transport Send Error: {e}")

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except: pass


class CommandRouter:
    """Layer 2: Control Plane - Decorator-based command dispatching."""
    
    def __init__(self):
        self.handlers = {}

    def handler(self, command_name: str):
        def decorator(func):
            self.handlers[command_name] = func
            return func
        return decorator

    async def dispatch(self, server: 'ZygoteServer', cmd: Any) -> Dict:
        """
        Dispatch command to handler. 
        Enforces pure Map-based (Dict) protocol for simplicity.
        """
        try:
            if not isinstance(cmd, dict):
                return {"type": "Error", "message": f"Malformed command format: {type(cmd)}, expected dict"}
            
            cmd_type = cmd.get("type")
            if not cmd_type:
                return {"type": "Error", "message": "Missing 'type' field in command"}

            handler = self.handlers.get(cmd_type)
            if not handler:
                return {"type": "Error", "message": f"Unknown command: {cmd_type}"}
            
            return await handler(server, cmd)
        except Exception as e:
            LogUtils.debug_log(f"Dispatch Error: {e}")
            return {"type": "Error", "message": f"Handler error: {e}"}


class WorkerRegistry:
    """Layer 3: State Management - Tracks worker lifecycle."""
    
    def __init__(self, worker_ttl: int = 3600):
        self.workers: Dict[int, Tuple[float, Any]] = {} # pid -> (start_time, metadata)
        self.worker_ttl = worker_ttl
        self.lock = threading.Lock()

    def add(self, pid: int, metadata: Any = None):
        with self.lock:
            self.workers[pid] = (time.time(), metadata)

    def remove(self, pid: int):
        with self.lock:
            self.workers.pop(pid, None)

    def is_alive(self, pid: int) -> bool:
        with self.lock:
            return pid in self.workers

    def get_stats(self) -> Dict:
        with self.lock:
            return {
                "count": len(self.workers),
                "pids": list(self.workers.keys())
            }

    @staticmethod
    def start_guardian(parent_pid: int, ttl: int):
        """Guardian thread to prevent orphans."""
        def guardian():
            start_time = time.time()
            while True:
                if os.getppid() != parent_pid: 
                    # Supervisor lost - terminate immediately
                    os._exit(1)
                if ttl > 0 and (time.time() - start_time) > ttl: 
                    # TTL expired
                    os._exit(1)
                time.sleep(1) # Reduced to 1s for immediate response (H-11 compliance)
        t = threading.Thread(target=guardian, daemon=True)
        t.start()

    def kill_all(self):
        """Emergency cleanup of all workers."""
        with self.lock:
            pids = list(self.workers.keys())
        for pid in pids:
            try: os.kill(pid, 9)
            except: pass
        with self.lock:
            self.workers.clear()

    def reap_stale(self):
        """Cleanup logic for timed-out or missing workers."""
        now = time.time()
        to_remove = []
        with self.lock:
            for pid, (start_time, _) in self.workers.items():
                if now - start_time > self.worker_ttl:
                    to_remove.append(pid)
        
        for pid in to_remove:
            LogUtils.log(f"Reaping stale worker: {pid}")
            try:
                os.kill(pid, 9)
            except: pass
            self.remove(pid)


class ReinitHooks:
    """Layer 3: Hook-based Re-initialization system."""
    
    def __init__(self):
        self.hooks = []

    def register(self, hook_func):
        self.hooks.append(hook_func)

    def run_all(self):
        for hook in self.hooks:
            try:
                hook()
            except Exception as e:
                LogUtils.debug_log(f"Hook Error: {e}")

# Global hooks registry
reinit_hooks = ReinitHooks()

def hook_security():
    """SecurityHook: FD hygiene and random reseed."""
    import random
    import resource
    # Whitelist-based cleanup of inherited file descriptors.
    try:
        keep_fds = {0, 1, 2}
        try:
            current_fds = set(int(fd) for fd in os.listdir('/proc/self/fd'))
            for fd in current_fds:
                if fd not in keep_fds:
                    try: os.close(fd)
                    except OSError: pass
        except:
            max_fd = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
            if max_fd == resource.RLIM_INFINITY: max_fd = 4096
            os.closerange(3, max_fd)
    except: pass

    random.seed()
    try:
        import secrets
        secrets.token_bytes(1)
    except: pass
    
    try:
        import ssl
        ssl._create_default_https_context = ssl.create_default_context
    except: pass
    
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    try: signal.set_wakeup_fd(-1)
    except: pass

def hook_computing():
    """ComputingHook: OpenMP and CUDA reset."""
    try:
        cpu_count = os.cpu_count() or 4
        os.environ['OMP_NUM_THREADS'] = str(cpu_count)
        os.environ['MKL_NUM_THREADS'] = str(cpu_count)
        os.environ['OPENBLAS_NUM_THREADS'] = str(cpu_count)
    except: pass 

def hook_telemetry():
    """TelemetryHook: Reset spans/trace context."""
    # Not yet implemented in legacy, added for future-proofing
    pass

reinit_hooks.register(hook_security)
reinit_hooks.register(hook_computing)
reinit_hooks.register(hook_telemetry)


def post_fork_reinit():
    """RFC-0011 6A.2: Reset child process state using Hooks Registry."""
    reinit_hooks.run_all()


class ForkHandler:
    """Handles the forking logic and child process environment setup."""

    @staticmethod
    def handle_fork(
        cmd: Dict[str, Any],
        worker_registry: WorkerRegistry,
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
                worker_registry.worker_ttl
            )
            return 0 # Should not be reached
        else:
            # Parent Process
            worker_registry.add(pid)
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
            WorkerRegistry.start_guardian(os.getppid(), worker_ttl)

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


# Global router for Command Dispatch
router = CommandRouter()

class ZygoteServer:
    """Layer 2: App Layer - Orchestrates the Zygote service."""

    def __init__(self, socket_path: str, preload: List[str] = None, idle_timeout: int = 300, worker_ttl: int = 3600):
        # RFC-0011 D.1: Support abstract sockets (@ -> \0)
        self.is_abstract = socket_path.startswith('@')
        if self.is_abstract:
            self.socket_path = '\0' + socket_path[1:]
        else:
            self.socket_path = socket_path
            
        self.idle_timeout = idle_timeout
        self.worker_registry = WorkerRegistry(worker_ttl)
        self.preload = preload or []
        self._preloaded_modules: List[str] = []
        self.memory_limit_mb = 1024 # 1GB default limit for Zygote process

    async def start(self):
        """Start the Zygote server using asyncio."""
        try:
            LogUtils.log(f"Starting Refactored Zygote (PID: {os.getpid()})")
            
            # RAII Reaper Chain: Monitor our own parent (the supervisor)
            # If the supervisor dies, we MUST die to prevent orphan leaks.
            WorkerRegistry.start_guardian(os.getppid(), 0)
            
            self._setup_signals()
            self._preload_modules()
            
            if check_cuda_initialized():
                LogUtils.log("CRITICAL: CUDA initialized in Zygote! Shutting down.")
                sys.exit(1)
            
            # Start background tasks
            asyncio.create_task(self._resource_guard())
            
            await self._run_loop()
        except Exception as e:
            LogUtils.debug_log(f"Server Startup Error: {e}")
            traceback.print_exc()
            sys.exit(1)

    def _setup_signals(self):
        loop = asyncio.get_event_loop()
        def handle_chld():
            loop.call_soon_threadsafe(lambda: asyncio.create_task(self._async_reap()))
        
        try:
            signal.signal(signal.SIGCHLD, lambda s, f: handle_chld())
        except ValueError:
            # Not in main thread, skip signal setup
            pass
            
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    async def _async_reap(self):
        """Async-safe zombie reaping."""
        self.worker_registry.reap_stale()
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid <= 0: break
                self.worker_registry.remove(pid)
            except ChildProcessError: break
            except: break

    def _preload_modules(self):
        for module in self.preload:
            try:
                __import__(module)
                if module not in self._preloaded_modules:
                    self._preloaded_modules.append(module)
                LogUtils.log(f"Pre-loaded: {module}")
            except ImportError as e:
                LogUtils.log(f"Warning: Failed to pre-load {module}: {e}")

    async def _resource_guard(self):
        """Layer 3: Resource Quotas - Monitor memory usage."""
        import resource
        while True:
            await asyncio.sleep(30)
            try:
                # Watch RSS (kilobytes)
                usage_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                if sys.platform != 'darwin': usage_kb = usage_kb # Already KB on Linux
                else: usage_kb = usage_kb // 1024 # B to KB on macOS
                
                usage_mb = usage_kb // 1024
                if usage_mb > self.memory_limit_mb:
                    LogUtils.log(f"Memory quota exceeded ({usage_mb}MB > {self.memory_limit_mb}MB). Requesting restart.")
                    # In a production environment, this would signal the supervisor to restart.
                    # For now, we allow the next IDLE timeout to handle it or shutdown.
            except: pass

    async def _run_loop(self):
        if not self.is_abstract:
            path = Path(self.socket_path)
            if path.exists(): path.unlink()
            
        server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)
        LogUtils.log("Zygote IPC Layer Ready.")
        
        async with server:
            try:
                await asyncio.wait_for(server.serve_forever(), timeout=self.idle_timeout)
            except (asyncio.TimeoutError, KeyboardInterrupt):
                LogUtils.log("Zygote Idle Timeout.")
            finally:
                LogUtils.log("Shutting down Zygote - Cleaning up workers.")
                self.worker_registry.kill_all() # RFC-0011 6A.1: Prevent orphan leaks

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        transport = ZygoteTransport(reader, writer)
        try:
            # 1. Send Ready
            await transport.send({"type": "Ready"})
            
            while True:
                cmd = await transport.recv()
                if not cmd: break
                
                response = await router.dispatch(self, cmd)
                if response:
                    await transport.send(response)
                    if isinstance(cmd, dict) and cmd.get("type") == "Shutdown":
                        asyncio.get_event_loop().stop()
                        break
        finally:
            await transport.close()


@router.handler("Handshake")
async def handle_handshake(server: ZygoteServer, cmd: Dict) -> Dict:
    """Protocol Handshake and Capability alignment."""
    server_version = PROTOCOL_VERSION
    capabilities = ["map-protocol", "async-reaper", "resource-guard", "hook-reinit"]
    return {
        "type": "Handshake",
        "version": server_version,
        "capabilities": capabilities
    }

@router.handler("Fork")
async def handle_fork(server: ZygoteServer, cmd: Dict) -> Dict:
    script_path = cmd.get("script_path", "")
    if not script_path or not Path(script_path).exists():
        return {"type": "Error", "message": f"Script not found: {script_path}"}
    
    valid, err = PathValidator.validate(script_path)
    if not valid:
        return {"type": "Error", "message": err}

    worker_pid = ForkHandler.handle_fork(cmd, server.worker_registry, server._preloaded_modules)
    
    if cmd.get("async_mode"):
        return {"type": "Forked", "worker_pid": worker_pid, "exit_code": None}
    else:
        # Sync mode: Wait for exit
        try:
            pid, status = os.waitpid(worker_pid, 0)
            exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
            server.worker_registry.remove(worker_pid)
            return {"type": "Forked", "worker_pid": worker_pid, "exit_code": exit_code}
        except ChildProcessError:
            return {"type": "Forked", "worker_pid": worker_pid, "exit_code": 0}

@router.handler("WaitWorker")
async def handle_wait_worker(server: ZygoteServer, cmd: Dict) -> Dict:
    pid = cmd.get("worker_pid")
    timeout = cmd.get("timeout_secs")
    if not server.worker_registry.is_alive(pid):
        return {"type": "WorkerExited", "worker_pid": pid, "exit_code": 0}
    
    try:
        start_time = time.time()
        while True:
            w_pid, status = os.waitpid(pid, os.WNOHANG)
            if w_pid == pid:
                server.worker_registry.remove(pid)
                return {"type": "WorkerExited", "worker_pid": pid, "exit_code": os.WEXITSTATUS(status)}
            if timeout and (time.time() - start_time) > timeout:
                return {"type": "Error", "message": "Wait timeout"}
            await asyncio.sleep(0.05)
    except ChildProcessError:
        server.worker_registry.remove(pid)
        return {"type": "WorkerExited", "worker_pid": pid, "exit_code": 0}

@router.handler("SignalWorker")
async def handle_signal(server: ZygoteServer, cmd: Dict) -> Dict:
    pid, sig = cmd.get("worker_pid"), cmd.get("signal")
    try:
        os.kill(pid, sig)
        return {"type": "Ack"}
    except:
        return {"type": "Error", "message": "Process not found"}

@router.handler("WorkerStatus")
async def handle_status(server: ZygoteServer, cmd: Dict) -> Dict:
    pid = cmd.get("worker_pid")
    alive = False
    try:
        os.kill(pid, 0)
        alive = True
    except:
        server.worker_registry.remove(pid)
    
    return {"type": "WorkerInfo", "worker_pid": pid, "is_running": alive, "uptime_secs": 0}

@router.handler("Shutdown")
async def handle_shutdown(server: ZygoteServer, cmd: Dict) -> Dict:
    LogUtils.log("Graceful Shutdown Initiated.")
    return {"type": "Ack"}

@router.handler("Status")
async def handle_zy_status(server: ZygoteServer, cmd: Dict) -> Dict:
    return {
        "type": "Status",
        "pid": os.getpid(),
        "preload": server._preloaded_modules
    }


def zygote_main(socket_path: str, preload: List[str], idle_timeout: int = 300, worker_ttl: int = 3600):
    """Main entry point for Zygote process."""
    server = ZygoteServer(socket_path, preload, idle_timeout, worker_ttl)
    asyncio.run(server.start())


def check_cuda_initialized() -> bool:
    """RFC-0011 6A.3: Enhanced check for CUDA library footprint."""
    if 'torch' in sys.modules:
        import torch
        if torch.cuda.is_initialized(): return True
    if 'tensorflow' in sys.modules: return True
    
    try:
        with open('/proc/self/maps', 'r') as f:
            content = f.read()
            if 'libcuda.so' in content or 'libcudart.so' in content: return True
    except: pass
    
    return 'cuda' in sys.modules


if __name__ == "__main__":
    os.environ['OMP_NUM_THREADS'] = '1'
    import argparse
    parser = argparse.ArgumentParser(description="Velo Zygote Process")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--preload", nargs="*", default=[])
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--worker-ttl", type=int, default=3600)
    args = parser.parse_args()
    
    zygote_main(args.socket, args.preload, args.timeout, args.worker_ttl)
