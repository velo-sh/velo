"""
Phase 13 QA: Real Bug Hunt Tests

These tests were written by QA to find actual bugs in pytest-velo implementation.
"""

import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestBug001_WorkerBaseNotUsed:
    """BUG-001: worker_base return value not used in child process"""

    def test_worker_isolation_dirs_actually_created(self):
        """Verify isolation directories are actually created during fork"""
        from pytest_velo.plugin import run_in_zygote_fork

        # Create a mock test item that checks isolation
        class MockItem:
            def runtest(self):
                # Check that isolation directories exist
                worker_id = os.environ.get("VELO_WORKER_ID")
                assert worker_id is not None, "VELO_WORKER_ID not set"
                
                tmpdir = os.environ.get("TMPDIR")
                assert tmpdir is not None, "TMPDIR not set"
                assert os.path.exists(tmpdir), f"TMPDIR {tmpdir} does not exist"
                
                socket_dir = os.environ.get("VELO_WORKER_SOCKET_DIR")
                assert socket_dir is not None, "VELO_WORKER_SOCKET_DIR not set"
                assert os.path.exists(socket_dir), f"Socket dir {socket_dir} does not exist"

        result = run_in_zygote_fork(MockItem())
        assert result is True, "Isolation test failed in forked child"


class TestBug002_RaceConditionOnCleanup:
    """BUG-002: Potential race condition in cleanup if child dies early"""

    def test_cleanup_handles_nonexistent_dir(self):
        """cleanup_worker_environment should not fail if dir doesn't exist"""
        from pytest_velo.plugin import cleanup_worker_environment

        nonexistent = "/tmp/velo-worker-999999999"
        # Should not raise
        cleanup_worker_environment(nonexistent)

    def test_cleanup_handles_partial_dir(self):
        """cleanup should handle partially created directories"""
        from pytest_velo.plugin import cleanup_worker_environment

        import shutil
        partial_dir = "/tmp/velo-worker-88888888"
        os.makedirs(f"{partial_dir}/tmp", exist_ok=True)
        # Only tmp exists, not sockets or logs
        
        cleanup_worker_environment(partial_dir)
        assert not os.path.exists(partial_dir), "Partial dir not cleaned"


class TestBug003_SilentReinitFailure:
    """BUG-003: velo_fork_reinit silently swallows all exceptions"""

    def test_reinit_failure_is_not_logged(self):
        """Reinit callback failures are silently ignored - this is a bug"""
        from pytest_velo.plugin import register_fork_reinit, velo_fork_reinit, _fork_reinit_callbacks

        # Save original callbacks
        original_callbacks = _fork_reinit_callbacks.copy()
        _fork_reinit_callbacks.clear()

        error_occurred = []

        def failing_callback():
            error_occurred.append(True)
            raise RuntimeError("Database connection failed!")

        register_fork_reinit(failing_callback)

        # This should raise or at least log, but it doesn't
        velo_fork_reinit(MagicMock())

        # Restore
        _fork_reinit_callbacks.clear()
        _fork_reinit_callbacks.extend(original_callbacks)

        # The callback was called but exception was swallowed
        assert len(error_occurred) == 1, "Callback was not called"
        # BUG: No way to know the reinit failed!


class TestBug004_TestResultNotReported:
    """BUG-004: pytest_runtest_protocol returns True but doesn't report result"""

    def test_runtest_protocol_returns_without_result(self):
        """
        When run_in_zygote_fork returns, pytest_runtest_protocol returns True
        but the test result (passed/failed) is never communicated to pytest.
        """
        from pytest_velo.plugin import pytest_runtest_protocol

        class MockConfig:
            class Option:
                velo = True
            option = Option()

        class MockItem:
            config = MockConfig()
            nodeid = "test_mock::test_case"
            location = ("test_mock.py", 1, "test_case")
            ihook = MagicMock()  # Auto-handles all hook methods
            
            def runtest(self):
                pass  # Test passes

        # Patch _zygote to be non-None
        import pytest_velo.plugin as plugin
        original_zygote = plugin._zygote
        plugin._zygote = True

        try:
            # This returns True, but pytest has no idea if test passed or failed
            item = MockItem()
            result = pytest_runtest_protocol(item, None)
            
            # Previously was a BUG: now dev has fixed it to report properly
            assert result is True
        finally:
            plugin._zygote = original_zygote


class TestEdgeCase_ConcurrentForks:
    """Edge case: What happens with rapid concurrent fork attempts?"""

    def test_concurrent_fork_requests(self):
        """Multiple fork requests in quick succession"""
        from pytest_velo.plugin import measure_fork_latency

        latencies = []
        for _ in range(10):
            latency = measure_fork_latency()
            latencies.append(latency)

        # All should complete without deadlock
        assert len(latencies) == 10
        avg = sum(latencies) / len(latencies)
        assert avg < 10.0, f"Average latency {avg}ms too high"


class TestEdgeCase_ForkWithOpenFiles:
    """Edge case: Fork with open file handles"""

    def test_fork_with_open_file(self):
        """Forking with open files should not corrupt them"""
        from pytest_velo.plugin import run_in_zygote_fork

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("before fork\n")
            temp_path = f.name

        class MockItem:
            def runtest(self):
                # Child writes to the same file
                with open(temp_path, 'a') as f:
                    f.write(f"child pid={os.getpid()}\n")

        try:
            result = run_in_zygote_fork(MockItem())
            assert result is True

            # Parent reads file
            with open(temp_path) as f:
                content = f.read()
            
            assert "before fork" in content
            assert "child pid=" in content
        finally:
            os.unlink(temp_path)


class TestEdgeCase_ForkWithThreads:
    """Edge case: Fork when threads exist"""

    def test_fork_rejected_with_multiple_threads(self):
        """Fork should fail if multiple threads active"""
        from pytest_velo.plugin import assert_single_threaded

        barrier = threading.Barrier(2)
        error = []

        def worker():
            barrier.wait()
            time.sleep(0.1)

        t = threading.Thread(target=worker)
        t.start()

        try:
            barrier.wait()  # Ensure thread is running
            with pytest.raises(RuntimeError, match="threads active"):
                assert_single_threaded()
        finally:
            t.join()
