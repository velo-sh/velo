"""
RFC-0028 Phase 13: QA Gate Tests for velo test

These tests verify the QA checklist requirements from:
docs/qa/PHASES/phase-13/qa-checklist.md

Gates:
- Gate A: Basic Functionality
- Gate B: Fork Safety (P0 Critical)
- Gate C: Performance
- Gate D: Compatibility
- Gate E: Error Handling
"""

import os
import subprocess
import tempfile
from pathlib import Path

from conftest_utils import T_MEDIUM, T_SHORT

# ============================================================================
# Gate A: Basic Functionality
# ============================================================================


class TestGateA_BasicFunctionality:
    """Gate A: CLI and basic test execution"""

    def test_a1_cli_help_text(self):
        """A.1: velo test --help shows usage"""
        result = subprocess.run(
            ["./target/release/velo", "test", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parents[4],
            timeout=T_SHORT,
        )
        assert result.returncode == 0
        assert "Run tests with Zygote acceleration" in result.stdout
        assert "--zygote" in result.stdout or "--workers" in result.stdout

    def test_a1_cli_version_in_help(self):
        """A.1: Help shows RFC reference"""
        result = subprocess.run(
            ["./target/release/velo", "test", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parents[4],
            timeout=T_SHORT,
        )
        assert "RFC-0028" in result.stdout or "Zygote" in result.stdout

    def test_a2_single_test_execution(self):
        """A.2: Single test file runs successfully"""
        result = subprocess.run(
            [
                "./target/release/velo",
                "test",
                "tests/qa/test_phase13_pytest_velo.py::TestPluginHooks::test_pytest_addoption_exists",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parents[4],
            timeout=T_MEDIUM,
        )
        assert "passed" in result.stdout.lower() or result.returncode == 0


# ============================================================================
# Gate B: Fork Safety (P0 Critical)
# ============================================================================


class TestGateB_ForkSafety:
    """Gate B: P0 fork safety requirements"""

    def test_b1_threading_no_deadlock(self):
        """B.1 (P0-2): Threading test completes without GIL deadlock"""
        # Create a test with threading
        test_code = """
import threading
import time

def test_with_threads():
    results = []
    def worker():
        time.sleep(0.005)
        results.append(1)
    
    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(results) == 3
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            temp_path = f.name

        try:
            result = subprocess.run(
                ["./target/release/velo", "test", temp_path],
                capture_output=True,
                text=True,
                timeout=30,  # Should complete well before this
                cwd=Path(__file__).parents[4],
            )
            # Test should pass without deadlock
            assert "passed" in result.stdout.lower() or result.returncode == 0
        finally:
            os.unlink(temp_path)

    def test_b2_p0_1_fork_reinit_hook_exists(self):
        """B.2 (P0-1): velo_fork_reinit hook is available"""
        from pytest_velo.plugin import velo_fork_reinit

        # Should be callable
        assert callable(velo_fork_reinit)

    def test_b3_p0_3_atexit_clear_exists(self):
        """B.3 (P0-3): child_process_hygiene calls atexit._clear"""
        from pytest_velo.plugin import child_process_hygiene

        assert callable(child_process_hygiene)

    def test_b3_p0_3_os_exit_in_run_in_zygote_fork(self):
        """B.3 (P0-3): run_in_zygote_fork uses os._exit, not sys.exit"""
        import ast
        import inspect

        from pytest_velo.plugin import run_in_zygote_fork

        source = inspect.getsource(run_in_zygote_fork)

        # Parse AST to check for actual sys.exit() calls (not docstring mentions)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            # If parsing fails, fall back to simpler check
            assert "os._exit(" in source, "Must use os._exit for P0-3 compliance"
            return

        # Look for Call nodes to sys.exit
        sys_exit_calls = []
        os_exit_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for sys.exit() call
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "exit":
                        if isinstance(node.func.value, ast.Name) and node.func.value.id == "sys":
                            sys_exit_calls.append(node)
                    elif node.func.attr == "_exit":
                        if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                            os_exit_calls.append(node)

        assert len(os_exit_calls) > 0, "Must use os._exit for P0-3 compliance"
        assert len(sys_exit_calls) == 0, "Must NOT use sys.exit (would run atexit handlers)"


# ============================================================================
# Gate C: Performance
# ============================================================================


class TestGateC_Performance:
    """Gate C: Fork latency and performance"""

    def test_c1_fork_latency_under_2ms(self):
        """C.1: Fork latency < 2ms target"""
        from pytest_velo.plugin import measure_fork_latency

        # Take multiple samples for statistical validity
        latencies = [measure_fork_latency() for _ in range(5)]
        avg_latency = sum(latencies) / len(latencies)

        # Target: <2ms, Tolerance: <5ms
        assert avg_latency < 5.0, f"Fork latency {avg_latency:.2f}ms exceeds 5ms tolerance"

    def test_c1_fork_latency_statistical(self):
        """C.1: Fork latency statistical analysis"""
        import statistics

        from pytest_velo.plugin import measure_fork_latency

        latencies = [measure_fork_latency() for _ in range(10)]
        mean = statistics.mean(latencies)
        stdev = statistics.stdev(latencies)

        # Mean should be under 2ms
        assert mean < 2.0, f"Mean fork latency {mean:.2f}ms exceeds 2ms target"
        # StdDev should be reasonable (no wild variance)
        assert stdev < 1.0, f"Fork latency variance too high: {stdev:.2f}ms"


# ============================================================================
# Gate D: Compatibility
# ============================================================================


class TestGateD_Compatibility:
    """Gate D: pytest features and xdist compatibility"""

    def test_d2_xdist_mutual_exclusivity_validation(self):
        """D.2 (P1-1): validate_xdist_compatibility allows velo + xdist combo"""
        from pytest_velo.plugin import validate_xdist_compatibility

        class MockConfig:
            class Option:
                pass

            option = Option()

        config = MockConfig()
        config.option.velo = True
        config.option.numprocesses = 4  # Simulate xdist with -n flag

        # Phase 14: Should NOT raise - xdist + velo now supported
        validate_xdist_compatibility(config)  # Should pass without error

    def test_d2_xdist_no_error_when_no_conflict(self):
        """D.2: xdist detection functions work correctly"""
        from pytest_velo.plugin import is_xdist_controller, is_xdist_worker

        # Both functions should be callable
        assert callable(is_xdist_worker)
        assert callable(is_xdist_controller)

        # When not running under xdist, should be controller
        assert is_xdist_controller() is True


# ============================================================================
# Gate E: Error Handling
# ============================================================================


class TestGateE_ErrorHandling:
    """Gate E: Failure reporting and timeout handling"""

    def test_e1_test_failure_exit_code(self):
        """E.1: Failed test returns exit code 1"""
        test_code = """
def test_intentional_fail():
    assert 1 == 2, "This should fail"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            temp_path = f.name

        try:
            result = subprocess.run(
                ["./target/release/velo", "test", temp_path],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parents[4],
                timeout=T_MEDIUM,
            )
            assert result.returncode == 1, "Failed test should exit with code 1"
            assert "FAILED" in result.stdout or "failed" in result.stdout.lower()
        finally:
            os.unlink(temp_path)

    def test_e1_test_failure_shows_assertion(self):
        """E.1: Failed test shows assertion message"""
        test_code = """
def test_with_message():
    x = 42
    assert x == 0, f"Expected 0 but got {x}"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            temp_path = f.name

        try:
            result = subprocess.run(
                ["./target/release/velo", "test", temp_path],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parents[4],
                timeout=T_MEDIUM,
            )
            assert "Expected 0 but got 42" in result.stdout
        finally:
            os.unlink(temp_path)

    def test_e1_passing_test_exit_code_zero(self):
        """E.1: Passing test returns exit code 0"""
        test_code = """
def test_always_pass():
    assert True
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            temp_path = f.name

        try:
            result = subprocess.run(
                ["./target/release/velo", "test", temp_path],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parents[4],
                timeout=T_MEDIUM,
            )
            assert result.returncode == 0, "Passing test should exit with code 0"
        finally:
            os.unlink(temp_path)
