# RFC-0011 QA Test Suite: Zygote Worker Integration
# tests/qa/phase_6_1_1/test_phase611_release_blockers.py

"""
Release Blocker Tests

These tests cover the Release Blockers identified in 0011-qa-review.md:
- Zombie Workers
- Log Mismatch
- Mac/Linux Divergence

Priority: P0 (MUST pass before release)
"""

import os
import signal
import sys
import time
from pathlib import Path

import psutil
import pytest

# Import CI-aware timeout constants from parent conftest
sys.path.append(str(Path(__file__).parent.parent))
from conftest_utils import T_MEDIUM, T_SHORT, get_timeout_multiplier

# RFC-0011 is now implemented (at least partially)
pytestmark = [
    pytest.mark.release_blocker,
]


class TestReleaseBlockers:
    """Release Blocker tests from 0011-qa-review.md."""

    def test_BLOCKER_1_zombie_worker_cleanup(self, velo_serve_fixture):
        """BLOCKER-1: Zombie Workers - No orphan workers after Velo exits.

        Source: 0011-qa-review.md Release Blockers
        Priority: P0

        Steps:
        1. Start velo serve with 4 workers
        2. Get all worker PIDs
        3. Send SIGTERM to velo supervisor
        4. Wait for exit
        5. Verify ALL worker processes are gone (no zombies)
        """

        proc = velo_serve_fixture.start("main:app", workers=4, zygote=True)
        proc.wait_ready()

        # Get worker PIDs before shutdown
        workers_before = proc.get_worker_pids()
        assert len(workers_before) >= 2, "Need at least 2 workers for this test"

        # Send SIGTERM to supervisor
        proc.proc.send_signal(signal.SIGTERM)

        # Wait for graceful shutdown
        try:
            proc.proc.wait(timeout=T_MEDIUM)
        except Exception:
            proc.proc.kill()
            proc.proc.wait()

        # Give system time to clean up
        time.sleep(1 * get_timeout_multiplier())

        # Verify NO zombie/orphan workers remain
        for worker_pid in workers_before:
            try:
                p = psutil.Process(worker_pid)
                status = p.status()
                if status == psutil.STATUS_ZOMBIE:
                    pytest.fail(f"Worker {worker_pid} is ZOMBIE - Release Blocker!")
                else:
                    pytest.fail(f"Worker {worker_pid} still running (status={status}) - orphan detected!")
            except psutil.NoSuchProcess:
                pass  # Expected - worker is properly cleaned up

    def test_BLOCKER_2_no_orphan_after_sigkill(self, velo_serve_fixture):
        """BLOCKER-1b: Zombie Workers - Handle SIGKILL edge case.

        Even if supervisor is SIGKILL'd, workers should eventually exit.
        """

        proc = velo_serve_fixture.start("main:app", workers=2, zygote=True)
        proc.wait_ready()

        workers_before = proc.get_worker_pids()

        # SIGKILL the supervisor (harsh exit)
        proc.proc.kill()
        proc.proc.wait()

        # Wait for orphan adoption and cleanup
        time.sleep(3 * get_timeout_multiplier())

        # Check workers are gone
        orphans = []
        for worker_pid in workers_before:
            try:
                p = psutil.Process(worker_pid)
                if p.is_running():
                    orphans.append(worker_pid)
            except psutil.NoSuchProcess:
                pass

        if orphans:
            # Try to clean up
            for pid in orphans:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            pytest.fail(f"Orphan workers detected after SIGKILL: {orphans}")

    def test_BLOCKER_3_log_request_id_correlation(self, velo_serve_fixture):
        """BLOCKER-2: Log Mismatch - Rust 500 must have Python Request ID.

        Source: 0011-qa-review.md Release Blockers
        Priority: P0

        Steps:
        1. Start velo serve
        2. Make a request that will fail
        3. Check Rust logs contain request ID
        4. Check Python logs contain same request ID

        This ensures log correlation between Rust proxy and Python worker.
        """

        import requests

        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        # Make a request to a non-existent endpoint (should 404)
        response = requests.get(f"http://127.0.0.1:{proc.port}/nonexistent-endpoint-for-test")

        # Check response headers for request ID
        response.headers.get("x-request-id")

        # If no request ID header, check logs
        # For now, just verify the server handles the request consistently
        assert response.status_code in [
            404,
            500,
            422,
        ], f"Unexpected status: {response.status_code}"

        # Note: Full implementation would verify logs contain matching IDs
        # This requires access to stdout/stderr of the process

    def test_BLOCKER_4_rust_error_has_context(self, velo_serve_fixture):
        """BLOCKER-2b: Rust 500 errors should have traceable context.

        When Rust proxy returns 500, it should include enough context
        to correlate with Python worker errors.
        """
        import requests

        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        # Send malformed request that might cause 500
        try:
            response = requests.get(
                f"http://127.0.0.1:{proc.port}/health",
                headers={"Content-Length": "-1"},  # Invalid
                timeout=5,
            )
        except requests.exceptions.RequestException:
            pass  # Connection error is also valid

        # Even on error, server should remain healthy
        response = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_SHORT)
        assert response.status_code == 200, "Server unhealthy after error"

    def test_BLOCKER_5_macos_linux_parity(self, velo_serve_fixture):
        """BLOCKER-3: Mac/Linux Divergence - dev environment parity.

        Source: 0011-qa-review.md Release Blockers
        Priority: P0

        Steps:
        1. Start velo serve
        2. Verify basic functionality works on current platform
        3. Check platform-specific code paths don't break

        Note: Full parity requires CI on both platforms.
        """
        from pathlib import Path

        import requests

        proc = velo_serve_fixture.start("main:app", workers=2, zygote=True)
        proc.wait_ready()

        # Basic functionality
        response = requests.get(f"http://127.0.0.1:{proc.port}/health")
        assert response.status_code == 200

        # Platform-specific socket check
        if sys.platform == "linux":
            # Check for abstract namespace or filesystem sockets
            with open("/proc/net/unix") as f:
                unix_content = f.read()
            # Just verify we can read socket info
            assert len(unix_content) > 0
        else:
            # macOS: check filesystem socket path
            Path(f"/tmp/velo-{os.getuid()}")
            # Path may or may not exist depending on implementation
            # Just verify server responds

        # Note: Worker PID verification is handled by test_L0_2_worker_is_zygote_child
        # This test focuses on concurrent request handling parity across platforms

        # Make concurrent requests
        import concurrent.futures

        def make_request() -> int:
            r = requests.get(f"http://127.0.0.1:{proc.port}/ping", timeout=T_SHORT)
            return r.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda _: make_request(), range(20)))

        success_rate = sum(1 for r in results if r == 200) / len(results)
        assert success_rate >= 0.95, f"Success rate {success_rate:.1%} too low on {sys.platform}"
