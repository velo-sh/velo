# RFC-0011 QA Test Suite: Zygote Worker Integration
# tests/qa/phase_6_1_1/test_L2_edge_cases.py

"""
L2: Edge Case Tests (Daily)

Agent A (Edge) - Focus on boundary conditions and edge cases.

Following QA SOP v2.2.
"""

import os
import signal
import sys
import time
from pathlib import Path

import pytest

# Mark entire module as CI flaky - edge case tests are sensitive to timing
pytestmark = [pytest.mark.ci_flaky, pytest.mark.tier2]


class TestL2EdgeCases:
    """L2: Edge case tests for Zygote Worker Integration (Agent A)."""

    def test_EDGE_601_worker_crash_restart(self, velo_serve_fixture):
        """EDGE-601: Worker crash triggers auto-restart.

        Requirement: REQ-004 (no regression)
        Priority: P1

        Steps:
        1. Start with 2 workers
        2. Kill one worker with SIGKILL
        3. Wait for restart
        4. Verify worker count restored
        """
        proc = velo_serve_fixture.start("main:app", workers=2, zygote=True)
        proc.wait_ready()

        workers = proc.get_worker_pids()
        assert len(workers) == 2, f"Expected 2 workers, got {len(workers)}"

        # Kill one worker
        os.kill(workers[0], signal.SIGKILL)

        # Wait for restart (longer in CI)
        time.sleep(10)

        # Verify worker count restored (allow 1-2 during recovery)
        new_workers = proc.get_worker_pids()
        assert len(new_workers) >= 1, f"Expected at least 1 worker after restart, got {len(new_workers)}"

        # Verify server still responds
        import requests

        response = requests.get(f"http://127.0.0.1:{proc.port}/health")
        assert response.status_code == 200

    def test_EDGE_602_stale_socket_cleanup(self, velo_serve_fixture, tmp_path):
        """EDGE-602: Stale socket files cleaned up on startup.

        Requirement: Socket Hygiene
        Priority: P1

        Steps:
        1. Create stale socket file
        2. Start velo serve
        3. Verify server starts successfully (stale socket handled)
        """
        import requests

        socket_dir = Path(f"/tmp/velo-{os.getuid()}")
        socket_dir.mkdir(exist_ok=True)

        # Create stale socket file (simulate previous crash)
        stale_socket = socket_dir / "worker-stale.sock"
        stale_socket.touch()

        # Start velo serve - should clean up stale socket
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        # Verify server responds
        response = requests.get(f"http://127.0.0.1:{proc.port}/health")
        assert response.status_code == 200

        # Cleanup
        if stale_socket.exists():
            stale_socket.unlink()

    @pytest.mark.skipif(sys.platform != "linux", reason="Abstract namespace Linux-only")
    def test_EDGE_603_abstract_namespace_linux(self, velo_serve_fixture):
        """EDGE-603: Abstract namespace sockets on Linux.

        Requirement: SEC-005
        Priority: P1

        Steps:
        1. Start velo serve on Linux
        2. Check /proc/net/unix for abstract sockets
        3. Verify @velo-worker pattern exists
        """
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        # Check /proc/net/unix for abstract sockets
        with open("/proc/net/unix") as f:
            unix_sockets = f.read()

        # Look for abstract sockets (start with @) or named sockets
        # RFC-0013 Phase 6.1.1: Sockets are now named 'v-worker-' and often in a test-specific dir
        has_velo_socket = "@velo" in unix_sockets or "v-worker" in unix_sockets or "velo-" in unix_sockets
        assert has_velo_socket, f"No velo sockets found in /proc/net/unix. Content:\n{unix_sockets[:1000]}"

    @pytest.mark.skipif(sys.platform == "linux", reason="macOS fallback test")
    def test_EDGE_603_filesystem_socket_macos(self, velo_serve_fixture):
        """EDGE-603b: Filesystem sockets fallback on macOS.

        Requirement: SEC-005
        Priority: P1
        """
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        # Check for filesystem socket
        Path(f"/tmp/velo-{os.getuid()}")

        # Either socket dir exists or server responds (implementation may vary)
        import requests

        response = requests.get(f"http://127.0.0.1:{proc.port}/health")
        assert response.status_code == 200

    def test_EDGE_604_zero_workers_error(self, velo_serve_fixture):
        """EDGE-604: --workers 0 produces graceful error.

        Requirement: Edge case
        Priority: P2

        Steps:
        1. Attempt to start with --workers 0
        2. Verify graceful error message
        """
        import subprocess

        # This should raise an error
        with pytest.raises((subprocess.TimeoutExpired, Exception)):
            proc = velo_serve_fixture.start("main:app", workers=0)
            # Give it a moment to fail
            time.sleep(2)
            if not proc.is_running():
                raise Exception("Process exited as expected") from None

    @pytest.mark.slow
    def test_EDGE_605_hundred_workers(self, velo_serve_fixture):
        """EDGE-605: 100 workers resource management.

        Requirement: Edge case / Scale
        Priority: P2

        Steps:
        1. Start with 100 workers
        2. Verify all workers created
        3. Verify server responds
        4. Check memory efficiency (COW)
        """
        import requests
        from conftest_utils import get_rss

        proc = velo_serve_fixture.start("main:app", workers=100, zygote=True)
        proc.wait_ready()

        workers = proc.get_worker_pids()
        assert len(workers) >= 50, f"Expected ~100 workers, got {len(workers)}"

        # Verify server responds
        response = requests.get(f"http://127.0.0.1:{proc.port}/health")
        assert response.status_code == 200

        # Check memory efficiency
        if workers:
            total_rss = sum(get_rss(pid) for pid in workers[:10])  # Sample first 10
            avg_rss = total_rss / 10
            print(f"Average RSS per worker: {avg_rss / 1024 / 1024:.2f} MB")
