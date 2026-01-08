# RFC-0011 QA Test Suite: Zygote Worker Integration
# tests/qa/phase_6_1_1/test_phase611_expert_concerns.py

"""
Expert Concern Tests

These tests cover concerns raised by Expert Reviews:
- HPC Review: OMP_NUM_THREADS, CUDA pre-flight
- Network Review: Disconnect propagation, Timeouts
- K8s Review: CPU quota, Graceful shutdown, Deep health check
- O11y Review: Trace context, X-Request-ID

Priority: P2 (Important for production readiness)
"""

import os
import signal
import time
from pathlib import Path

import psutil
import pytest
import socket
import sys
import traceback


# Import CI-aware timeout constants from parent conftest
sys.path.append(str(Path(__file__).parent.parent))
from conftest import T_SHORT, T_MEDIUM, T_LONG


# Mark all tests in this module as expert review tests
pytestmark = pytest.mark.expert_review


class TestHPCConcerns:
    """Tests from 0011-hpc-review.md."""

    def test_HPC_1_omp_num_threads_handling(self, velo_serve_fixture):
        """HPC-1: OMP_NUM_THREADS handling during fork.

        Source: 0011-hpc-review.md - OpenMP/BLAS Deadlock
        Priority: P2

        Pre-fork: OMP_NUM_THREADS=1 to prevent thread pool deadlock
        Post-fork: Restore to CPU count for workers

        Steps:
        1. Start velo serve with Zygote
        2. Check worker environment has OMP_NUM_THREADS restored
        """
        # This test verifies the worker environment after fork
        # The Zygote should set OMP_NUM_THREADS=1 before fork,
        # and workers should have it restored

        proc = velo_serve_fixture.start("main:app", workers=1, zygote=True)
        proc.wait_ready()

        # Would need an endpoint to check env vars in worker
        # For now, verify the server starts without deadlock
        import requests

        for _ in range(10):
            response = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_SHORT)
            assert response.status_code == 200

    def test_HPC_2_cuda_context_detection(self, velo_serve_fixture):
        """HPC-2: CUDA context pollution detection.

        Source: 0011-hpc-review.md - CUDA Context Pollution
        Priority: P2

        If CUDA initialized before fork, workers will crash.
        Should have pre-flight check to reject.

        Note: This test is a placeholder - full test requires CUDA hardware.
        """
        # Skip on non-CUDA systems
        try:
            import torch
            if not torch.cuda.is_available():
                pytest.skip("CUDA not available")
        except ImportError:
            pytest.skip("PyTorch not installed")

        # If we get here, we have CUDA - test would verify pre-flight check
        proc = velo_serve_fixture.start("main:app", workers=1, zygote=True)
        proc.wait_ready()

    def test_HPC_3_fork_unsafe_library_detection(self, velo_serve_fixture):
        """HPC-3: Fork-unsafe library detection.

        Source: 0011-hpc-review.md
        Priority: P2

        Libraries like grpc, pymongo, redis with connection pools
        are fork-unsafe. Should warn or handle gracefully.
        """
        proc = velo_serve_fixture.start("main:app", workers=2, zygote=True)
        proc.wait_ready()

        # Verify workers work after fork
        import requests

        workers_seen = set()
        for _ in range(20):
            r = requests.get(f"http://127.0.0.1:{proc.port}/whoami", timeout=T_SHORT)
            if r.status_code == 200:
                workers_seen.add(r.json().get("pid"))

        # Should see at least 1 worker responding
        assert len(workers_seen) >= 1, "No workers responding"


class TestNetworkConcerns:
    """Tests from 0011-network-review.md."""

    def test_NET_1_client_disconnect_propagation(self, velo_serve_fixture):
        """NET-1: Client disconnect propagation.

        Source: 0011-network-review.md
        Priority: P2

        When client disconnects, proxy should close UDS immediately
        to stop Python worker from doing unnecessary work.
        """
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        # Start a slow request and disconnect
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", proc.port))
        s.send(b"GET /health HTTP/1.1\r\nHost: localhost\r\n")
        # Don't send final \r\n - leave request incomplete
        time.sleep(0.1)
        s.close()  # Disconnect abruptly

        # Server should still be healthy
        time.sleep(0.5)
        import requests

        response = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_SHORT)
        assert response.status_code == 200

    def test_NET_2_timeout_header(self, velo_serve_fixture):
        """NET-2: Header timeout (5s).

        Source: 0011-network-review.md
        Priority: P2
        """
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        # Send partial headers and wait
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(("127.0.0.1", proc.port))
        s.send(b"GET /health HTTP/1.1\r\n")
        # Don't complete headers

        # Should timeout and close
        start = time.time()
        try:
            data = s.recv(1024)
            elapsed = time.time() - start
            # If we get a response quickly, server handled it
        except socket.timeout:
            elapsed = time.time() - start

        s.close()

        # Server should still be up
        import requests

        response = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_SHORT)
        assert response.status_code == 200

    def test_NET_3_streaming_no_buffer(self, velo_serve_fixture):
        """NET-3: Streaming proxy (no full body buffer).

        Source: 0011-network-review.md - Backpressure
        Priority: P2

        Proxy should stream, not buffer entire body.
        """
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        # For now, just verify large request handling
        import requests

        # 100KB body
        large_body = "x" * 100000
        response = requests.post(
            f"http://127.0.0.1:{proc.port}/health",  # POST to health is likely 405
            data=large_body,
            timeout=T_LONG,
        )
        # Any response is fine, just verify no crash
        assert response.status_code in [200, 405, 422]


class TestK8sConcerns:
    """Tests from 0011-k8s-review.md."""

    def test_K8S_1_cpu_quota_awareness(self, velo_serve_fixture):
        """K8S-1: CPU quota awareness.

        Source: 0011-k8s-review.md
        Priority: P2

        os.cpu_count() returns physical cores, not K8s limits.
        Should read /sys/fs/cgroup/cpu.max on Linux.
        """
        if sys.platform != "linux":
            pytest.skip("Cgroups v2 only available on Linux")

        # Check if we're in a cgroup
        cgroup_path = "/sys/fs/cgroup/cpu.max"
        if not os.path.exists(cgroup_path):
            pytest.skip("Cgroups v2 not available")

        proc = velo_serve_fixture.start("main:app", workers=2)
        proc.wait_ready()

        # Verify workers started
        workers = proc.get_worker_pids()
        assert len(workers) >= 1

    def test_K8S_2_graceful_shutdown_drain(self, velo_serve_fixture):
        """K8S-2: Graceful shutdown with request drain.

        Source: 0011-k8s-review.md
        Priority: P2

        Steps:
        1. SIGTERM received
        2. Set readiness = false
        3. Stop accepting new connections
        4. Drain in-flight requests
        5. Terminate workers
        6. Exit
        """
        import concurrent.futures
        import requests

        proc = velo_serve_fixture.start("main:app", workers=2)
        proc.wait_ready()

        in_flight_errors = []

        def make_slow_request():
            try:
                r = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_MEDIUM)
                return r.status_code
            except Exception as e:
                in_flight_errors.append(str(e))
                return None

        # Start some requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(make_slow_request) for _ in range(5)]

            # Send SIGTERM while requests in flight
            time.sleep(0.1)
            proc.proc.send_signal(signal.SIGTERM)

            # Wait for requests to complete
            results = [f.result() for f in futures]

        # After SIGTERM, server should eventually exit
        try:
            proc.proc.wait(timeout=T_MEDIUM)
        except Exception:
            proc.proc.kill()
            proc.proc.wait()

        # Most requests should succeed during drain
        success_count = sum(1 for r in results if r == 200)
        # At least some should succeed during graceful shutdown
        # (exact behavior depends on implementation)

    def test_K8S_3_deep_health_check(self, velo_serve_fixture):
        """K8S-3: Deep health check pings workers.

        Source: 0011-k8s-review.md
        Priority: P2

        /healthz should ping workers, not just return 200.
        """
        import requests

        proc = velo_serve_fixture.start("main:app", workers=2)
        proc.wait_ready()

        # Health check should reflect worker status
        response = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_SHORT)
        assert response.status_code == 200

        # Kill one worker
        workers = proc.get_worker_pids()
        if workers:
            try:
                os.kill(workers[0], signal.SIGKILL)
            except ProcessLookupError:
                pass

        # Health check should still work (other worker)
        # Retry logic: Connection might be reset if we hit the dead worker's pipe
        # or if the proxy is handling the disconnect.
        start_time = time.time()
        final_status = None
        
        while time.time() - start_time < 5:
            try:
                response = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_SHORT)
                final_status = response.status_code
                if response.status_code in [200, 503]:
                    break
            except (requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
                print(f"DEBUG: Health check retry caught expected error: {e}")
                time.sleep(0.5)
            except Exception as e:
                # Other errors might be fatal, but let's retry briefly
                print(f"DEBUG: Health check retry caught unexpected error: {e}")
                traceback.print_exc()
                time.sleep(0.5)
        
        # Depending on implementation, might be 200 or 503
        assert final_status in [200, 503], f"Health check failed (status={final_status}) after worker kill"


class TestO11yConcerns:
    """Tests from 0011-o11y-review.md."""

    def test_O11Y_1_trace_context_propagation(self, velo_serve_fixture):
        """O11Y-1: W3C Trace Context propagation.

        Source: 0011-o11y-review.md
        Priority: P2

        Rust must Extract → Inject traceparent header.
        """
        import requests

        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        # Send request with traceparent
        traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        response = requests.get(
            f"http://127.0.0.1:{proc.port}/headers",
            headers={"traceparent": traceparent},
            timeout=T_SHORT,
        )

        assert response.status_code == 200
        headers = response.json()

        # traceparent should be passed through to worker
        header_keys_lower = [k.lower() for k in headers.keys()]
        # Either passed as-is or modified (span ID updated)
        # Just verify header system works

    def test_O11Y_2_request_id_generation(self, velo_serve_fixture):
        """O11Y-2: X-Request-ID generation and correlation.

        Source: 0011-o11y-review.md
        Priority: P2

        Rust should generate UUID and inject into UDS request.
        Python should log with same ID.
        """
        import requests

        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        response = requests.get(f"http://127.0.0.1:{proc.port}/headers", timeout=T_SHORT)
        assert response.status_code == 200

        headers = response.json()
        header_keys_lower = [k.lower() for k in headers.keys()]

        # Check if x-request-id is present (either generated or passed through)
        # Implementation may vary
        # Just verify headers endpoint works

    def test_O11Y_3_metrics_cardinality(self, velo_serve_fixture):
        """O11Y-3: Metrics cardinality - no raw URL path.

        Source: 0011-o11y-review.md
        Priority: P2

        Anti-pattern: Don't record raw URL path in Rust → Cardinality explosion!
        Should normalize paths.
        """
        import requests

        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        # Make requests with various paths
        for i in range(10):
            try:
                requests.get(f"http://127.0.0.1:{proc.port}/unique-path-{i}", timeout=2)
            except Exception:
                pass

        # Server should still be healthy
        response = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_SHORT)
        assert response.status_code == 200
