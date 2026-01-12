import os
import pytest
import subprocess
import signal
import time
import psutil
import socket
from pathlib import Path

# CI Timeout Multiplier (RFC-0012)
TIMEOUT_MULTIPLIER = float(os.environ.get("VELO_TIMEOUT_MULTIPLIER", "1.0"))

def scaled_timeout(base: float) -> float:
    """Apply CI timeout multiplier to base timeout."""
    return base * TIMEOUT_MULTIPLIER

# QA Agent B: Hardened Stability & Platform Parity
# Requirements: RFC-0010 §4.1, §4.4, §4.6, §4.9


@pytest.mark.tier1
class TestPhase61StabilityHardened:
    def test_stab_rs_003_raii_cleanup(self, isolated_env):
        """
        RS-P0-003: RAII Child Cleanup (Drop)
        Goal: Verify child process is killed when parent exits/panics.
        """
        env = isolated_env
        env.create_app("main.py", "app = lambda s, r, se: None\nprint('READY')")

        port = env.next_port()

        # Start velo serve in a new process group
        proc = env.spawn_velo(
            "serve",
            "main:app",
            "--bind",
            f"127.0.0.1:{port}",
            "--timeout",
            "5",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )

        # Wait longer for debug build
        time.sleep(10)
        parent_pid = proc.pid

        # Find child (uvicorn/gunicorn)
        try:
            p = psutil.Process(parent_pid)
            children = p.children(recursive=True)
            if not children:
                # Still no children? Try one more short wait
                time.sleep(5)
                children = p.children(recursive=True)
        except psutil.NoSuchProcess as err:
            stdout, stderr = proc.communicate()
            raise RuntimeError(
                f"Velo exited prematurely.\nSTDOUT: {stdout}\nSTDERR: {stderr}"
            ) from err

        assert (
            len(children) >= 1
        ), f"No child processes detected after 15s.\nSTDOUT: {proc.stdout.read() if proc.stdout else ''}"
        child_pid = children[0].pid

        # Terminate parent (causes graceful exit where Drop can run)
        # Note: kill() sends SIGKILL which doesn't give Rust Drop a chance to run
        proc.terminate()  # SIGTERM allows cleanup
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            # In container environments, SIGTERM may be slow; force kill and still verify cleanup
            proc.kill()
            proc.wait(timeout=5)

        # Requirement: Child MUST be reaped (either by SIGTERM or SIGKILL enforced Drop)
        time.sleep(2)
        assert not psutil.pid_exists(child_pid)

    def _read_with_timeout(self, stream, timeout=5):
        import select

        start_time = time.time()
        while time.time() - start_time < timeout:
            r, _, _ = select.select([stream], [], [], 0.1)
            if r:
                line = stream.readline()
                if line:
                    return line
        return None

    def _read_until(self, stream, pattern, timeout=15) -> str:
        import select

        output = ""
        start_time = time.time()
        while time.time() - start_time < timeout:
            r, _, _ = select.select([stream], [], [], 0.1)
            if r:
                line = stream.readline()
                if not line:
                    break
                output += line
                if pattern in line:
                    return output
        return output

    def test_stab_rs_002_watcher_debounce(self, isolated_env):
        """
        ENG-P0-002: 300ms Watcher Debounce
        Goal: Rapid file events should trigger only one restart.
        """
        env = isolated_env
        env.create_app(
            "main.py",
            "app = lambda s, r, se: None\nimport time\nprint(f'START_{time.time()}')",
        )

        port = env.next_port()

        proc = env.spawn_velo(
            "serve",
            "main:app",
            "--reload",
            "--bind",
            f"127.0.0.1:{port}",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )

        # Wait for first start (until first START_)
        self._read_until(proc.stdout, "START_", timeout=15)
        start_count = 1  # We just found it

        # Blast 100 events in 200ms
        for _ in range(100):
            (env.path / "main.py").touch()
            time.sleep(0.002)

        # Wait and see how many starts
        time.sleep(2)
        while True:
            line = self._read_with_timeout(proc.stdout, timeout=1)
            if not line:
                break
            if "START_" in line:
                start_count += 1

        # Debounce should have merged these into 1 or maybe 2 restarts max
        # (depending on timing exactness)
        assert start_count <= 2
        proc.kill()

    @pytest.mark.xfail(
        os.environ.get("GITHUB_ACTIONS") == "true",
        reason="File watcher on CI may use poll mode without inotify support",
    )
    def test_stab_rs_002_starvation_vulnerability(self, isolated_env):
        """
        A-EDGE-6.1-001: Debouncer Starvation (Agent A Finding)
        Requirement: Debouncer MUST have a hard-cap (e.g. 2s) to prevent starvation.
        Goal: Continuous events for 3s should still trigger at least one restart.
        """
        env = isolated_env
        env.create_app(
            "main.py",
            "app = lambda s, r, se: None\nimport time\nprint(f'START_{time.time()}', flush=True)",
        )

        port = env.next_port()

        proc = env.spawn_velo(
            "serve",
            "main:app",
            "--reload",
            "--bind",
            f"127.0.0.1:{port}",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # Wait for first start (drain everything until first START_)
        prefix = self._read_until(proc.stdout, "START_", timeout=20)
        assert (
            "START_" in prefix
        ), f"Server failed to start the first time.\nLOGS: {prefix}"

        # DRAIN any remaining startup logs to avoid false positives in second phase
        time.sleep(2)
        while True:
            line = self._read_with_timeout(proc.stdout, timeout=0.5)
            if not line:
                break
            prefix += line

        # Continuous events every 200ms for 3 seconds ( > default 300ms debounce)
        start_trigger = time.time()
        while time.time() - start_trigger < 3:
            (env.path / "main.py").touch()
            time.sleep(0.2)

        # If implementation is vulnerable, it will NEVER restart during these 3s.
        # Requirement: It MUST restart at least once due to a hard-cap.
        # Wait for the restart's START_ marker.
        # Debug build is slow, give it 30s to finish the restart cycles.
        output = self._read_until(proc.stdout, "START_", timeout=30)

        # Kill immediately to release port
        proc.kill()

        assert (
            "START_" in output
        ), f"Vulnerability Detected: Debouncer Starvation (restart never triggered during continuous events).\nFull Trace: {prefix}\nNew Logs: {output}"

    def test_stab_deadlock_pipe_saturation(self, isolated_env):
        """
        B-STAB-6.1-001: Subprocess Pipe Deadlock
        Goal: Parent MUST NOT deadlock when child produces massive output.
        """
        env = isolated_env
        # App that writes 1MB of text and then exits
        env.create_app(
            "main.py",
            "import sys\nfor i in range(10000):\n    print('X' * 100)\nsys.exit(0)",
        )

        # This will time out if Velo deadlocks on pipe read
        result = env.run_velo("run", "main.py", timeout=10)
        assert result.returncode == 0

    @pytest.mark.skipif(
        os.name != "posix", reason="SIGTERM forwarding is Unix-specific"
    )
    def test_stab_cn_002_sigterm_forwarding(self, isolated_env):
        """
        CN-P0-002: SIGTERM Forwarding
        Goal: Velo forwards SIGTERM to child and waits for graceful exit.
        """
        env = isolated_env
        env.create_app(
            "main.py",
            """
app = lambda s, r, se: None
import signal, time, sys
def handler(sig, frame):
    print("CHILD_RECEIVED_SIGTERM")
    time.sleep(1)
    sys.exit(0)
signal.signal(signal.SIGTERM, handler)
print("CHILD_READY")
time.sleep(60)
""",
        )

        port = env.next_port()

        proc = env.spawn_velo(
            "serve",
            "main:app",
            "--bind",
            f"127.0.0.1:{port}",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Wait for child ready
        while "CHILD_READY" not in proc.stdout.readline():
            pass

        # Sent SIGTERM to Velo
        proc.terminate()

        # Verify child received it
        output = ""
        while True:
            line = self._read_with_timeout(proc.stdout, timeout=scaled_timeout(10))
            if not line:
                break
            output += line
            if "CHILD_RECEIVED_SIGTERM" in line:
                break

        assert "CHILD_RECEIVED_SIGTERM" in output, f"SIGTERM not forwarded. Output: {output[:500]}"
        proc.wait(timeout=scaled_timeout(15))

    def test_stab_zombie_orphan_leak(self, isolated_env):
        """
        D-CHAO-6.1-002: Zombie/Orphan Leak (Agent D Finding)
        Goal: Verify no orphan/zombie processes after graceful shutdown (SIGTERM).

        This test verifies that when Velo receives SIGTERM and performs graceful shutdown,
        all child processes (including uvicorn workers) are properly cleaned up.
        """
        env = isolated_env
        env.create_app("main.py", "app = lambda s, r, se: None\nprint('READY')")

        # Use ephemeral port (0) to avoid conflicts
        # We don't need to connect, only verify lifecycle
        port = env.next_port()

        # Start server in new session
        # Use --timeout 5 for fast graceful shutdown in tests
        proc = env.spawn_velo(
            "serve",
            "main:app",
            "--bind",
            f"127.0.0.1:{port}",
            "--timeout",
            "5",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )

        time.sleep(3)
        parent_pid = proc.pid
        children = psutil.Process(parent_pid).children(recursive=True)
        assert len(children) >= 1, "Expected at least one child process (server worker)"
        child_pids = [c.pid for c in children]

        # Graceful shutdown with SIGTERM (allows Drop to run)
        # NOTE: Use os.kill() directly instead of proc.terminate() because
        # eventlet monkey-patches subprocess and its terminate() doesn't work properly
        os.kill(parent_pid, signal.SIGTERM)

        # Wait for process to exit (allow time for graceful shutdown + force kill)
        for _ in range(15):
            if proc.poll() is not None:
                break
            time.sleep(1)
        else:
            # Force kill if still running
            os.killpg(parent_pid, signal.SIGKILL)
            pytest.fail("Velo did not exit within 15s after SIGTERM")

        time.sleep(2)
        # Requirement: All child processes MUST be cleaned up
        for child_pid in child_pids:
            assert not psutil.pid_exists(
                child_pid
            ), f"Leak Detected: Child process {child_pid} survived graceful shutdown"

    @pytest.mark.xfail(
        os.environ.get("GITHUB_ACTIONS") == "true"
        or os.path.exists("/.dockerenv")
        or (
            Path("/proc/1/cgroup").exists()
            and "docker" in Path("/proc/1/cgroup").read_text()
        ),
        reason="File watcher race test is environment-sensitive (poll mode in containers, timing variance in CI)",
    )
    def test_stab_large_file_write_race(self, isolated_env):
        """
        D-CHAO-6.1-003: Large File Write Race (Agent D Finding)
        Goal: Watcher should NOT trigger restart until file write is complete/stable.
        """
        env = isolated_env
        env.create_app("main.py", "app = lambda s, r, se: None\nprint('READY')")

        port = env.next_port()

        proc = env.spawn_velo(
            "serve",
            "main:app",
            "--reload",
            "--bind",
            f"127.0.0.1:{port}",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Wait for ready
        line_count = 0
        while line_count < 10:
            line = proc.stdout.readline()
            if "READY" in line:
                break
            line_count += 1

        # Write 5MB file slowly (1MB chunks every 200ms)
        app_file = env.path / "main.py"
        with open(app_file, "w") as f:
            for i in range(5):
                # Write 1MB comment block + a few prints to reach 5MB total
                f.write(f"# {'x' * 1_000_000}\n")
                f.write("print('LOADING')\n")
                f.flush()
                os.fsync(f.fileno())
                time.sleep(0.5)
            f.write("print('FINAL_READY')\n")

        # Requirement: It should only restart once or twice, not for every chunk.
        # And specifically, it should eventually reach FINAL_READY.
        output = ""
        try:
            while True:
                line = self._read_with_timeout(proc.stdout, timeout=15)
                if not line:
                    break
                output += line
        finally:
            proc.kill()

        assert "FINAL_READY" in output
        # If it triggers too early, it might fail to import or show partial code errors
        assert (
            "SyntaxError" not in output
        ), "Race Detected: Watcher triggered on partially written file"


    @pytest.mark.xfail(
        os.environ.get(\"GITHUB_ACTIONS\") == \"true\",
        reason=\"File watcher on CI uses poll mode without inotify support; starvation behavior differs\",
    )
    def test_stab_rs_002_starvation_hard_cap(self, isolated_env):

        """
        STB-RS-002 (Hard-Cap): Continuous events MUST trigger a restart after hard-cap (max 5s).
        Proves: Watcher does not reset debouncer indefinitely (Starvation).
        """
        env = isolated_env
        app_code = """
import os
import time
print(f"START_{os.getpid()}", flush=True)
app = lambda s, r, se: None
"""
        app_file = env.path / "main.py"
        app_file.write_text(app_code)

        port = env.next_port()

        # Start server
        proc = env.spawn_velo(
            "serve",
            "main:app",
            "--reload",
            "--port",
            str(port),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        try:
            # Wait for first start
            time.sleep(2)
            # Continuous events every 150ms for 4 seconds
            # Debounce delay is 300ms. If we send events every 150ms, it should NEVER restart
            # unless a hard-cap (of say 2s or 5s) is implemented.
            for i in range(30):
                with open(app_file, "a") as f:
                    f.write(f"\n# event {i}")
                time.sleep(0.15)

            # Now wait a bit for any pending restart to complete
            time.sleep(2)

            # Kill and collect
            proc.terminate()
            out, err = proc.communicate(timeout=scaled_timeout(5))
            starts = out.count("START_")
            if starts < 2:
                print(f"DEBUG: Captured Output (stderr merged):\n{out}")
            # If starvation exists, starts will be 1 (the initial one).
            # If hard-cap exists, starts will be >= 2.
            assert (
                starts >= 2
            ), f"Starvation Detected: Only {starts} starts found after 4s of continuous events. Hard-cap missing in watcher.rs."
        except Exception:
            proc.kill()
            raise
        finally:
            if proc.poll() is None:
                proc.kill()


# =============================================================================
# REGRESSION TESTS - Solidify Bug Fixes (2026-01-04)
# =============================================================================


@pytest.mark.tier1
class TestRegressionBugFixes:
    """
    Regression tests for bugs fixed on 2026-01-04.
    These tests ensure the bugs don't resurface.
    """

    def test_reg_001_exit_on_child_failure_without_reload(self, isolated_env):
        """
        BUG-6.1-001: velo serve hangs on child failure when --reload is not enabled.

        Root cause: When uvicorn exits with error (e.g., module not found),
        velo would 'continue' waiting for reload signal even without --reload.

        Fix: Return error immediately when child fails and --reload is not enabled.
        Commit: af815a2
        """
        env = isolated_env
        # No main.py - module doesn't exist

        import time

        start = time.perf_counter()

        result = subprocess.run(
            [env.velo, "serve", "nonexistent_module:app"],
            cwd=env.path,
            capture_output=True,
            text=True,
            timeout=10,  # Should exit well before this
        )

        elapsed = time.perf_counter() - start

        # Must exit with error code
        assert result.returncode != 0, "Should exit with error when module not found"
        # Must exit quickly (not hang for 30s)
        assert elapsed < 5, f"Should exit in <5s, but took {elapsed:.1f}s (hanging bug)"
        # Should have helpful error message (either old uvicorn message or new early validation)
        combined = result.stdout + result.stderr
        assert (
            "Could not import" in combined
            or "exited with code" in combined
            or "not found" in combined  # New early module validation (SEC-P0-006)
        )

    def test_reg_002_process_group_cleanup_kills_workers(self, isolated_env):
        """
        BUG-6.1-002: Drop only killed direct child, not process group.

        Root cause: ManagedChild::drop() called self.child.kill() which only kills
        the direct child (uvicorn main process), not workers in the same process group.

        Fix: Use kill(-pgid, SIGKILL) to kill entire process group in Drop.
        Commit: c915723
        """
        env = isolated_env
        env.create_app("main.py", "app = lambda s, r, se: None\nprint('READY')")

        port = env.next_port()

        proc = env.spawn_velo(
            "serve",
            "main:app",
            "--bind",
            f"127.0.0.1:{port}",
            "--timeout",
            "5",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )

        time.sleep(10)
        parent_pid = proc.pid

        # Find ALL children (uvicorn + workers)
        try:
            children = psutil.Process(parent_pid).children(recursive=True)
        except psutil.NoSuchProcess as err:
            stdout, _ = proc.communicate()
            raise RuntimeError(f"Velo exited prematurely.\nLOGS: {stdout}") from err

        assert len(children) >= 1, "Expected at least one child process"
        child_pids = [c.pid for c in children]

        # Send SIGTERM (graceful shutdown - allows Drop to run)
        os.kill(parent_pid, signal.SIGTERM)

        # Wait for exit
        for _ in range(15):
            if proc.poll() is not None:
                break
            time.sleep(1)
        else:
            os.killpg(parent_pid, signal.SIGKILL)
            pytest.fail("Velo did not exit within 15s after SIGTERM")

        time.sleep(2)

        # ALL children must be cleaned up (not just direct child)
        for child_pid in child_pids:
            assert not psutil.pid_exists(
                child_pid
            ), f"Leak Detected: Child {child_pid} survived graceful shutdown (process group not killed)"

    def test_reg_003_partial_import_capture_on_crash(self, isolated_env):
        """
        BUG-6.1-003: velo analyze returns empty table when script crashes on import.

        Root cause: sitecustomize.py only used atexit which doesn't run on crash.
        When script fails to import a module (e.g., ModuleNotFoundError), atexit
        callbacks are never called, so profile data is never written.

        Fix: Added sys.excepthook handler to write profile data before exception propagates.
        Commit: ce4200b
        """
        env = isolated_env

        # Script that imports something (captures time) then crashes on missing module
        env.create_app(
            "crash_test.py",
            """
import json  # This should be captured
import nonexistent_pandas  # This will crash
print("OK")
""",
        )

        result = subprocess.run(
            [env.velo, "analyze", "crash_test.py"],
            cwd=env.path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Command may fail (due to import crash), but output should NOT be empty
        output = result.stdout.lower()

        # MUST have captured the successful import (json) before crash
        # The table should show json import time, not be completely empty
        has_timing = "ms" in output
        has_import = "json" in output

        assert (
            has_timing or has_import
        ), f"Partial imports not captured on crash. Output:\n{result.stdout[:500]}"


if __name__ == "__main__":
    pytest.main([__file__])
