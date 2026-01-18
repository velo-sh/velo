
import os
import socket
import sys
from typing import Any

import execnet.gateway_base
from execnet.gateway_socket import SocketIO

import execnet.gateway

# Phase 14 P1: Import shared logic from Zygote core
try:
    from velo_zygote.transport_sync import ZygoteTransport
    from velo_zygote.paths import VeloPaths
except (ImportError, ValueError):
    # Fallback/Diagnostic
    ZygoteTransport = None  # type: ignore
    VeloPaths = None  # type: ignore


class ZygoteGateway(execnet.gateway.Gateway):
    """
    Velo 'Miracle' Gateway: Eliminates intermediate processes by forking 
    directly into an execnet listener.
    """
    
    def __init__(self, spec: Any, socket_path: str = None, secret: str = None):
        if socket_path is None:
            if VeloPaths:
                socket_path = str(VeloPaths.zygote_socket())
            else:
                socket_path = "/tmp/velo-zygote-v01.sock"
            
        # 1. Physical Connect
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(socket_path)
        except Exception as e:
            raise RuntimeError(f"Velo Gateway could not connect to Zygote at {socket_path}: {e}")

        # 2. Negotiate Handover
        transport = ZygoteTransport(sock)
        
        # A. Wait for Zygote Ready
        ready = transport.recv()
        if not ready or ready.get("type") != "Ready":
            sock.close()
            raise RuntimeError(f"Velo Gateway Handover failed (Ready expected): {ready}")
            
        # B. Authenticate if needed
        if secret:
            transport.send({"type": "Auth", "secret": secret})
            auth_resp = transport.recv()
            if not auth_resp or auth_resp.get("type") != "Ack":
                sock.close()
                raise RuntimeError(f"Velo Gateway Auth failed: {auth_resp}")
        
        # C. Request Gateway Hijack
        transport.send({"type": "GatewayFork", "nodeid": spec.id})
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
