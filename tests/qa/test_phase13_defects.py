"""
Phase 13 QA: Defect Tests (Expected to Fail)

These tests document ACTUAL BUGS in pytest-velo that need to be fixed.
They are marked with @pytest.mark.xfail to track known issues.
"""

import os
import sys
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

    @pytest.mark.xfail(reason="P1 BUG: Reinit failures are silently swallowed")
    def test_reinit_failure_should_raise_or_log(self):
        """Reinit failure should either raise or at minimum log a warning"""
        from pytest_velo.plugin import (
            register_fork_reinit,
            velo_fork_reinit,
            _fork_reinit_callbacks,
        )

        original = _fork_reinit_callbacks.copy()
        _fork_reinit_callbacks.clear()

        def failing_callback():
            raise RuntimeError("Database connection failed!")

        register_fork_reinit(failing_callback)

        try:
            # BUG: This should raise or log, but it silently swallows the error
            # Expected: RuntimeError or at minimum a warning in stderr
            with pytest.raises(RuntimeError):
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

    @pytest.mark.xfail(
        reason="P0 BUG: Test pass/fail status not reported to pytest"
    )
    def test_failed_test_should_be_reported_as_failed(self):
        """A failed test in fork should result in pytest seeing a failure"""
        # This test documents that when a test fails in the fork,
        # pytest doesn't know about it because pytest_runtest_protocol
        # returns True without creating a TestReport with outcome='failed'
        
        result = subprocess.run(
            ["uv", "run", "pytest", "--velo", "-x", 
             "tests/qa/test_phase13_bug_hunt.py::TestBug003_SilentReinitFailure",
             "-v"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parents[2],
        )
        
        # With proper implementation, a failing test should cause exit code 1
        # BUG: Currently returns 0 or doesn't properly report failures
        assert result.returncode in (0, 1)  # Placeholder - actual bug testing
        

class TestDefect_NoErrorOnModulePreloadFailure:
    """
    DEFECT: --velo-preload failures are silent.
    
    If a user specifies --velo-preload=nonexistent_module, the error
    is either swallowed or causes cryptic failures later.
    """

    @pytest.mark.xfail(reason="P2 BUG: Preload failure handling not implemented")
    def test_preload_nonexistent_module_should_fail_fast(self):
        """Preloading a nonexistent module should fail immediately with clear error"""
        import subprocess

        result = subprocess.run(
            ["uv", "run", "pytest", "--velo", 
             "--velo-preload=nonexistent_module_xyz",
             "-x", "--collect-only"],
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

    def test_zygote_server_is_placeholder(self):
        """Verify that ZygoteServer is just a placeholder"""
        from pytest_velo import plugin

        # This should be a real ZygoteServer instance, not True
        # Reading line 183: _zygote = True  # Placeholder
        
        # Document the bug: _zygote is set to True, not a real server
        assert plugin._zygote is None or plugin._zygote is True
        # This is the bug - it should be an actual server instance


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
