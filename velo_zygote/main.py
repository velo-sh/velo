#!/usr/bin/env python3
"""
Velo Zygote Python Module (Modularized Refactor Phase 11.0)
"""

# --- Velo Bootstrap ---
import os
import sys
_pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from velo_zygote import bootstrap
bootstrap.initialize()
# --------------------

import asyncio
import signal
import socket
import struct
import time
import traceback
from pathlib import Path
from typing import List, Optional, Set, Dict, Any, Tuple

try:
    from .constants import PROTOCOL_VERSION, MAX_MESSAGE_SIZE
    from .paths import VeloPaths
    from .settings import velo_config
    from .shield import PathValidator
    from .utils import ForkRateLimiter, LogUtils
    from .lifecycle import WorkerRegistry, post_fork_reinit
    from .routing import CommandRouter
    from .fork import ForkHandler, InboundSharedMemory
    from .transport_sync import ZygoteTransport, ProtocolError
except (ImportError, ValueError):
    from constants import PROTOCOL_VERSION, MAX_MESSAGE_SIZE
    from paths import VeloPaths
    from settings import velo_config
    from shield import PathValidator
    from utils import ForkRateLimiter, LogUtils
    from lifecycle import WorkerRegistry, post_fork_reinit
    from routing import CommandRouter
    from fork import ForkHandler, InboundSharedMemory
    from transport_sync import ZygoteTransport, ProtocolError

# Shared Memory Management (Phase 7.2)
try:
    from velo_zygote import memory as _memory
    MEMORY_MANAGER = getattr(_memory, "MEMORY_MANAGER", None) if _memory else None
except (ImportError, ValueError):
    MEMORY_MANAGER = None

# Global router for Command Dispatch
router = CommandRouter()

# ============================================================================
# Command Handlers
# ============================================================================

@router.handler("Handshake")
async def handle_handshake(server: 'ZygoteServer', cmd: Dict) -> Dict:
    """Protocol Handshake and Capability alignment."""
    server_version = PROTOCOL_VERSION
    client_app = cmd.get("app_name")
    
    if server.app_name and client_app and client_app != server.app_name:
        return {"type": "Error", "message": f"App affinity mismatch: expected {server.app_name}, got {client_app}"}
    
    capabilities_dict = {
        "protocol": "map",
        "preload": server.preload_state.lower(),
        "features": ["async-reaper", "resource-guard", "hook-reinit", "rate-limit", "shadow-preload"],
    }
    if server.app_name:
        capabilities_dict["app"] = server.app_name
    
    capabilities_list = ["map-protocol", "async-reaper", "resource-guard", "hook-reinit"]
    if server.app_name:
        capabilities_list.append(f"app:{server.app_name}")
    capabilities_list.append(f"preload:{server.preload_state.lower()}")
    
    return {
        "type": "Handshake",
        "version": server_version,
        "capabilities": capabilities_list,
        "caps": capabilities_dict,
    }

@router.handler("Fork")
async def handle_fork(server: 'ZygoteServer', cmd: Dict) -> Dict:
    # Shadow Preloading: Wait for preload to complete if still loading
    if server.preload_state == "LOADING":
        try:
            await asyncio.wait_for(server.preload_complete.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            return {"type": "Error", "message": "Preload timeout: modules still loading after 30s"}
    
    if not server.fork_rate_limiter.acquire():
        return {"type": "Error", "message": "Rate limit exceeded: too many Fork requests"}
    
    script_path = cmd.get("script_path", "")
    if script_path:
        p = Path(script_path)
        if not p.exists():
            return {"type": "Error", "message": f"Execution Intent Failure: Script not found at '{script_path}'. The Zygote cannot fork a non-existent target."}
        valid, err = PathValidator.validate(script_path)
        if not valid:
            return {"type": "Error", "message": f"Security Intent Violation: Target '{script_path}' failed shield validation: {err}"}

    if not server.app_name and script_path:
        server.app_name = Path(script_path).name

    try:
        worker_pid = ForkHandler.handle_fork(cmd, server.worker_registry, server._preloaded_modules)
    except Exception as e:
        return {"type": "Error", "message": f"Fork Execution Failed: {e}"}
    
    if cmd.get("async_mode"):
        return {"type": "Forked", "worker_pid": worker_pid, "exit_code": None}
    else:
        try:
            loop = asyncio.get_event_loop()
            future = loop.create_future()
            server.pending_forks[worker_pid] = future
            exit_code = await asyncio.wait_for(future, timeout=30.0)
            return {"type": "Forked", "worker_pid": worker_pid, "exit_code": exit_code}
        except asyncio.TimeoutError:
            server.pending_forks.pop(worker_pid, None)
            return {"type": "Error", "message": "Fork wait timeout (30s exceeded)"}
        except Exception as e:
            server.pending_forks.pop(worker_pid, None)
            return {"type": "Error", "message": f"Fork wait failure: {e}"}

@router.handler("WaitWorker")
async def handle_wait_worker(server: 'ZygoteServer', cmd: Dict) -> Dict:
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
async def handle_signal(server: 'ZygoteServer', cmd: Dict) -> Dict:
    pid, sig = cmd.get("worker_pid"), cmd.get("signal")
    try:
        os.kill(pid, sig)
        return {"type": "Ack"}
    except:
        return {"type": "Error", "message": "Process not found"}

@router.handler("WorkerStatus")
async def handle_worker_status(server: 'ZygoteServer', cmd: Dict) -> Dict:
    pid = cmd.get("worker_pid")
    alive = server.worker_registry.is_alive(pid)
    return {"type": "WorkerInfo", "worker_pid": pid, "is_running": alive, "uptime_secs": 0}

@router.handler("Shutdown")
async def handle_shutdown(server: 'ZygoteServer', cmd: Dict) -> Dict:
    LogUtils.log("Graceful Shutdown Initiated.")
    asyncio.get_event_loop().call_later(0.1, sys.exit, 0)
    return {"type": "Ack"}

@router.handler("Status")
async def handle_zy_status(server: 'ZygoteServer', cmd: Dict) -> Dict:
    return {
        "type": "Status",
        "pid": os.getpid(),
        "state": server.preload_state,
        "workers": server.worker_registry.get_stats(),
        "app": server.app_name
    }

# ============================================================================
# Zygote Server
# ============================================================================

class ZygoteServer:
    """Layer 2: App Layer - Orchestrates the Zygote service."""

    def __init__(self, socket_path: str, preload: List[str] = None, idle_timeout: int = None, worker_ttl: int = None, app_name: str = None, monitor_parent: bool = True):
        self.config = velo_config
        
        # RFC-0011 D.1: Support abstract sockets (@ -> \0)
        self.is_abstract = socket_path.startswith('@')
        if self.is_abstract:
            self.socket_path = '\0' + socket_path[1:]
        else:
            self.socket_path = socket_path
            
        self.idle_timeout = idle_timeout or self.config.graceful_shutdown_timeout
        self.worker_registry = WorkerRegistry(worker_ttl or 3600)
        self.preload = preload or self.config.preload_modules
        self._preloaded_modules: List[str] = []
        self.memory_limit_mb = self.config.max_bundle_size // (1024 * 1024)
        self.app_name: Optional[str] = app_name  
        self.fork_rate_limiter = ForkRateLimiter()  
        self._monitor_parent = monitor_parent 
        
        self.preload_state: str = "STARTING"  
        self.preload_complete = asyncio.Event()  
        self.fork_queue: asyncio.Queue = asyncio.Queue()  
        
        self.pending_forks: Dict[int, asyncio.Future] = {}
        self._last_activity = time.time()

    async def start(self):
        """Start the Zygote server using asyncio."""
        LogUtils.log(f"Zygote initializing (PID: {os.getpid()})")
        
        # 1. Open Socket
        if not self.is_abstract and os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError as e:
                LogUtils.log(f"Zygote Cleanup Error: Failed to unlink stale socket at '{self.socket_path}': {e}")
            
        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server_sock.bind(self.socket_path)
        except OSError as e:
            LogUtils.log(f"Zygote Bootstrap Failure: Cannot bind to {self.socket_path}. Ensure parent directory exists and permissions are correct. Detail: {e}")
            sys.exit(1)
            
        if not self.is_abstract:
            try:
                os.chmod(self.socket_path, 0o600)
            except OSError as e:
                LogUtils.log(f"Zygote Security Warning: Failed to set permissions on {self.socket_path}: {e}")
        server_sock.listen(128)
        server_sock.setblocking(False)
        
        # 2. Start Guardian
        if self._monitor_parent:
            self.worker_registry.start_guardian(os.getppid(), 3600, True)
            
        # 3. Setup Signal Handlers
        self._setup_signals()
        
        # 4. Background Preloading
        asyncio.create_task(self._async_preload())
        
        # 5. Resource Monitoring
        asyncio.create_task(self._resource_guard())
        
        LogUtils.log(f"Listening on {self.socket_path}")
        
        loop = asyncio.get_event_loop()
        while True:
            try:
                # Use loop.sock_accept for non-blocking accept
                try:
                    client_sock, _ = await asyncio.wait_for(
                        loop.sock_accept(server_sock), 
                        timeout=5.0
                    )
                    # We keep client_sock non-blocking or blocking?
                    # The sync transport expects blocking behavior for recvmsg/sendall
                    client_sock.setblocking(True)
                    asyncio.create_task(self._handle_client_socket(client_sock))
                    self._last_activity = time.time()
                except asyncio.TimeoutError:
                    # Check for idle timeout
                    if self.idle_timeout and (time.time() - self._last_activity) > self.idle_timeout:
                        if not self.worker_registry.workers:
                            LogUtils.log(f"Idle timeout ({self.idle_timeout}s). Shutting down.")
                            break
            except Exception as e:
                if not isinstance(e, (asyncio.TimeoutError, KeyboardInterrupt)):
                    LogUtils.log(f"Accept error: {e}")

    async def _handle_client_socket(self, sock: socket.socket):
        """Handle a client connection using the synchronous transport."""
        transport = ZygoteTransport(sock)
        try:
            while True:
                # Use run_in_executor for blocking recvmsg
                msg = await asyncio.get_event_loop().run_in_executor(None, transport.recv)
                if not msg:
                    break
                
                response = await router.dispatch(self, msg)
                await asyncio.get_event_loop().run_in_executor(None, transport.send, response)
                
                if response.get("type") == "Ack" and msg.get("type") == "Shutdown":
                    break
        except Exception as e:
            LogUtils.log(f"Client error: {e}")
        finally:
            transport.close()

    async def _async_preload(self):
        """Async preloading of modules."""
        self.preload_state = "LOADING"
        loop = asyncio.get_event_loop()
        
        # Run preloading in a thread to keep reactor alive
        await loop.run_in_executor(None, self._preload_modules)
        
        self.preload_state = "READY"
        self.preload_complete.set()
        LogUtils.log(f"Preload complete. {len(self._preloaded_modules)} modules loaded.")
        
        # Process fork queue
        await self._process_fork_queue()

    def _preload_modules(self):
        import importlib
        for module_name in self.preload:
            try:
                importlib.import_module(module_name)
                self._preloaded_modules.append(module_name)
            except Exception as e:
                LogUtils.log(f"Preload failed for {module_name}: {e}")

    async def _process_fork_queue(self):
        while not self.fork_queue.empty():
            cmd, future = await self.fork_queue.get()
            result = await handle_fork(self, cmd)
            future.set_result(result)

    def _setup_signals(self):
        def handle_chld(sig, frame):
            # We can't do much in a signal handler, so we just trigger the async reaper
            pass
        signal.signal(signal.SIGCHLD, signal.SIG_IGN) # Auto-reap if we don't care about exit codes?
        # Actually we DO care about exit codes for WaitWorker.
        # But for async workers, we want to prevent zombies.
        # Re-enable SIGCHLD and use waitpid in a loop or thread.
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        asyncio.create_task(self._async_reap())

    async def _async_reap(self):
        """Async-safe zombie reaping."""
        while True:
            await asyncio.sleep(1.0)
            try:
                while True:
                    pid, status = os.waitpid(-1, os.WNOHANG)
                    if pid == 0:
                        break
                    
                    # Log exit
                    exit_code = os.WEXITSTATUS(status)
                    LogUtils.debug_log(f"Worker {pid} exited with code {exit_code}")
                    
                    # Handle pending futures
                    future = self.pending_forks.pop(pid, None)
                    if future and not future.done():
                        future.set_result(exit_code)
                    
                    # Remove from registry
                    self.worker_registry.remove(pid)
            except ChildProcessError:
                pass
            except Exception as e:
                LogUtils.log(f"Reaper error: {e}")

    async def _resource_guard(self):
        """Monitor memory usage and guard resources."""
        while True:
            await asyncio.sleep(60.0)
            self.worker_registry.reap_stale()
            # Memory check logic here...

# ============================================================================
# Entry Point
# ============================================================================

def zygote_main():
    import argparse
    parser = argparse.ArgumentParser(description="Velo Zygote Process")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--preload", nargs='*', default=[])
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--worker-ttl", type=int)
    parser.add_argument("--no-guardian", action="store_true")
    parser.add_argument("--app", help="App name for affinity verification")
    
    args = parser.parse_args()
    
    # Pillar 1: Env Isolation Check (Council Rule)
    if not os.environ.get("VELO_ENV"):
         print("FATAL: VELO_ENV not set. Zygote cannot start.", file=sys.stderr)
         sys.exit(1)
         
    server = ZygoteServer(
        socket_path=args.socket,
        preload=args.preload,
        idle_timeout=args.timeout,
        worker_ttl=args.worker_ttl,
        app_name=args.app,
        monitor_parent=not args.no_guardian
    )
    
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        LogUtils.log(f"Fatal server failure: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    zygote_main()
