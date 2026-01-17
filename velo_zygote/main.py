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

import os

# print(f"DEBUG: VELO_IS_ZYGOTE={os.environ.get('VELO_IS_ZYGOTE')}", file=sys.stderr)
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
    from velo_zygote.constants import PROTOCOL_VERSION, MAX_MESSAGE_SIZE
    from velo_zygote.paths import VeloPaths
    from velo_zygote.settings import velo_config
    from velo_zygote.v_shield import PathValidator
    from velo_zygote.utils import ForkRateLimiter, LogUtils, request_context
    from velo_zygote.lifecycle import WorkerRegistry, post_fork_reinit, ZygoteState
    from velo_zygote.routing import CommandRouter
    from velo_zygote.v_fork import ForkHandler, InboundSharedMemory
    from velo_zygote.transport_sync import ZygoteTransport, ProtocolError
except (ImportError, ValueError):
    try:
        from .constants import PROTOCOL_VERSION, MAX_MESSAGE_SIZE
        from .paths import VeloPaths
        from .settings import velo_config
        from .v_shield import PathValidator
        from .utils import ForkRateLimiter, LogUtils, request_context
        from .lifecycle import WorkerRegistry, post_fork_reinit
        from .routing import CommandRouter
        from .v_fork import ForkHandler, InboundSharedMemory
        from .transport_sync import ZygoteTransport, ProtocolError
    except (ImportError, ValueError):
        from constants import PROTOCOL_VERSION, MAX_MESSAGE_SIZE  # type: ignore[no-redef, import-not-found]
        from paths import VeloPaths  # type: ignore[no-redef, import-not-found]
        from settings import velo_config  # type: ignore[no-redef, import-not-found]
        from v_shield import PathValidator  # type: ignore[no-redef, import-not-found]
        from utils import ForkRateLimiter, LogUtils, request_context  # type: ignore[no-redef, import-not-found]
        from lifecycle import WorkerRegistry, post_fork_reinit  # type: ignore[no-redef, import-not-found]
        from routing import CommandRouter  # type: ignore[no-redef, import-not-found]
        from v_fork import ForkHandler, InboundSharedMemory  # type: ignore[no-redef, import-not-found]
        from transport_sync import ZygoteTransport, ProtocolError  # type: ignore[no-redef, import-not-found]

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
async def handle_handshake(
    server: "ZygoteServer", cmd: Dict[str, Any]
) -> Dict[str, Any]:
    """Protocol Handshake and Capability alignment."""
    server_version = PROTOCOL_VERSION
    client_app = cmd.get("app_name")

    if server.app_name and client_app and client_app != server.app_name:
        return {
            "type": "Error",
            "message": f"App affinity mismatch: expected {server.app_name}, got {client_app}",
        }

    if not server.app_name and client_app:
        server.app_name = client_app
        LogUtils.log(f"Zygote app affinity established: {client_app}")

    capabilities_dict = {
        "protocol": "map",
        "preload": server.state.name.lower(),
        "features": [
            "async-reaper",
            "resource-guard",
            "hook-reinit",
            "rate-limit",
            "shadow-preload",
        ],
    }
    if server.app_name:
        capabilities_dict["app"] = server.app_name

    # Zygote Capabilites System (Phase 11.0)
    capabilities_list = ["fork:sync", "fork:async", "shm:v1"]
    capabilities_list.append(f"preload:{server.state.name.lower()}")
    if server.app_name:
        capabilities_list.append(f"app:{server.app_name}")

    # 3. Decision Logic - Wait for preload if necessary (Shadow Preloading Pattern)
    if server.state == ZygoteState.PRELOADING:
        try:
            await asyncio.wait_for(server.preload_complete.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            return {
                "type": "Error",
                "message": "Handshake Timeout: Zygote still preloading after 30s",
            }

    if server.state == ZygoteState.ERROR:
        return {"type": "Error", "message": "Zygote is in ERROR state."}

    return {
        "type": "Handshake",
        "version": server_version,
        "capabilities": capabilities_list,
        "caps": capabilities_dict,
    }


@router.handler("Fork")
async def handle_fork(server: "ZygoteServer", cmd: Dict[str, Any]) -> Dict[str, Any]:
    LogUtils.log(f"Zygote receiving Fork request for {cmd.get('script_path')}")
    # Shadow Preloading: Wait for preload to complete if still loading
    if server.state == ZygoteState.PRELOADING:
        try:
            await asyncio.wait_for(server.preload_complete.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            return {
                "type": "Error",
                "message": "Preload timeout: modules still loading after 30s",
            }

    if not server.fork_rate_limiter.acquire():
        return {
            "type": "Error",
            "message": "Rate limit exceeded: too many Fork requests",
        }

    script_path = cmd.get("script_path", "")
    if script_path:
        p = Path(script_path)
        if not p.exists():
            return {
                "type": "Error",
                "message": f"Execution Intent Failure: Script not found at '{script_path}'. The Zygote cannot fork a non-existent target.",
            }
        valid, err = PathValidator.validate(script_path)
        if not valid:
            return {
                "type": "Error",
                "message": f"Security Intent Violation: Target '{script_path}' failed shield validation: {err}",
            }

    if not server.app_name and script_path:
        server.app_name = Path(script_path).name

    try:
        worker_pid = ForkHandler.handle_fork(
            cmd, server.worker_registry, server._preloaded_modules
        )
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
async def handle_wait_worker(
    server: "ZygoteServer", cmd: Dict[str, Any]
) -> Dict[str, Any]:
    pid = int(cmd.get("worker_pid", 0))
    timeout = cmd.get("timeout_secs")
    if not server.worker_registry.is_alive(pid):
        return {"type": "WorkerExited", "worker_pid": pid, "exit_code": 0}

    try:
        start_time = time.time()
        while True:
            w_pid, status = os.waitpid(pid, os.WNOHANG)
            if w_pid == pid:
                server.worker_registry.remove(pid)
                return {
                    "type": "WorkerExited",
                    "worker_pid": pid,
                    "exit_code": os.WEXITSTATUS(status),
                }
            if timeout and (time.time() - start_time) > timeout:
                return {"type": "Error", "message": "Wait timeout"}
            await asyncio.sleep(0.05)
    except ChildProcessError:
        server.worker_registry.remove(pid)
        return {"type": "WorkerExited", "worker_pid": pid, "exit_code": 0}


@router.handler("SignalWorker")
async def handle_signal(server: "ZygoteServer", cmd: Dict[str, Any]) -> Dict[str, Any]:
    pid, sig = int(cmd.get("worker_pid", 0)), int(cmd.get("signal", 0))
    try:
        os.kill(pid, sig)
        return {"type": "Ack"}
    except:
        return {"type": "Error", "message": "Process not found"}


@router.handler("WorkerStatus")
async def handle_worker_status(
    server: "ZygoteServer", cmd: Dict[str, Any]
) -> Dict[str, Any]:
    pid = int(cmd.get("worker_pid", 0))
    alive = server.worker_registry.is_alive(pid)
    return {
        "type": "WorkerInfo",
        "worker_pid": pid,
        "is_running": alive,
        "uptime_secs": 0,
    }


@router.handler("Shutdown")
async def handle_shutdown(server: "ZygoteServer", cmd: Dict) -> Dict:
    LogUtils.log("Graceful Shutdown Initiated.")
    server._set_state(ZygoteState.SHUTDOWN)
    # RFC-0012 C.6: Kill all workers before Zygote exits to prevent orphans
    server.worker_registry.kill_all()
    # Use os._exit to bypass any blocking cleanup handlers
    os._exit(0)


@router.handler("Status")
async def handle_zy_status(
    server: "ZygoteServer", cmd: Dict[str, Any]
) -> Dict[str, Any]:
    status = {
        "type": "Status",
        "pid": os.getpid(),
        "state": server.state.name,
        "preload": server._preloaded_modules,
        # RFC-0011: Optional fields moved to extra or kept if known to supervisor
        "workers": server.worker_registry.get_stats(),
        "app": server.app_name,
    }
    return status


# ============================================================================
# Zygote Server
# ============================================================================


class ZygoteServer:
    """Layer 2: App Layer - Orchestrates the Zygote service."""

    def __init__(
        self,
        socket_path: str,
        preload: Optional[List[str]] = None,
        idle_timeout: Optional[int] = None,
        worker_ttl: Optional[int] = None,
        app_name: Optional[str] = None,
        monitor_parent: bool = True,
        authorized_secret: Optional[str] = None,
    ):
        self.config = velo_config

        # RFC-0011 D.1: Support abstract sockets (@ -> \0)
        self.is_abstract = socket_path.startswith("@")
        if self.is_abstract:
            self.socket_path = "\0" + socket_path[1:]
        else:
            self.socket_path = socket_path

        self.idle_timeout = idle_timeout or self.config.graceful_shutdown_timeout
        self.worker_ttl = worker_ttl
        self.app_name = app_name
        self._monitor_parent = monitor_parent
        self._authorized_secret = authorized_secret
        if self._authorized_secret:
            LogUtils.log(f"Zygote initialized with forensic secret (len={len(self._authorized_secret)})")
        else:
            LogUtils.log("Zygote initialized WITHOUT forensic secret")
        
        # Internal state
        self.state = ZygoteState.INIT
        self.worker_registry = WorkerRegistry(worker_ttl or 3600)
        self.preload = preload or self.config.preload_modules
        self._preloaded_modules: List[str] = []
        self.memory_limit_mb = self.config.max_bundle_size // (1024 * 1024)
        self.fork_rate_limiter = ForkRateLimiter(60, 1) # 1 fork per sec avg, burst 60
        self.preload_complete = asyncio.Event()
        self.fork_queue: asyncio.Queue[
            Tuple[Dict[str, Any], asyncio.Future[Any]]
        ] = asyncio.Queue()

        self.pending_forks: Dict[int, asyncio.Future[Any]] = {}
        self._last_activity = time.time()
        self._active_clients = 0
        self._start_time = time.time()
        
        # PID Check State (SEC-005)
        self._needs_auth: Dict[socket.socket, bool] = {}

    def _set_state(self, new_state: ZygoteState) -> None:
        """Standardized state transition with audit trail."""
        old_state = self.state
        if old_state != new_state:
            self.state = new_state
            LogUtils.debug_log(
                f"State Transition: {old_state.name} -> {new_state.name}"
            )

    async def start(self) -> None:
        """Start the Zygote server using asyncio."""
        try:
            from velo_zygote.utils import MacOSDeathSigMonitor
        except ImportError:
            try:
                from utils import MacOSDeathSigMonitor
            except ImportError:
                # Last resort relative import (but usually fails in script mode)
                from .utils import MacOSDeathSigMonitor

        if self._monitor_parent:
            MacOSDeathSigMonitor.start_monitoring()

        LogUtils.log(f"Zygote initializing (PID: {os.getpid()})")

        # 1. Open Socket
        if not self.is_abstract and os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError as e:
                LogUtils.log(
                    f"Zygote Cleanup Error: Failed to unlink stale socket at '{self.socket_path}': {e}"
                )

        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server_sock.bind(self.socket_path)
        except OSError as e:
            LogUtils.log(
                f"Zygote Bootstrap Failure: Cannot bind to {self.socket_path}. Ensure parent directory exists and permissions are correct. Detail: {e}"
            )
            sys.exit(1)

        if not self.is_abstract:
            try:
                os.chmod(self.socket_path, 0o600)
            except OSError as e:
                LogUtils.log(
                    f"Zygote Security Warning: Failed to set permissions on {self.socket_path}: {e}"
                )
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

        self._set_state(ZygoteState.IDLE)
        LogUtils.log(f"Listening on {self.socket_path}")

        loop = asyncio.get_event_loop()
        # RFC-0012: Ensure enough threads for concurrent blocking IPC (Trap 178.9)
        from concurrent.futures import ThreadPoolExecutor

        loop.set_default_executor(ThreadPoolExecutor(max_workers=200))

        while True:
            try:
                # Use loop.sock_accept for non-blocking accept
                try:
                    client_sock, _ = await asyncio.wait_for(
                        loop.sock_accept(server_sock), timeout=5.0
                    )
                    # We keep client_sock non-blocking or blocking?
                    # The sync transport expects blocking behavior for recvmsg/sendall
                    client_sock.setblocking(True)
                    asyncio.create_task(self._handle_client_socket(client_sock))
                    self._last_activity = time.time()
                except asyncio.TimeoutError:
                    # Check for idle timeout
                    if (
                        self.idle_timeout
                        and (time.time() - self._last_activity) > self.idle_timeout
                    ):
                        if not self.worker_registry.workers and self._active_clients <= 0:
                            LogUtils.log(
                                f"Idle timeout ({self.idle_timeout}s). Shutting down."
                            )
                            break
            except Exception as e:
                if not isinstance(e, (asyncio.TimeoutError, KeyboardInterrupt)):
                    LogUtils.log(f"Accept error: {e}")

    def _verify_peer(self, sock: socket.socket) -> bool:
        """
        Verify peer identity (SEC-005).
        Returns True if peer is fully trusted (Supervisor).
        Returns False if peer needs additional Auth (Forensic Agent).
        Raises PermissionError if peer is unauthorized.
        """
        # RFC-0012 Gate SEC-005: Sovereign Identity Verification (PeerCred)
        # 1. Platform-specific check
        uid, pid, gid = -1, -1, -1
        
        if sys.platform == "linux":
            import struct
            # ... linux implementation ...
            creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
            pid, uid, gid = struct.unpack('3i', creds)
        elif sys.platform == "darwin":
            # macOS implementation
            import ctypes
            import ctypes.util
            libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
            # LOCAL_PEERCRED = 0x001 # macOS constant
            # class Xucred(ctypes.Structure):
            #     _fields_ = [("cr_version", ctypes.c_uint),
            #                ("cr_uid", ctypes.c_uint),
            #                ("cr_ngroups", ctypes.c_short),
            #                ("cr_groups", ctypes.c_uint * 16)]
            
            # Note: macOS getpeereid is more direct for UID
            # But we often need PID for Guardian checks
            # LOCAL_PEERPID is a better fit for strict supervisor check
            LOCAL_PEERPID = 0x002
            pid_val = ctypes.c_int()
            size = ctypes.c_uint(ctypes.sizeof(pid_val))
            # SOL_LOCAL is 0 on macOS
            if libc.getsockopt(sock.fileno(), 0, LOCAL_PEERPID, ctypes.byref(pid_val), ctypes.byref(size)) == 0:
                pid = pid_val.value
            
            uid = os.getuid() # Fallback for UID on same-system probes

        # 1. UID Check (Basic sanitization)
        # RFC-0012: Sovereign Identity Verification must at least match the owner UID.
        if uid != -1 and uid != os.getuid():
             raise PermissionError(f"Unauthorized peer connection attempt (UID: {uid}, Expected: {os.getuid()})")
              
        # 2. Strict PID Check (Guardian/Supervisor Only)
        # Only the parent process (Supervisor) is allowed to talk to Zygote without Auth.
        if self._monitor_parent and pid != -1:
            ppid = os.getppid() 
            if pid == ppid:
                 return True # Fully trusted (Supervisor)
            
        # 3. Forensic Agent Auth (Authorized Secret required)
        if self._authorized_secret:
            # If a secret is set, ANY non-supervisor connection MUST perform Auth handshake.
            return False # Needs Auth
            
        # 4. Default Trust (Same UID, No Secret)
        # If no secret is set, we trust same-UID peers (like Docker/Postgres model).
        # This allows 'velo status' to work without a global secret file.
        return True

    async def _handle_client_socket(self, sock: socket.socket) -> None:
        """Handle a client connection using the synchronous transport."""
        self._active_clients += 1
        transport = ZygoteTransport(sock)
        try:
            # RFC-0012 Gate SEC-005: Sovereign Identity Verification (PeerCred)
            try:
                fully_trusted = self._verify_peer(sock)
            except PermissionError as e:
                LogUtils.log(f"Access Denied: {e}")
                sock.close()
                return

            try:
                transport.send({"type": "Ready"})
            except BrokenPipeError:
                # Drive-by probe (Trap 178.7) - ignore silently
                return

            authorized = fully_trusted
            while True:
                # Use run_in_executor for blocking recvmsg
                msg = await asyncio.get_event_loop().run_in_executor(
                    None, transport.recv
                )
                if not msg:
                    break

                self._last_activity = time.time()
                
                # SEC-005: Forensic Auth Handshake
                if msg.get("type") == "Auth":
                    secret = msg.get("secret")
                    if secret == self._authorized_secret:
                        authorized = True
                        LogUtils.log("[SEC-005] Auth Success: Forensic Agent accepted.")
                        transport.send({"type": "Ack", "message": "Authorized"})
                        continue
                    elif not authorized:
                        # Only reject if we weren't already trusted via PeerIdentity
                        LogUtils.log("[SEC-005] Auth Failure: Invalid secret.")
                        transport.send({"type": "Error", "message": "Invalid secret"})
                        break
                    else:
                        # Already authorized (e.g. via PeerIdentity), but sent an Auth command?
                        # We accept it if the secret is valid, or if we already trust them.
                        if secret == self._authorized_secret:
                            LogUtils.log("[SEC-005] Auth Success: Redundant Auth accepted.")
                            transport.send({"type": "Ack", "message": "Authorized"})
                        else:
                            LogUtils.log("[SEC-005] Auth Warning: Redundant Auth with mismatching secret (ignoring as already trusted).")
                            transport.send({"type": "Ack", "message": "Already authorized"})
                        continue

                # SEC-005: Mandatory Auth Handshake check
                if not authorized:
                    LogUtils.log("[SEC-005] Auth Violation: Command received before Auth.")
                    transport.send({"type": "Error", "message": "Auth required"})
                    break

                req_id = msg.get("request_id")
                token = request_context.set(req_id)
                try:
                    response = await router.dispatch(self, msg)
                    await asyncio.get_event_loop().run_in_executor(
                        None, transport.send, response
                    )
                finally:
                    request_context.reset(token)

                if response.get("type") == "Ack" and msg.get("type") == "Shutdown":
                    break
        except ProtocolError as pe:
            # Rule 2: Fail-Loud for protocol violations
            LogUtils.log(f"🚨 IPC Protocol Violation: {pe}")
        except Exception as e:
            LogUtils.log(f"Unexpected Client error (PID:{os.getpid()}): {e}")
            import traceback

            LogUtils.debug_log(traceback.format_exc())
        finally:
            self._active_clients -= 1
            transport.close()

    async def _async_preload(self) -> None:
        """Handle preloading modules in the background."""
        self._set_state(ZygoteState.PRELOADING)
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._preload_modules)
            self._set_state(ZygoteState.READY)
            LogUtils.log(
                f"Preload complete. {len(self._preloaded_modules)} modules loaded."
            )
        except Exception as e:
            LogUtils.log(f"Preload Critical Failure: {e}")
            self._set_state(ZygoteState.ERROR)

        self.preload_complete.set()

        # Process fork queue
        await self._process_fork_queue()

    def _preload_modules(self) -> None:
        import importlib

        for module_name in self.preload:
            try:
                importlib.import_module(module_name)
                self._preloaded_modules.append(module_name)
            except Exception as e:
                LogUtils.log(f"Preload failed for {module_name}: {e}")

    async def _process_fork_queue(self) -> None:
        while not self.fork_queue.empty():
            cmd, future = await self.fork_queue.get()
            result = await handle_fork(self, cmd)
            future.set_result(result)

    def _setup_signals(self) -> None:
        def handle_termination(sig: int, frame: Any) -> None:
            # SEC-P0-006: Immediate cleanup on signal, bypassing event loop
            sys.stderr.write(f"\nZygote received signal {sig}. Cleaning up workers...\n")
            sys.stderr.flush()
            self.worker_registry.kill_all()
            # Use os._exit to ensure immediate death and no orphans
            os._exit(0)

        # Use standard signal.signal for reliable termination even if loop is hung
        signal.signal(signal.SIGTERM, handle_termination)
        signal.signal(signal.SIGINT, handle_termination)

        # Standard SIGCHLD behavior for async reaping
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        asyncio.get_event_loop().create_task(self._async_reap())

    async def _async_reap(self) -> None:
        """Async-safe zombie reaping."""
        while True:
            await asyncio.sleep(0.01)
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
                    LogUtils.log(f"Child {pid} exited with status {status}")
                    self.worker_registry.remove(pid)
            except ChildProcessError:
                pass
            except Exception as e:
                LogUtils.log(f"Reaper error: {e}")

    async def _resource_guard(self) -> None:
        """Monitor memory usage and guard resources."""
        while True:
            await asyncio.sleep(60.0)
            self.worker_registry.reap_stale()
            # Memory check logic here...


# ============================================================================
# Entry Point
# ============================================================================


def zygote_main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Velo Zygote Process")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--preload", nargs="*", default=[])
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--worker-ttl", type=int)
    parser.add_argument("--no-guardian", action="store_true")
    parser.add_argument("--app", help="App name for affinity verification")
    parser.add_argument("--authorized-secret", help="Forensic secret for external auth")

    args = parser.parse_args()

    # Pillar 1: Env Isolation Check (Council Rule)
    # RFC-0012: Environment is already normalized/checked in bootstrap.initialize()

    server = ZygoteServer(
        socket_path=args.socket,
        preload=args.preload,
        idle_timeout=args.timeout,
        worker_ttl=args.worker_ttl,
        app_name=args.app,
        monitor_parent=not args.no_guardian,
        authorized_secret=args.authorized_secret,
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
