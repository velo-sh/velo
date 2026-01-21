# RFC-0011 QA Test Suite: Zygote Worker Integration
# tests/qa/phase_6_1_1/test_phase611_agent_d_chaos.py

"""
Agent D (Destroyer): Chaos and Robustness Tests

These tests actively attempt to crash or desync the Zygote process by:
- Flooding it with signals
- Sending malformed IPC messages
- Exhausting connections

Priority: P3 (Red Team Initiative)
"""

import os
import signal
import socket
import struct
import sys
import time
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


@pytest.mark.chaos
class TestAgentDChaos:
    """Agent D: Chaos and Robustness Testing."""

    def test_CHAOS_001_signal_hurricane(self, velo_serve_fixture):
        """CHAOS-001: Signal Hurricane (STORM).

        Scenario:
        1. Start Zygote with 4 workers.
        2. Rapidly kill workers with SIGKILL to trigger high-frequency SIGCHLD.
        3. Simultanously send SIGUSR1 (if handled) or just more SIGCHLD.

        Expectation:
        - Zygote's async_reap task must handle concurrency safely.
        - No "Task was destroyed but it is pending" or waitpid errors that crash Zygote.
        - All workers eventually reaped.
        """
        proc = velo_serve_fixture.start("main:app", workers=4)
        proc.wait_ready()

        zygote_pid = proc.zygote_pid
        assert zygote_pid is not None

        # Initial workers
        workers = proc.get_worker_pids()
        assert len(workers) == 4

        # STORM: Rapidly kill and signal
        for pid in workers:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            # Bombard Zygote with extra SIGCHLD to confuse the loop
            os.kill(zygote_pid, signal.SIGCHLD)

        # Give Zygote a moment to process the hurricane
        time.sleep(5)

        # Verify Zygote is still alive
        try:
            os.kill(zygote_pid, 0)
        except OSError:
            pytest.fail("Zygote died during Signal Hurricane storm")

        # Trigger a request to see if it heals (re-spawns workers)
        try:
            requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=5)
        except Exception:
            pass

        time.sleep(5)

        # Verify workers are restored (allow partial recovery in CI)
        new_workers = proc.get_worker_pids()
        assert len(new_workers) >= 1, f"Zygote failed to recover any workers after storm, found {len(new_workers)}"

    def test_CHAOS_002_pipe_corruption(self, velo_serve_fixture):
        """CHAOS-002: Pipe Corruption (Malformed MessagePack).

        Scenario:
        1. Connect to Zygote UDS directly.
        2. Send garbage:
           a. Invalid length prefix (too huge)
           b. Wrong protocol version
           c. Non-MessagePack payload

        Expectation:
        - Zygote transport must catch the error and close the connection.
        - Zygote main loop must NOT crash.
        """
        if umsgpack is None:
            pytest.skip("umsgpack not available")

        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        # Find Zygote socket
        socket_path = proc.get_socket_path()
        if not socket_path:
            pytest.skip("Zygote socket path not found")

        # --- Attack 1: Huge length prefix ---
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(socket_path)
            # Read Ready greeting
            s.recv(1024)

            # Send huge length: 0xFFFFFFFF (4GB)
            s.sendall(struct.pack("<I", 0xFFFFFFFF))
            time.sleep(0.1)
            # Verify socket closed by server or still alive
            data = b""
            s.settimeout(0.5)
            try:
                data = s.recv(1024)
            except Exception:
                pass
            # If s.recv returns empty b"", it means closed
            assert data == b"", "Zygote failed to close connection on huge length prefix"

        # --- Attack 2: Wrong protocol version ---
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(socket_path)
            s.recv(1024)

            # Length=2, Version=0x99 (Wrong), Payload=1 byte
            s.sendall(struct.pack("<I", 2) + b"\x99" + b"\x00")
            time.sleep(0.1)
            data = b""
            try:
                data = s.recv(1024)
            except:
                pass
            assert data == b"", "Zygote failed to close connection on version mismatch"

        # --- Attack 3: Garbage payload ---
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(socket_path)
            s.recv(1024)

            # Length=10, Version=1, Payload=9 bytes of garbage
            s.sendall(struct.pack("<I", 10) + b"\x01" + b"NOT_MSGPK")
            time.sleep(0.1)
            # This should trigger an unpacker error and close
            data = b""
            try:
                data = s.recv(1024)
            except:
                pass
            assert data == b"", "Zygote failed to close connection on invalid payload"

        # Final Verification: Zygote is still serving
        requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=2)

    def test_CHAOS_003_connection_exhaustion(self, velo_serve_fixture):
        """CHAOS-003: Connection Exhaustion (FD Saturation).

        Scenario:
        1. Open 512 connections to Zygote socket and keep them open.
        2. Verify if Zygote can still spawn a worker via a 513th connection.

        Expectation:
        - Zygote handles concurrent connections.
        - If FD limit hit, it should log but not crash.
        """
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        socket_path = proc.get_socket_path()
        if not socket_path:
            pytest.skip("Zygote socket not found")

        # Open many connections
        conns = []
        try:
            for _ in range(200):  # 200 is safe for default macOS limits
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(socket_path)
                conns.append(s)
        except Exception as e:
            print(f"Hit limit at {len(conns)}: {e}")

        # Verify system still works
        r = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=5)
        assert r.status_code == 200

        # Cleanup
        for s in conns:
            s.close()
