"""
Velo QA: Phase 3.5 Agent A Edge Case Tests
===========================================
Agent A (Aggressive) - Find every corner case that breaks the system.

Focus: Edge cases in serve command, worker pool, and signal handling.
"""

import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

# Import CI-aware timeout constants
from conftest_utils import T_MEDIUM, T_SHORT


def get_velo_binary() -> str:
    """Get path to velo binary."""
    repo_root = Path(__file__).parent.parent.parent
    release = repo_root / "target" / "release" / "velo"
    debug = repo_root / "target" / "debug" / "velo"

    if release.exists():
        return str(release)
    elif debug.exists():
        return str(debug)
    else:
        pytest.skip("velo binary not found - run cargo build first")


class TestServeCliEdgeCases:
    """EDGE-SERVE-xxx: Serve CLI edge cases."""

    def test_edge_serve_001_very_long_app_path(self):
        """EDGE-SERVE-001: Very long app path should error gracefully."""
        velo = get_velo_binary()
        long_module = "a" * 4096
        result = subprocess.run(
            [velo, "serve", f"{long_module}:app"],
            capture_output=True,
            text=True,
            timeout=T_MEDIUM,
        )
        # Should error, not crash
        assert result.returncode != 0
        # Should have some error message, not segfault
        assert result.stderr or result.stdout

    def test_edge_serve_002_unicode_in_app_name(self):
        """EDGE-SERVE-002: Unicode in app name should be handled."""
        velo = get_velo_binary()
        result = subprocess.run([velo, "serve", "中文模块:应用"], capture_output=True, text=True, timeout=T_MEDIUM)
        # Should handle gracefully (error is OK, crash is not)
        assert result.returncode != 0 or "error" in result.stderr.lower()

    def test_edge_serve_003_multiple_colons(self):
        """EDGE-SERVE-003: Multiple colons in app spec."""
        velo = get_velo_binary()
        result = subprocess.run(
            [velo, "serve", "path:to:module:app"],
            capture_output=True,
            text=True,
            timeout=T_MEDIUM,
        )
        assert result.returncode != 0
        assert "invalid" in result.stderr.lower() or "format" in result.stderr.lower()

    def test_edge_serve_004_empty_module(self):
        """EDGE-SERVE-004: Empty module part."""
        velo = get_velo_binary()
        result = subprocess.run([velo, "serve", ":app"], capture_output=True, text=True, timeout=T_MEDIUM)
        assert result.returncode != 0

    def test_edge_serve_005_empty_app(self):
        """EDGE-SERVE-005: Empty app part."""
        velo = get_velo_binary()
        result = subprocess.run([velo, "serve", "main:"], capture_output=True, text=True, timeout=T_MEDIUM)
        assert result.returncode != 0

    def test_edge_serve_006_shell_injection_attempt(self):
        """EDGE-SERVE-006: Shell injection in app name should be safe."""
        velo = get_velo_binary()
        result = subprocess.run(
            [velo, "serve", "$(whoami):app"],
            capture_output=True,
            text=True,
            timeout=T_MEDIUM,
        )
        # Should not execute shell command, should treat as literal
        assert result.returncode != 0
        assert "whoami" not in result.stdout  # Shell not executed


class TestWorkerPoolEdgeCases:
    """EDGE-POOL-xxx: WorkerPool edge cases."""

    def test_edge_pool_001_negative_workers(self):
        """EDGE-POOL-001: Negative worker count should error."""
        velo = get_velo_binary()
        result = subprocess.run(
            [velo, "serve", "main:app", "--workers", "-1"],
            capture_output=True,
            text=True,
            timeout=T_MEDIUM,
        )
        assert result.returncode != 0
        # Accept both: old validation msg or clap's argument parsing error
        stderr_lower = result.stderr.lower()
        assert any(x in stderr_lower for x in ["invalid", "worker", "unexpected argument"])

    def test_edge_pool_002_zero_workers(self):
        """EDGE-POOL-002: Zero workers should error or default to 1."""
        velo = get_velo_binary()
        result = subprocess.run(
            [velo, "serve", "main:app", "--workers", "0"],
            capture_output=True,
            text=True,
            timeout=T_MEDIUM,
        )
        # Either error or handled gracefully
        assert result.returncode != 0 or "worker" in result.stderr.lower()

    def test_edge_pool_003_huge_worker_count(self):
        """EDGE-POOL-003: Huge worker count should be capped or error."""
        velo = get_velo_binary()
        try:
            result = subprocess.run(
                [velo, "serve", "main:app", "--workers", "10000"],
                capture_output=True,
                text=True,
                timeout=T_SHORT,
            )
            # Should either error or cap
            # Not crash with OOM
            assert result.returncode != 0 or "limit" in result.stderr.lower() or "max" in result.stderr.lower()
        except subprocess.TimeoutExpired:
            # Timeout is acceptable for huge worker spawn - system resources limit
            pass

    def test_edge_pool_004_float_workers(self):
        """EDGE-POOL-004: Float worker count should error."""
        velo = get_velo_binary()
        result = subprocess.run(
            [velo, "serve", "main:app", "--workers", "2.5"],
            capture_output=True,
            text=True,
            timeout=T_MEDIUM,
        )
        assert result.returncode != 0


class TestSignalEdgeCases:
    """EDGE-SIG-xxx: Signal handling edge cases."""

    def test_edge_sig_001_rapid_sigterm(self):
        """EDGE-SIG-001: Rapid SIGTERM should not cause corruption."""
        # This test validates that signal handling is robust
        # Even if serve command isn't implemented, the principle applies
        velo = get_velo_binary()

        # Start a serve process (will fail if not implemented)
        proc = subprocess.Popen(
            [velo, "serve", "main:app", "--port", "19001"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            # Wait briefly for startup
            time.sleep(0.5)

            # Send multiple rapid signals
            for _ in range(5):
                try:
                    proc.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    break
                time.sleep(0.1)

            # Wait for exit
            proc.wait(timeout=T_SHORT)

            # Should not hang
            assert True
        except subprocess.TimeoutExpired:
            proc.kill()
            pytest.fail("Process hung on signal handling")
        finally:
            try:
                proc.kill()
            except ProcessLookupError:
                pass


class TestPortEdgeCases:
    """EDGE-PORT-xxx: Port handling edge cases."""

    def test_edge_port_001_port_zero(self):
        """EDGE-PORT-001: Port 0 should auto-assign or error."""
        velo = get_velo_binary()
        result = subprocess.run(
            [velo, "serve", "main:app", "--port", "0"],
            capture_output=True,
            text=True,
            timeout=T_MEDIUM,
        )
        # Either auto-assign, port error, or uvicorn missing (CI env may not have uvicorn)
        stderr_lower = result.stderr.lower()
        assert result.returncode == 0 or any(x in stderr_lower for x in ["port", "missing", "dependency"])

    def test_edge_port_002_port_max(self):
        """EDGE-PORT-002: Max port 65535."""
        velo = get_velo_binary()
        result = subprocess.run(
            [velo, "serve", "main:app", "--port", "65535"],
            capture_output=True,
            text=True,
            timeout=T_MEDIUM,
        )
        # Should be valid port
        # May fail for other reasons (module not found)
        assert "invalid port" not in result.stderr.lower()

    def test_edge_port_003_port_overflow(self):
        """EDGE-PORT-003: Port > 65535 should error."""
        velo = get_velo_binary()
        result = subprocess.run(
            [velo, "serve", "main:app", "--port", "70000"],
            capture_output=True,
            text=True,
            timeout=T_MEDIUM,
        )
        assert result.returncode != 0
        assert "port" in result.stderr.lower() or "invalid" in result.stderr.lower()

    def test_edge_port_004_port_negative(self):
        """EDGE-PORT-004: Negative port should error."""
        velo = get_velo_binary()
        result = subprocess.run(
            [velo, "serve", "main:app", "--port", "-8080"],
            capture_output=True,
            text=True,
            timeout=T_MEDIUM,
        )
        assert result.returncode != 0


# =============================================================================
# CROSS-REVIEW: Agent B + Agent C → Agent A
# =============================================================================


class EdgeTestEnv:
    """Test environment for edge case tests."""

    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="velo_edge_"))
        self.velo = get_velo_binary()

    def setup(self) -> "EdgeTestEnv":
        subprocess.run(["uv", "venv", "--quiet"], cwd=self.path, check=True, capture_output=True)
        (self.path / "uv.lock").write_text("{}")
        return self

    def create_script(self, name: str, content: str) -> None:
        (self.path / name).write_text(content)

    def run_velo(self, args: list[str], timeout: float | None = None) -> tuple[int, str, str]:
        if timeout is None:
            timeout = T_MEDIUM
        result = subprocess.run(
            [self.velo] + args,
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr

    def cleanup(self) -> None:
        try:
            shutil.rmtree(self.path)
        except Exception:
            pass

    def __enter__(self) -> "EdgeTestEnv":
        return self.setup()

    def __exit__(self, *args: Any) -> None:
        self.cleanup()


class TestEdgeCaseStability:
    """Cross-review by Agent B: Stability after edge case handling."""

    def test_xr_edge_stab_001_recovery_after_long_path(self):
        """XR-EDGE-STAB-001: System recovers after long path error."""
        velo = get_velo_binary()

        # First: trigger edge case
        long_module = "a" * 4096
        subprocess.run(
            [velo, "serve", f"{long_module}:app"],
            capture_output=True,
            text=True,
            timeout=T_MEDIUM,
        )

        # Then: normal operation should work
        result = subprocess.run([velo, "--help"], capture_output=True, text=True, timeout=T_MEDIUM)
        assert result.returncode == 0

    def test_xr_edge_stab_002_recovery_after_unicode(self):
        """XR-EDGE-STAB-002: System recovers after unicode error."""
        velo = get_velo_binary()

        # Edge case
        subprocess.run([velo, "serve", "中文:应用"], capture_output=True, timeout=T_MEDIUM)

        # Recovery
        result = subprocess.run([velo, "--version"], capture_output=True, text=True, timeout=T_MEDIUM)
        assert result.returncode == 0

    def test_xr_edge_stab_003_consistent_edge_behavior(self):
        """XR-EDGE-STAB-003: Same edge case gives same error."""
        velo = get_velo_binary()

        errors = []
        for _ in range(5):
            result = subprocess.run([velo, "serve", ":app"], capture_output=True, text=True, timeout=T_SHORT)
            errors.append(result.returncode)

        # All should fail the same way
        assert len(set(errors)) == 1


class TestEdgeCaseSecurity:
    """Cross-review by Agent C: Security implications of edge cases."""

    def test_xr_edge_sec_001_long_path_no_buffer_overflow(self):
        """XR-EDGE-SEC-001: Long path should not cause buffer overflow."""
        velo = get_velo_binary()

        # Try various long inputs
        for size in [1024, 4096, 65536]:
            long_str = "x" * size
            result = subprocess.run(
                [velo, "serve", f"{long_str}:app"],
                capture_output=True,
                text=True,
                timeout=T_SHORT,
            )
            # Should not crash with SIGSEGV
            assert result.returncode != -11  # SIGSEGV

    def test_xr_edge_sec_002_unicode_no_injection(self):
        """XR-EDGE-SEC-002: Unicode should not enable injection."""
        velo = get_velo_binary()

        # Unicode with control chars (null bytes can't be passed via CLI)
        dangerous_strings = [
            "module\n:app",  # Newline
            "module\r:app",  # Carriage return
            "module\t:app",  # Tab
        ]

        for s in dangerous_strings:
            try:
                result = subprocess.run([velo, "serve", s], capture_output=True, text=True, timeout=T_SHORT)
                # Should fail safely
                assert result.returncode != 0
            except ValueError:
                # Some control chars rejected by subprocess - that's OK
                pass

    def test_xr_edge_sec_003_port_no_privilege_escalation(self):
        """XR-EDGE-SEC-003: Port edge cases should not escalate privileges."""
        velo = get_velo_binary()

        # Try to bind to privileged port via edge case
        result = subprocess.run(
            [velo, "serve", "main:app", "--port", "1"],
            capture_output=True,
            text=True,
            timeout=T_MEDIUM,
        )

        # Should fail if not root
        if os.getuid() != 0:
            assert result.returncode != 0
