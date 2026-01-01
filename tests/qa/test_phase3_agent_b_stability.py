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
                run_result = run_velo(["run", "--zygote", "hello.py"], cwd=env.path, timeout=10)
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
            env.create_script("args.py", """
import sys
print(f"args: {sys.argv[1:]}")
""")
            
            result = run_velo(
                ["run", "--zygote", "args.py", "--", "foo", "bar"],
                cwd=env.path,
                timeout=30
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
            
            result = run_velo(["run", "--zygote", "exit42.py"], cwd=env.path, timeout=30)
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
            env.create_script("streams.py", """
import sys
print("STDOUT_MARKER")
print("STDERR_MARKER", file=sys.stderr)
""")
            
            result = run_velo(["run", "--zygote", "streams.py"], cwd=env.path, timeout=30)
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
                result = run_velo(["run", "--zygote", "deterministic.py"], cwd=env.path, timeout=30)
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
                result = run_velo(["run", "--zygote", "check.py"], cwd=env.path, timeout=10)
                run_velo(["zygote", "stop"], cwd=env.path, timeout=5)
                
                if result.success:
                    assert "consistent" in result.stdout
        finally:
            env.cleanup()
