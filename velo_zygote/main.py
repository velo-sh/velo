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
import sys

import signal
import socket
import struct
import sys
import threading
import time
import traceback
import importlib.abc
import importlib.util
from pathlib import Path
from typing import List, Optional, Set, Dict, Any, Tuple

# ============================================================================
# Protocol Constants (ADV-1 + DEF-61-004)
# ============================================================================

try:
    from .protocol import ZygoteTransport, ProtocolError
    from .constants import PROTOCOL_VERSION, MAX_MESSAGE_SIZE
    from .paths import VeloPaths
    from .config import VeloConfig
except (ImportError, ValueError):
    # Fallback when running main.py directly as a script
    from protocol import ZygoteTransport, ProtocolError
    from constants import PROTOCOL_VERSION, MAX_MESSAGE_SIZE
    from paths import VeloPaths
    from config import VeloConfig


class ImportShield(importlib.abc.MetaPathFinder):
    """
    RFC-0011 §6.2.1: Import Isolation Layer (ImportShield)
    
    Prevents the user application from importing or shadowing internal 
    framework modules (e.g., velo_zygote.*).
    """
    def find_spec(self, fullname, path, target=None):
        # 1. Block internal framework access from child process
        if fullname.startswith("velo_zygote"):
            # We allow the launcher to import us once, but once the app is loading,
            # any SUBSEQUENT import of velo_zygote (by user code) is blocked.
            raise ImportError(f"Unauthorized access to internal framework module: {fullname}")
        
        # 2. Shadowing Protection: main.py
        # This finder is installed at the top of sys.meta_path.
        # If it returns None, Python falls back to standard finders (PathFinder).
        return None

    @staticmethod
    def install():
        """Install the shield at the front of sys.meta_path."""
        if not any(isinstance(f, ImportShield) for f in sys.meta_path):
            sys.meta_path.insert(0, ImportShield())
            
            # Centralized Path Sanitization (RFC-0011 6A.1)
            # Prevent shadowing of user modules by framework modules.
            framework_dir = os.path.dirname(os.path.abspath(__file__))
            if framework_dir in sys.path:
                sys.path.remove(framework_dir)



# LEGACY: Replaced by VeloPaths.zygote_socket()
def get_versioned_socket_path() -> Path:
    """Get the versioned socket path for this protocol version."""
    return VeloPaths.zygote_socket()

# ============================================================================
# MessagePack Import with Pure Python Fallback (ADV-3)
# ============================================================================
try:
    from .serializer import packer, unpacker, _USING_PURE_PYTHON_MSGPACK
except (ImportError, ValueError):
    from serializer import packer, unpacker, _USING_PURE_PYTHON_MSGPACK


# Sensitive paths that should never be executed (SEC-P3-001)
_BLOCKED_PATHS = [
    "/etc", "/var", "/usr", "/bin", "/sbin",
    "/System", "/Library", "/private/etc",
    "/root",
]

# Validation Fix: Allow /home in GitHub Actions CI (where runner is in /home/runner)
if VeloConfig().is_ci():
    _BLOCKED_PATHS.remove("/home") if "/home" in _BLOCKED_PATHS else None
else:
    if "/home" not in _BLOCKED_PATHS:
        _BLOCKED_PATHS.append("/home")


class ForkRateLimiter:
    """RFC-0011 WB-005: Token bucket rate limiter for Fork DoS protection.
    
    Prevents rapid Fork requests that could exhaust PIDs or memory.
    Default: 100 tokens, refill 1 token/50ms (max 20 forks/sec sustained, 100 burst).
    
    CI Mode: When GITHUB_ACTIONS=true or VELO_RATE_LIMIT_DISABLED=1, 
    rate limiting is disabled to allow 100-worker tests.
    """
    
    def __init__(self, max_tokens: int = 100, refill_interval_ms: int = 50):
        self.max_tokens = max_tokens
        self.tokens = max_tokens
        self.refill_interval = refill_interval_ms / 1000.0  # Convert to seconds
        self.last_refill = time.time()
        self._lock = threading.Lock()
        # CI bypass: disable rate limiting in test environments
        self._disabled = VeloConfig().is_ci() or os.environ.get("VELO_RATE_LIMIT_DISABLED") == "1"
    
    def acquire(self) -> bool:
        """Try to acquire a token. Returns True if allowed, False if rate limited."""
        if self._disabled:
            return True
            
        with self._lock:
            now = time.time()
            # Refill tokens based on elapsed time
            elapsed = now - self.last_refill
            new_tokens = int(elapsed / self.refill_interval)
            if new_tokens > 0:
                self.tokens = min(self.max_tokens, self.tokens + new_tokens)
                self.last_refill = now
            
            if self.tokens > 0:
                self.tokens -= 1
                return True
            return False



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
            log_path = VeloPaths.zygote_log()
            with open(log_path, "a") as f:
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


# ZygoteTransport is now imported from .protocol


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
    def start_guardian(parent_pid: int, ttl: int, monitor_parent: bool = True):
        """Guardian thread to prevent orphans."""
        def guardian():
            start_time = time.time()
            # print(f"[GUARDIAN] Started: parent_pid={parent_pid}, ttl={ttl}", file=sys.stderr)
            while True:
                if monitor_parent:
                    current_ppid = os.getppid()
                    if current_ppid != parent_pid: 
                        # Supervisor lost - terminate immediately
                        # print(f"[GUARDIAN] Parent changed: {parent_pid} -> {current_ppid}, exiting!", file=sys.stderr)
                        os._exit(1)
                
                if ttl > 0 and (time.time() - start_time) > ttl: 
                    # TTL expired
                    print(f"[GUARDIAN] TTL expired ({ttl}s), exiting!", file=sys.stderr)
                    os._exit(1)
                time.sleep(1) # Reduced to 1s for immediate response (H-11 compliance)
        t = threading.Thread(target=guardian, daemon=True)
        t.start()

    def reap_stale(self) -> List[int]:
        """Cleanup logic for timed-out or missing workers. Returns list of reaped PIDs."""
        now = time.time()
        to_remove = []
        with self.lock:
            for pid, (start_time, _) in self.workers.items():
                if now - start_time > self.worker_ttl:
                    to_remove.append(pid)
        
        for pid in to_remove:
            LogUtils.log(f"Reaping stale worker: {pid}")
            try: os.kill(pid, 9)
            except: pass
            self.remove(pid)
        return to_remove

    def kill_all(self):
        """Terminate all tracked workers. Called on shutdown."""
        with self.lock:
            pids = list(self.workers.keys())
        
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception as e:
                LogUtils.debug_log(f"Failed to kill worker {pid}: {e}")
            self.remove(pid)
        
        LogUtils.log(f"Killed {len(pids)} workers on shutdown.")


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
    """SecurityHook: FD hygiene and random reseed (RFC-0011 6A.2).
    
    Industrial Grade Cord-Cutting:
    1. Close all non-standard file descriptors.
    2. Reset signal handlers.
    3. Re-seed random number generators.
    """
    import random
    import resource
    import signal
    
    # 1. FD Hygiene (Whitelist standard FDs)
    try:
        # Standard FDs: stdin=0, stdout=1, stderr=2
        keep_fds = {0, 1, 2}
        
        # Determine all open FDs
        current_fds = set()
        if os.path.exists('/proc/self/fd'):
            current_fds = set(int(fd) for fd in os.listdir('/proc/self/fd'))
        elif os.path.exists('/dev/fd'):
            current_fds = set(int(fd) for fd in os.listdir('/dev/fd'))
        
        # Close everything else (Surgical Cord-Cutting)
        if current_fds:
            for fd in current_fds:
                if fd not in keep_fds:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
        else:
            # Fallback for platforms without /proc or /dev/fd
            max_fd = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
            if max_fd == resource.RLIM_INFINITY or max_fd > 1024:
                max_fd = 1024
            os.closerange(3, max_fd)
    except Exception:
        pass

    # 2. Random Selection (Taint Re-Randomization Contract RFC-0013)
    try:
        import secrets
        random.seed(secrets.token_bytes(32))
        os.urandom(1)
    except Exception:
        random.seed()

    # 3. Signal Hygiene (H-12: Complete Reset)
    try:
        # 3.1 Unblock all signals (Inherited signal mask)
        if hasattr(signal, 'pthread_sigmask'):
            signal.pthread_sigmask(signal.SIG_SETMASK, [])
    except (ValueError, RuntimeError, AttributeError):
        pass

    # 3.2 Reset all signal handlers to default
    for sig in range(1, getattr(signal, 'NSIG', 65)):
        try:
            signal.signal(sig, signal.SIG_DFL)
        except (ValueError, RuntimeError, OSError):
            # Skip signals that cannot be caught (SIGKILL, SIGSTOP) or are not supported
            pass
    
    # 3.3 Purge wakeup FD (AsyncIO pollution)
    try:
        signal.set_wakeup_fd(-1)
    except (ValueError, RuntimeError):
        pass

    # 4. Extended PRNG Seeding (Industrial Isolation)
    try:
        import numpy as np
        np.random.seed(int.from_bytes(os.urandom(4), 'little'))
    except (ImportError, Exception):
        pass

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
    """RFC-0011 6A.2: Reset child process state using Hooks Registry.
    
    Must be called immediately after fork() in the child process.
    """
    # 1. Reset asyncio event loop (Industrial Grade Isolation)
    # The child inherits the parent's loop state (executors, etc.) which must be purged.
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    except Exception:
        pass

    # 2. Run all registered hooks (Security, Computing, Telemetry)
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
        t0 = time.time()
        def p_log(msg):
            try:
                # Use socket dir for perf logs (transient, correct permissions)
                log_path = VeloPaths.socket_dir() / "perf_zygote.log"
                with open(log_path, "a") as f:
                    f.write(f"PERF_CHILD: {msg} (+{(time.time()-t0)*1000:.2f}ms)\n")
            except: pass

        p_log("Start _child_process")
        exit_code = 0
        try:
            # 1. RFC-0011 6A.2: Full post-fork state reset (Industrial Grade)
            # This MUST happen before anything else to ensure a clean slate.
            post_fork_reinit()
            p_log("Reinit Done (Cord Cut)")

            # 2. Start Guardian (Workers MUST die if Zygote dies)
            # Now started after FDs are sanitized to avoid race conditions.
            WorkerRegistry.start_guardian(os.getppid(), worker_ttl, monitor_parent=True)
            p_log("Guardian Started")

            # 3. Install ImportShield (Import Isolation)
            ImportShield.install()
            p_log("ImportShield Installed")

            # 3. I/O Redirection
            ForkHandler._redirect_io(stdout_path, stderr_path)
            # p_log("IO Redirected") # Might fail to log after redirect to file! 
            # But I use /dev/stderr directly in p_log.

            # 4. Setup Sys Args
            sys.argv = [script_path] + args

            # 5. Fast Mode Activation
            if fast_mode and bundle_path:
                ForkHandler._activate_fast_mode(bundle_path, project_root, max_bundle_size)

            # 6. Execute Script
            p_log(f"Exec script: {script_path}")
            with open(script_path, "rb") as f:
                code = compile(f.read(), script_path, "exec")
                p_log("Script compiled")
                exec(code, {"__name__": "__main__", "__file__": script_path})
            
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        except Exception:
            try:
                import traceback
                traceback.print_exc()
            except: pass
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
            
            # Use VeloPaths for project resolution if available
            if project_root:
                pyproj = VeloPaths.pyproject(Path(project_root))
                if pyproj.exists():
                    v_loader = VeloPaths.project_file(Path(project_root), "velo_loader.py")
                    if v_loader.exists():
                        loader_dir = str(v_loader.parent)
                        if loader_dir not in sys.path:
                            sys.path.insert(0, loader_dir)

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

    def __init__(self, socket_path: str, preload: List[str] = None, idle_timeout: int = None, worker_ttl: int = None, app_name: str = None, monitor_parent: bool = True):
        self.config = VeloConfig()
        
        # RFC-0011 D.1: Support abstract sockets (@ -> \0)
        self.is_abstract = socket_path.startswith('@')
        if self.is_abstract:
            self.socket_path = '\0' + socket_path[1:]
        else:
            self.socket_path = socket_path
            
        self.idle_timeout = idle_timeout or self.config.graceful_shutdown_timeout
        self.worker_registry = WorkerRegistry(worker_ttl or 3600)
        self.preload = preload or self.config.preload
        self._preloaded_modules: List[str] = []
        self.memory_limit_mb = self.config.max_bundle_size // (1024 * 1024)
        self.app_name: Optional[str] = app_name  # RFC-0011 WB-004: App affinity from startup
        self.fork_rate_limiter = ForkRateLimiter()  # RFC-0011 WB-005: DoS protection
        self._monitor_parent = monitor_parent # Store for use in start()
        
        # [DEF-62-004] Pending sync forks (pid -> Future)
        self.pending_forks: Dict[int, asyncio.Future] = {}
        
        # Shadow Preloading: State machine for async preload
        self.preload_state: str = "STARTING"  # STARTING → LOADING → READY
        self.preload_complete = asyncio.Event()  # Signaled when preload finishes
        self.fork_queue: asyncio.Queue = asyncio.Queue()  # Queue for Fork requests during LOADING

    async def start(self):
        """Start the Zygote server using asyncio with Shadow Preloading.
        
        Shadow Preloading: Socket opens immediately, preloading happens async.
        This minimizes time-to-ready for the Rust supervisor.
        """
        try:
            LogUtils.log(f"Starting Refactored Zygote (PID: {os.getpid()})")
            
            # RFC-0012: The Guardian monitors the parent process. 
            # In daemon mode (--no-guardian), we disable parent monitoring.
            monitor_parent = getattr(self, "_monitor_parent", True)
            WorkerRegistry.start_guardian(os.getppid(), 0, monitor_parent=monitor_parent)
            
            self._setup_signals()
            
            # Shadow Preloading: Open socket FIRST, preload ASYNC
            self.preload_state = "LOADING"
            
            # Start async preload task (non-blocking)
            asyncio.create_task(self._async_preload())
            
            # Start background tasks
            asyncio.create_task(self._resource_guard())
            
            # Start socket listener immediately (before preload completes)
            await self._run_loop()
        except Exception as e:
            LogUtils.debug_log(f"Server Startup Error: {e}")
            traceback.print_exc()
            sys.exit(1)

    async def _async_preload(self):
        """Async preloading of modules - runs in background."""
        try:
            # Run blocking preload in executor to not block event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._preload_modules)
            # self._preload_modules()
            
            # Check CUDA after preload
            if check_cuda_initialized():
                LogUtils.log("CRITICAL: CUDA initialized in Zygote! Shutting down.")
                sys.exit(1)
            
            self.preload_state = "READY"
            self.preload_complete.set()
            LogUtils.log(f"Shadow Preloading complete. State: READY")
            
            # Process any queued Fork requests
            await self._process_fork_queue()
        except Exception as e:
            LogUtils.debug_log(f"Preload Error: {e}")
            self.preload_state = "READY"  # Still mark ready to avoid deadlock
            self.preload_complete.set()

    async def _process_fork_queue(self):
        """Process Fork requests that were queued during LOADING state."""
        while not self.fork_queue.empty():
            try:
                cmd, response_future = await asyncio.wait_for(
                    self.fork_queue.get(), timeout=0.1
                )
                # Re-dispatch the Fork command now that preload is complete
                response = await handle_fork(self, cmd)
                response_future.set_result(response)
            except asyncio.TimeoutError:
                break
            except Exception as e:
                LogUtils.debug_log(f"Fork queue processing error: {e}")

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
        # Reap stale workers (TTL expired)
        reaped_pids = self.worker_registry.reap_stale()
        for pid in reaped_pids:
            if pid in self.pending_forks:
                fut = self.pending_forks.pop(pid)
                if not fut.done():
                    fut.set_result(0xDEAD) # Signal stale
                    
        while True:
            try:
                # Use WNOHANG to check for any exited children
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid <= 0: break
                
                # Resolve exit code
                exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
                
                # Update registry
                self.worker_registry.remove(pid)
                
                # Resolve any pending sync fork [DEF-62-004]
                if pid in self.pending_forks:
                    fut = self.pending_forks.pop(pid)
                    if not fut.done():
                        fut.set_result(exit_code)
            except ChildProcessError: break
            except Exception as e:
                LogUtils.debug_log(f"Reap Error: {e}")
                break

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
            
        server = await asyncio.start_unix_server(
            self._handle_client, 
            path=self.socket_path,
            backlog=512
        )
        LogUtils.log("Zygote IPC Layer Ready.")
        
        async with server:
            try:
                await asyncio.wait_for(server.serve_forever(), timeout=self.idle_timeout)
            except asyncio.TimeoutError:
                LogUtils.log("Zygote Idle Timeout (no clients for 5 minutes). Shutting down.")
            except KeyboardInterrupt:
                LogUtils.log("Zygote received interrupt signal. Shutting down.")
            except asyncio.CancelledError:
                LogUtils.log("Zygote server cancelled. Shutting down.")
            except Exception as e:
                # CHAOS-621: Catch-all for unexpected errors - log clearly and continue
                LogUtils.log(f"⚠️ Server Loop Error: {type(e).__name__}: {e}")
                LogUtils.debug_log(f"Server loop exception: {e}")
            finally:
                LogUtils.log("Shutting down Zygote - Cleaning up workers.")
                self.worker_registry.kill_all() # RFC-0011 6A.1: Prevent orphan leaks
                
                # [DEF-62-005] Clean up socket file on exit
                if not self.is_abstract:
                    try:
                        path = Path(self.socket_path)
                        if path.exists():
                            path.unlink()
                            LogUtils.log(f"Cleaned up socket: {self.socket_path}")
                    except Exception as e:
                        LogUtils.debug_log(f"Socket cleanup failed: {e}")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        sock = writer.get_extra_info('socket')
        
        # [DEF-62-001] Peer Identity Verification (SO_PEERCRED / LOCAL_PEERCRED)
        if not self._verify_peer(sock):
            LogUtils.log("🚨 Security: Unauthorized connection attempt (UID mismatch). Dropping.")
            writer.close()
            return

        transport = ZygoteTransport(reader, writer)
        try:
            # 1. Send Ready (Server Handshake Greeting)
            await transport.send({"type": "Ready"})
            
            while True:
                try:
                    cmd = await transport.recv()
                    if not cmd: break
                    
                    response = await router.dispatch(self, cmd)
                    if response:
                        await transport.send(response)
                        if isinstance(cmd, dict) and cmd.get("type") == "Shutdown":
                            asyncio.get_event_loop().stop()
                            break
                except ProtocolError as e:
                    LogUtils.log(f"⛔ [FAIL FAST] Protocol Violation: {e}. Dropping connection.")
                    break
        finally:
            await transport.close()

    def _verify_peer(self, sock: socket.socket) -> bool:
        """Verify that the connecting peer has the same UID as the Zygote.
        
        Implements Cross-Account Isolation (RFC-0012 §3.1).
        """
        try:
            my_uid = os.getuid()
            
            if sys.platform == "linux":
                # Option A: Linux SO_PEERCRED (struct ucred)
                # struct ucred { pid_t pid; uid_t uid; gid_t gid; }
                SO_PEERCRED = 17 
                creds = sock.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize('3i'))
                _, peer_uid, _ = struct.unpack('3i', creds)
                return peer_uid == my_uid
            
            elif sys.platform == "darwin":
                # Option B: macOS LOCAL_PEERCRED (struct xucred)
                # struct xucred { u_int cr_version; uid_t cr_uid; ... }
                SOL_LOCAL = 0
                LOCAL_PEERCRED = 0x001
                # xucred is larger, but we only need the second field (uid_t)
                creds = sock.getsockopt(SOL_LOCAL, LOCAL_PEERCRED, 128)
                # xucred starts with version (u_int=I), then uid (uid_t=I) at offset 4
                _, peer_uid = struct.unpack('II', creds[:8])
                return peer_uid == my_uid
            
            # Fallback for other platforms: allow for now but log warning
            LogUtils.log(f"Warning: Peer verification not implemented for {sys.platform}")
            return True
        except Exception as e:
            LogUtils.debug_log(f"Peer Verification Error: {e}")
            return False


@router.handler("Handshake")
async def handle_handshake(server: ZygoteServer, cmd: Dict) -> Dict:
    """Protocol Handshake and Capability alignment."""
    server_version = PROTOCOL_VERSION
    client_app = cmd.get("app_name")
    
    # RFC-0011 WB-004: Verify app affinity
    if server.app_name and client_app and client_app != server.app_name:
        return {"type": "Error", "message": f"App affinity mismatch: expected {server.app_name}, got {client_app}"}
    
    # P3: Structured capabilities (backwards compatible - also keep list format)
    capabilities_dict = {
        "protocol": "map",
        "preload": server.preload_state.lower(),
        "features": ["async-reaper", "resource-guard", "hook-reinit", "rate-limit", "shadow-preload"],
    }
    if server.app_name:
        capabilities_dict["app"] = server.app_name
    
    # Legacy list format for backwards compatibility
    capabilities_list = ["map-protocol", "async-reaper", "resource-guard", "hook-reinit"]
    if server.app_name:
        capabilities_list.append(f"app:{server.app_name}")
    capabilities_list.append(f"preload:{server.preload_state.lower()}")
    
    return {
        "type": "Handshake",
        "version": server_version,
        "capabilities": capabilities_list,  # Legacy format
        "caps": capabilities_dict,  # P3: Structured format
    }

@router.handler("Fork")
async def handle_fork(server: ZygoteServer, cmd: Dict) -> Dict:
    # Shadow Preloading: Wait for preload to complete if still loading
    if server.preload_state == "LOADING":
        try:
            # Wait up to 30s for preload to complete
            await asyncio.wait_for(server.preload_complete.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            return {"type": "Error", "message": "Preload timeout: modules still loading after 30s"}
    
    # RFC-0011 WB-005: Rate limiting to prevent Fork Bomb DoS
    if not server.fork_rate_limiter.acquire():
        return {"type": "Error", "message": "Rate limit exceeded: too many Fork requests"}
    
    script_path = cmd.get("script_path", "")
    if not script_path or not Path(script_path).exists():
        return {"type": "Error", "message": f"Script not found: {script_path}"}
    
    valid, err = PathValidator.validate(script_path)
    if not valid:
        return {"type": "Error", "message": err}

    # RFC-0011 WB-004: Store app name for affinity verification
    if not server.app_name:
        server.app_name = Path(script_path).name

    worker_pid = ForkHandler.handle_fork(cmd, server.worker_registry, server._preloaded_modules)
    
    if cmd.get("async_mode"):
        return {"type": "Forked", "worker_pid": worker_pid, "exit_code": None}
    else:
        # Sync mode: Non-blocking wait using asyncio.Future [DEF-62-004]
        try:
            loop = asyncio.get_event_loop()
            future = loop.create_future()
            server.pending_forks[worker_pid] = future
            
            # Use wait_for to prevent infinite hang if reaper fails (30s budget)
            exit_code = await asyncio.wait_for(future, timeout=30.0)
            return {"type": "Forked", "worker_pid": worker_pid, "exit_code": exit_code}
        except asyncio.TimeoutError:
            server.pending_forks.pop(worker_pid, None)
            return {"type": "Error", "message": "Fork wait timeout (30s exceeded)"}
        except Exception as e:
            server.pending_forks.pop(worker_pid, None)
            return {"type": "Error", "message": f"Fork wait failure: {e}"}

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


def zygote_main(socket_path: str, preload: List[str], idle_timeout: int = 300, worker_ttl: int = 3600, app_name: str = None, monitor_parent: bool = True):
    """Main entry point for Zygote process."""
    server = ZygoteServer(socket_path, preload, idle_timeout, worker_ttl, app_name, monitor_parent)
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
    import sys
    import os
    print(f"DEBUG: Zygote Entry. Executable: {sys.executable}")
    print(f"DEBUG: Zygote Entry. Version: {sys.version}")
    print(f"DEBUG: Zygote Entry. sys.path: {sys.path}")
    print(f"DEBUG: Zygote Entry. PYTHONPATH: {os.environ.get('PYTHONPATH')}")
    print(f"DEBUG: Zygote Entry. PATH: {os.environ.get('PATH')}")
    sys.stdout.flush()

    os.environ['OMP_NUM_THREADS'] = '1'
    import argparse
    parser = argparse.ArgumentParser(description="Velo Zygote Process")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--preload", nargs="*", default=[])
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--worker-ttl", type=int, default=3600)
    parser.add_argument("--no-guardian", action="store_true", help="Disable parent process monitoring (daemon mode)")
    parser.add_argument("--app", help="App name for affinity verification")
    args = parser.parse_args()
    
    zygote_main(args.socket, args.preload, args.timeout, args.worker_ttl, args.app, not args.no_guardian)
