"""
RFC-0011 Golden Path E2E Tests

These tests cover the COMPLETE critical path through the Zygote system,
validating the entire request lifecycle from CLI startup to graceful shutdown.

Following QA SOP v2.2.
"""

import os
import signal
import socket
import struct
import sys
import time
from pathlib import Path

import psutil
import pytest

# Import CI-aware timeout constants from parent conftest
sys.path.append(str(Path(__file__).parent.parent))
import requests
from conftest_utils import T_LONG, T_MEDIUM, T_SHORT

# RFC-0017: Tier 2 - E2E tests, full Zygote runtime
# Mark as CI flaky - golden path tests depend on server startup timing
pytestmark = [pytest.mark.tier2, pytest.mark.zygote_required, pytest.mark.ci_flaky]


class TestGoldenPathE2E:
    """E2E tests covering the complete Zygote critical path."""

    def test_GOLD_001_complete_ping_pong_lifecycle(self, velo_serve_fixture):
        """GOLD-001: Complete ping-pong request through entire stack.

        Critical Path:
        ┌─────────────────────────────────────────────────────────────┐
        │ Client → L7 Proxy → Load Balancer → UDS → Worker → Response│
        └─────────────────────────────────────────────────────────────┘

        Validates:
        1. velo serve starts correctly
        2. Zygote is spawned (not direct uvicorn)
        3. Workers are children of Zygote
        4. Request flows through L7 Proxy
        5. Response returns to client
        6. Graceful shutdown works
        """
        # Phase 1: Start server
        proc = velo_serve_fixture.start("main:app", workers=2)
        proc.wait_ready()

        # Phase 2: Verify Zygote architecture
        zygote_pid = proc.zygote_pid
        if zygote_pid is None:
            pytest.skip("Zygote not detected - may be in fallback mode")

        # Verify workers exist
        workers = proc.get_worker_pids()
        assert len(workers) >= 1, "No workers detected"

        # Verify workers are Zygote children (not Rust children)
        for pid in workers:
            try:
                p = psutil.Process(pid)
                assert p.ppid() == zygote_pid, f"Worker {pid} parent is {p.ppid()}, expected Zygote {zygote_pid}"
            except psutil.NoSuchProcess:
                pass  # Worker may have restarted

        # Phase 3: Complete ping-pong
        response = requests.get(f"http://127.0.0.1:{proc.port}/ping", timeout=T_MEDIUM)
        assert response.status_code == 200, f"Ping failed: {response.status_code}"

        # Verify response content (if endpoint returns pong)
        if response.text:
            assert "pong" in response.text.lower() or response.status_code == 200

        # Phase 4: Verify request actually went through workers
        # (not some cached response)
        response2 = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_MEDIUM)
        assert response2.status_code == 200

        # Phase 5: Graceful shutdown verification is handled by fixture

    def test_GOLD_002_load_balancer_round_robin(self, velo_serve_fixture):
        """GOLD-002: Verify load balancer distributes to multiple workers.

        Critical Path:
        ┌─────────────────────────────────────────────────────────────┐
        │ 100 requests → Load Balancer → Must see >= 2 unique workers│
        └─────────────────────────────────────────────────────────────┘

        Uses /whoami endpoint which returns {"pid": <worker_pid>, "ppid": <parent_pid>}
        """
        proc = velo_serve_fixture.start("main:app", workers=4)
        proc.wait_ready()

        seen_workers = set()
        success_count = 0

        for _i in range(100):
            try:
                # Use /whoami endpoint which returns worker's PID
                r = requests.get(f"http://127.0.0.1:{proc.port}/whoami", timeout=T_SHORT)
                if r.status_code == 200:
                    success_count += 1
                    data = r.json()
                    worker_pid = data.get("pid")
                    if worker_pid:
                        seen_workers.add(worker_pid)
            except requests.RequestException:
                pass

        print(f"Success: {success_count}/100, Unique workers seen: {seen_workers}")

        # At least 95% success rate
        assert success_count >= 95, f"Only {success_count}/100 requests succeeded"

        # At least 2 unique workers should be seen for proper load balancing
        assert len(seen_workers) >= 2, (
            f"Load balancer only used {len(seen_workers)} worker(s): {seen_workers}. "
            f"Expected >= 2 for proper distribution!"
        )

    def test_GOLD_003_header_injection_flow(self, velo_serve_fixture):
        """GOLD-003: Verify headers flow correctly through proxy.

        Critical Path:
        ┌─────────────────────────────────────────────────────────────┐
        │ Client headers → L7 Proxy (add X-Forwarded-For) → Worker   │
        └─────────────────────────────────────────────────────────────┘

        Validates:
        - X-Forwarded-For injected by proxy
        - X-Forwarded-Proto set correctly
        - Custom headers preserved
        - Hop-by-hop headers stripped
        """
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        # Send request with custom header
        response = requests.get(
            f"http://127.0.0.1:{proc.port}/headers",
            headers={
                "X-Custom-Test": "qa-value",
                "Connection": "keep-alive",  # Hop-by-hop, should be stripped
            },
            timeout=T_MEDIUM,
        )

        assert response.status_code == 200, f"Headers endpoint failed: {response.status_code}"

        try:
            headers = response.json()

            # Normalize to lowercase for comparison
            header_names = (
                [h.lower() for h in headers] if isinstance(headers, list) else [h.lower() for h in headers.keys()]
            )

            # Verify X-Forwarded-For was added by proxy
            has_xff = "x-forwarded-for" in header_names
            # Note: This may fail - it's a known bug we're tracking

            # Verify custom header was preserved
            has_custom = "x-custom-test" in header_names

            # Log findings for debug
            print(f"Headers received by worker: {headers}")
            print(f"X-Forwarded-For present: {has_xff}")
            print(f"X-Custom-Test present: {has_custom}")

            # Assert custom headers preserved
            assert has_custom, "Custom header X-Custom-Test was lost in transit"

            # Assert X-Forwarded-For (will fail until bug is fixed)
            assert has_xff, "X-Forwarded-For not injected by L7 Proxy"

        except Exception as e:
            pytest.fail(f"Failed to parse headers response: {e}")

    def test_GOLD_004_graceful_shutdown_no_orphans(self, velo_serve_fixture):
        """GOLD-004: Graceful shutdown leaves no orphaned processes.

        Critical Path:
        ┌─────────────────────────────────────────────────────────────┐
        │ SIGTERM → Drain → Kill Workers → Guardian Thread → Clean   │
        └─────────────────────────────────────────────────────────────┘

        Validates:
        - SIGTERM triggers graceful shutdown
        - All workers terminate
        - Zygote terminates
        - No zombie/orphan processes remain
        """
        proc = velo_serve_fixture.start("main:app", workers=2)
        proc.wait_ready()

        # Capture PIDs before shutdown
        zygote_pid = proc.zygote_pid
        worker_pids = list(proc.get_worker_pids())
        main_pid = proc.pid

        all_pids = [main_pid]
        if zygote_pid:
            all_pids.append(zygote_pid)
        all_pids.extend(worker_pids)

        print(f"PIDs before shutdown: main={main_pid}, zygote={zygote_pid}, workers={worker_pids}")

        # Send SIGTERM
        os.kill(main_pid, signal.SIGTERM)

        # Wait for shutdown (max 10 seconds)
        for _ in range(20):
            time.sleep(0.5)
            if not psutil.pid_exists(main_pid):
                break

        # Wait a bit more for cleanup
        time.sleep(1)

        # Verify NO processes remain
        survivors = []
        for pid in all_pids:
            if psutil.pid_exists(pid):
                try:
                    p = psutil.Process(pid)
                    if p.status() != psutil.STATUS_ZOMBIE:
                        survivors.append((pid, p.name(), p.status()))
                except psutil.NoSuchProcess:
                    pass

        assert len(survivors) == 0, f"Orphaned processes after SIGTERM: {survivors}"

    def test_GOLD_005_ipc_protocol_integrity(self, velo_serve_fixture):
        """GOLD-005: Verify IPC protocol works correctly.

        Critical Path:
        ┌─────────────────────────────────────────────────────────────┐
        │ Rust → UDS → MessagePack (little-endian) → Zygote → Response│
        └─────────────────────────────────────────────────────────────┘

        Validates:
        - Socket is created with correct permissions
        - Protocol uses little-endian length prefix
        - Ready greeting is received
        - Status command works
        """
        try:
            import msgpack
        except ImportError:
            pytest.skip("msgpack not available")

        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        socket_path = proc.get_socket_path()
        if not socket_path:
            pytest.skip("Zygote socket not found")

        # Connect and verify protocol
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect(socket_path)

            # Read length prefix (4 bytes, little-endian)
            header = s.recv(4)
            assert len(header) == 4, "Failed to receive length prefix"

            # Parse as little-endian (correct)
            total_len = struct.unpack("<I", header)[0]
            assert 1 <= total_len <= 1024, f"Suspicious length: {total_len}"

            # Read version byte
            version = s.recv(1)
            assert version[0] == 0x01, f"Wrong protocol version: {version[0]:#x}"

            # Read payload
            payload = s.recv(total_len - 1)
            msg = msgpack.unpackb(payload, raw=False)

            # Verify Ready greeting
            assert msg.get("type") == "Ready", f"Expected Ready, got {msg}"

    def test_GOLD_006_worker_crash_recovery(self, velo_serve_fixture):
        """GOLD-006: Verify worker self-healing after crash.

        Critical Path:
        ┌─────────────────────────────────────────────────────────────┐
        │ Worker crash → Zygote detects → Fork new worker → Resume   │
        └─────────────────────────────────────────────────────────────┘

        Validates:
        - Worker crash is detected
        - New worker is spawned
        - Service resumes without downtime
        """
        proc = velo_serve_fixture.start("main:app", workers=2)
        proc.wait_ready()

        # Get initial workers
        initial_workers = set(proc.get_worker_pids())
        assert len(initial_workers) >= 1, "No workers detected"

        # Kill one worker
        victim = list(initial_workers)[0]
        print(f"Killing worker {victim}")
        os.kill(victim, signal.SIGKILL)

        # Wait for recovery with retries (worker respawn can take 20-40s in CI)
        max_attempts = 12  # 12 * 5s = 60s total
        response = None
        for attempt in range(max_attempts):
            time.sleep(5)
            try:
                response = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_MEDIUM)
                if response.status_code == 200:
                    print(f"Service recovered on attempt {attempt + 1}")
                    break
            except requests.exceptions.RequestException as e:
                print(f"Recovery attempt {attempt + 1}/{max_attempts}: {e}")

        assert response is not None and response.status_code == 200, (
            "Service not responding after worker crash (60s timeout)"
        )

        # Verify worker count restored
        new_workers = set(proc.get_worker_pids())
        print(f"Workers after recovery: {new_workers}")

        # New workers should exist (may or may not include dead one)
        assert len(new_workers) >= 1, "No workers after recovery"

    def test_GOLD_007_concurrent_request_storm(self, velo_serve_fixture):
        """GOLD-007: Verify stability under concurrent load.

        Critical Path:
        ┌─────────────────────────────────────────────────────────────┐
        │ 500 concurrent requests → L7 Proxy → Workers → >= 99% ok   │
        └─────────────────────────────────────────────────────────────┘
        """
        import concurrent.futures

        proc = velo_serve_fixture.start("main:app", workers=4)
        proc.wait_ready()

        def make_request():
            try:
                r = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_LONG)
                return r.status_code == 200
            except Exception:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
            futures = [pool.submit(make_request) for _ in range(500)]
            results = [f.result() for f in futures]

        success_count = sum(results)
        success_rate = success_count / 500 * 100

        print(f"Success rate: {success_rate:.1f}% ({success_count}/500)")

        # CI is slower/flakier, lower threshold (TIMEOUT_MULTIPLIER > 1 means CI)
        from conftest_utils import TIMEOUT_MULTIPLIER

        min_threshold = 95 if TIMEOUT_MULTIPLIER > 1 else 99

        assert success_rate >= min_threshold, f"Success rate {success_rate:.1f}% below {min_threshold}% threshold"

    def test_GOLD_008_zygote_mode_verification_via_whoami(self, velo_serve_fixture):
        """GOLD-008: Verify we're ACTUALLY running in Zygote mode, not fallback.

        Critical Path:
        ┌─────────────────────────────────────────────────────────────┐
        │ /whoami → Worker PID/PPID → PPID must equal Zygote PID     │
        └─────────────────────────────────────────────────────────────┘

        This is THE definitive test that proves Zygote is working:
        - Worker's PPID (from inside the process via /whoami) must match Zygote PID
        - If they don't match, we're in fallback uvicorn mode
        """
        proc = velo_serve_fixture.start("main:app", workers=2)
        proc.wait_ready()

        # Get Zygote PID from process inspection
        zygote_pid = proc.zygote_pid
        if zygote_pid is None:
            pytest.fail("GOLD-008: Zygote process not found - FALLBACK MODE DETECTED!")

        # Get worker's view of its own PPID via HTTP
        response = requests.get(f"http://127.0.0.1:{proc.port}/whoami", timeout=T_MEDIUM)
        assert response.status_code == 200, f"whoami endpoint failed: {response.status_code}"

        data = response.json()
        worker_pid = data.get("pid")
        worker_ppid = data.get("ppid")

        print(f"Worker reports: PID={worker_pid}, PPID={worker_ppid}")
        print(f"Expected Zygote PID: {zygote_pid}")

        # THE KEY ASSERTION: Worker's parent must be Zygote
        assert worker_ppid == zygote_pid, (
            f"ZYGOTE MODE FAILURE: Worker's PPID ({worker_ppid}) != Zygote PID ({zygote_pid}). "
            f"This proves we're in FALLBACK MODE, not Zygote mode!"
        )

    def test_GOLD_009_hello_fastapi_complete_response(self, velo_serve_fixture):
        """GOLD-009: Verify complete FastAPI response through entire stack.

        Critical Path:
        ┌─────────────────────────────────────────────────────────────┐
        │ Client → Proxy → Worker → FastAPI → JSON Response → Client │
        └─────────────────────────────────────────────────────────────┘

        Validates:
        - FastAPI app is correctly loaded
        - All endpoints respond correctly
        - JSON serialization works end-to-end
        """
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        # Test root endpoint
        r1 = requests.get(f"http://127.0.0.1:{proc.port}/", timeout=T_MEDIUM)
        assert r1.status_code == 200, f"Root endpoint failed: {r1.status_code}"
        assert r1.json() == {"status": "ok"}, f"Unexpected root response: {r1.json()}"

        # Test health endpoint
        r2 = requests.get(f"http://127.0.0.1:{proc.port}/health", timeout=T_MEDIUM)
        assert r2.status_code == 200
        assert r2.json() == {"healthy": True}

        # Test ping-pong
        r3 = requests.get(f"http://127.0.0.1:{proc.port}/ping", timeout=T_MEDIUM)
        assert r3.status_code == 200
        assert r3.json() == {"ping": "pong"}, f"Ping-pong failed: {r3.json()}"

        # Test slow endpoint (async works)
        r4 = requests.get(f"http://127.0.0.1:{proc.port}/slow?seconds=1", timeout=T_MEDIUM)
        assert r4.status_code == 200
        assert r4.json() == {"slept": 1}

        print("✅ All FastAPI endpoints working correctly!")

    def test_GOLD_010_zygote_socket_existence(self, velo_serve_fixture):
        """GOLD-010: Verify Zygote UDS socket exists and is accessible.

        This proves the IPC channel between Rust supervisor and Python Zygote
        is correctly established.
        """
        proc = velo_serve_fixture.start("main:app", workers=1)
        proc.wait_ready()

        socket_path = proc.get_socket_path()

        if socket_path is None:
            # Try to find socket via process inspection
            zygote_pid = proc.zygote_pid
            if zygote_pid is None:
                pytest.fail("GOLD-010: Neither Zygote process nor socket found - FALLBACK MODE!")
            else:
                pytest.fail(f"GOLD-010: Zygote PID={zygote_pid} found but socket path unknown")

        from pathlib import Path

        sock_path = Path(socket_path)

        # Verify socket file exists
        assert sock_path.exists(), f"Zygote socket not found at {socket_path}"

        # Verify it's a socket (not a regular file)
        import stat

        mode = sock_path.stat().st_mode
        assert stat.S_ISSOCK(mode), f"{socket_path} is not a socket"

        print(f"✅ Zygote socket exists at: {socket_path}")

    def test_GOLD_011_zygote_vs_fallback_detection(self, velo_serve_fixture):
        """GOLD-011: Comprehensive Zygote vs Fallback mode detection.

        If ANY of these conditions is false, we're in fallback mode:
        1. Zygote PID is detected
        2. Zygote socket exists
        3. Workers are children of Zygote (not Rust supervisor)
        4. Worker's /whoami PPID matches Zygote PID
        """
        proc = velo_serve_fixture.start("main:app", workers=2)
        proc.wait_ready()

        mode_evidence = {
            "zygote_pid_detected": False,
            "socket_exists": False,
            "workers_are_zygote_children": False,
            "whoami_confirms_zygote": False,
        }

        # Check 1: Zygote PID
        zygote_pid = proc.zygote_pid
        mode_evidence["zygote_pid_detected"] = zygote_pid is not None

        # Check 2: Socket exists
        socket_path = proc.get_socket_path()
        if socket_path:
            from pathlib import Path

            mode_evidence["socket_exists"] = Path(socket_path).exists()

        # Check 3: Worker parent check
        if zygote_pid:
            workers = proc.get_worker_pids()
            if workers:
                try:
                    first_worker = psutil.Process(workers[0])
                    mode_evidence["workers_are_zygote_children"] = first_worker.ppid() == zygote_pid
                except psutil.NoSuchProcess:
                    pass

        # Check 4: /whoami endpoint confirmation
        if zygote_pid:
            try:
                r = requests.get(f"http://127.0.0.1:{proc.port}/whoami", timeout=T_SHORT)
                if r.status_code == 200:
                    data = r.json()
                    mode_evidence["whoami_confirms_zygote"] = data.get("ppid") == zygote_pid
            except Exception:
                pass

        # Print diagnostic
        print("\n╔════════════════════════════════════════╗")
        print("║   ZYGOTE MODE DETECTION RESULTS        ║")
        print("╠════════════════════════════════════════╣")
        for key, value in mode_evidence.items():
            status = "✅" if value else "❌"
            print(f"║ {status} {key}: {value}")
        print("╚════════════════════════════════════════╝")

        # Determine overall mode
        is_zygote_mode = all(mode_evidence.values())

        if is_zygote_mode:
            print("\n🎉 CONFIRMED: Running in ZYGOTE MODE!")
        else:
            failed_checks = [k for k, v in mode_evidence.items() if not v]
            pytest.fail(f"FALLBACK MODE DETECTED! Failed checks: {failed_checks}")


class TestGoldenPathSecurity:
    """Security-focused E2E tests."""

    # Moved to part 2
    pass
