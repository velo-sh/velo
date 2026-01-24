"""
RFC-0035 Native Library Preload QA Tests

Authority: handoff_qa_rfc_0035.md.resolved
Branch: feat/rfc-0035-native-preload

Test Tiers:
- L0: Smoke Tests (5)
- L2: Edge Cases (8)
- SEC-035: Security Tests (12)
"""

import json
import subprocess
from pathlib import Path

import pytest

# Path to velo binary
VELO = Path(__file__).parents[2] / "target" / "debug" / "velo"
PROJECT_ROOT = Path(__file__).parents[2]


def run_velo(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run velo command and return result."""
    cmd = [str(VELO), *args]
    return subprocess.run(
        cmd,
        cwd=cwd or PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


# =============================================================================
# L0: Smoke Tests
# =============================================================================


class TestL0SmokeTests:
    """L0: Basic smoke tests per handoff ticket."""

    def test_L0_001_preload_help(self) -> None:
        """L0-001: velo preload --help shows help text."""
        result = run_velo("preload", "--help")
        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "analyze" in result.stdout
        assert "verify" in result.stdout
        assert "stats" in result.stdout

    def test_L0_002_preload_analyze_creates_lock(self, tmp_path: Path) -> None:
        """L0-002: velo preload analyze creates preload.lock."""
        # Run in project root where pyproject.toml exists
        result = run_velo("preload", "analyze")
        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "Generated preload.lock" in result.stdout
        lock_path = PROJECT_ROOT / "preload.lock"
        assert lock_path.exists(), "preload.lock not created"

    def test_L0_003_preload_verify_valid_lock(self) -> None:
        """L0-003: velo preload verify with valid lock exits 0."""
        # First generate a valid lock
        run_velo("preload", "analyze")
        result = run_velo("preload", "verify")
        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "Verification successful" in result.stdout

    def test_L0_004_run_with_preload_lock(self, tmp_path: Path) -> None:
        """L0-004: velo run works with preload.lock present."""
        # Create test script
        script = tmp_path / "test.py"
        script.write_text("print('L0-004 PASS')")

        # Ensure preload.lock exists
        run_velo("preload", "analyze")

        result = run_velo("run", str(script))
        assert "L0-004 PASS" in result.stdout, f"Output: {result.stdout}"

    def test_L0_005_run_without_preload_lock(self, tmp_path: Path) -> None:
        """L0-005: velo run works without preload.lock (fallback)."""
        # Remove preload.lock if exists
        lock_path = PROJECT_ROOT / "preload.lock"
        if lock_path.exists():
            lock_path.unlink()

        script = tmp_path / "test.py"
        script.write_text("print('L0-005 PASS')")

        result = run_velo("run", str(script))
        assert "L0-005 PASS" in result.stdout, f"Output: {result.stdout}"


# =============================================================================
# L2: Edge Cases
# =============================================================================


class TestL2EdgeCases:
    """L2: Edge case tests per handoff ticket."""

    def test_L2_001_missing_library_in_lock(self) -> None:
        """L2-001: Missing library in lock gives graceful skip."""
        # Create lock with non-existent library
        lock = {
            "version": "1.0",
            "generator": "velo-test",
            "fingerprints": [
                {
                    "relative_path": "nonexistent/library.so",
                    "package": "fake",
                    "soname": "",
                    "hash": "abc",
                    "header_hash": "abc",
                    "mtime": 0,
                    "platform": {
                        "os": "macos",
                        "arch": "aarch64",
                        "python_version": "3.11",
                        "libc_type": "bsd",
                        "libc_version": "unknown",
                        "soabi": "cpython-311-darwin",
                    },
                    "load_stage": "PreInit",
                }
            ],
        }
        lock_path = PROJECT_ROOT / "preload.lock"
        lock_path.write_text(json.dumps(lock, indent=2))

        result = run_velo("preload", "verify")
        # Should report error but not crash
        assert result.returncode != 0  # Verification should fail
        assert "Error" in result.stdout or "error" in result.stderr.lower()

    def test_L2_005_empty_preload_lock(self) -> None:
        """L2-005: Empty preload.lock - no crash, no preload."""
        lock_path = PROJECT_ROOT / "preload.lock"
        lock_path.write_text("")

        result = run_velo("preload", "verify")
        # Should fail gracefully with parse error
        assert result.returncode != 0
        assert "parse" in result.stderr.lower() or "json" in result.stderr.lower()

    def test_L2_006_invalid_json_in_lock(self) -> None:
        """L2-006: Invalid JSON - parse error, fallback."""
        lock_path = PROJECT_ROOT / "preload.lock"
        lock_path.write_text("{{{INVALID JSON")

        result = run_velo("preload", "verify")
        assert result.returncode != 0
        assert "parse" in result.stderr.lower() or "json" in result.stderr.lower()


# =============================================================================
# SEC-035: Security Tests
# =============================================================================


class TestSEC035Security:
    """SEC-035: Security tests per handoff ticket."""

    def test_SEC_035_001_symlink_escape(self, tmp_path: Path) -> None:
        """SEC-035-001: Symlink escape attempt is blocked."""
        # Create symlink pointing outside venv
        escape_link = tmp_path / "escape.so"
        escape_link.symlink_to("/etc/passwd")

        result = run_velo("preload", "check", "--path", str(escape_link))
        assert result.returncode != 0, "Symlink escape should be blocked"
        assert (
            "violation" in result.stderr.lower()
            or "blocked" in result.stderr.lower()
            or "outside" in result.stderr.lower()
        )

    def test_SEC_035_003_absolute_path_outside_venv(self) -> None:
        """SEC-035-003: Absolute path outside venv is blocked."""
        result = run_velo("preload", "check", "--path", "/usr/lib/libSystem.B.dylib")
        assert result.returncode != 0, "Absolute path outside venv should be blocked"

    def test_SEC_035_004_path_traversal(self) -> None:
        """SEC-035-004: Relative path escape ../../../ is blocked."""
        # Create lock with path traversal
        lock = {
            "version": "1.0",
            "generator": "velo-test",
            "fingerprints": [
                {
                    "relative_path": "../../../etc/passwd",
                    "package": "evil",
                    "soname": "",
                    "hash": "fake",
                    "header_hash": "fake",
                    "mtime": 0,
                    "platform": {
                        "os": "macos",
                        "arch": "aarch64",
                        "python_version": "3.11",
                        "libc_type": "bsd",
                        "libc_version": "unknown",
                        "soabi": "cpython-311-darwin",
                    },
                    "load_stage": "PreInit",
                }
            ],
        }
        lock_path = PROJECT_ROOT / "preload.lock"
        lock_path.write_text(json.dumps(lock, indent=2))

        result = run_velo("preload", "verify")
        # Should not succeed - path traversal blocked
        assert result.returncode != 0

    def test_SEC_035_005_tmp_path_rejected(self) -> None:
        """SEC-035-005: /tmp path is rejected."""
        result = run_velo("preload", "check", "--path", "/tmp/malicious.so")
        assert result.returncode != 0, "/tmp path should be rejected"


# =============================================================================
# L1-GATE-B: Fingerprint Verification
# =============================================================================


class TestL1GateBFingerprint:
    """L1-GATE-B: Fingerprint verification tests."""

    def test_L1_GATE_B_001_hash_mismatch_detected(self) -> None:
        """L1-GATE-B-001: Modify library hash, verify reports mismatch."""
        # Generate valid lock
        run_velo("preload", "analyze")

        # Tamper with hash
        lock_path = PROJECT_ROOT / "preload.lock"
        lock_data = json.loads(lock_path.read_text())
        if lock_data["fingerprints"]:
            lock_data["fingerprints"][0]["hash"] = "TAMPERED_HASH"
            lock_path.write_text(json.dumps(lock_data, indent=2))

        result = run_velo("preload", "verify")
        assert result.returncode != 0, "Tampered hash should fail verification"
        assert "mismatch" in result.stdout.lower() or "❌" in result.stdout


# =============================================================================
# Cleanup
# =============================================================================


@pytest.fixture(autouse=True)
def cleanup_lock():
    """Clean up preload.lock after each test."""
    yield
    lock_path = PROJECT_ROOT / "preload.lock"
    if lock_path.exists():
        lock_path.unlink()
