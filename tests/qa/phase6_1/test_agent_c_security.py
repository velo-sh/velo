# Agent C (Security Specialist) - Phase 6.1 Serve & Analyze
# 安全专家 QA: "Trust nothing. Verify everything."

import pytest
import os
import subprocess
from pathlib import Path


@pytest.mark.tier1
@pytest.mark.security
class TestAgentCSecurity:
    """Agent C: Security Specialist for Phase 6.1 velo serve."""

    # ===== SEC-61-INJ: Command Injection Tests =====

    @pytest.mark.parametrize(
        "payload",
        [
            "main:app; rm -rf /",
            "main:app | cat /etc/passwd",
            "main:app && whoami",
            "main:`id`:app",
            "main:$(cat /etc/passwd)",
            "main:app\nid",
        ],
    )
    @pytest.mark.skip(reason="Awaiting D1: Command injection validation")
    def test_SEC_61_INJ_all_shell_metacharacters(self, isolated_env, payload):
        """SEC-P0-001: All shell metacharacters rejected."""
        result = isolated_env.run_velo("serve", payload, timeout=2)
        assert result.returncode != 0
        # Should contain error about invalid characters
        assert "invalid" in result.stderr.lower() or "metachar" in result.stderr.lower()

    # ===== SEC-61-PATH: Path Traversal Tests =====

    @pytest.mark.skip(reason="Awaiting D1: Path validation implementation")
    def test_SEC_61_PATH_001_parent_directory(self, isolated_env):
        """SEC-P0-002: Parent directory traversal rejected."""
        result = isolated_env.run_velo(
            "serve", "--detect-in", "../../../etc", timeout=2
        )
        assert result.returncode != 0
        assert (
            "within project" in result.stderr.lower()
            or "traversal" in result.stderr.lower()
        )

    @pytest.mark.skip(reason="Awaiting D1: Symlink validation implementation")
    def test_SEC_61_PATH_002_symlink_escape(self, isolated_env):
        """SEC-P0-002: Symlink escape rejected."""
        env = isolated_env
        # Create symlink pointing outside project
        outside = Path("/tmp")
        link = env.path / "escape_link"
        link.symlink_to(outside)

        result = env.run_velo("serve", "--detect-in", str(link), timeout=2)
        assert result.returncode != 0

    @pytest.mark.skip(reason="Awaiting D1: URL-encoded path validation")
    def test_SEC_61_PATH_003_url_encoded_traversal(self, isolated_env):
        """SEC-P0-002: URL-encoded traversal rejected."""
        result = isolated_env.run_velo(
            "serve", "--detect-in", "%2e%2e%2fetc", timeout=2
        )
        assert result.returncode != 0

    @pytest.mark.skip(reason="Awaiting D1: Null byte path validation")
    def test_SEC_61_PATH_004_null_byte_truncation(self, isolated_env):
        """SEC-P0-002: Null byte in path rejected."""
        result = isolated_env.run_velo(
            "serve", "--detect-in", "path\x00../etc", timeout=2
        )
        assert result.returncode != 0

    # ===== SEC-61-PID: PID File Security Tests =====

    @pytest.mark.skip(reason="Awaiting D1: --pid-file implementation")
    def test_SEC_61_PID_001_existing_file_rejected(self, isolated_env):
        """SEC-P0-003: Existing PID file rejected."""
        env = isolated_env
        pid_file = env.path / "velo.pid"
        pid_file.write_text("12345")

        result = env.run_velo("serve", "--pid-file", str(pid_file), timeout=2)
        assert result.returncode != 0
        assert "exists" in result.stderr.lower()

    @pytest.mark.skip(reason="Awaiting D1: --pid-file implementation")
    def test_SEC_61_PID_002_symlink_attack_rejected(self, isolated_env):
        """SEC-P0-003: Symlink PID file rejected."""
        env = isolated_env
        target = env.path / "target"
        symlink = env.path / "velo.pid"
        symlink.symlink_to(target)

        result = env.run_velo("serve", "--pid-file", str(symlink), timeout=2)
        assert result.returncode != 0

    @pytest.mark.skip(reason="Awaiting D1: --pid-file O_EXCL implementation")
    def test_SEC_61_PID_003_race_condition_prevented(self, isolated_env):
        """SEC-P0-003: Concurrent PID file writes - only one wins."""
        # Would need multiprocessing to test properly
        pass

    # ===== SEC-61-ENV: Environment Security Tests =====

    @pytest.mark.skip(reason="Awaiting environment sanitization implementation")
    def test_SEC_61_ENV_001_pythonpath_sanitized(self, isolated_env):
        """SEC-P0-005: PYTHONPATH is removed from subprocess."""
        env = isolated_env
        env.create_fastapi_app()

        env_vars = os.environ.copy()
        env_vars["PYTHONPATH"] = "/tmp/evil"

        result = env.run_velo("serve", "--dry-run", env=env_vars, timeout=2)
        # Verify PYTHONPATH was not passed to subprocess
        # This would need to check the spawned uvicorn's environment

    @pytest.mark.skip(reason="Awaiting environment sanitization implementation")
    def test_SEC_61_ENV_002_ld_preload_sanitized(self, isolated_env):
        """SEC-P0-005: LD_PRELOAD is removed from subprocess."""
        pass

    @pytest.mark.skip(reason="Awaiting environment sanitization implementation")
    def test_SEC_61_ENV_004_ld_library_path_sanitized(self, isolated_env):
        """[GAP-04] LD_LIBRARY_PATH is removed from subprocess."""
        env = isolated_env
        env.create_fastapi_app()

        env_vars = os.environ.copy()
        env_vars["LD_LIBRARY_PATH"] = "/tmp/evil"

        result = env.run_velo("serve", "--dry-run", env=env_vars, timeout=2)
        # Verify LD_LIBRARY_PATH was not passed to subprocess

    @pytest.mark.skip(reason="Awaiting D1: --health-bind implementation")
    def test_SEC_61_ENV_003_health_no_secrets(self, isolated_env):
        """SEC-P0-004: Health endpoint exposes no secrets."""
        # Start server, hit /health, verify minimal JSON response
        pass

    # ===== SEC-61-RATE: Rate Limiting Tests =====

    @pytest.mark.skip(reason="Awaiting D6/D7: File watcher implementation")
    def test_SEC_61_RATE_001_watcher_dos_prevention(self, isolated_env):
        """SEC-P0-006: File watcher has rate limiting for DoS prevention."""
        # Trigger very rapid file changes, verify no crash/hang
        pass
