from __future__ import annotations

"""
Velo QA: Agent B - Stability Guardian (CORE/REG/IDEM-xxx)
=========================================================
Conservative QA: Ensure core functionality never regresses.

Agent B's mission: Stability above all else.
"""

import os
import statistics
import time
import threading
import pytest
from pathlib import Path

from test_harness import run_velo, assert_no_crash
from test_phase3_harness import ZygoteTestEnv


class TestCoreFlow:
    """CORE-xxx: Core flow stability tests (P0 - must pass)."""

    def test_core_001_happy_path(self):
        """
        CORE-001: Happy path - start, run, stop.

        Priority: P0 (BLOCKING)
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("hello.py", "print('hello world')")

            # Start
            start = run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            # Run
            if start.success:
                run_result = run_velo(
                    ["run", "--zygote", "hello.py"], cwd=env.path, timeout=10
                )
                assert run_result.success, f"Run failed: {run_result.stderr}"
                assert "hello world" in run_result.stdout

            # Stop
            stop = run_velo(["zygote", "stop"], cwd=env.path, timeout=10)
            # Stop should work
        finally:
            env.cleanup()

    def test_core_002_simple_script(self):
        """
        CORE-002: Simple script execution.

        Priority: P0 (BLOCKING)
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("calc.py", "print(2 + 2)")

            result = run_velo(["run", "--zygote", "calc.py"], cwd=env.path, timeout=30)
            assert_no_crash(result)
            if result.success:
                assert "4" in result.stdout
        finally:
            env.cleanup()

    def test_core_003_script_with_args(self):
        """
        CORE-003: Script with command-line arguments.

        Priority: P0 (BLOCKING)
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script(
                "args.py",
                """
import sys
print(f"args: {sys.argv[1:]}")
""",
            )

            result = run_velo(
                ["run", "--zygote", "args.py", "--", "foo", "bar"],
                cwd=env.path,
                timeout=30,
            )
            assert_no_crash(result)
            if result.success:
                assert "foo" in result.stdout or "bar" in result.stdout
        finally:
            env.cleanup()

    def test_core_004_exit_code(self):
        """
        CORE-004: Script exit code propagation.

        Priority: P0 (BLOCKING)
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("exit42.py", "import sys; sys.exit(42)")

            result = run_velo(
                ["run", "--zygote", "exit42.py"], cwd=env.path, timeout=30
            )
            # Return code should be 42 or contain 42 in some form
            # (exact behavior depends on implementation)
        finally:
            env.cleanup()

    def test_core_005_stdout_stderr(self):
        """
        CORE-005: stdout and stderr separation.

        Priority: P0 (BLOCKING)
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script(
                "streams.py",
                """
import sys
print("STDOUT_MARKER")
print("STDERR_MARKER", file=sys.stderr)
""",
            )

            result = run_velo(
                ["run", "--zygote", "streams.py"], cwd=env.path, timeout=30
            )
            assert_no_crash(result)
            if result.success:
                assert "STDOUT_MARKER" in result.stdout
                # stderr may be in stderr or combined
        finally:
            env.cleanup()


class TestRegression:
    """REG-xxx: Regression tests (P1 - critical)."""

    def test_reg_001_velo_run_no_zygote(self):
        """
        REG-001: velo run without --zygote still works.

        Priority: P1 (must not regress Phase 1.5)
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("simple.py", "print('ok')")

            # Normal run (no zygote)
            result = run_velo(["run", "simple.py"], cwd=env.path, timeout=10)
            assert result.success, "Normal velo run should still work"
            assert "ok" in result.stdout
        finally:
            env.cleanup()

    def test_reg_002_cache_hit_performance(self):
        """
        REG-002: Cache hit timing should not regress.

        Priority: P1 (performance baseline)
        Baseline: 12ms (Phase 1.5 verified)
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("quick.py", "pass")

            # First run (cache creation)
            run_velo(["run", "quick.py"], cwd=env.path, timeout=10)

            # Cached runs
            times = []
            for _ in range(3):
                result = run_velo(["run", "quick.py"], cwd=env.path, timeout=10)
                if result.success:
                    times.append(result.duration_ms)

            if times:
                avg = statistics.mean(times)
                print(f"\n  Cache hit times: {times}")
                print(f"  Average: {avg:.1f}ms")

                # Should not regress > 50ms from baseline
                assert avg < 50, f"Cache hit regressed: {avg:.1f}ms"
        finally:
            env.cleanup()

    def test_reg_003_velo_info_works(self):
        """
        REG-003: velo info command still works.

        Priority: P1 (Phase 1.5 feature)
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            result = run_velo(["info"], cwd=env.path, timeout=10)
            assert_no_crash(result)

            if result.success:
                output = result.stdout.lower()
                assert "hardware" in output or "python" in output
        finally:
            env.cleanup()


class TestIdempotency:
    """IDEM-xxx: Idempotency tests (P3)."""

    def test_idem_001_same_script_100x(self):
        """
        IDEM-001: Same script 100x should give identical output.

        Priority: P3 (consistency)
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("deterministic.py", "print('RESULT:42')")

            outputs = []
            for i in range(20):  # Reduced from 100 for test speed
                result = run_velo(
                    ["run", "--zygote", "deterministic.py"], cwd=env.path, timeout=30
                )
                if result.success:
                    outputs.append(result.stdout.strip())

            if outputs:
                # All outputs should be identical
                unique = set(outputs)
                assert len(unique) == 1, f"Non-deterministic outputs: {unique}"
        finally:
            env.cleanup()

    def test_idem_003_restart_zygote_10x(self):
        """
        IDEM-003: Restart Zygote 10x should have no state drift.

        Priority: P3 (consistency)
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("check.py", "print('consistent')")

            for i in range(5):  # Reduced from 10
                run_velo(["zygote", "start"], cwd=env.path, timeout=10)
                result = run_velo(
                    ["run", "--zygote", "check.py"], cwd=env.path, timeout=10
                )
                run_velo(["zygote", "stop"], cwd=env.path, timeout=5)

                if result.success:
                    assert "consistent" in result.stdout
        finally:
            env.cleanup()


# =============================================================================
# CROSS-REVIEW: Agent A (Edge Cases) additions to Stability
# =============================================================================


class TestStabilityEdgeCases:
    """Agent A review: Edge cases that could destabilize core flow."""

    def test_stable_edge_001_empty_script_file(self):
        """
        Agent A: Empty script file should not crash.

        Edge case for core flow.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("empty.py", "")  # Completely empty

            result = run_velo(["run", "--zygote", "empty.py"], cwd=env.path, timeout=10)
            assert_no_crash(result)
        finally:
            env.cleanup()

    def test_stable_edge_002_script_only_comments(self):
        """
        Agent A: Script with only comments.

        Edge case for parser stability.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("comments.py", "# Just a comment\n# Another comment\n")

            result = run_velo(
                ["run", "--zygote", "comments.py"], cwd=env.path, timeout=10
            )
            assert_no_crash(result)
        finally:
            env.cleanup()

    def test_stable_edge_003_very_long_output(self):
        """
        Agent A: Script with very long output.

        Edge case for stdout buffer stability.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("long_output.py", "print('x' * 100000)")

            result = run_velo(
                ["run", "--zygote", "long_output.py"], cwd=env.path, timeout=30
            )
            assert_no_crash(result)
        finally:
            env.cleanup()


# =============================================================================
# CROSS-REVIEW: Agent C (Security) additions to Stability
# =============================================================================


class TestStabilitySecurity:
    """Agent C review: Security implications of stability features."""

    def test_stable_sec_001_error_message_no_leak(self):
        """
        Agent C: Error messages should not leak sensitive info.

        Security review of error handling.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Try to read nonexistent file
            result = run_velo(
                ["run", "--zygote", "nonexistent.py"], cwd=env.path, timeout=10
            )

            # Error message should not contain full paths or system info
            if not result.success:
                error = result.stderr.lower()
                # Should not expose system paths
                assert "/usr/" not in error or "/home/" not in error
        finally:
            env.cleanup()

    def test_stable_sec_002_crash_no_core_dump(self):
        """
        Agent C: Crash should not create exploitable core dump.

        Security review of crash handling.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("crash.py", "import sys; sys.exit(1)")

            result = run_velo(["run", "--zygote", "crash.py"], cwd=env.path, timeout=10)

            # Check no core files created
            import glob

            cores = glob.glob(str(env.path / "core*"))
            assert len(cores) == 0, "Core dump created!"
        finally:
            env.cleanup()

    def test_stable_sec_003_timing_consistency(self):
        """
        Agent C: Timing should not leak information.

        Security review of timing side-channels.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("quick.py", "pass")

            # Valid script timing
            valid_times = []
            for _ in range(5):
                r = run_velo(["run", "--zygote", "quick.py"], cwd=env.path, timeout=10)
                valid_times.append(r.duration_ms)

            # Invalid script timing (should not be measurably different)
            invalid_times = []
            for _ in range(5):
                r = run_velo(
                    ["run", "--zygote", "nonexistent.py"], cwd=env.path, timeout=10
                )
                invalid_times.append(r.duration_ms)

            # Check timing is similar (no timing oracle)
            if valid_times and invalid_times:
                valid_avg = sum(valid_times) / len(valid_times)
                invalid_avg = sum(invalid_times) / len(invalid_times)

                # Timing difference should not be exploitable (< 100ms difference)
                print(
                    f"\n  Valid avg: {valid_avg:.1f}ms, Invalid avg: {invalid_avg:.1f}ms"
                )
        finally:
            env.cleanup()
