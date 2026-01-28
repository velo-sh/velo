from __future__ import annotations

"""
Velo QA: Cache Chaos Tests (CHAOS-xxx)
======================================
Adversarial tests targeting cache resilience.

These tests attempt to BREAK the cache handling by:
- Corrupting cache files
- Creating race conditions
- Exhausting resources

Goal: Velo should NEVER panic, always recover gracefully.
"""

import threading

import pytest
from qa_harness import (
    VeloTestEnv,
    assert_no_crash,
    run_velo,
)


class TestCacheChaosCORRUPTION:
    """CHAOS-001 to CHAOS-004: Cache corruption tests."""

    def test_chaos_001_corrupted_random_bytes(self):
        """CHAOS-001: Random bytes in cache file should not crash velo."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()

            # First run to create valid cache
            result1 = run_velo(["run", "test.py"], cwd=env.path)
            assert result1.success, f"First run failed: {result1.stderr}"

            # Corrupt the cache with random bytes
            env.corrupt_cache("random")

            # Second run should recover gracefully
            result2 = run_velo(["run", "test.py"], cwd=env.path)
            assert_no_crash(result2)
            # Should still succeed by rebuilding cache
            assert result2.success, f"Recovery failed: {result2.stderr}"
        finally:
            env.cleanup()

    def test_chaos_002_truncated_cache(self):
        """CHAOS-002: Truncated cache file should not crash velo."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()

            result1 = run_velo(["run", "test.py"], cwd=env.path)
            assert result1.success

            # Truncate the cache
            env.corrupt_cache("truncated")

            result2 = run_velo(["run", "test.py"], cwd=env.path)
            assert_no_crash(result2)
            assert result2.success
        finally:
            env.cleanup()

    def test_chaos_003_empty_cache_file(self):
        """CHAOS-003: Empty cache file should not crash velo."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()

            # Create empty cache file
            env.corrupt_cache("empty")

            result = run_velo(["run", "test.py"], cwd=env.path)
            assert_no_crash(result)
            assert result.success
        finally:
            env.cleanup()

    def test_chaos_004_cache_dir_is_file(self):
        """CHAOS-004: Cache directory path is actually a file."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()

            # Create a file where cache directory should be
            cache_path = env.cache_path
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            # Write a file (not directory) at .velo_cache path
            with open(cache_path, "w") as f:
                f.write("I am a file, not a directory")

            result = run_velo(["run", "test.py"], cwd=env.path)
            assert_no_crash(result)
            # May fail but should not crash
        finally:
            env.cleanup()


class TestCacheChaosRESOURCES:
    """CHAOS-005 to CHAOS-008: Resource exhaustion tests."""

    def test_chaos_005_readonly_cache_dir(self):
        """CHAOS-005: Read-only cache dir should not crash velo."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()

            # Create and make cache dir read-only
            env.make_cache_readonly()

            result = run_velo(["run", "test.py"], cwd=env.path)
            assert_no_crash(result)
            # Should succeed even without caching
            assert result.success, f"Should work without cache: {result.stderr}"
        finally:
            env.cleanup()

    def test_chaos_008_huge_cache_file(self):
        """CHAOS-008: Huge cache file should not exhaust memory."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()

            # Create 10MB cache file
            env.corrupt_cache("huge")

            result = run_velo(["run", "test.py"], cwd=env.path, timeout=10)
            assert_no_crash(result)
            # Should either succeed or fail gracefully
        finally:
            env.cleanup()


class TestCacheChaosRACE:
    """CHAOS-007: Race condition tests."""

    def test_chaos_007_parallel_cache_writes(self):
        """CHAOS-007: Multiple velo processes should not corrupt cache."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()

            results = []
            errors = []

            def run_velo_thread():
                try:
                    result = run_velo(["run", "test.py"], cwd=env.path, timeout=30)
                    results.append(result)
                except Exception as e:
                    errors.append(e)

            # Launch 5 parallel velo processes
            threads = [threading.Thread(target=run_velo_thread) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # All should complete without crashing
            assert not errors, f"Thread errors: {errors}"
            for result in results:
                assert_no_crash(result)

            # At least one should succeed
            successes = sum(1 for r in results if r.success)
            assert successes >= 1, "At least one parallel run should succeed"
        finally:
            env.cleanup()


# Pytest configuration
@pytest.fixture(autouse=True)
def check_velo_binary():
    """Ensure velo binary exists before running tests."""
    from qa_harness import VELO_BINARY

    if not VELO_BINARY.exists():
        pytest.skip("Velo binary not found. Run 'cargo build --release' first.")
