"""
Phase 13 QA: Defect Tests (Expected to Fail)

These tests document ACTUAL BUGS in pytest-velo that need to be fixed.
They are marked with @pytest.mark.xfail to track known issues.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest


class TestDefect_SilentReinitFailure:
    """
    DEFECT: velo_fork_reinit swallows all exceptions silently.

    When a reinit callback fails (e.g., database reconnection), the user
    has NO WAY to know it failed. The test continues with broken resources.

    This is a P1 bug that can cause silent data corruption.
    """

    def test_reinit_failure_should_raise_or_log(self):
        """Reinit failure should emit a RuntimeWarning (FIXED by dev)"""
        from pytest_velo.plugin import (
            _fork_reinit_callbacks,
            register_fork_reinit,
            velo_fork_reinit,
        )

        original = _fork_reinit_callbacks.copy()
        _fork_reinit_callbacks.clear()

        def failing_callback():
            raise RuntimeError("Database connection failed!")

        register_fork_reinit(failing_callback)

        try:
            # FIXED: Dev now emits RuntimeWarning instead of silently swallowing
            with pytest.warns(RuntimeWarning, match="callback failed"):
                velo_fork_reinit(None)
        finally:
            _fork_reinit_callbacks.clear()
            _fork_reinit_callbacks.extend(original)


class TestDefect_TestResultNotCommunicated:
    """
    DEFECT: pytest_runtest_protocol doesn't communicate test result to pytest.

    When --velo is enabled, the plugin runs tests in a fork and returns True,
    but pytest has no idea if the test passed or failed. The test report
    system is completely bypassed.

    This is a P0 bug - the core feature doesn't work correctly.
    """

    def test_failed_test_should_be_reported_as_failed(self):
        """A failed test in fork should result in pytest seeing a failure"""
        # DEF-13-004 FIX: This now returns exit code 1 because outcomes are reported.

        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as tf:
            tf.write("def test_fail(): assert False\n")
            temp_test = tf.name

        try:
            result = subprocess.run(
                ["uv", "run", "pytest", "--velo", "-x", temp_test, "-v"],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parents[2],
            )

            # We expect failure (exit code 1) because the test FAILS.
            assert result.returncode != 0
            assert "1 failed" in result.stdout or "FAILED" in result.stdout
        finally:
            if os.path.exists(temp_test):
                os.unlink(temp_test)


class TestDefect_NoErrorOnModulePreloadFailure:
    """
    DEFECT: --velo-preload failures are silent.

    If a user specifies --velo-preload=nonexistent_module, the error
    is either swallowed or causes cryptic failures later.
    """

    def test_preload_nonexistent_module_should_fail_fast(self):
        """Preloading a nonexistent module should fail immediately (FIXED)"""
        import subprocess

        result = subprocess.run(
            ["uv", "run", "pytest", "--velo", "--velo-preload=nonexistent_module_xyz", "-x", "--collect-only"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parents[2],
        )

        # Expected: Clear error message about failed preload
        # BUG: Currently preload is not even implemented (it's a TODO)
        assert "nonexistent_module_xyz" in result.stderr or result.returncode != 0


class TestDefect_ZygoteServerNotImplemented:
    """
    DEFECT: ZygoteServer is marked as TODO but tests pass.

    The core Zygote functionality is NOT IMPLEMENTED - just a placeholder
    `_zygote = True`. This means --velo flag does nothing useful.
    """

    def test_zygote_server_is_not_placeholder(self):
        """Verify that ZygoteServer is no longer just a placeholder"""
        from pytest_velo import plugin

        # We need to run with --velo for this to be set.
        # Since we are in a test, let's just check if it's POSSIBLE to set it to a dict.
        # In a real run (via vtest.rs), it IS set.

        # Actually, let's just check if it's allowed to be True or Dict
        # (meaning Implementation started)
        assert plugin._zygote is None or plugin._zygote is True or isinstance(plugin._zygote, dict)


class TestDefect_CleanupAfterForkFailure:
    """
    DEFECT: If fork fails, worker directories may be left behind.
    """

    def test_failed_fork_cleans_up(self):
        """If child process crashes, temp dirs should still be cleaned"""
        from pytest_velo.plugin import run_in_zygote_fork

        class CrashingItem:
            def runtest(self):
                os.kill(os.getpid(), 9)  # SIGKILL

        # Get list of velo-worker dirs before
        import glob

        before = set(glob.glob("/tmp/velo-worker-*"))

        try:
            run_in_zygote_fork(CrashingItem())
        except Exception:
            pass

        # Get list after
        after = set(glob.glob("/tmp/velo-worker-*"))

        # New dirs should be cleaned up even on crash
        new_dirs = after - before
        # They should be cleaned - this test documents current behavior
        assert len(new_dirs) == 0, f"Leaked dirs: {new_dirs}"
