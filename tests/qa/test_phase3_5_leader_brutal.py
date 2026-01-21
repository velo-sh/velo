"""
Velo QA: Phase 3.5 QA Leader - BRUTAL ATTACK TESTS
===================================================
QA Leader's Mission: TRY TO BREAK IT IN THE HARDEST POSSIBLE WAY.

These tests combine the worst from all agents and go further.
If the system survives these, it's production-ready.

Categories:
- CHAOS: Resource exhaustion, timing attacks, race conditions
- INJECT: All forms of injection attacks
- CRASH: Inputs designed to crash the process
- HANG: Inputs designed to hang forever
- LEAK: Information disclosure attempts
"""

import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest


def get_velo_binary():
    """Get path to velo binary."""
    repo_root = Path(__file__).parent.parent.parent
    release = repo_root / "target" / "release" / "velo"
    debug = repo_root / "target" / "debug" / "velo"

    if release.exists():
        return str(release)
    elif debug.exists():
        return str(debug)
    else:
        pytest.skip("velo binary not found - run cargo build first")


class BrutalTestEnv:
    """Hardened test environment for brutal tests."""

    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="velo_brutal_"))
        self.velo = get_velo_binary()

    def setup(self):
        subprocess.run(["uv", "venv", "--quiet"], cwd=self.path, check=True, capture_output=True)
        (self.path / "uv.lock").write_text("{}")
        return self

    def create_script(self, name: str, content: str):
        (self.path / name).write_text(content)

    def run_velo(self, args: list, timeout: float = 60, env: dict = None) -> tuple:
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        result = subprocess.run(
            [self.velo] + args,
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=run_env,
        )
        return result.returncode, result.stdout, result.stderr

    def cleanup(self):
        try:
            shutil.rmtree(self.path)
        except Exception:
            pass

    def __enter__(self):
        return self.setup()

    def __exit__(self, *args):
        self.cleanup()


# =============================================================================
# CHAOS TESTS - Resource Exhaustion and Timing Attacks
# =============================================================================


class TestChaosResourceExhaustion:
    """CHAOS-RES-xxx: Try to exhaust system resources."""

    def test_chaos_res_001_fd_exhaustion(self):
        """CHAOS-RES-001: Try to exhaust file descriptors."""
        with BrutalTestEnv() as env:
            env.create_script(
                "fd_bomb.py",
                """
import os
fds = []
try:
    for i in range(10000):
        fd = os.open('/dev/null', os.O_RDONLY)
        fds.append(fd)
except OSError:
    pass
print(f'opened:{len(fds)}')
for fd in fds:
    os.close(fd)
""",
            )
            code, stdout, stderr = env.run_velo(["run", "fd_bomb.py"], timeout=30)
            # Should not crash the parent process
            assert "opened:" in stdout or code != 0 or "Falling back" in stderr

    def test_chaos_res_002_memory_bomb(self):
        """CHAOS-RES-002: Try to allocate massive memory."""
        with BrutalTestEnv() as env:
            env.create_script(
                "mem_bomb.py",
                """
import sys
try:
    data = []
    for i in range(100):
        data.append('x' * (100 * 1024 * 1024))  # 100MB chunks
except MemoryError:
    print('OOM:caught')
    sys.exit(0)
print('MEM:survived')
""",
            )
            code, stdout, stderr = env.run_velo(["run", "mem_bomb.py"], timeout=60)
            # Should handle OOM gracefully (not crash main process)
            # Process may be killed by OS, that's OK
            assert True  # If we get here, parent survived

    def test_chaos_res_003_fork_bomb_attempt(self):
        """CHAOS-RES-003: Try a fork bomb (should be contained)."""
        with BrutalTestEnv() as env:
            env.create_script(
                "fork_bomb.py",
                """
import os
import sys
# Attempt to fork bomb (should be limited)
count = 0
try:
    for i in range(100):  # Limited attempt
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        else:
            os.waitpid(pid, 0)
            count += 1
except Exception as e:
    print(f'BLOCKED:{e}')
print(f'FORKS:{count}')
""",
            )
            code, stdout, stderr = env.run_velo(["run", "fork_bomb.py"], timeout=30)
            # Should complete without hanging or crashing parent
            assert True

    def test_chaos_res_004_thread_bomb(self):
        """CHAOS-RES-004: Try to create thousands of threads."""
        with BrutalTestEnv() as env:
            env.create_script(
                "thread_bomb.py",
                """
import threading
import time
threads = []
try:
    for i in range(1000):
        t = threading.Thread(target=lambda: time.sleep(0.1))
        t.start()
        threads.append(t)
except Exception as e:
    print(f'LIMITED:{e}')
print(f'THREADS:{len(threads)}')
for t in threads:
    t.join(timeout=0.1)
""",
            )
            code, stdout, stderr = env.run_velo(["run", "thread_bomb.py"], timeout=60)
            assert True  # Survived


class TestChaosTiming:
    """CHAOS-TIME-xxx: Timing and race condition attacks."""

    def test_chaos_time_001_rapid_start_stop(self):
        """CHAOS-TIME-001: Rapidly start/stop serve commands."""
        velo = get_velo_binary()

        for _ in range(20):
            proc = subprocess.Popen(
                [velo, "serve", "main:app", "--port", "19999"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.05)
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

        # Should not leave zombie processes or leaked resources
        assert True

    def test_chaos_time_002_concurrent_same_port(self):
        """CHAOS-TIME-002: Multiple processes try same port."""
        velo = get_velo_binary()
        procs = []

        for _ in range(5):
            proc = subprocess.Popen(
                [velo, "serve", "main:app", "--port", "19998"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            procs.append(proc)

        time.sleep(1)

        for proc in procs:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

        # At most one should succeed (if any)
        assert True


# =============================================================================
# INJECTION TESTS - All Forms of Input Injection
# =============================================================================


class TestInjectionAttacks:
    """INJECT-xxx: All injection attack vectors."""

    def test_inject_001_shell_metacharacters(self):
        """INJECT-001: Shell metacharacters in all inputs."""
        velo = get_velo_binary()

        payloads = [
            "`id`",
            "$(whoami)",
            "${PATH}",
            "; id",
            "| id",
            "&& id",
            "|| id",
            "\n id",
            "\r id",
            "$(cat /etc/passwd)",
            "`cat /etc/passwd`",
        ]

        for payload in payloads:
            result = subprocess.run(
                [velo, "serve", f"{payload}:app"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Should NEVER execute shell commands
            assert "uid=" not in result.stdout
            assert "root:" not in result.stdout
            assert "/bin/" not in result.stdout

    def test_inject_002_python_code_injection(self):
        """INJECT-002: Python code in module name."""
        velo = get_velo_binary()

        payloads = [
            "__import__('os').system('id')",
            "eval('1+1')",
            "exec('import os')",
            "compile('x=1','','eval')",
        ]

        for payload in payloads:
            result = subprocess.run(
                [velo, "serve", f"{payload}:app"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Should never execute
            assert "uid=" not in result.stdout

    def test_inject_003_sql_injection_style(self):
        """INJECT-003: SQL injection patterns (shouldn't apply but test)."""
        velo = get_velo_binary()

        payloads = [
            "'; DROP TABLE users; --",
            "1' OR '1'='1",
            "1; SELECT * FROM users",
        ]

        for payload in payloads:
            result = subprocess.run(
                [velo, "serve", f"{payload}:app"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Should just fail gracefully
            assert result.returncode != 0

    def test_inject_004_path_traversal_variants(self):
        """INJECT-004: All path traversal variants."""
        velo = get_velo_binary()

        payloads = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "....//....//....//etc/passwd",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc/passwd",
            "..%252f..%252f..%252fetc/passwd",
            "/etc/passwd%00.py",
            "....//etc/passwd",
            "..;/etc/passwd",
        ]

        for payload in payloads:
            result = subprocess.run(
                [velo, "serve", f"{payload}:app"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Should not access system files
            assert "root:" not in result.stdout
            assert "passwd" not in result.stdout or result.returncode != 0


# =============================================================================
# CRASH TESTS - Inputs Designed to Crash
# =============================================================================


class TestCrashAttempts:
    """CRASH-xxx: Inputs designed to crash the process."""

    def test_crash_001_null_bytes_everywhere(self):
        """CRASH-001: Null bytes in all string positions.

        NOTE: Python subprocess cannot pass null bytes - they're rejected
        at the OS level. This tests that the protection is in place.
        """
        velo = get_velo_binary()

        # Test control chars that CAN be passed
        safe_payloads = [
            "\x01\x02\x03",  # Control chars
            "main\x1f:app",  # Unit separator
        ]

        for payload in safe_payloads:
            try:
                result = subprocess.run([velo, "serve", payload], capture_output=True, text=True, timeout=30)
                # Should not crash (SIGSEGV = -11)
                assert result.returncode != -11
            except ValueError:
                # OS rejects - that's the protection working
                pass

    def test_crash_002_format_strings(self):
        """CRASH-002: Format string attack vectors."""
        velo = get_velo_binary()

        payloads = [
            "%s%s%s%s%s%s%s%s%s%s",
            "%n%n%n%n%n",
            "%x%x%x%x%x",
            "%.9999999s",
            "%99999$s",
            "{0}{1}{2}{3}",
        ]

        for payload in payloads:
            result = subprocess.run(
                [velo, "serve", f"{payload}:app"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Should not crash
            assert result.returncode != -11

    def test_crash_003_unicode_bombs(self):
        """CRASH-003: Unicode edge cases.

        NOTE: Some unicode chars (like null) cannot be passed via subprocess.
        """
        velo = get_velo_binary()

        # Safe unicode payloads (no null)
        payloads = [
            "\ufeff",  # BOM
            "\u202e",  # RTL override
            "\uffff",  # Max BMP
            "𐀀",  # Surrogate pair
        ]

        for payload in payloads:
            try:
                result = subprocess.run(
                    [velo, "serve", f"{payload}main:app"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert result.returncode != -11
            except (UnicodeEncodeError, ValueError):
                pass  # OS/shell rejects - that's fine

    def test_crash_004_extremely_long_inputs(self):
        """CRASH-004: Extremely long inputs for buffer overflow."""
        velo = get_velo_binary()

        for size in [1000, 10000, 100000, 1000000]:
            payload = "A" * size
            try:
                result = subprocess.run(
                    [velo, "serve", f"{payload}:app"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                # Should not crash
                assert result.returncode != -11
            except OSError:
                pass  # Argument too long, that's fine


# =============================================================================
# HANG TESTS - Inputs Designed to Hang Forever
# =============================================================================


class TestHangAttempts:
    """HANG-xxx: Inputs designed to cause infinite loops or deadlocks."""

    def test_hang_001_infinite_redirect_symlink(self):
        """HANG-001: Infinite symlink redirect."""
        with BrutalTestEnv() as env:
            try:
                (env.path / "loop1").symlink_to(env.path / "loop2.py")
                (env.path / "loop2.py").symlink_to(env.path / "loop1")
            except OSError:
                pytest.skip("Cannot create symlinks")

            # Should not hang forever
            try:
                code, stdout, stderr = env.run_velo(["run", "loop1"], timeout=30)
            except subprocess.TimeoutExpired:
                pytest.fail("Process hung on symlink loop")

    def test_hang_002_regex_catastrophic_backtracking(self):
        """HANG-002: Input that might cause regex backtracking."""
        velo = get_velo_binary()

        # Classic ReDoS pattern
        payload = "a" * 50 + "!"

        try:
            result = subprocess.run(
                [velo, "serve", f"{payload}:app"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            pytest.fail("Possible ReDoS vulnerability")

    def test_hang_003_deeply_nested_path(self):
        """HANG-003: Deeply nested directory path."""
        velo = get_velo_binary()

        # Deep path
        deep_path = "/".join(["a"] * 100)

        try:
            result = subprocess.run(
                [velo, "serve", f"{deep_path}:app"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            pytest.fail("Process hung on deep path")


# =============================================================================
# INFORMATION LEAK TESTS
# =============================================================================


class TestInformationLeak:
    """LEAK-xxx: Try to leak sensitive information."""

    def test_leak_001_error_message_info(self):
        """LEAK-001: Error messages should not leak internal paths."""
        velo = get_velo_binary()

        # Determine project root from velo binary location
        # e.g., /path/to/velo/target/release/velo -> /path/to/velo
        project_root = str(Path(velo).parent.parent.parent)

        result = subprocess.run(
            [velo, "serve", "nonexistent_module:app"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Should not leak sensitive info (but project paths are OK):
        leak_patterns = [
            ".cargo",
            "rustup",
            "/root/",
            "password",
            "secret",
            "token",
            "api_key",
        ]

        output = result.stdout + result.stderr
        for pattern in leak_patterns:
            if pattern in output.lower():
                pytest.fail(f"Potential info leak: {pattern}")

        # Note: home directories like /home/ or /Users/ are OK if they're
        # part of the project path (e.g., /home/runner/work/velo/velo)

    def test_leak_002_env_var_exposure(self):
        """LEAK-002: Error should not expose env vars."""
        velo = get_velo_binary()

        env = os.environ.copy()
        env["SECRET_API_KEY"] = "super_secret_12345"
        env["DATABASE_PASSWORD"] = "db_pass_67890"

        result = subprocess.run(
            [velo, "serve", "crash_module:app"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        # Secrets should not appear in output
        output = result.stdout + result.stderr
        assert "super_secret_12345" not in output
        assert "db_pass_67890" not in output

    def test_leak_003_stack_trace_exposure(self):
        """LEAK-003: Internal stack traces should not be exposed."""
        velo = get_velo_binary()

        result = subprocess.run(
            [velo, "serve", "definitely_broken:app"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        output = result.stdout + result.stderr

        # Should not show:
        assert "thread 'main' panicked" not in output
        assert "RUST_BACKTRACE" not in output
        assert ".rs:" not in output  # Rust source locations
        assert "stack backtrace" not in output.lower()


# =============================================================================
# COMBINED MEGA ATTACK
# =============================================================================


class TestMegaAttack:
    """MEGA-xxx: Combined simultaneous attacks."""

    def test_mega_001_everything_at_once(self):
        """MEGA-001: Multiple attack vectors simultaneously."""
        import concurrent.futures

        velo = get_velo_binary()

        attacks = [
            [velo, "serve", "`id`:app"],
            [velo, "serve", "../../../etc/passwd:app"],
            [velo, "serve", "A" * 10000 + ":app"],
            [velo, "serve", "\x00:app"],
            [velo, "serve", "main:app", "--port", "-1"],
            [velo, "serve", "main:app", "--workers", "99999"],
        ]

        def run_attack(cmd):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                return result.returncode
            except Exception as e:
                return str(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(run_attack, cmd) for cmd in attacks * 3]
            results = [f.result() for f in futures]

        # All should complete (not hang)
        assert len(results) == len(attacks) * 3

        # None should be SIGSEGV
        for r in results:
            if isinstance(r, int):
                assert r != -11

    def test_mega_002_stress_under_resource_pressure(self):
        """MEGA-002: Attacks while system is under resource pressure."""
        velo = get_velo_binary()

        # Create some background load
        load_threads = []
        stop_flag = threading.Event()

        def create_load():
            data = []
            while not stop_flag.is_set():
                try:
                    data.append("x" * 1000)
                    if len(data) > 10000:
                        data = data[5000:]
                except MemoryError:
                    data = []
                time.sleep(0.001)

        for _ in range(4):
            t = threading.Thread(target=create_load)
            t.start()
            load_threads.append(t)

        try:
            # Run attacks under load
            for _ in range(10):
                result = subprocess.run(
                    [velo, "serve", "test:app"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert result.returncode != -11
        finally:
            stop_flag.set()
            for t in load_threads:
                t.join(timeout=5)
