"""
RFC-0011 Golden Path E2E Tests (Part 2)

Split from Part 1 for CI parallelization.
Following QA SOP v2.2.
"""

import sys
import time
from pathlib import Path

import psutil
import pytest
import requests

# Import CI-aware timeout constants from parent conftest
sys.path.append(str(Path(__file__).parent.parent))
from conftest_utils import T_MEDIUM, TIMEOUT_MULTIPLIER

# RFC-0017: Tier 2 - E2E tests, full Zygote runtime
pytestmark = [pytest.mark.tier2, pytest.mark.zygote_required, pytest.mark.ci_flaky]


class TestGoldenPathPart2:
    """E2E tests focusing on security and protocol integrity."""

    def test_GOLD_012_post_body_through_proxy(self, velo_serve_fixture):
        """GOLD-012: POST request body flows correctly through L7 Proxy."""
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        test_body = {"message": "Hello from QA!", "number": 42}
        response = requests.post(f"http://127.0.0.1:{proc.port}/echo", json=test_body, timeout=T_MEDIUM)
        assert response.status_code == 200
        data = response.json()
        assert data["received_message"] == "Hello from QA!"

    @pytest.mark.parametrize("rsgi_mode", [True, False])
    def test_GOLD_013_asgi_scope_client_ip(self, velo_serve_fixture, rsgi_mode):
        """GOLD-013: ASGI scope["client"] is correctly populated."""
        extra_args = ["--rsgi"] if rsgi_mode else []
        proc = velo_serve_fixture.start("main:app", workers=1, extra_args=extra_args)
        proc.wait_ready()

        response = requests.get(f"http://127.0.0.1:{proc.port}/scope", timeout=T_MEDIUM)
        assert response.status_code == 200
        scope = response.json()
        assert scope.get("client") is not None

    def test_GOLD_014_async_concurrent_handling(self, velo_serve_fixture):
        """GOLD-014: Async requests are handled concurrently, not sequentially."""
        import concurrent.futures

        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [
                pool.submit(lambda: requests.get(f"http://127.0.0.1:{proc.port}/concurrent", timeout=T_MEDIUM))
                for _ in range(10)
            ]
            responses = [f.result() for f in futures]

        elapsed = time.time() - start_time
        max_concurrent_seen = max(r.json().get("max_concurrent_seen", 0) for r in responses if r.status_code == 200)
        assert max_concurrent_seen > 1
        assert elapsed < 0.8 * TIMEOUT_MULTIPLIER

    def test_GOLD_SEC_001_socket_permissions(self, velo_serve_fixture):
        """GOLD-SEC-001: UDS socket has restrictive permissions."""
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()
        socket_path = proc.get_socket_path()
        if not socket_path:
            pytest.skip("Zygote socket not found")

        sock_dir = Path(socket_path).parent
        dir_mode = sock_dir.stat().st_mode & 0o777
        assert (dir_mode & 0o077) == 0

    def test_GOLD_SEC_002_no_fd_leak(self, velo_serve_fixture):
        """GOLD-SEC-002: Workers don't leak file descriptors."""
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()
        workers = proc.get_worker_pids()
        if not workers:
            pytest.skip("No workers detected")

        worker_pid = workers[0]
        p = psutil.Process(worker_pid)
        open_files = p.open_files()
        for f in open_files:
            # Basic check: no inherited log files
            assert "zygote" not in f.path.lower() or "log" not in f.path.lower()
