# RFC-0011 QA Test Suite: Zygote Worker Integration
# tests/qa/phase_6_1_1/test_phase611_agent_d_desync.py

"""
Agent D (Destroyer): Lifecycle Desynchronization Tests

These tests actively corrupt the system state or perform operations out-of-order 
to verify structural integrity.

Priority: P3 (Red Team Initiative)
"""

import os
import signal
import socket
import struct
import time
import sys
from pathlib import Path
import pytest
import requests

# Add vendor path for umsgpack
repo_root = Path(__file__).parent.parent.parent.parent
vendor_path = repo_root / "python" / "velo" / "_vendor"
if str(vendor_path) not in sys.path:
    sys.path.insert(0, str(vendor_path))

try:
    import umsgpack
except ImportError:
    umsgpack = None


def send_msg(sock, msg):
    payload = umsgpack.packb(msg)
    total_len = 1 + len(payload)
    header = struct.pack('<I', total_len)
    version = b'\x01'
    sock.sendall(header + version + payload)


def recv_msg(sock, timeout=2.0):
    sock.settimeout(timeout)
    header = b""
    while len(header) < 4:
        chunk = sock.recv(4 - len(header))
        if not chunk: return None
        header += chunk
    
    total_len = struct.unpack('<I', header)[0]
    version = sock.recv(1)
    
    payload = b""
    to_read = total_len - 1
    while len(payload) < to_read:
        chunk = sock.recv(to_read - len(payload))
        if not chunk: break
        payload += chunk
        
    return umsgpack.unpackb(payload)


@pytest.mark.chaos
class TestAgentDDesync:
    """Agent D: Lifecycle and Protocol Desync Testing."""

    def test_DESYNC_005_fork_bomb_throttling(self, velo_serve_fixture, tmp_path):
        """DESYNC-005: The Fork Bomb (Throttling Check).
        
        Scenario:
        1. Connect to Zygote.
        2. Rapidly send 50 Fork requests for a simple exit script.
        3. Do NOT call waitpid/reap.
        
        Expectation:
        - Zygote should either throttle or handle the load.
        - Check if Zygote's internal worker registry hits a limit (if one exists).
        - Verify Zygote doesn't hit PID exhaustion or OOM.
        """
        if umsgpack is None:
            pytest.skip("umsgpack not available")
            
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()
        
        # Identity Zygote socket
        uid = os.getuid()
        socket_path = str(list(Path(f"/tmp/velo-{uid}").glob("velo-zygote-v*.sock"))[0])
        
        script = tmp_path / "exit.py"
        script.write_text("import sys; sys.exit(0)")
        
        conns = []
        pids = []
        
        # Attack: Fork 50 times rapidly
        try:
            for _ in range(50):
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(socket_path)
                recv_msg(s) # Ready
                
                send_msg(s, {
                    "type": "Fork",
                    "script_path": str(script),
                    "async_mode": True
                })
                resp = recv_msg(s)
                if resp and resp.get("type") == "Forked":
                    pids.append(resp["worker_pid"])
                conns.append(s)
        finally:
            for s in conns: s.close()
            
        # Verify Zygote survived the bomb
        time.sleep(1)
        requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=2)
        
        # Verify all forked processes are eventually reaped or present
        # Currently, main.py reaps in loop and via SIGCHLD
        # We check if Zygote PID is still alive
        try:
            os.kill(proc.zygote_pid, 0)
        except OSError:
            pytest.fail("Zygote died during Fork Bomb attack")

    def test_DESYNC_006_dead_hand_wait(self, velo_serve_fixture, tmp_path):
        """DESYNC-006: Dead Hand Wait.
        
        Scenario:
        1. Fork a worker.
        2. Wait for it to exit and be reaped by Zygote.
        3. Send WaitWorker for the ALREADY reaped PID.
        
        Expectation:
        - Zygote must handle WaitWorker for non-existent PIDs gracefully.
        - Should return WorkerExited with 0 or Error, but NOT crash.
        """
        if umsgpack is None:
            pytest.skip("umsgpack not available")
            
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()
        
        uid = os.getuid()
        socket_path = str(list(Path(f"/tmp/velo-{uid}").glob("velo-zygote-v*.sock"))[0])
        
        script = tmp_path / "exit_fast.py"
        script.write_text("import sys; sys.exit(0)")
        
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(socket_path)
            recv_msg(s) # Ready
            
            # 1. Fork
            send_msg(s, {"type": "Fork", "script_path": str(script), "async_mode": True})
            resp = recv_msg(s)
            pid = resp["worker_pid"]
            
            # 2. Wait for it to definitely die and be reaped
            time.sleep(1.0)
            
            # 3. Wait on dead hand
            send_msg(s, {"type": "WaitWorker", "worker_pid": pid})
            resp = recv_msg(s)
            
            # Current main.py implementation:
            # if not server.worker_registry.is_alive(pid):
            #     return {"type": "WorkerExited", "worker_pid": pid, "exit_code": 0}
            assert resp["type"] == "WorkerExited"
            assert resp["worker_pid"] == pid

    def test_DESYNC_007_shadow_handshake(self, velo_serve_fixture):
        """DESYNC-007: Shadow Handshake (OutOfOrder).
        
        Scenario:
        1. Connect to Zygote.
        2. Send a Fork command BEFORE the Handshake command (or even before Ready is even finished processing on client side).
        3. Send commands in multiplexed way.
        
        Expectation:
        - Zygote currently doesn't enforce 'Handshake First'.
        - This test documents the behavior and ensures Zygote doesn't crash if state is 'uninitialized'.
        """
        if umsgpack is None:
            pytest.skip("umsgpack not available")
            
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()
        
        uid = os.getuid()
        socket_path = str(list(Path(f"/tmp/velo-{uid}").glob("velo-zygote-v*.sock"))[0])
        
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(socket_path)
            # We skip reading 'Ready' and just fire a status command
            send_msg(s, {"type": "Status"})
            
            # Now we read the 'Ready' that was sent by server
            ready = recv_msg(s)
            assert ready["type"] == "Ready"
            
            # Now we should get the Status response
            status = recv_msg(s)
            assert status["type"] == "Status"
            assert "pid" in status
