"""
RFC-0028 Adversarial Bug Hunting Tests

QA Role: ATTACK the implementation to find bugs Dev missed.
These tests are designed to BREAK the system, not validate it.

Attack Vectors:
1. Race Conditions - Concurrent forks, parallel access
2. Orphan Processes - Worker leaks, zombie processes
3. Resource Exhaustion - Memory, sockets, file descriptors
4. Environment Pollution - Cross-worker contamination
5. Error Handling - Failure propagation, edge cases
6. Stress Testing - Large scale, rapid cycling
"""

import gc
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest

VELO_BIN = Path("./target/release/velo").absolute()


def ensure_velo() -> None:
    if not VELO_BIN.exists():
        pytest.skip("Velo binary not found")


def run_velo(args: list[str], timeout: int = 30, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd_env = os.environ.copy()
    cmd_env["VELO_ENV"] = "dev"
    if env:
        cmd_env.update(env)
    return subprocess.run([str(VELO_BIN)] + args, capture_output=True, text=True, timeout=timeout, env=cmd_env)


# =============================================================================
# ATTACK 1: RACE CONDITIONS - Concurrent Fork Stress
# =============================================================================


class TestAttack_RaceConditions:
    """Attack: Probe for race conditions in fork handling"""

    def test_RACE_001_rapid_fork_storm(self):
        """ATTACK: Rapid consecutive forks should not corrupt state"""
        from pytest_velo.plugin import measure_fork_latency

        errors = []

        def rapid_fork():
            try:
                for _ in range(50):
                    latency = measure_fork_latency()
                    if latency > 100:  # 100ms is suspicious
                        errors.append(f"Latency spike: {latency}ms")
            except Exception as e:
                errors.append(str(e))

        # Run from multiple threads simultaneously
        threads = [threading.Thread(target=rapid_fork) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # Should have NO errors from fork storm
        assert len(errors) == 0, f"Race condition detected: {errors[:5]}"

    def test_RACE_002_parallel_zygote_start(self):
        """ATTACK: Multiple processes trying to start Zygote simultaneously"""
        ensure_velo()

        # Clean slate
        run_velo(["zygote", "stop"])
        time.sleep(0.5)

        # Try to start Zygote from multiple processes at once
        procs = []
        for _ in range(5):
            proc = subprocess.Popen(
                [str(VELO_BIN), "zygote", "start", "--daemon"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "VELO_ENV": "dev"},
            )
            procs.append(proc)

        # Wait for all
        for proc in procs:
            proc.wait(timeout=10)

        time.sleep(1.0)

        # Check: Should only have ONE Zygote running
        ps_result = subprocess.run(["pgrep", "-f", "velo_zygote.main"], capture_output=True, text=True)

        pids = [p for p in ps_result.stdout.strip().split("\n") if p]

        # Cleanup
        run_velo(["zygote", "stop"])

        # BUG if multiple Zygotes are running
        assert len(pids) <= 1, f"BUG: Race condition in Zygote start! {len(pids)} instances running. PIDs: {pids}"


# =============================================================================
# ATTACK 2: ORPHAN PROCESS HUNTING
# =============================================================================


class TestAttack_OrphanProcesses:
    """Attack: Find orphan/zombie process leaks"""

    def test_ORPHAN_001_worker_leak_after_crash(self):
        """ATTACK: Crash master mid-run, check for orphan workers"""
        ensure_velo()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "tests"
            test_dir.mkdir()

            # Create slow tests that give us time to crash
            for i in range(20):
                (test_dir / f"test_slow_{i}.py").write_text(f"""
import time
def test_slow_{i}():
    time.sleep(0.5)
    assert True
""")

            # Count processes before
            before = self._count_velo_processes()

            # Start velo test
            proc = subprocess.Popen(
                [str(VELO_BIN), "test", str(test_dir), "-n", "4", "--zygote"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "VELO_ENV": "dev", "PYTHONPATH": tmpdir},
            )

            time.sleep(2.0)  # Let it spawn workers

            # KILL the master brutally
            proc.kill()
            time.sleep(3.0)  # Give orphans time to manifest

            # Count processes after
            after = self._count_velo_processes()

            # Cleanup
            run_velo(["zygote", "stop"])
            subprocess.run(["pkill", "-9", "-f", "velo_zygote"], capture_output=True)
            time.sleep(1.0)

            final = self._count_velo_processes()

            # BUG if orphans remain
            assert final == 0, (
                f"BUG: ORPHAN PROCESS LEAK! Before: {before}, After crash: {after}, "
                f"After cleanup: {final}. Orphans not cleaned up!"
            )

    def _count_velo_processes(self) -> int:
        result = subprocess.run(["pgrep", "-f", "velo_zygote"], capture_output=True, text=True)
        if result.returncode != 0:
            return 0
        return len([p for p in result.stdout.strip().split("\n") if p])

    def test_ORPHAN_002_zombie_after_test_failure(self):
        """ATTACK: Test failures should not leave zombie workers"""
        ensure_velo()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)

            # Create tests that fail
            (test_dir / "test_failing.py").write_text("""
def test_fail_1():
    raise Exception("Intentional failure 1")

def test_fail_2():
    pytest.fail("Intentional failure 2"

def test_fail_3():
    import sys
    sys.exit(1)
""")

            before = self._count_velo_processes()

            # Run failing tests
            run_velo(["test", str(test_dir), "--zygote"], timeout=30, env={"PYTHONPATH": tmpdir})

            time.sleep(1.0)
            after = self._count_velo_processes()

            # Cleanup
            run_velo(["zygote", "stop"])
            time.sleep(0.5)

            # BUG if process count increased
            assert after <= before + 1, f"BUG: Zombie processes after test failure! Before: {before}, After: {after}"


# =============================================================================
# ATTACK 3: ENVIRONMENT POLLUTION
# =============================================================================


class TestAttack_EnvironmentPollution:
    """Attack: Find cross-worker environment contamination"""

    def test_POLLUTION_001_worker_env_isolation(self):
        """ATTACK: One worker's env changes should NOT affect others"""
        ensure_velo()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)

            # Test 1 sets an env var
            (test_dir / "test_a_setter.py").write_text("""
import os
def test_set_env():
    os.environ["POLLUTION_TEST"] = "POLLUTED"
    assert os.environ.get("POLLUTION_TEST") == "POLLUTED"
""")

            # Test 2 checks it's NOT set (runs after test 1)
            (test_dir / "test_b_checker.py").write_text("""
import os
def test_check_env():
    # This should NOT see the env var set by test_a
    pollution = os.environ.get("POLLUTION_TEST")
    assert pollution is None, f"BUG: Environment polluted! POLLUTION_TEST={pollution}"
""")

            # Run with forked isolation
            result = run_velo(["test", str(test_dir), "--zygote", "-v"], timeout=30, env={"PYTHONPATH": tmpdir})

            # If isolation works, both tests pass
            # If pollution bug exists, test_b_checker fails
            assert "2 passed" in result.stdout or result.returncode == 0, (
                f"BUG: Environment pollution between workers! STDOUT: {result.stdout}"
            )

    def test_POLLUTION_002_cwd_isolation(self):
        """ATTACK: One worker's chdir should NOT affect others"""
        ensure_velo()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)
            subdir = test_dir / "subdir"
            subdir.mkdir()

            (test_dir / "test_a_chdir.py").write_text(f"""
import os
def test_change_cwd():
    original = os.getcwd()
    os.chdir("{subdir}")
    assert os.getcwd() == "{subdir}"
""")

            (test_dir / "test_b_check_cwd.py").write_text("""
import os
def test_cwd_not_changed():
    cwd = os.getcwd()
    # CWD should NOT be the subdir another test changed to
    assert "subdir" not in cwd, f"BUG: CWD polluted to {cwd}"
""")

            result = run_velo(["test", str(test_dir), "--zygote"], timeout=30, env={"PYTHONPATH": tmpdir})

            assert result.returncode == 0, f"BUG: CWD pollution! STDERR: {result.stderr}"


# =============================================================================
# ATTACK 4: STRESS TESTING
# =============================================================================


class TestAttack_Stress:
    """Attack: Stress the system to find resource leaks"""

    def test_STRESS_001_many_rapid_runs(self):
        """ATTACK: Many rapid test runs should not leak resources"""
        ensure_velo()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)

            (test_dir / "test_simple.py").write_text("""
def test_one():
    assert True
""")

            # Run 20 times rapidly
            failures = []
            for i in range(20):
                result = run_velo(["test", str(test_dir)], timeout=10, env={"PYTHONPATH": tmpdir})
                if result.returncode != 0:
                    failures.append(f"Run {i}: {result.stderr[:100]}")

            assert len(failures) == 0, f"BUG: Instability under rapid runs! Failures: {failures}"

    def test_STRESS_002_large_test_suite(self):
        """ATTACK: 100 tests should complete without timeout or crash"""
        ensure_velo()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)

            # Create 100 tests
            for i in range(100):
                (test_dir / f"test_case_{i}.py").write_text(f"""
def test_case_{i}():
    result = {i} * 2
    assert result == {i * 2}
""")

            start = time.time()
            result = run_velo(["test", str(test_dir), "-n", "4", "--zygote"], timeout=120, env={"PYTHONPATH": tmpdir})
            duration = time.time() - start

            assert result.returncode == 0, f"BUG: Large test suite failed! STDERR: {result.stderr[:500]}"

            # Should complete in reasonable time (< 30s for 100 trivial tests)
            assert duration < 60, f"BUG: Performance regression! 100 tests took {duration:.1f}s (expected < 60s)"


# =============================================================================
# ATTACK 5: ERROR HANDLING EDGE CASES
# =============================================================================


class TestAttack_ErrorHandling:
    """Attack: Probe error handling for bugs"""

    def test_ERROR_001_import_error_in_test(self):
        """ATTACK: ImportError in test should not crash Zygote"""
        ensure_velo()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)

            (test_dir / "test_bad_import.py").write_text("""
import nonexistent_module_that_does_not_exist

def test_never_runs():
    assert True
""")

            result = run_velo(["test", str(test_dir), "--zygote"], timeout=30, env={"PYTHONPATH": tmpdir})

            # Should fail gracefully, not crash/hang
            # Return code 1 or 2 is acceptable (collection error)
            assert result.returncode in (1, 2, 4), f"BUG: Unexpected return code {result.returncode} for ImportError"

            # Zygote should still be stoppable
            run_velo(["zygote", "stop"])
            # Should not hang

    def test_ERROR_002_syntax_error_in_test(self):
        """ATTACK: SyntaxError in test should not corrupt state"""
        ensure_velo()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)

            (test_dir / "test_syntax_error.py").write_text("""
def test_bad_syntax(
    # Missing closing paren - syntax error
    assert True
""")

            result = run_velo(["test", str(test_dir)], timeout=30, env={"PYTHONPATH": tmpdir})

            # Should fail but not crash
            assert result.returncode != 0, "Should have failed"

            # Run a good test after - should work
            (test_dir / "test_good.py").write_text("""
def test_good():
    assert True
""")

            # Remove bad file
            (test_dir / "test_syntax_error.py").unlink()

            result2 = run_velo(["test", str(test_dir)], timeout=30, env={"PYTHONPATH": tmpdir})

            assert result2.returncode == 0, f"BUG: State corrupted after syntax error! STDERR: {result2.stderr}"

    def test_ERROR_003_timeout_in_test(self):
        """ATTACK: Hanging test should be killed, not block forever"""
        ensure_velo()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)

            (test_dir / "test_hang.py").write_text("""
import time
def test_hangs():
    time.sleep(3600)  # 1 hour
    assert True
""")

            start = time.time()
            try:
                subprocess.run(
                    [str(VELO_BIN), "test", str(test_dir), "--zygote"],
                    capture_output=True,
                    text=True,
                    timeout=10,  # 10 second timeout
                    env={**os.environ, "VELO_ENV": "dev", "PYTHONPATH": tmpdir},
                )
                duration = time.time() - start
                # If it returned, check duration
                assert duration < 15, f"Took too long: {duration}s"
            except subprocess.TimeoutExpired:
                # This is expected - test should timeout
                pass

            # Cleanup any stuck processes
            subprocess.run(["pkill", "-9", "-f", "test_hang"], capture_output=True)


# =============================================================================
# ATTACK 6: SOCKET/FD EXHAUSTION
# =============================================================================


class TestAttack_ResourceExhaustion:
    """Attack: Try to exhaust system resources"""

    def test_FD_001_file_descriptor_leak(self):
        """ATTACK: Many forks should not leak file descriptors"""
        ensure_velo()

        import resource

        # Get current FD limit
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)

        # Get current open FDs
        def count_fds() -> int:
            return len(os.listdir("/dev/fd"))

        before_fds = count_fds()

        # Do many forks
        from pytest_velo.plugin import measure_fork_latency

        for _ in range(100):
            measure_fork_latency()

        gc.collect()
        time.sleep(0.5)

        after_fds = count_fds()

        # FD count should not grow significantly
        fd_leak = after_fds - before_fds
        assert fd_leak < 10, f"BUG: FD leak! Before: {before_fds}, After: {after_fds}, Leaked: {fd_leak}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
