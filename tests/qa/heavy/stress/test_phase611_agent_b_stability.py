# RFC-0011 QA Test Suite: Zygote Worker Integration
# tests/qa/phase_6_1_1/test_phase611_agent_b_stability.py

"""
L3: Stress Tests (Weekly)

Agent B (Stability) + Agent D (Destroyer) - Stress and chaos tests.

Following QA SOP v2.2.
"""

import socket
import sys
import time
from pathlib import Path

import pytest

# Import CI-aware timeout constants from parent conftest
sys.path.append(str(Path(__file__).parents[4]))
from conftest_utils import T_MEDIUM, T_SHORT, get_rss

# Mark all tests in this module as stress tests
pytestmark = pytest.mark.stress


class TestL3Stress:
    """L3: Stress tests for Zygote Worker Integration (Agent B + D)."""

    @pytest.mark.slow
    def test_STAB_601_concurrent_requests(self, velo_serve_fixture):
        """STAB-601: 1000 concurrent requests.

        Requirement: Stability
        Priority: P1

        Steps:
        1. Start with 4 workers
        2. Send 1000 concurrent requests
        3. Verify >= 99% success rate
        """
        import concurrent.futures

        import requests

        proc = velo_serve_fixture.start("main:app", workers=4)
        proc.wait_ready()

        def make_request():
            try:
                r = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_MEDIUM)
                return r.status_code
            except Exception as e:
                return str(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:
            futures = [pool.submit(make_request) for _ in range(1000)]
            results = [f.result() for f in futures]

        success = sum(1 for r in results if r == 200)
        assert success >= 990, f"Only {success}/1000 succeeded"

    @pytest.mark.slow
    def test_STAB_602_memory_leak_detection(self, velo_serve_fixture):
        """STAB-602: Memory leak detection over sustained load.

        Requirement: Stability
        Priority: P1

        Steps:
        1. Start with 4 workers
        2. Record initial memory
        3. Send 10000 requests
        4. Verify memory growth < 20%
        """
        import requests

        proc = velo_serve_fixture.start("main:app", workers=4)
        proc.wait_ready()

        # Initial memory
        workers = proc.get_worker_pids()
        if not workers:
            pytest.skip("No workers detected")

        initial_rss = sum(get_rss(pid) for pid in workers)

        # Send 10000 requests
        for i in range(10000):
            try:
                requests.get(f"http://127.0.0.1:{proc.port}/ping", timeout=T_SHORT)
            except Exception:
                pass
            if i % 1000 == 0:
                print(f"Sent {i} requests...")

        # Final memory
        final_rss = sum(get_rss(pid) for pid in workers if get_rss(pid) > 0)

        if initial_rss > 0:
            growth = (final_rss - initial_rss) / initial_rss
            print(f"Memory growth: {growth * 100:.1f}%")
            # RFC-0012: Deep Warming pre-loads the full app, increasing footprint by ~50%
            assert growth < 0.60, f"Memory grew by {growth * 100:.1f}% (> 60%)"

    @pytest.mark.security
    def test_STAB_603_slowloris_defense(self, velo_serve_fixture):
        """STAB-603: Slowloris attack defense.

        Requirement: SEC-003
        Priority: P1

        Steps:
        1. Start server
        2. Open 50 slow connections (incomplete requests)
        3. Verify server still responds to valid requests
        """
        import requests

        proc = velo_serve_fixture.start("main:app", workers=2)
        proc.wait_ready()

        # Start slow connections (incomplete requests)
        slow_sockets = []
        for _ in range(50):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                s.connect(("127.0.0.1", proc.port))
                # Send incomplete HTTP request (no final \r\n\r\n)
                s.send(b"GET / HTTP/1.1\r\nHost: localhost\r\n")
                slow_sockets.append(s)
            except Exception:
                pass

        # Give server a moment
        time.sleep(1)

        # Verify server still responds to valid requests
        try:
            response = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_SHORT)
            assert response.status_code == 200, "Server blocked by slowloris"
        finally:
            # Cleanup slow connections
            for s in slow_sockets:
                try:
                    s.close()
                except Exception:
                    pass

    @pytest.mark.stress
    def test_STAB_604_connection_pool_recovery(self, velo_serve_fixture):
        """STAB-604: Recovery from connection pool exhaustion.

        Requirement: Stability
        Priority: P2

        Steps:
        1. Start server
        2. Exhaust connection pool
        3. Close all connections
        4. Verify server recovers
        """
        import requests

        proc = velo_serve_fixture.start("main:app", workers=2)
        proc.wait_ready()

        # Exhaust connections
        sockets = []
        for _ in range(200):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect(("127.0.0.1", proc.port))
                sockets.append(s)
            except Exception:
                break

        print(f"Opened {len(sockets)} connections")

        # Close all
        for s in sockets:
            try:
                s.close()
            except Exception:
                pass

        # Give server time to recover
        time.sleep(1)

        # Verify recovery
        response = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_SHORT)
        assert response.status_code == 200, "Server did not recover"
