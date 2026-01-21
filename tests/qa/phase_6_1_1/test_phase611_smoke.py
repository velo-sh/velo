# RFC-0011 QA Test Suite: Zygote Worker Integration
# tests/qa/phase_6_1_1/test_phase611_smoke.py

"""
L0: Smoke Tests (Every Commit)

These tests verify absolute basic functionality.
If any L0 test fails, do NOT proceed to L1+.

Following QA SOP v2.2 Fail-Fast Rule.
"""

import sys
from pathlib import Path

import psutil
import pytest
import requests

# Import CI-aware timeout constants from parent conftest
sys.path.append(str(Path(__file__).parent.parent))
from conftest_utils import T_SHORT

# Smoke tests are now verified to pass with the new implementation
pytestmark = [pytest.mark.smoke]


class TestL0Smoke:
    """L0: Core smoke tests for Zygote Worker Integration."""

    def test_L0_1_single_worker_startup(self, velo_serve_fixture):
        """L0-1: Velo serve starts with single worker.

        Requirement: REQ-005
        Priority: P0

        Steps:
        1. Start velo serve with sample FastAPI app
        2. Wait for ready signal
        3. Verify process is running
        4. Send HTTP request
        5. Verify 200 OK response
        """

        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()
        assert proc.is_running(), "Velo serve process should be running"

        response = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_SHORT)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert response.json()["healthy"] is True

    def test_L0_2_worker_is_zygote_child(self, velo_serve_fixture):
        """L0-2: Worker process is child of Zygote (pstree verification).

        Requirement: REQ-001
        Priority: P0

        Steps:
        1. Start velo serve with --zygote
        2. Get process tree via psutil
        3. Verify worker PPID = Zygote PID or is descendant of Zygote
        """
        proc = velo_serve_fixture.start("main:app", workers=2, zygote=True)
        proc.wait_ready()

        workers = proc.get_worker_pids()
        assert len(workers) >= 1, "Expected at least 1 worker"

        # Verify Zygote exists in process tree
        assert proc.zygote_pid is not None, "Zygote process not detected"

        # Verify workers are descendants of Zygote

        for worker_pid in workers:
            # Walk up the process tree to find Zygote
            try:
                worker_proc = psutil.Process(worker_pid)
                found_zygote = False
                # .parents() is a generator starting from PPID
                for parent in worker_proc.parents():
                    if parent.pid == proc.zygote_pid:
                        found_zygote = True
                        break
                    if parent.pid <= 1:
                        break
                assert found_zygote, (
                    f"Worker {worker_pid} (PPID={worker_proc.ppid()}) is not a Zygote ({proc.zygote_pid}) descendant"
                )
            except psutil.NoSuchProcess:
                pytest.skip(f"Worker {worker_pid} died during verification")

    def test_L0_3_http_request_success(self, velo_serve_fixture):
        """L0-3: HTTP request returns 200 OK.

        Requirement: REQ-004
        Priority: P0

        Steps:
        1. Start velo serve
        2. Send HTTP GET request
        3. Verify 200 OK response with correct body
        """

        proc = velo_serve_fixture.start("main:app", workers=2)
        proc.wait_ready()

        response = requests.get(f"http://127.0.0.1:{proc.port}/", timeout=T_SHORT)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert response.json()["status"] == "ok"

        # Also test /ping endpoint
        response = requests.get(f"http://127.0.0.1:{proc.port}/ping", timeout=T_SHORT)
        assert response.status_code == 200
        assert response.json() == {"ping": "pong"}
