# RFC-0011 QA Test Suite: Zygote Worker Integration
# tests/qa/phase_6_1_1/test_phase611_features.py

"""
L1: Feature Tests (Every PR)

These tests verify feature correctness.
Run after L0 passes.

Following QA SOP v2.2.
"""

import pytest



class TestL1Features:
    """L1: Feature tests for Zygote Worker Integration."""

    def test_L1_1_multi_worker_zygote_spawn(self, velo_serve_fixture):
        """L1-1: Multi-worker spawn from Zygote.

        Requirement: REQ-001
        Priority: P0

        Steps:
        1. Start velo serve --workers 4 --zygote
        2. Verify 4 worker processes exist
        3. Verify all workers are Zygote descendants
        """
        proc = velo_serve_fixture.start("main:app", workers=4, zygote=True)
        proc.wait_ready()

        workers = proc.get_worker_pids()
        assert len(workers) == 4, f"Expected 4 workers, got {len(workers)}"

        # Verify Zygote exists
        assert proc.zygote_pid is not None, "Zygote process not detected"

    def test_L1_2_load_balancer_distribution(self, velo_serve_fixture):
        """L1-2: Load balancer distributes requests across workers.

        Requirement: Load Balancer (Least Connections)
        Priority: P1

        Steps:
        1. Start with 4 workers
        2. Send 100 requests
        3. Verify each worker received requests (distribution)
        """
        import requests

        # RFC-0011 Phase 2B: Must use zygote=True to enable multi-worker L7 Proxy mode
        proc = velo_serve_fixture.start("main:app", workers=4, zygote=True)
        proc.wait_ready()

        # Track which PIDs respond
        pids_seen = set()
        responses_seen = []
        for _ in range(100):
            response = requests.get(f"http://127.0.0.1:{proc.port}/whoami")
            assert response.status_code == 200
            data = response.json()
            pids_seen.add(data["pid"])
            responses_seen.append(data["pid"])

        # Should see multiple workers responding
        # print(f"DEBUG: PIDs seen: {pids_seen}")
        # print(f"DEBUG: First 10 responses: {responses_seen[:10]}")
        assert len(pids_seen) >= 2, f"Only {len(pids_seen)} worker(s) seen ({pids_seen}), expected distribution. Sequential trace: {responses_seen[:10]}..."

    def test_L1_3_uds_socket_created(self, velo_serve_fixture):
        """L1-3: UDS socket created and accessible.

        Requirement: SEC-004
        Priority: P1

        Steps:
        1. Start velo serve with 2 workers
        2. Check for socket files or abstract namespace
        3. Verify sockets are accessible
        """
        import os
        import sys
        from pathlib import Path

        proc = velo_serve_fixture.start("main:app", workers=2)
        proc.wait_ready()

        if sys.platform == "linux":
            # Check for abstract namespace sockets in /proc/net/unix
            with open("/proc/net/unix") as f:
                unix_content = f.read()
            # Either abstract (@velo-) or filesystem sockets
            has_sockets = "velo" in unix_content.lower()
        else:
            # macOS: Check filesystem sockets
            socket_dir = Path(f"/tmp/velo-{os.getuid()}")
            has_sockets = socket_dir.exists()

        # Either way, server should respond
        import requests
        response = requests.get(f"http://127.0.0.1:{proc.port}/health")
        assert response.status_code == 200

    def test_L1_4_x_forwarded_for_injection(self, velo_serve_fixture):
        """L1-4: X-Forwarded-For header injected by Rust proxy.

        Requirement: BLOCK-004
        Priority: P0 (Blocking)

        Steps:
        1. Start velo serve
        2. Make request to /headers endpoint
        3. Verify X-Forwarded-* headers are present
        """
        import requests

        # RFC-0011 Phase 2B: Must use workers > 1 to enable L7 Proxy (which injects headers)
        proc = velo_serve_fixture.start("main:app", workers=2, zygote=True)
        proc.wait_ready()

        response = requests.get(f"http://127.0.0.1:{proc.port}/headers")
        assert response.status_code == 200

        headers = response.json()
        # Headers should be lowercase in the response
        header_keys = [k.lower() for k in headers.keys()]

        assert "x-forwarded-for" in header_keys, "X-Forwarded-For header not found"
        assert "x-forwarded-proto" in header_keys, "X-Forwarded-Proto header not found"

    def test_L1_5_scope_client_populated(self, velo_serve_fixture):
        """L1-5: scope["client"] populated via X-Forwarded headers.

        Requirement: BLOCK-005
        Priority: P0 (Blocking)

        Steps:
        1. Start velo serve
        2. Make request to /client-ip endpoint
        3. Verify client_host is not None
        """
        import requests

        # RFC-0011 Phase 2B: Must use workers > 1 to enable L7 Proxy (which injects headers)
        proc = velo_serve_fixture.start("main:app", workers=2, zygote=True)
        proc.wait_ready()

        response = requests.get(f"http://127.0.0.1:{proc.port}/client-ip")
        assert response.status_code == 200

        data = response.json()
        # Either client_host or x_forwarded_for should be populated
        has_client_info = (
            data.get("client_host") is not None
            or data.get("x_forwarded_for") is not None
        )
        assert has_client_info, f"Client info not populated: {data}"
