import os
import socket
from typing import Any

import execnet.gateway
import execnet.gateway_base
from execnet.gateway_socket import SocketIO

# Phase 14 P1: Import shared logic from Zygote core
try:
    from velo_zygote.paths import VeloPaths
    from velo_zygote.transport_sync import ZygoteTransport
except (ImportError, ValueError) as e:
    # Fallback/Diagnostic
    print(f"!!! [Velo] Gateway Import Error: {e}")
    ZygoteTransport = None  # type: ignore
    VeloPaths = None  # type: ignore


class ZygoteGateway(execnet.gateway.Gateway):
    """
    Velo 'Miracle' Gateway: Eliminates intermediate processes by forking
    directly into an execnet listener.
    """

    def __init__(
        self,
        spec: Any,
        socket_path: str | None = None,
        secret: str | None = None,
        project_root: str | None = None,
    ):
        self.project_root = project_root
        if socket_path is None:
            # First Principles: Try VeloPaths, but gracefully fallback if unavailable
            try:
                if VeloPaths is not None:
                    socket_path = str(VeloPaths.zygote_socket())
            except Exception:
                pass

            if not socket_path:
                # Ultimate fallback: standard temp location
                import tempfile

                uid = os.getuid() if hasattr(os, "getuid") else 0
                socket_path = f"{tempfile.gettempdir()}/velo-{uid}/velo-zygote.sock"

        # 1. Physical Connect
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(socket_path)
        except Exception as e:
            raise RuntimeError(f"Velo Gateway could not connect to Zygote at {socket_path}: {e}") from e

        # 2. Negotiate Handover
        transport = ZygoteTransport(sock)

        # A. Wait for Zygote Ready
        ready = transport.recv()
        if not ready or ready.get("type") != "Ready":
            sock.close()
            raise RuntimeError(f"Velo Gateway Handover failed (Ready expected): {ready}")

        # B. Authenticate (SEC-005: Auto-discover secret from .auth file)
        if secret is None:
            # Try to read secret from .auth file (SEC-005 parity with Rust)
            try:
                from pathlib import Path

                auth_path = Path(socket_path).with_suffix(".auth")
                if auth_path.exists():
                    secret = auth_path.read_text().strip()
            except Exception:
                pass  # No auth file or unreadable - proceed without auth

        transport.send({"type": "Auth", "secret": secret})
        auth_resp = transport.recv()
        if not auth_resp or auth_resp.get("type") != "Ack":
            sock.close()
            raise RuntimeError(f"Velo Gateway Auth failed: {auth_resp}")

        # C. Request Gateway Hijack (pass critical env vars for worker)
        # RFC-0028: Propagate project root and PYTHONPATH to miracle workers
        fork_env = {
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "VELO_ZYGOTE_SOCKET": os.environ.get("VELO_ZYGOTE_SOCKET", ""),
            "VELO_ZYGOTE_AUTH": os.environ.get("VELO_ZYGOTE_AUTH", ""),
            "VELO_MIRACLE_WORKER": "1",
            "VELO_ENV": os.environ.get("VELO_ENV", "dev"),
            # RFC-0029: Propagate xdist worker ID to prevent recursive fork bomb
            "PYTEST_XDIST_WORKER": os.environ.get("PYTEST_XDIST_WORKER", ""),
            "PYTEST_XDIST_WORKER_ID": os.environ.get("PYTEST_XDIST_WORKER_ID", ""),
        }
        transport.send({"type": "GatewayFork", "nodeid": spec.id, "env": fork_env, "project_root": self.project_root})
        fork_resp = transport.recv()
        if not fork_resp or fork_resp.get("type") != "Ack":
            sock.close()
            raise RuntimeError(f"Velo Gateway Handover rejected: {fork_resp}")

        # 3. Takeover Socket for execnet
        # At this point, Zygote parent closed its side, child is listening.
        sock.setblocking(True)

        # Initialize execnet Gateway
        # execnet 2.x uses SocketIO
        io = SocketIO(sock, execmodel=execnet.gateway_base.get_execmodel("thread"))

        super().__init__(io=io, spec=spec)

    def __repr__(self) -> str:
        return f"<ZygoteGateway id={self.id!r} zygote-forked>"
