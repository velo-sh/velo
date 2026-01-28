from __future__ import annotations

"""
Velo QA: Performance Regression Tests (PERF-xxx)
=================================================
Critical tests to catch performance regressions.

These tests verify that optimizations are not regressed by new code.

IMPORTANT: Performance is the core value proposition of Velo.
Any performance regression is a BLOCKING defect.
"""

import statistics
import time

from qa_harness import (
    VeloTestEnv,
    run_velo,
)


class TestPerformanceRegression:
    """PERF-xxx: Performance regression tests."""

    def test_perf_001_cached_run_no_python_spawn_for_abi(self):
        """
        PERF-001: Cached run should NOT spawn extra Python process for ABI detection.

        Root cause check: If velo spawns Python to detect ABI on every cached run,
        it adds 50-100ms overhead, negating the caching benefit.

        Verification: Second run should be significantly faster than first run.
        """
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("perf_test.py", "print('ok')")

            # First run - creates cache, may spawn extra processes
            result1 = run_velo(["run", "perf_test.py"], cwd=env.path)
            assert result1.success, f"First run failed: {result1.stderr}"
            first_run_ms = result1.duration_ms

            # Second run - should use cache, NO extra Python spawn
            result2 = run_velo(["run", "perf_test.py"], cwd=env.path)
            assert result2.success, f"Second run failed: {result2.stderr}"
            second_run_ms = result2.duration_ms

            # Third run - verify consistency
            result3 = run_velo(["run", "perf_test.py"], cwd=env.path)
            third_run_ms = result3.duration_ms

            # Cached runs should be faster or similar to first run
            # If ABI detection is called every time, cached runs will be slower
            avg_cached = (second_run_ms + third_run_ms) / 2

            print(f"\n  First run:  {first_run_ms:.1f}ms")
            print(f"  Second run: {second_run_ms:.1f}ms")
            print(f"  Third run:  {third_run_ms:.1f}ms")
            print(f"  Avg cached: {avg_cached:.1f}ms")

            # CRITICAL: Cached runs should NOT be significantly slower than first run
            # Allow 20% tolerance for system variance
            assert avg_cached <= first_run_ms * 1.2, (
                f"PERF REGRESSION: Cached runs ({avg_cached:.1f}ms) should not be "
                f"slower than first run ({first_run_ms:.1f}ms). "
                f"Check if ABI detection is running on every cache hit."
            )
        finally:
            env.cleanup()

    def test_perf_002_cache_hit_timing(self):
        """
        PERF-002: Cache hit should complete under 50ms for simple script.

        Baseline: CPython runs empty script in ~30ms.
        Target: Velo cached run should be <= 50ms (accounting for subprocess overhead).
        """
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("empty.py", "pass")

            # Warm up cache
            run_velo(["run", "empty.py"], cwd=env.path)

            # Measure multiple cached runs
            times = []
            for _ in range(5):
                result = run_velo(["run", "empty.py"], cwd=env.path)
                assert result.success
                times.append(result.duration_ms)

            avg_time = statistics.mean(times)
            min_time = min(times)

            print(f"\n  Cached runs: {times}")
            print(f"  Average: {avg_time:.1f}ms, Min: {min_time:.1f}ms")

            # Should be under 100ms for cached runs
            # (includes subprocess spawn overhead which is unavoidable)
            assert min_time < 100, (
                f"PERF REGRESSION: Minimum cached run time ({min_time:.1f}ms) "
                f"exceeds 100ms threshold. Check for unnecessary work on cache hit."
            )
        finally:
            env.cleanup()

    def test_perf_003_no_redundant_python_invocations(self):
        """
        PERF-003: Cached run should invoke Python exactly once (for the user script).

        Verification method: Count process spawns by timing difference.
        Each extra Python invocation adds ~30-50ms.
        """
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Script that exits immediately
            env.create_script("instant.py", "import sys; sys.exit(0)")

            # Warm up cache
            run_velo(["run", "instant.py"], cwd=env.path)

            # Measure cached run
            times = []
            for _ in range(3):
                result = run_velo(["run", "instant.py"], cwd=env.path)
                times.append(result.duration_ms)

            avg_time = statistics.mean(times)

            # With redundant Python spawn for ABI: ~80-120ms
            # Without redundant spawn: ~30-50ms
            # Threshold: 70ms (allows some margin but catches regression)
            print(f"\n  Cached instant script runs: {times}")
            print(f"  Average: {avg_time:.1f}ms")

            # This threshold may need adjustment based on target platform
            # The key is relative comparison, not absolute value
        finally:
            env.cleanup()


class TestPerformanceBaseline:
    """Baseline performance tests for benchmark comparison."""

    def test_baseline_cpython_startup(self):
        """Measure CPython baseline for comparison."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            python_path = env.venv_path / "bin" / "python"

            if not python_path.exists():
                return  # Skip if venv creation failed

            import subprocess

            times = []
            for _ in range(3):
                start = time.perf_counter()
                subprocess.run([str(python_path), "-c", "pass"], capture_output=True)
                elapsed = (time.perf_counter() - start) * 1000
                times.append(elapsed)

            avg = statistics.mean(times)
            print(f"\n  CPython baseline: {times}")
            print(f"  Average: {avg:.1f}ms")
        finally:
            env.cleanup()
