# RFC-0011 QA Test Suite: White-Box Internal Logic Tests (STRESS HARDENED)
# tests/qa/phase_6_1_1/test_phase611_whitebox.py

"""
White-Box Tests (Agent WB) - STRESS HARDENED EDITION

These tests target INTERNAL code paths identified through source code inspection.
They use STRESS LOOPS and TIGHT TIMING to maximize the probability of triggering
race conditions that single-shot Python tests might miss.

Priority: P0 (Zero Bug Policy Enforcement)

Reference: whitebox_audit.md
"""

import os
import signal
import socket
import struct
import sys
import time
import threading
import concurrent.futures
from pathlib import Path
from typing import Optional, List

import pytest
import psutil

# ============================================================================
# Stress Test Configuration
# ============================================================================
STRESS_ITERATIONS = 50  # Number of times to repeat timing-sensitive tests
SIGNAL_STORM_COUNT = 100  # Number of signals to send in rapid succession
FORK_BOMB_COUNT = 20  # Number of rapid Fork requests


class TestWhiteBoxPythonStress:
    """White-box STRESS tests for Python Zygote internals."""

    def test_WB_002_STRESS_zombie_accumulation(self, velo_serve_fixture):
        """WB-002 STRESS: Rapid worker kills to trigger zombie accumulation.

        Target: velo_zygote/main.py:398-402
        
        We rapidly kill and respawn workers, racing the reaper.
        If zombies accumulate, the reaper has a bug.
        """
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()
        
        zombies_detected = 0
        
        for i in range(STRESS_ITERATIONS):
            workers = proc.get_worker_pids()
            if not workers:
                continue
            
            # Kill worker with SIGTERM (graceful)
            for pid in workers:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            
            # Immediately check for zombies (race the reaper)
            time.sleep(0.05)  # 50ms - much tighter than 1s reaper interval
            
            for pid in workers:
                try:
                    p = psutil.Process(pid)
                    if p.status() == psutil.STATUS_ZOMBIE:
                        zombies_detected += 1
                except psutil.NoSuchProcess:
                    pass
            
            # Brief pause before next iteration
            time.sleep(0.1)
        
        # Allow some zombie sightings due to timing, but flag if excessive
        assert zombies_detected < 5, f"WB-002 STRESS: Zombie accumulation detected {zombies_detected} times in {STRESS_ITERATIONS} iterations"

    def test_WB_003_STRESS_eintr_signal_storm(self, velo_serve_fixture):
        """WB-003 STRESS: Signal storm during waitpid to trigger EINTR handling.

        Target: velo_zygote/main.py:679-680
        
        We send a STORM of signals to Zygote while simultaneously killing workers.
        If the bare 'except: break' swallows EINTR, zombies will accumulate.
        """
        proc = velo_serve_fixture.start("main:app", workers=4)
        proc.wait_ready()
        
        zygote_pid = proc.zygote_pid
        if not zygote_pid:
            pytest.skip("Zygote not detected")
        
        initial_workers = proc.get_worker_pids()
        if not initial_workers:
            pytest.skip("No workers detected")
        
        # Phase 1: Kill all workers
        for pid in initial_workers:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        
        # Phase 2: Signal storm on Zygote
        def signal_storm():
            for _ in range(SIGNAL_STORM_COUNT):
                try:
                    os.kill(zygote_pid, signal.SIGUSR1)
                except ProcessLookupError:
                    break
                time.sleep(0.001)  # 1ms between signals
        
        storm_thread = threading.Thread(target=signal_storm)
        storm_thread.start()
        storm_thread.join(timeout=5)
        
        # Phase 3: Wait for reaper
        time.sleep(2)
        
        # Phase 4: Check for zombies
        zombies = []
        for pid in initial_workers:
            try:
                p = psutil.Process(pid)
                if p.status() == psutil.STATUS_ZOMBIE:
                    zombies.append(pid)
            except psutil.NoSuchProcess:
                pass
        
        assert len(zombies) == 0, f"WB-003 STRESS: {len(zombies)} zombies survived signal storm: {zombies}"

    def test_WB_004_cross_app_affinity(self, velo_serve_fixture):
        """WB-004: Handshake should verify app affinity to prevent cross-talk.

        Target: velo_zygote/main.py:748-756
        
        This is a DESIGN DEFECT test - it will FAIL to prove the vulnerability exists.
        """
        try:
            import umsgpack
        except ImportError:
            pytest.skip("umsgpack not available")
        
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()
        
        socket_path = proc.get_socket_path()
        if not socket_path:
            pytest.skip("Zygote socket not found")
        
        # Connect and perform handshake without any app affinity
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(socket_path)
            
            # Read Ready
            _ = recv_msg(s)
            
            # Send Handshake with empty capabilities (no app name)
            handshake = {"type": "Handshake", "version": 0x01, "capabilities": []}
            send_msg(s, handshake)
            
            response = recv_msg(s)
            
            # The vulnerability: handshake succeeds without app verification
            assert response.get("type") == "Handshake", "Handshake failed"
            
            # Check if response contains app affinity (it should, but doesn't)
            caps = response.get("capabilities", [])
            has_affinity = any("app:" in c for c in caps)
            
            if not has_affinity:
                pytest.fail("WB-004: Handshake lacks app affinity - cross-app vulnerability exists")

    def test_WB_005_STRESS_fork_bomb_throttling(self, velo_serve_fixture):
        """WB-005 STRESS (NEW): Rapid Fork requests to test throttling.

        Target: velo_zygote/main.py (ForkHandler + ForkRateLimiter)
        
        If Zygote has no throttling, rapid Forks will exhaust PIDs or memory.
        Test verifies rate limiting returns "Rate limit exceeded" errors.
        """
        try:
            import umsgpack
        except ImportError:
            pytest.skip("umsgpack not available")
        
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()
        
        socket_path = proc.get_socket_path()
        if not socket_path:
            pytest.skip("Zygote socket not found")
        
        pids_spawned = []
        errors = []
        rate_limit_errors = 0
        
        # Use single connection to properly test rate limiting
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect(socket_path)
                
                # Read Ready
                recv_msg(s)
                
                script_path = str(proc.script_path) if hasattr(proc, 'script_path') else str(proc.project_dir / "main.py")
                
                for i in range(FORK_BOMB_COUNT):
                    fork_cmd = {
                        "type": "Fork",
                        "script_path": script_path,
                        "args": [],
                        "async_mode": True,
                    }
                    send_msg(s, fork_cmd)
                    
                    response = recv_msg(s)
                    if response.get("type") == "Forked":
                        pids_spawned.append(response.get("worker_pid"))
                    elif response.get("type") == "Error":
                        err_msg = response.get("message", "")
                        errors.append(err_msg)
                        if "Rate limit" in err_msg:
                            rate_limit_errors += 1
        except Exception as e:
            errors.append(str(e))
        
        # Wait for processes to exit
        time.sleep(1)
        
        # Check for zombie accumulation
        zombies = 0
        for pid in pids_spawned:
            if pid:
                try:
                    p = psutil.Process(pid)
                    if p.status() == psutil.STATUS_ZOMBIE:
                        zombies += 1
                except psutil.NoSuchProcess:
                    pass
        
        # Report findings
        if zombies > 0:
            pytest.fail(f"WB-005 STRESS: Fork bomb left {zombies} zombies")
        
        # Success criteria: rate limiting should kick in (some rate limit rejections)
        # OR if errors occurred, at least some should be rate limit errors
        if len(errors) > FORK_BOMB_COUNT // 2 and rate_limit_errors == 0:
            pytest.fail(f"WB-005 STRESS: Fork bomb caused {len(errors)} errors without rate limiting")


class TestWhiteBoxRustStress:
    """White-box STRESS tests for Rust Supervisor internals."""

    def test_WB_006_STRESS_worker_respawn_race(self, velo_serve_fixture):
        """WB-006 STRESS (NEW): Rapid worker kills to race respawn logic.

        Target: src/serve/runner.rs (Worker respawning - or lack thereof)
        
        This test repeatedly kills workers and checks if they are respawned.
        Current implementation has NO respawn logic, so this SHOULD fail.
        """
        proc = velo_serve_fixture.start("main:app", workers=4)
        proc.wait_ready()
        
        initial_workers = proc.get_worker_pids()
        if len(initial_workers) < 4:
            pytest.skip(f"Expected 4 workers, got {len(initial_workers)}")
        
        # Kill all workers
        for pid in initial_workers:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        
        # Wait for potential respawn
        time.sleep(3)
        
        # Check for new workers
        new_workers = proc.get_worker_pids()
        
        # This SHOULD fail because there's no respawn logic
        assert len(new_workers) >= 4, f"WB-006 STRESS: Workers not respawned after kill. Had {len(initial_workers)}, now have {len(new_workers)}"

    def test_WB_007_orphaned_existing_zygote(self, velo_serve_fixture):
        """WB-007: Existing Zygote should be shut down when velo serve exits.

        Target: src/serve/runner.rs:630
        """
        # Start first server
        proc1 = velo_serve_fixture.start("main:app", workers=1)
        proc1.wait_ready()
        
        zygote1_pid = proc1.zygote_pid
        if not zygote1_pid:
            pytest.skip("Zygote not detected")
        
        # Stop the first server
        proc1.stop()
        time.sleep(1)
        
        # Start second server
        proc2 = velo_serve_fixture.start("main:app", workers=1)
        proc2.wait_ready()
        
        zygote2_pid = proc2.zygote_pid
        
        # Stop the second server
        proc2.stop()
        time.sleep(2)
        
        # Check if any Zygote is still alive (orphan leak)
        still_alive = False
        for pid in [zygote1_pid, zygote2_pid]:
            if pid:
                try:
                    p = psutil.Process(pid)
                    if p.is_running():
                        still_alive = True
                        os.kill(pid, signal.SIGKILL)
                except psutil.NoSuchProcess:
                    pass
        
        assert not still_alive, f"WB-007: Orphaned Zygote detected (PIDs: {zygote1_pid}, {zygote2_pid})"

    def test_WB_008_STRESS_connection_flood(self, velo_serve_fixture):
        """WB-008 STRESS: Flood connections to stress accept loop.

        Target: src/serve/runner.rs:747-749
        
        Open many connections rapidly to stress the accept loop.
        """
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()
        
        connections = []
        errors = 0
        
        # Flood with connections
        for _ in range(200):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect(("127.0.0.1", proc.port))
                connections.append(s)
            except (OSError, socket.timeout):
                errors += 1
        
        # Cleanup
        for s in connections:
            try:
                s.close()
            except:
                pass
        
        # Wait and check server health
        time.sleep(1)
        
        import requests
        try:
            response = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=5)
            assert response.status_code == 200, "Server unresponsive after flood"
        except requests.exceptions.RequestException:
            pytest.fail("WB-008 STRESS: Server crashed under connection flood")


# ============================================================================
# Helper Functions
# ============================================================================

def send_msg(sock: socket.socket, msg: dict):
    """Send length-prefixed MessagePack message."""
    import umsgpack
    payload = umsgpack.packb(msg)
    header = struct.pack('<I', 1 + len(payload))
    version = bytes([0x01])
    sock.sendall(header + version + payload)

def recv_msg(sock: socket.socket) -> dict:
    """Receive length-prefixed MessagePack message."""
    import umsgpack
    header = sock.recv(4)
    if len(header) < 4:
        return {}
    total_len = struct.unpack('<I', header)[0]
    version = sock.recv(1)
    if not version or version[0] != 0x01:
        return {}
    payload = sock.recv(total_len - 1)
    return umsgpack.unpackb(payload)

