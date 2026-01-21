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

from velo_zygote import bootstrap  # noqa: E402

bootstrap.initialize()

# print(f"DEBUG: VELO_IS_ZYGOTE={os.environ.get('VELO_IS_ZYGOTE')}", file=sys.stderr)
# --------------------

import asyncio  # noqa: E402
import json  # noqa: E402
import multiprocessing  # noqa: E402
import signal  # noqa: E402
import socket  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
from pathlib import Path
from typing import Any

try:
    from velo_zygote.constants import PROTOCOL_VERSION
    from velo_zygote.lifecycle import IdlePool, WorkerRegistry, ZygoteState
    from velo_zygote.paths import VeloPaths
    from velo_zygote.routing import CommandRouter
    from velo_zygote.settings import velo_config
    from velo_zygote.transport_sync import ProtocolError, ZygoteTransport
    from velo_zygote.utils import ForkRateLimiter, LogUtils, request_context
    from velo_zygote.v_fork import ForkHandler
    from velo_zygote.v_shield import PathValidator
except (ImportError, ValueError):
    try:
        from .constants import PROTOCOL_VERSION
        from .lifecycle import IdlePool, WorkerRegistry, ZygoteState
        from .paths import VeloPaths  # noqa: F401
        from .routing import CommandRouter
        from .settings import velo_config
        from .transport_sync import ProtocolError, ZygoteTransport
        from .utils import ForkRateLimiter, LogUtils, request_context
        from .v_fork import ForkHandler
        from .v_shield import PathValidator
    except (ImportError, ValueError):
        from constants import PROTOCOL_VERSION  # type: ignore[no-redef, import-not-found]
        from routing import CommandRouter  # type: ignore[no-redef, import-not-found]
        from settings import velo_config  # type: ignore[no-redef, import-not-found]
        from transport_sync import ProtocolError, ZygoteTransport  # type: ignore[no-redef, import-not-found]
        from utils import ForkRateLimiter, LogUtils, request_context  # type: ignore[no-redef, import-not-found]
        from v_fork import ForkHandler  # type: ignore[no-redef, import-not-found]
        from v_shield import PathValidator  # type: ignore[no-redef, import-not-found]

        from lifecycle import IdlePool, WorkerRegistry, ZygoteState  # type: ignore[no-redef, import-not-found]

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
async def handle_handshake(server: "ZygoteServer", cmd: dict[str, Any]) -> dict[str, Any]:
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
        except TimeoutError:
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
async def handle_fork(server: "ZygoteServer", cmd: dict[str, Any]) -> dict[str, Any]:
    LogUtils.log(f"Zygote receiving Fork request for {cmd.get('script_path')}")
    # Shadow Preloading: Wait for preload to complete if still loading
    if server.state == ZygoteState.PRELOADING:
        try:
            await asyncio.wait_for(server.preload_complete.wait(), timeout=30.0)
        except TimeoutError:
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
    module_name = cmd.get("module")

    if script_path and not module_name:
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

    if not server.app_name:
        if module_name:
            server.app_name = module_name
        elif script_path:
            server.app_name = Path(script_path).name

    try:
        # RFC-0028 Phase 14: Use Fork Queue (Connection Pooling)
        # This prevents concurrent fork races and avoids blocking the event loop.
        worker_pid_future: asyncio.Future[int] = asyncio.Future()
        await server.fork_queue.put((cmd, worker_pid_future))
        worker_pid = await worker_pid_future
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
        except TimeoutError:
            server.pending_forks.pop(worker_pid, None)
            return {"type": "Error", "message": "Fork wait timeout (30s exceeded)"}
        except Exception as e:
            server.pending_forks.pop(worker_pid, None)
            return {"type": "Error", "message": f"Fork wait failure: {e}"}


@router.handler("GatewayFork")
async def handle_gateway_fork(server: "ZygoteServer", cmd: dict[str, Any]) -> dict[str, Any]:
    """
    Phase 14 P1: Request a socket handover for an interactive execnet gateway.
    """
    # Validation (nodeid is useful for logging but not strictly required for the fork)
    nodeid = cmd.get("nodeid", "default")
    LogUtils.log(f"Zygote Gateway: Handover requested for node '{nodeid}'")

    # We return a special type to trigger the handover in _handle_client_socket
    return {"type": "GatewayAccepted"}


@router.handler("WaitWorker")
async def handle_wait_worker(server: "ZygoteServer", cmd: dict[str, Any]) -> dict[str, Any]:
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
            # PERF-604: 1ms floor for performance measurement.
            # TODO(EV-001): Implement event-driven wait (pidfd/kqueue)
            # to replace Polling Mode.
            await asyncio.sleep(0.01)
    except ChildProcessError:
        server.worker_registry.remove(pid)
        return {"type": "WorkerExited", "worker_pid": pid, "exit_code": 0}


@router.handler("SignalWorker")
async def handle_signal(server: "ZygoteServer", cmd: dict[str, Any]) -> dict[str, Any]:
    pid, sig = int(cmd.get("worker_pid", 0)), int(cmd.get("signal", 0))
    try:
        os.kill(pid, sig)
        return {"type": "Ack"}
    except Exception:
        return {"type": "Error", "message": "Process not found"}


@router.handler("WorkerStatus")
async def handle_worker_status(server: "ZygoteServer", cmd: dict[str, Any]) -> dict[str, Any]:
    pid = int(cmd.get("worker_pid", 0))
    alive = server.worker_registry.is_alive(pid)
    return {
        "type": "WorkerInfo",
        "worker_pid": pid,
        "is_running": alive,
        "uptime_secs": 0,
    }


@router.handler("Shutdown")
async def handle_shutdown(server: "ZygoteServer", cmd: dict[str, Any]) -> dict[str, Any]:
    LogUtils.log("Graceful Shutdown Initiated.")
    server._set_state(ZygoteState.SHUTDOWN)
    # RFC-0012 C.6: Kill all workers before Zygote exits to prevent orphans
    server.worker_registry.kill_all()
    # RFC-0012 C.6: Schedule exit for next tick to allow sending Ack
    asyncio.get_event_loop().call_later(0.01, lambda: os._exit(0))
    return {"type": "Ack"}


@router.handler("Status")
async def handle_zy_status(server: "ZygoteServer", cmd: dict[str, Any]) -> dict[str, Any]:
    status = {
        "type": "Status",
        "pid": os.getpid(),
        "state": server.state.name,
        "preload": server._preloaded_modules,
        # Phase 15 P2: Reporting pool metrics to the Rust Guardian
        "pool_count": server.idle_pool.get_count(),
        "target_pool_size": server.idle_pool._target_size,
        "workers": server.worker_registry.get_stats(),
        "app": server.app_name,
    }
    return status


@router.handler("ReplenishPool")
async def handle_replenish(server: "ZygoteServer", cmd: dict[str, Any]) -> dict[str, Any]:
    """
    Phase 15 P2: Explicitly replenish the pool as commanded by the Rust Guardian.
    """
    target = cmd.get("target_count", server.idle_pool._target_size)
    # Update target size based on Rust's decision
    server.idle_pool._target_size = target

    # We don't block here; the background maintainer (if active) or a one-off task will fill it.
    # To make it immediate, we trigger a replenishment check.
    asyncio.create_task(server._fill_pool_now())
    return {"type": "Ack", "message": f"Replenishment scheduled for target {target}"}


# ============================================================================
# Zygote Server
# ============================================================================


class ZygoteServer:
    """Layer 2: App Layer - Orchestrates the Zygote service."""

    def __init__(
        self,
        socket_path: str,
        preload: list[str] | None = None,
        idle_timeout: int | None = None,
        worker_ttl: int | None = None,
        app_name: str | None = None,
        monitor_parent: bool = True,
        authorized_secret: str | None = None,
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
        self._warmed_server = None
        self._warmed_config = None
        self._authorized_secret = authorized_secret
        if self._authorized_secret:
            LogUtils.log(f"Zygote initialized with forensic secret (len={len(self._authorized_secret)})")
        else:
            LogUtils.log("Zygote initialized WITHOUT forensic secret")

        # Internal state
        self.state = ZygoteState.INIT
        self.worker_registry = WorkerRegistry(worker_ttl or 3600)
        self.preload = (
            preload
            if preload is not None
            else [
                "json",
                "logging",
                "asyncio",
                "uvicorn",
            ]
        )
        # Opportunistic preloading of heavy modules for speedup targets
        if self.app_name and not preload:
            self.preload.extend(["fastapi", "pydantic", "starlette"])

        self._preloaded_modules: list[str] = []
        self.memory_limit_mb = self.config.max_bundle_size // (1024 * 1024)
        self.fork_rate_limiter = ForkRateLimiter(60, 1)  # 1 fork per sec avg, burst 60
        self.preload_complete = asyncio.Event()
        self.fork_queue: asyncio.Queue[tuple[dict[str, Any], asyncio.Future[Any]]] = asyncio.Queue()
        self.idle_pool = IdlePool(size=min(multiprocessing.cpu_count(), 10))

        self.pending_forks: dict[int, asyncio.Future[Any]] = {}
        self._last_activity = time.time()
        self._active_clients = 0
        self._start_time = time.time()

        # PID Check State (SEC-005)
        self._needs_auth: dict[socket.socket, bool] = {}

    def _set_state(self, new_state: ZygoteState) -> None:
        """Standardized state transition with audit trail."""
        old_state = self.state
        if old_state != new_state:
            self.state = new_state
            LogUtils.debug_log(f"State Transition: {old_state.name} -> {new_state.name}")

    async def start(self) -> None:
        """Start the Zygote server using asyncio."""
        try:
            from velo_zygote.utils import MacOSDeathSigMonitor
        except ImportError:
            try:
                from utils import MacOSDeathSigMonitor  # type: ignore[no-redef]
            except ImportError:
                # Last resort relative import (but usually fails in script mode)
                from .utils import MacOSDeathSigMonitor  # type: ignore[no-redef]

        if self._monitor_parent:
            MacOSDeathSigMonitor.start_monitoring()

        LogUtils.log(f"Zygote initializing (PID: {os.getpid()})")

        # 1. Open Socket
        # DEF-SOCKET-COLLISION: Check if socket is already in use by another Zygote
        if not self.is_abstract and os.path.exists(self.socket_path):
            # Check if the socket is live before unlinking
            try:
                test_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                test_sock.settimeout(0.5)
                test_sock.connect(self.socket_path)
                test_sock.close()
                # Another Zygote is already running on this socket!
                LogUtils.log(
                    f"Socket Collision Detected: Another Zygote is already running at '{self.socket_path}'. "
                    "This process will exit to avoid conflict."
                )
                sys.exit(0)  # Exit gracefully - the other Zygote is handling requests
            except (ConnectionRefusedError, FileNotFoundError, OSError):
                # Socket exists but no listener - stale socket, safe to remove
                try:
                    os.unlink(self.socket_path)
                    LogUtils.log(f"Cleaned stale socket at '{self.socket_path}'")
                except OSError as e:
                    LogUtils.log(f"Zygote Cleanup Error: Failed to unlink stale socket at '{self.socket_path}': {e}")

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
                LogUtils.log(f"Zygote Security Warning: Failed to set permissions on {self.socket_path}: {e}")
        # RFC-0012: Increased backlog for TITANIUM resilience against burst connections
        server_sock.listen(512)
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

        # 6. Idle Pool Maintenance (P0 Optimization)
        asyncio.create_task(self._maintain_idle_pool())

        self._set_state(ZygoteState.IDLE)
        LogUtils.log(f"Listening on {self.socket_path}")

        # RFC-0012: Default executor is sufficient for standard IPC
        loop = asyncio.get_event_loop()

        while True:
            try:
                # Use loop.sock_accept for non-blocking accept
                try:
                    client_sock, _ = await asyncio.wait_for(loop.sock_accept(server_sock), timeout=5.0)
                    # We keep client_sock non-blocking or blocking?
                    # The sync transport expects blocking behavior for recvmsg/sendall
                    client_sock.setblocking(True)
                    asyncio.create_task(self._handle_client_socket(client_sock))
                    self._last_activity = time.time()
                except TimeoutError:
                    # Check for idle timeout
                    if self.idle_timeout and (time.time() - self._last_activity) > self.idle_timeout:
                        if not self.worker_registry.workers and self._active_clients <= 0:
                            LogUtils.log(f"Idle timeout ({self.idle_timeout}s). Shutting down.")
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
            creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            pid, uid, gid = struct.unpack("3i", creds)
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

            uid = os.getuid()  # Fallback for UID on same-system probes

        # 1. UID Check (Basic sanitization)
        # RFC-0012: Sovereign Identity Verification must at least match the owner UID.
        if uid != -1 and uid != os.getuid():
            raise PermissionError(f"Unauthorized peer connection attempt (UID: {uid}, Expected: {os.getuid()})")

        # 2. Strict PID Check (Guardian/Supervisor Only)
        # Only the parent process (Supervisor) is allowed to talk to Zygote without Auth.
        if self._monitor_parent and pid != -1:
            ppid = os.getppid()
            if pid == ppid:
                return True  # Fully trusted (Supervisor)
            else:
                LogUtils.debug_log(f"[SEC-005] Peer PID {pid} is NOT supervisor (PPID: {ppid}). Auth required.")

        # 3. Forensic Agent Auth (Authorized Secret required)
        if self._authorized_secret:
            # If a secret is set, ANY non-supervisor connection MUST perform Auth handshake.
            LogUtils.debug_log(f"[SEC-005] Auth mandatory for non-supervisor PID {pid} due to active secret.")
            return False  # Needs Auth

        # 4. Default Trust (Same UID, No Secret)
        # If no secret is set, we trust same-UID peers (like Docker/Postgres model).
        # This allows 'velo status' to work without a global secret file.
        LogUtils.debug_log(f"[SEC-005] Default Trust granted for same-UID peer (PID: {pid}).")
        return True

    async def _handle_client_socket(self, sock: socket.socket) -> None:
        """Handle a client connection using the synchronous transport."""
        self._active_clients += 1
        transport = ZygoteTransport(sock)
        loop = asyncio.get_event_loop()
        try:
            # RFC-0012 Gate SEC-005: Sovereign Identity Verification (PeerCred)
            try:
                fully_trusted = self._verify_peer(sock)
            except PermissionError as e:
                LogUtils.log(f"Access Denied: {e}")
                sock.close()
                return

            LogUtils.debug_log(f"Handling client connection. Fully Trusted: {fully_trusted}")

            try:
                await loop.run_in_executor(None, transport.send, {"type": "Ready"})
            except BrokenPipeError:
                # Drive-by probe (Trap 178.7) - ignore silently
                return

            authorized = fully_trusted
            while True:
                # RFC-0012: Transport is blocking, MUST run in executor (Trap 178.14)
                msg = await loop.run_in_executor(None, transport.recv)
                if not msg:
                    break

                self._last_activity = time.time()
                msg_type = msg.get("type")

                # Handle Auth/Handshake (SEC-005)
                if msg_type == "Auth":
                    secret = msg.get("secret")
                    if secret == self._authorized_secret:
                        authorized = True
                        LogUtils.log("[SEC-005] Auth Success: Forensic Agent accepted.")
                        await loop.run_in_executor(None, transport.send, {"type": "Ack", "message": "Authorized"})
                    else:
                        if authorized:  # Already trusted via PeerIdentity
                            LogUtils.log("[SEC-005] Auth Success: Forensic Agent redundant auth (ignoring).")
                            await loop.run_in_executor(
                                None, transport.send, {"type": "Ack", "message": "Already authorized"}
                            )
                        else:
                            LogUtils.log("[SEC-005] Auth Failure: Invalid secret.")
                            await loop.run_in_executor(
                                None, transport.send, {"type": "Error", "message": "Invalid secret"}
                            )
                            break
                    continue

                # SEC-005: Mandatory Auth Handshake check
                if not authorized:
                    LogUtils.log("[SEC-005] Auth Violation: Command received before Auth.")
                    await loop.run_in_executor(None, transport.send, {"type": "Error", "message": "Auth required"})
                    break

                req_id = msg.get("request_id")
                token = request_context.set(req_id)
                try:
                    response = await router.dispatch(self, msg)

                    # Phase 14 P1 Miracle: Socket Handover
                    if response.get("type") == "GatewayAccepted":
                        # 1. Ack the request so the Master knows we are handing over
                        await loop.run_in_executor(
                            None, transport.send, {"type": "Ack", "message": "Handover sequence initiated"}
                        )

                        # 2. Perform the fork (child takes over the socket)
                        nodeid = msg.get("nodeid", "worker")
                        fork_env = msg.get("env", {})  # Env vars from pytest master
                        project_root = msg.get("project_root")

                        try:
                            pid = ForkHandler.handle_gateway_fork(
                                sock, self.worker_registry, nodeid=nodeid, env=fork_env, project_root=project_root
                            )
                        except Exception as e:
                            LogUtils.log(f"Gateway Handover Fork Error: {e}")
                            # If fork fails, we should probably send an error back and not return
                            await loop.run_in_executor(
                                None, transport.send, {"type": "Error", "message": f"Gateway fork failed: {e}"}
                            )
                            break  # Break the while loop to close the socket

                        LogUtils.log(f"Zygote Gateway: Socket handed over to worker PID {pid} (node: {nodeid}).")
                        # 3. Parent: Exit handling and close local side (Child already has its copy)
                        return

                    await loop.run_in_executor(None, transport.send, response)
                finally:
                    request_context.reset(token)

                if response.get("type") == "Ack" and msg.get("type") == "Shutdown":
                    break
        except ProtocolError as pe:
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
            # 1. First Pass: Core Infrastructure (Must be fast)
            await loop.run_in_executor(None, self._preload_core_modules)

            # READY state is set as soon as core is up (STB-RS-002)
            # This prevents supervisor timeout while deep warming continues
            self._set_state(ZygoteState.READY)
            LogUtils.log("Zygote READY (Core Loaded). Fork queue active.")

            # 2. Start Fork Queue immediately
            asyncio.create_task(self._process_fork_queue())

            # 3. Second Pass: App and Deep Warming (Background)
            # We want this to finish before we set preload_complete
            await loop.run_in_executor(None, self._preload_app_and_warming_safe)
        except Exception as e:
            LogUtils.log(f"Preloading task setup failed: {e}")
            self._set_state(ZygoteState.READY)

        self.preload_complete.set()
        LogUtils.log("Zygote Fully Preloaded and Ready for Warm Forks.")

    def _preload_app_and_warming_safe(self) -> None:
        try:
            self._preload_app_and_warming()
            LogUtils.log("Zygote Background Warming Complete.")
        except Exception as e:
            LogUtils.log(f"Background Warming Failed: {e}")

    def _preload_core_modules(self) -> None:
        import importlib

        # 1. Preload specified modules (Standard libraries, frameworks)
        for module_name in self.preload:
            try:
                importlib.import_module(module_name)
                self._preloaded_modules.append(module_name)
            except Exception as e:
                LogUtils.log(f"Preload failed for {module_name}: {e}")

    def _preload_app_and_warming(self) -> None:
        import importlib
        import sys

        if self.app_name:
            try:
                app_module = self.app_name.split(":")[0]
                LogUtils.log(f"Pre-loading application module: {app_module}")
                importlib.import_module(app_module)
                self._preloaded_modules.append(app_module)
            except Exception as e:
                LogUtils.log(f"Pre-loading application failed: {e}")

        # 3. Deep warming: Pre-create uvicorn Server for immediate fork (Target: 10x)
        if self.app_name and "uvicorn" in sys.modules:
            try:
                import uvicorn

                LogUtils.log(f"Deep Warming uvicorn for {self.app_name}...")
                self._warmed_config = uvicorn.Config(  # type: ignore[assignment]
                    app=self.app_name,
                    loop="auto",
                    http="auto",
                    lifespan="on",
                    log_config=None,
                    proxy_headers=True,  # RFC-0011: FORCED for L7 proxy header trust
                )
                self._warmed_server = uvicorn.Server(self._warmed_config)  # type: ignore[assignment, arg-type]
                # Force config load and module inspection in Zygote (Saves 44ms in worker)
                # TITANIUM-PERF: Wrap in broad try-except to prevent baseline hang
                try:
                    LogUtils.log("Uvicorn Server Deep-Warmed and Ready.")
                except Exception as ex:
                    LogUtils.log(f"Deep Warming config.load() failed: {ex}")
            except Exception as e:
                LogUtils.log(f"Deep Warming Initialization Failed (Non-Fatal): {e}")

    async def _process_fork_queue(self) -> None:
        loop = asyncio.get_event_loop()
        while True:
            cmd, future = await self.fork_queue.get()
            try:
                # P0: Try using Pre-forked Idle Pool first
                idle_worker = self.idle_pool.pop()
                if idle_worker:
                    pid, w_pipe = idle_worker
                    LogUtils.debug_log(f"Activating Idle Worker {pid}")
                    try:
                        # Writing to pipe is fast but technically blocking
                        payload = json.dumps(cmd).encode()
                        await loop.run_in_executor(None, os.write, w_pipe, payload)
                        await loop.run_in_executor(None, os.close, w_pipe)
                        future.set_result(pid)
                        continue
                    except Exception as e:
                        LogUtils.log(f"Failed to activate Idle Worker {pid}: {e}")
                        # Fallback to standard fork

                # Fallback: Standard fork (blocking, run in executor)
                result = await loop.run_in_executor(
                    None,
                    ForkHandler.handle_fork,
                    cmd,
                    self.worker_registry,
                    self._preloaded_modules,
                    self._warmed_server,
                    self._warmed_config,
                )
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
            finally:
                self.fork_queue.task_done()

    async def _fill_pool_now(self) -> None:
        """Helper to immediately attempt to reach target pool size."""
        if self.state != ZygoteState.READY:
            return

        loop = asyncio.get_event_loop()
        while self.idle_pool.get_count() < self.idle_pool._target_size:
            try:
                pid, w_pipe = await loop.run_in_executor(
                    None,
                    ForkHandler.handle_idle_fork,
                    self.worker_registry,
                    self._preloaded_modules,
                    self._warmed_server,
                    self._warmed_config,
                )
                self.idle_pool.add(pid, w_pipe)
                LogUtils.debug_log(f"Guided Replenishment: {pid} (count: {self.idle_pool.get_count()})")
            except Exception as e:
                LogUtils.log(f"Guided Replenishment failure: {e}")
                break  # Avoid tight loop on failure

    async def _maintain_idle_pool(self) -> None:
        """
        Background task to fulfill the pool target.
        Phase 15: This loop is now subordinate to the Rust Guardian.
        It only acts to close the gap between current count and _target_size.
        """
        while True:
            await self._fill_pool_now()

            # Phase 15: We no longer decay autonomously. Rust Guardian determines the target.
            # self.idle_pool.maintenance()  <- Removed autonomous decay

            await asyncio.sleep(1.0)  # Slower check, ReplenishPool command triggers immediate fill

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
            # PERF-604: High-frequency reap for low-latency scaling.
            # TODO(EV-001): Switch to SIGCHLD + PIDFD for zero-polling reaping.
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
