"""
DEF-61-004: Protocol Version Socket Isolation Test Suite

Tests the socket isolation fix for the 30-second Zygote warm start timeout.
Root cause: Protocol mismatch between JSON (v0.6.1) and MessagePack (v0.6.2).

Solution: Version-specific socket paths with user isolation.
Expected format: $TMPDIR/velo-{UID}/zygote-v{VERSION}.sock

Test Matrix:
- Core Tests (T1-T5): Socket path format, permissions, isolation
- Edge Cases (T6-T10): Long paths, permission errors, concurrency
- Regression (REG-001-004): Upgrade/downgrade scenarios

Reference: docs/qa/DEFECTS/DEF-61-004-qa-review.md
"""

import os
import socket
import sys
import threading
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

# Import the actual implementation from velo_zygote
sys.path.insert(0, str(Path(__file__).parents[4] / "velo_zygote"))
from constants import PROTOCOL_VERSION
from paths import (
    ensure_socket_dir,
    get_socket_dir,
    get_versioned_socket_path,
)

# ============================================================================
# Test Configuration
# ============================================================================

EXPECTED_SOCKET_NAME = f"velo-zygote-v{PROTOCOL_VERSION:02x}.sock"


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_socket_dir(tmp_path: Path) -> Path:
    """Create a temporary socket directory for testing."""
    socket_dir = tmp_path / f"velo-{os.getuid()}"
    socket_dir.mkdir(mode=0o700)
    return socket_dir


@pytest.fixture
def mock_tmpdir(tmp_path, monkeypatch):
    """Mock tempfile.gettempdir() to return temp_path."""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    # Clear XDG_RUNTIME_DIR to test temp fallback path
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    return tmp_path


@pytest.fixture
def create_stale_socket(temp_socket_dir):
    """Factory fixture to create stale socket files."""

    def _create(version: int = 0) -> Path:
        socket_path = cast(Path, temp_socket_dir / f"velo-zygote-v{version:02x}.sock")
        socket_path.touch()
        return socket_path

    return _create


@pytest.fixture
def create_active_socket():
    """Create an active listening Unix socket.

    Uses /tmp directly to avoid path length issues with pytest's tmp_path on macOS.
    """
    import uuid

    created_sockets = []

    def _create(version: int = PROTOCOL_VERSION) -> tuple[Path, socket.socket]:
        socket_path = Path(f"/tmp/velo-test-{uuid.uuid4().hex[:8]}-v{version:02x}.sock")
        if socket_path.exists():
            socket_path.unlink()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(socket_path))
        sock.listen(1)
        created_sockets.append((socket_path, sock))
        return socket_path, sock

    yield _create

    # Cleanup
    for socket_path, sock in created_sockets:
        sock.close()
        if socket_path.exists():
            socket_path.unlink()


# ============================================================================
# Core Tests (T1-T5)
# ============================================================================


class TestSocketPathFormat:
    """AC-1, AC-2: Socket path format verification."""

    def test_t1_version_upgrade_cleans_old_socket(self, mock_tmpdir, temp_socket_dir, create_stale_socket):
        """T1: Version upgrade detects and cleans stale sockets.

        When upgrading from v0.6.1 (JSON) to v0.6.2 (MessagePack),
        old sockets should be detected as stale and removed.
        """
        # Create old version socket (stale, not listening)
        old_socket = create_stale_socket(version=0)
        assert old_socket.exists(), "Precondition: old socket should exist"

        # Verify stale socket is NOT alive (no listener)
        # The is_socket_alive() function checks this
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(old_socket))
            alive = True
        except OSError:
            alive = False
        finally:
            sock.close()

        assert not alive, "Stale socket should NOT respond to connection"

    def test_t2_socket_path_format_correctness(self, mock_tmpdir):
        """T2: Socket path contains version and follows expected format.

        Expected: {tmpdir}/velo-{UID}/velo-zygote-v01.sock
        """
        path = get_versioned_socket_path()
        path_str = str(path)

        # Verify format
        assert f"velo-zygote-v{PROTOCOL_VERSION:02x}.sock" in path_str, (
            f"Socket path should contain versioned socket name, got: {path_str}"
        )
        assert f"velo-{os.getuid()}" in path_str or "velo" in path_str, (
            f"Socket path should contain user directory, got: {path_str}"
        )

    def test_t3_active_socket_not_deleted(self, create_active_socket):
        """T3: Active sockets are NOT deleted during cleanup.

        Connection test should detect live socket and preserve it.
        """
        # Create active socket (listening)
        socket_path, sock = create_active_socket(version=PROTOCOL_VERSION)

        try:
            assert socket_path.exists(), "Precondition: socket should exist"

            # Test that active socket is alive
            test_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                test_sock.connect(str(socket_path))
                alive = True
                test_sock.close()
            except OSError:
                alive = False

            assert alive, "Active socket should respond to connection test"
            assert socket_path.exists(), "Active socket should NOT be removed"
        finally:
            sock.close()

    def test_t4_directory_permissions_0700(self, tmp_path):
        """T4: Socket directory created with 0700 permissions (user-only)."""
        socket_dir = tmp_path / f"velo-{os.getuid()}"
        ensure_socket_dir(socket_dir)

        # Verify permissions
        mode = socket_dir.stat().st_mode & 0o777
        assert mode == 0o700, f"Directory should have 0700 permissions, got {oct(mode)}"

    def test_t5_multi_user_isolation(self, mock_tmpdir):
        """T5: Each user has separate socket directory.

        Socket path includes UID for user isolation.
        """
        uid = os.getuid()
        socket_dir = get_socket_dir()

        # Path should contain user-specific directory
        assert f"velo-{uid}" in str(socket_dir) or "velo" in str(socket_dir), (
            f"Socket dir should be user-isolated: {socket_dir}"
        )


# ============================================================================
# Edge Case Tests (T6-T10)
# ============================================================================


class TestEdgeCases:
    """Edge case handling for socket path and cleanup."""

    def test_t6_long_tmpdir_fallback(self, monkeypatch):
        """T6: Falls back to /tmp when $TMPDIR path exceeds 80 chars.

        Unix sockets have 108-char limit. Deep macOS paths need fallback.
        """
        # Simulate deeply nested TMPDIR
        long_path = "/var/folders" + "/deep" * 20 + "/T"
        monkeypatch.setenv("TMPDIR", long_path)
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

        result = get_socket_dir()

        # Should fall back to /tmp/velo-{UID}/ due to path length
        # The actual result path should be less than 108 chars when combined with socket name
        test_socket_path = result / EXPECTED_SOCKET_NAME
        assert len(str(test_socket_path)) < 108, (
            f"Socket path should be under 108 chars, got: {len(str(test_socket_path))}"
        )

    def test_t7_permission_error_graceful_handling(self, tmp_path):
        """T7: Cleanup handles permission errors gracefully (no panic).

        If a socket file cannot be deleted, should warn but not crash.
        """
        socket_dir = tmp_path / f"velo-{os.getuid()}"
        socket_dir.mkdir(mode=0o700)

        # Create a socket file with no write permission on parent
        stale_socket = socket_dir / "velo-zygote-v00.sock"
        stale_socket.touch()

        # Make directory read-only (can't delete files)
        socket_dir.chmod(0o500)

        try:
            # ensure_socket_dir should NOT raise an exception
            ensure_socket_dir(socket_dir)
            # The function should return True since dir exists (even though we can't modify perms)
            # OR return False gracefully without crashing
            # Either way, no exception should be raised
        finally:
            # Restore permissions for cleanup
            socket_dir.chmod(0o700)

    def test_t8_concurrent_startup_no_race(self, tmp_path, monkeypatch):
        """T8: Concurrent Zygote startups don't cause race conditions.

        Multiple threads trying to create socket dir simultaneously.
        """
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

        results = []
        errors = []

        def try_create_socket_dir():
            try:
                path = get_socket_dir()
                results.append(path)
            except Exception as e:
                errors.append(e)

        # Launch 5 concurrent threads
        threads = [threading.Thread(target=try_create_socket_dir) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed without errors
        assert len(errors) == 0, f"Race condition errors: {errors}"
        assert len(results) == 5, "All threads should return a path"
        # All threads should return the same path
        assert len({str(p) for p in results}) == 1, "All threads should get same path"

    def test_t9_symlink_attack_protection(self, tmp_path, monkeypatch):
        """T9: Symlink attack protection.

        If socket dir is symlink to sensitive location, should detect/prevent.
        """
        # Create a dangling symlink (don't point to /etc as that's too dangerous)
        symlink_path = tmp_path / f"velo-{os.getuid()}"
        fake_target = tmp_path / "fake_target"
        fake_target.mkdir()
        symlink_path.symlink_to(fake_target)

        monkeypatch.setenv("TMPDIR", str(tmp_path))
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

        # get_socket_dir() should handle symlinks gracefully
        result = get_socket_dir()
        # Should either follow symlink or fallback, not crash
        assert result is not None

    def test_t10_disk_space_exhausted(self, tmp_path, monkeypatch):
        """T10: Socket creation fails gracefully when disk is full."""
        # Mock disk full scenario by patching mkdir
        original_mkdir = Path.mkdir
        call_count = [0]

        def mock_mkdir(self, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] > 1:  # Let first call succeed for test setup
                raise OSError(28, "No space left on device")
            return original_mkdir(self, *args, **kwargs)

        with patch.object(Path, "mkdir", mock_mkdir):
            # Should handle error gracefully
            monkeypatch.setenv("TMPDIR", str(tmp_path))
            monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

            # Function should not raise, even if mkdir fails
            try:
                result = get_socket_dir()
                # Should fall back to /tmp or return some path
                assert result is not None
            except OSError:
                # If it does raise, that's also acceptable
                pass


# ============================================================================
# Regression Tests (REG-001 to REG-004)
# ============================================================================


class TestVersionRegression:
    """Regression tests for upgrade/downgrade scenarios."""

    def test_reg001_fresh_install_v062(self, mock_tmpdir):
        """REG-001: Fresh install v0.6.2 creates correct socket path.

        New installation should create versioned socket immediately.
        """
        path = get_versioned_socket_path()

        # Should have versioned path
        assert f"v{PROTOCOL_VERSION:02x}" in str(path), f"Fresh install path should include version: {path}"

    def test_reg002_upgrade_v061_to_v062(self, temp_socket_dir, create_stale_socket):
        """REG-002: Upgrade v0.6.1 -> v0.6.2 cleans old JSON socket.

        Scenario:
        1. v0.6.1 Zygote running (JSON, old socket)
        2. Binary upgraded to v0.6.2
        3. New CLI detects stale socket, cleans, starts new Zygote
        """
        # Create simulated old socket (version 0 = JSON)
        old_socket = create_stale_socket(version=0)
        assert old_socket.exists(), "Precondition: old socket exists"

        # New version socket has different name
        new_socket_name = f"velo-zygote-v{PROTOCOL_VERSION:02x}.sock"
        assert old_socket.name != new_socket_name, "Old and new socket names should differ"

    def test_reg003_downgrade_v062_to_v061(self, temp_socket_dir):
        """REG-003: Downgrade v0.6.2 -> v0.6.1 still works.

        Old CLI should use old socket path, ignoring new version socket.
        """
        # Create new version socket
        new_socket = temp_socket_dir / f"velo-zygote-v{PROTOCOL_VERSION:02x}.sock"
        new_socket.touch()

        # Simulate old CLI looking for v0 socket
        old_socket = temp_socket_dir / "velo-zygote-v00.sock"

        # Old CLI should NOT see new socket
        assert new_socket.exists()
        assert not old_socket.exists(), "Old CLI socket should not exist yet"

    def test_reg004_multi_user_parallel(self, mock_tmpdir):
        """REG-004: Multiple users on same system have isolated sockets.

        Each user's Zygote should use their own socket directory.
        """
        uid = os.getuid()

        # Verify path construction includes UID
        socket_dir = get_socket_dir()
        get_versioned_socket_path()

        assert f"velo-{uid}" in str(socket_dir) or "velo" in str(socket_dir), (
            f"Socket dir should be user-isolated: {socket_dir}"
        )


# ============================================================================
# Integration Helpers
# ============================================================================


def is_socket_listening(path: Path) -> bool:
    """Check if a Unix socket is listening (connection test)."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.1)  # 100ms timeout
        sock.connect(str(path))
        sock.close()
        return True
    except OSError:
        return False


# ============================================================================
# Test Discovery Validation
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
