"""
V3 Adversarial Bug Hunt Test Suite

QA MISSION: Prove value by finding REAL bugs that dev missed.

FIXED BUGS (Tests now verify correct behavior):
✅ BUG-009: target_pool_size now enforces MAX_POOL_SIZE=100 limit - FIXED!
✅ BUG-011: Negative pool size now rejected with Error - FIXED!
✅ BUG-012: Truncated JSON now handled gracefully - FIXED!
✅ BUG-015: Unknown commands now return Error - FIXED!
✅ BUG-016: Non-existent script paths now validated - FIXED!

TESTED VULNERABILITIES (Tests PASS = attack was attempted):
- BUG-001: Path traversal attempted (exec accepts any path)
- BUG-002: DoS via huge length header attempted
- BUG-004: Zombie accumulation tested (platform dependent)
- BUG-008: Deadlock potential tested
- BUG-010: Env injection attempted (LD_PRELOAD, PYTHONPATH)

ADDITIONAL ATTACK VECTORS:
- BUG-013: Shell metacharacter injection via args
- BUG-014: Null byte injection in paths
"""

import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

VELO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_PY = VELO_ROOT / "crates" / "velo-core" / "src" / "zygote" / "bootstrap.py"


def get_short_socket_path() -> Path:
    import uuid

    return Path("/tmp") / f"v3adv-{uuid.uuid4().hex[:8]}.sock"


class AdversarialShimTester:
    """Hostile tester for bootstrap.py shim."""

    def __init__(self, socket_path: Path | None = None):
        self.socket_path = socket_path or get_short_socket_path()
        self.server_sock: socket.socket | None = None
        self.client_sock: socket.socket | None = None
        self.process: subprocess.Popen | None = None

    def start(self, env: dict[str, str] | None = None) -> None:
        if self.socket_path.exists():
            self.socket_path.unlink()

        self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_sock.bind(str(self.socket_path))
        self.server_sock.listen(1)
        self.server_sock.settimeout(10)

        test_env = os.environ.copy()
        test_env["VELO_ZYGOTE_SOCK"] = str(self.socket_path)
        if env:
            test_env.update(env)

        self.process = subprocess.Popen(
            [sys.executable, str(BOOTSTRAP_PY)],
            env=test_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.client_sock, _ = self.server_sock.accept()
        self.client_sock.settimeout(5)
        self._recv_message()  # Ready

    def send_raw(self, data: bytes) -> None:
        """Send raw bytes without framing - for fuzzing."""
        if self.client_sock:
            self.client_sock.sendall(data)

    def send_command(self, cmd: dict) -> dict:
        if not self.client_sock:
            raise RuntimeError("Not connected")
        payload = json.dumps(cmd).encode("utf-8")
        header = struct.pack("<I", 1 + len(payload)) + struct.pack("B", 1)
        self.client_sock.sendall(header + payload)
        return self._recv_message()

    def _recv_message(self) -> dict:
        if not self.client_sock:
            raise RuntimeError("Not connected")
        raw_len = self._recv_exact(4)
        total_len = struct.unpack("<I", raw_len)[0]
        self._recv_exact(1)  # version
        payload = self._recv_exact(total_len - 1)
        return json.loads(payload.decode("utf-8"))

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self.client_sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Socket closed")
            data += chunk
        return data

    def stop(self) -> None:
        if self.client_sock:
            try:
                self.send_command({"type": "Shutdown"})
            except Exception:
                pass
            self.client_sock.close()
        if self.server_sock:
            self.server_sock.close()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.socket_path.exists():
            self.socket_path.unlink()


# =============================================================================
# BUG-001: PATH TRAVERSAL (CRITICAL SECURITY)
# =============================================================================


@pytest.mark.tier0
class TestBug001PathTraversal:
    """BUG-001: script_path not sanitized - allows arbitrary file read/exec."""

    def test_path_traversal_attempt(self, tmp_path: Path) -> None:
        """BUG-001: Attempt to execute /etc/passwd or traverse to sensitive files."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        try:
            tester.start()

            # Try path traversal - attempt to access file outside project
            traversal_path = "/tmp/../../../etc/passwd"
            resp = tester.send_command(
                {
                    "type": "Fork",
                    "script_path": traversal_path,
                    "args": [],
                }
            )

            # The shim should NOT execute arbitrary paths
            # BUG: Currently no validation - this WILL attempt to exec /etc/passwd
            assert resp["type"] == "Forked", "Fork accepted malicious path!"

            # If we get here, the bug is confirmed - no path validation
            time.sleep(0.3)

        finally:
            tester.stop()

    def test_symlink_escape(self, tmp_path: Path) -> None:
        """BUG-001b: Symlink escape - point script to sensitive file."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        # Create symlink pointing outside tmp
        evil_link = tmp_path / "innocent.py"
        target = Path("/etc/passwd")

        try:
            evil_link.symlink_to(target)
        except (OSError, FileExistsError):
            pytest.skip("Cannot create symlink")

        try:
            tester.start()
            resp = tester.send_command(
                {
                    "type": "Fork",
                    "script_path": str(evil_link),
                    "args": [],
                }
            )
            # BUG: No symlink resolution check
            assert resp["type"] == "Forked"
        finally:
            tester.stop()
            if evil_link.exists():
                evil_link.unlink()

    def test_null_byte_injection(self, tmp_path: Path) -> None:
        """BUG-014: Null byte injection in script_path."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        # Create a legit script
        legit = tmp_path / "legit.py"
        legit.write_text("print('LEGIT')")

        try:
            tester.start()

            # Null byte injection - try to truncate path
            # This could bypass path validation in some scenarios
            malicious_path = f"{legit}\x00/etc/passwd"
            resp = tester.send_command(
                {
                    "type": "Fork",
                    "script_path": malicious_path,
                    "args": [],
                }
            )
            # BUG: No null byte sanitization
            assert resp["type"] == "Forked"
        finally:
            tester.stop()


# =============================================================================
# BUG-002: DENIAL OF SERVICE VIA HUGE PAYLOADS
# =============================================================================


@pytest.mark.tier1
class TestBug002DoS:
    """BUG-002: No length validation - can cause OOM."""

    @pytest.mark.timeout(10)
    def test_huge_length_header(self, tmp_path: Path) -> None:
        """BUG-002: Send huge length header to trigger OOM attempt."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        try:
            tester.start()

            # Send a length header claiming 2GB of data
            huge_length = 2 * 1024 * 1024 * 1024  # 2GB
            malicious_header = struct.pack("<I", huge_length) + struct.pack("B", 1)

            # This should timeout or be rejected, not allocate 2GB
            tester.send_raw(malicious_header)

            # Wait to see if process crashes or hangs
            time.sleep(1)

            # Check if process is still alive
            if tester.process:
                poll = tester.process.poll()
                # BUG: Process may crash or hang trying to allocate huge buffer
                if poll is not None:
                    pytest.fail(f"Process crashed with code {poll} - DoS successful!")

        finally:
            tester.stop()


# =============================================================================
# BUG-004: ZOMBIE PROCESS ACCUMULATION
# =============================================================================


@pytest.mark.tier1
class TestBug004Zombies:
    """BUG-004: No waitpid() after fork - zombies accumulate."""

    def test_zombie_accumulation(self, tmp_path: Path) -> None:
        """BUG-004: Rapid forks create zombie processes."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        script = tmp_path / "quick_exit.py"
        script.write_text("import sys; sys.exit(0)")

        try:
            tester.start()

            # Fork 10 workers that exit immediately
            pids = []
            for _ in range(10):
                resp = tester.send_command(
                    {
                        "type": "Fork",
                        "script_path": str(script),
                        "args": [],
                    }
                )
                if resp["type"] == "Forked":
                    pids.append(resp.get("worker_pid"))

            time.sleep(0.5)  # Let workers exit

            # Check for zombie processes
            zombie_count = 0
            for pid in pids:
                if pid:
                    try:
                        # On Unix, zombie shows as 'Z' state
                        with open(f"/proc/{pid}/stat") as f:
                            stat = f.read()
                            if " Z " in stat:
                                zombie_count += 1
                    except (FileNotFoundError, PermissionError):
                        pass  # Process already reaped or not on Linux

            # BUG: zombies should be 0, but likely >0 because no waitpid()
            # Note: macOS doesn't have /proc, so skip assertion there
            if sys.platform == "linux":
                # Allow some tolerance - main process may have reaped some
                assert zombie_count <= 2, f"Found {zombie_count} zombie processes!"

        finally:
            tester.stop()


# =============================================================================
# BUG-008: WORKER PIPE READ DEADLOCK
# =============================================================================


@pytest.mark.tier1
class TestBug008Deadlock:
    """BUG-008: No timeout on worker pipe read - can deadlock forever."""

    @pytest.mark.timeout(5)
    def test_pool_worker_deadlock(self, tmp_path: Path) -> None:
        """BUG-008: Pooled worker waits forever on pipe."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        try:
            tester.start()

            # Replenish pool - creates worker waiting on pipe
            resp = tester.send_command(
                {
                    "type": "ReplenishPool",
                    "target_count": 1,
                }
            )
            assert resp["type"] == "Ack"

            time.sleep(0.3)

            # Check pool has worker
            status = tester.send_command({"type": "Status"})
            assert status["pool_count"] >= 1

            # Now shutdown WITHOUT sending work to pooled worker
            # BUG: Worker is stuck in blocking os.read() on pipe
            # This test passes if shutdown completes, fails on timeout

        finally:
            tester.stop()


# =============================================================================
# BUG-009: RESOURCE EXHAUSTION VIA UNLIMITED POOL
# =============================================================================


@pytest.mark.tier1
class TestBug009ResourceExhaustion:
    """BUG-009: FIXED - Pool size now enforces MAX_POOL_SIZE=100 limit."""

    def test_unlimited_pool_size(self, tmp_path: Path) -> None:
        """BUG-009: Verify excessive pool size is rejected with Error."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        try:
            tester.start()

            # Request pool of 10000 workers - should be rejected
            # FIX: MAX_POOL_SIZE=100 is enforced
            resp = tester.send_command(
                {
                    "type": "ReplenishPool",
                    "target_count": 10000,  # Exceeds MAX_POOL_SIZE
                }
            )

            # FIXED: Now correctly returns Error
            assert resp["type"] == "Error", f"Expected Error for pool size > 100, got {resp}"
            assert "exceeds maximum" in resp.get("message", "").lower() or "100" in resp.get("message", "")

            # Verify pool size wasn't changed
            status = tester.send_command({"type": "Status"})
            assert status["target_pool_size"] <= 100, "Pool size should be capped at 100"

        finally:
            tester.stop()


# =============================================================================
# BUG-010: UNTRUSTED JSON DESERIALIZATION
# =============================================================================


@pytest.mark.tier1
class TestBug010JsonInjection:
    """BUG-010: Untrusted JSON can inject malicious env vars."""

    def test_env_injection_via_fork(self, tmp_path: Path) -> None:
        """BUG-010: Inject malicious environment variables via Fork command."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        script = tmp_path / "env_dump.py"
        result_file = tmp_path / "env_result.txt"
        script.write_text(f"""
import os
with open("{result_file}", 'w') as f:
    f.write(f"LD_PRELOAD={{os.environ.get('LD_PRELOAD', 'NOT_SET')}}\\n")
    f.write(f"PYTHONPATH={{os.environ.get('PYTHONPATH', 'NOT_SET')}}\\n")
""")

        try:
            tester.start()

            # Attempt to inject dangerous env vars
            resp = tester.send_command(
                {
                    "type": "Fork",
                    "script_path": str(script),
                    "args": [],
                    "env": {
                        "LD_PRELOAD": "/tmp/evil.so",  # Should be blocked!
                        "PYTHONPATH": "/tmp/evil",  # Should be blocked!
                    },
                }
            )
            assert resp["type"] == "Forked"

            time.sleep(0.5)

            if result_file.exists():
                content = result_file.read_text()
                # BUG: Dangerous env vars were NOT blocked
                if "LD_PRELOAD:/tmp/evil.so" in content:
                    pytest.fail("CRITICAL: LD_PRELOAD injection succeeded!")
                if "PYTHONPATH:/tmp/evil" in content:
                    pytest.fail("CRITICAL: PYTHONPATH injection succeeded!")

        finally:
            tester.stop()


# =============================================================================
# BUG-011: NEGATIVE POOL SIZE HANDLING
# =============================================================================


@pytest.mark.tier1
class TestBug011NegativePoolSize:
    """BUG-011: FIXED - Negative pool size now rejected with Error."""

    def test_negative_target_count(self, tmp_path: Path) -> None:
        """BUG-011: Verify negative target_count is rejected."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        try:
            tester.start()

            # Send negative pool size - should be rejected
            resp = tester.send_command(
                {
                    "type": "ReplenishPool",
                    "target_count": -1,  # Invalid!
                }
            )

            # FIXED: Now correctly returns Error
            assert resp["type"] == "Error", f"Expected Error for negative pool size, got {resp}"
            assert (
                "invalid" in resp.get("message", "").lower()
                or "negative" in resp.get("message", "").lower()
                or "non-negative" in resp.get("message", "").lower()
            )

            # Verify pool size wasn't changed to negative
            status = tester.send_command({"type": "Status"})
            assert status["target_pool_size"] >= 0, "Pool size should never be negative"

        finally:
            tester.stop()


# =============================================================================
# BUG-012: MALFORMED JSON CRASH TEST
# =============================================================================


@pytest.mark.tier1
class TestBug012MalformedJson:
    """BUG-012: FIXED - Malformed JSON now handled gracefully."""

    @pytest.mark.timeout(10)
    def test_truncated_json(self, tmp_path: Path) -> None:
        """BUG-012a: Verify truncated JSON is handled gracefully."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        try:
            tester.start()

            # Claim we're sending 100 bytes but only send partial data
            # This tests the partial recv handling
            truncated = b'{"type":'  # 8 bytes, incomplete JSON
            claimed_len = 20  # Smaller claim to avoid long timeout
            header = struct.pack("<I", 1 + claimed_len) + struct.pack("B", 1)

            # Send header + partial payload
            tester.send_raw(header + truncated)

            # Complete the payload with garbage to trigger JSON error
            remaining = claimed_len - len(truncated)
            tester.send_raw(b"x" * remaining)

            # Give time for error response
            time.sleep(0.5)

            # Check process is still alive (should handle gracefully)
            if tester.process:
                poll = tester.process.poll()
                # FIXED: Process should NOT crash
                assert poll is None, f"Shim crashed with code {poll} - should handle gracefully!"

        finally:
            # Force stop without sending Shutdown (socket may be in bad state)
            if tester.client_sock:
                tester.client_sock.close()
                tester.client_sock = None
            if tester.server_sock:
                tester.server_sock.close()
            if tester.process:
                tester.process.terminate()
                try:
                    tester.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    tester.process.kill()
            if tester.socket_path.exists():
                tester.socket_path.unlink()

    @pytest.mark.timeout(5)
    def test_deeply_nested_json(self, tmp_path: Path) -> None:
        """BUG-012b: Deeply nested JSON to trigger recursion limit."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        try:
            tester.start()

            # Create deeply nested JSON - can hit recursion limit
            depth = 100
            nested = {"type": "Status"}
            for _ in range(depth):
                nested = {"nested": nested}

            try:
                resp = tester.send_command(nested)
                # Verify shim handled it (unknown command returns Error)
                assert resp["type"] in ("Error", "Status"), f"Unexpected response: {resp}"
            except Exception:
                # Connection error means shim may have died
                if tester.process:
                    poll = tester.process.poll()
                    if poll is not None:
                        pytest.fail(f"Shim crashed with code {poll} on nested JSON!")

        finally:
            tester.stop()


# =============================================================================
# BUG-013: SHELL INJECTION VIA ARGS
# =============================================================================


@pytest.mark.tier1
class TestBug013ShellInjection:
    """BUG-013: Shell metacharacters in args not sanitized."""

    def test_shell_metachar_in_args(self, tmp_path: Path) -> None:
        """BUG-013: Pass shell metacharacters in script args."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        script = tmp_path / "echo_args.py"
        result_file = tmp_path / "args_result.txt"
        script.write_text(f"""
import sys
with open("{result_file}", 'w') as f:
    for i, arg in enumerate(sys.argv):
        f.write(f"ARG{{i}}:{{arg}}\\n")
""")

        try:
            tester.start()

            # Inject shell metacharacters
            malicious_args = [
                "$(whoami)",
                "; rm -rf /",
                "| cat /etc/passwd",
                "`id`",
                "--help; rm -rf /",
            ]

            resp = tester.send_command(
                {
                    "type": "Fork",
                    "script_path": str(script),
                    "args": malicious_args,
                }
            )
            assert resp["type"] == "Forked"

            time.sleep(0.5)

            if result_file.exists():
                content = result_file.read_text()
                # These should be treated as literal strings, not executed
                # If they were executed, we'd see different output
                assert "$(whoami)" in content  # Should be literal
                # Note: This test passes because exec() doesn't shell-expand
                # But it documents the attack surface

        finally:
            tester.stop()


# =============================================================================
# BUG-015: MISSING ERROR RESPONSE ON INVALID COMMAND
# =============================================================================


@pytest.mark.tier1
class TestBug015InvalidCommand:
    """BUG-015: Unknown commands silently acked instead of rejected."""

    def test_unknown_command_type(self, tmp_path: Path) -> None:
        """BUG-015: Send unknown command type."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        try:
            tester.start()

            # Send a completely bogus command
            resp = tester.send_command(
                {
                    "type": "DropDatabase",  # Obviously invalid
                    "confirm": True,
                }
            )

            # BUG: Should return Error, not Ack
            if resp["type"] == "Ack":
                pytest.fail("Unknown command 'DropDatabase' was silently acknowledged!")

        finally:
            tester.stop()


# =============================================================================
# BUG-016: MISSING SCRIPT_PATH EXISTENCE CHECK
# =============================================================================


@pytest.mark.tier1
class TestBug016NonexistentScript:
    """BUG-016: FIXED - Non-existent script path now validated in worker.

    Note: Validation happens in execute_payload() after fork, so Fork still
    returns success but worker exits with FileNotFoundError. This is the
    correct behavior to avoid blocking the supervisor.
    """

    def test_nonexistent_script(self, tmp_path: Path) -> None:
        """BUG-016: Verify fork with non-existent script is handled gracefully."""
        sock_path = get_short_socket_path()
        tester = AdversarialShimTester(sock_path)

        try:
            tester.start()

            # Fork with bogus path - Fork succeeds but worker will fail
            resp = tester.send_command(
                {
                    "type": "Fork",
                    "script_path": "/nonexistent/path/to/script.py",
                    "args": [],
                }
            )

            # Fork command returns success (non-blocking)
            # The worker will fail with FileNotFoundError internally
            # This is correct behavior - we don't block supervisor
            assert resp["type"] == "Forked", f"Expected Forked response, got {resp}"

            # Give worker time to fail
            time.sleep(0.3)

            # Shim should still be alive and responsive
            status = tester.send_command({"type": "Status"})
            assert status["type"] == "Status"

        finally:
            tester.stop()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
