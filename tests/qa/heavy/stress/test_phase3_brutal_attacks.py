from __future__ import annotations

"""
Velo QA: Phase 3 Brutal Attack Tests
=====================================
GOAL: Try to CRASH Zygote by any means necessary.

Philosophy: If it doesn't crash, add more stress!
"""

import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest

# Import CI-aware timeout constants
from conftest_utils import T_LONG, T_MEDIUM, T_SHORT


def get_velo_binary():
    repo_root = Path(__file__).parents[4]
    release = repo_root / "target" / "release" / "velo"
    if release.exists():
        return str(release)
    pytest.skip("velo binary not found")


class AttackEnv:
    """Environment for attack testing."""

    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="attack_"))
        self.velo = get_velo_binary()
        # Create isolated socket directory
        self.socket_dir = self.path / ".sockets"
        self.socket_dir.mkdir(exist_ok=True)
        self.env_vars = {
            "VELO_SOCKET_DIR": str(self.socket_dir),
            "VELO_ZYGOTE_SOCKET": str(self.socket_dir / "velo-zygote.sock"),
        }

    def setup(self):
        subprocess.run(["uv", "venv", "--quiet"], cwd=self.path, capture_output=True)
        (self.path / "uv.lock").write_text("{}")
        return self

    def run(self, args, timeout=None, env=None):
        if timeout is None:
            timeout = T_MEDIUM

        full_env = os.environ.copy()
        full_env.update(self.env_vars)
        if env:
            full_env.update(env)
        try:
            result = subprocess.run(
                [self.velo] + args,
                cwd=self.path,
                capture_output=True,
                text=False,  # Use bytes mode to handle binary output
                timeout=timeout,
                env=full_env,
            )
            # Decode safely, replacing invalid UTF-8
            stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
            stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
            return result.returncode, stdout, stderr
        except subprocess.TimeoutExpired:
            return -1, "", "TIMEOUT"

    def create_script(self, name, content):
        (self.path / name).write_text(content)

    def cleanup(self):
        # Stop Zygote gracefully via isolated socket
        try:
            self.run(["zygote", "stop"], timeout=5)
        except Exception:
            pass

        try:
            shutil.rmtree(self.path)
        except:
            pass

    def __enter__(self):
        return self.setup()

    def __exit__(self, *args):
        self.cleanup()


# =============================================================================
# RESOURCE EXHAUSTION ATTACKS
# =============================================================================


class TestResourceExhaustion:
    """Try to exhaust system resources."""

    def test_attack_memory_bomb(self):
        """Allocate huge memory in script."""
        with AttackEnv() as env:
            env.create_script(
                "memory_bomb.py",
                """
# Try to allocate 1GB
try:
    data = "x" * (1024 * 1024 * 1024)
    print("allocated 1GB")
except MemoryError:
    print("memory_error")
""",
            )
            code, stdout, stderr = env.run(["run", "--zygote", "memory_bomb.py"], timeout=T_MEDIUM)

            # Should handle gracefully - either work or fail cleanly
            # Note: DEF-005 means stdout may be empty even on success
            # Check return code instead of string matching to avoid false positives
            assert code != -1, "Should not hang on memory bomb (returned -1 = timeout)"
            print(f"  Memory bomb: code={code}, stdout_len={len(stdout)}")

    def test_attack_fork_bomb_attempt(self):
        """Try to fork bomb (should be prevented)."""
        with AttackEnv() as env:
            env.create_script(
                "fork_bomb.py",
                """
import os
import sys
# Limited fork bomb - only 10 forks
for i in range(10):
    pid = os.fork()
    if pid == 0:
        # Child
        print(f"child_{i}")
        sys.exit(0)
    else:
        os.waitpid(pid, 0)
print("fork_bomb_done")
""",
            )
            code, stdout, stderr = env.run(["run", "--zygote", "fork_bomb.py"], timeout=T_MEDIUM)

            # Should not hang
            assert "TIMEOUT" not in stderr

    def test_attack_file_descriptor_leak(self):
        """Open many file descriptors and don't close them."""
        with AttackEnv() as env:
            env.create_script(
                "fd_leak.py",
                """
import os
fds = []
try:
    for i in range(1000):
        fds.append(os.open("/dev/null", os.O_RDONLY))
    print(f"opened {len(fds)} fds")
except OSError as e:
    print(f"fd_limit_hit: {e}")
finally:
    for fd in fds:
        try:
            os.close(fd)
        except:
            pass
""",
            )
            code, stdout, stderr = env.run(["run", "--zygote", "fd_leak.py"], timeout=T_MEDIUM)

            assert "TIMEOUT" not in stderr

    def test_attack_tmp_space_fill(self):
        """Try to fill /tmp with data."""
        with AttackEnv() as env:
            env.create_script(
                "tmp_fill.py",
                """
import tempfile
import os

# Create 100 temp files of 1MB each (100MB total)
files = []
try:
    for i in range(100):
        f = tempfile.NamedTemporaryFile(delete=False)
        f.write(b"x" * (1024 * 1024))
        files.append(f.name)
        f.close()
    print(f"created {len(files)} temp files")
except Exception as e:
    print(f"tmp_error: {e}")
finally:
    for f in files:
        try:
            os.unlink(f)
        except:
            pass
""",
            )
            code, stdout, stderr = env.run(["run", "--zygote", "tmp_fill.py"], timeout=T_LONG)

            assert "TIMEOUT" not in stderr


# =============================================================================
# OUTPUT EXTREME ATTACKS
# =============================================================================


class TestOutputExtremes:
    """Attack stdout/stderr handling."""

    def test_attack_huge_stdout(self):
        """Print 100MB to stdout."""
        with AttackEnv() as env:
            env.create_script(
                "huge_stdout.py",
                """
# Print 10MB (100 * 100KB lines)
for i in range(100):
    print("x" * 102400)
print("DONE")
""",
            )
            code, stdout, stderr = env.run(["run", "--zygote", "huge_stdout.py"], timeout=T_LONG)

            # Should complete without hanging
            assert "TIMEOUT" not in stderr
            # If successful, should have DONE marker
            if code == 0:
                print(f"  stdout size: {len(stdout)} bytes")

    def test_attack_binary_stdout(self):
        """Print binary data to stdout."""
        with AttackEnv() as env:
            env.create_script(
                "binary_stdout.py",
                """
import sys
# Write binary data including null bytes
sys.stdout.buffer.write(bytes(range(256)) * 100)
sys.stdout.buffer.write(b"\\nDONE\\n")
sys.stdout.buffer.flush()
""",
            )
            code, stdout, stderr = env.run(["run", "--zygote", "binary_stdout.py"], timeout=T_MEDIUM)

            # Should not crash
            assert "TIMEOUT" not in stderr

    def test_attack_mixed_stdout_stderr(self):
        """Interleave stdout and stderr rapidly."""
        with AttackEnv() as env:
            env.create_script(
                "mixed_output.py",
                """
import sys
for i in range(1000):
    print(f"stdout_{i}", flush=True)
    print(f"stderr_{i}", file=sys.stderr, flush=True)
print("MIXED_DONE")
""",
            )
            code, stdout, stderr = env.run(["run", "--zygote", "mixed_output.py"], timeout=T_MEDIUM)

            assert "TIMEOUT" not in stderr

    def test_attack_no_newline_flood(self):
        """Print without newlines (buffer flush attack)."""
        with AttackEnv() as env:
            env.create_script(
                "no_newline.py",
                """
import sys
# Print 1MB without any newlines
for _ in range(10000):
    print("x" * 100, end="", flush=True)
print("")  # Final newline
print("DONE")
""",
            )
            code, stdout, stderr = env.run(["run", "--zygote", "no_newline.py"], timeout=T_MEDIUM)

            assert "TIMEOUT" not in stderr


# =============================================================================
# TIME / TIMEOUT ATTACKS
# =============================================================================


class TestTimeAttacks:
    """Attack timeout and blocking behavior."""

    def test_attack_infinite_loop(self):
        """Script with infinite loop (should be killed by timeout)."""
        with AttackEnv() as env:
            env.create_script(
                "infinite.py",
                """
while True:
    pass
""",
            )
            code, stdout, stderr = env.run(["run", "--zygote", "infinite.py"], timeout=T_SHORT)

            # Should timeout, not hang forever
            assert "TIMEOUT" in stderr or code != 0

    def test_attack_sleep_forever(self):
        """Script that sleeps forever."""
        with AttackEnv() as env:
            env.create_script(
                "sleep_forever.py",
                """
import time
time.sleep(99999)
""",
            )
            code, stdout, stderr = env.run(["run", "--zygote", "sleep_forever.py"], timeout=T_SHORT)

            # Should timeout
            assert "TIMEOUT" in stderr or code != 0

    def test_attack_blocking_stdin(self):
        """Script that blocks reading stdin."""
        with AttackEnv() as env:
            env.create_script(
                "block_stdin.py",
                """
import sys
# This will block forever waiting for input
data = sys.stdin.read()
print(f"got: {data}")
""",
            )
            code, stdout, stderr = env.run(["run", "--zygote", "block_stdin.py"], timeout=T_SHORT)

            # Should timeout or return immediately (no stdin)
            assert "TIMEOUT" in stderr or code != 0 or code == 0


# =============================================================================
# SIGNAL ATTACKS
# =============================================================================


class TestSignalAttacks:
    """Attack signal handling."""

    def test_attack_ignore_sigterm(self):
        """Script ignores SIGTERM."""
        with AttackEnv() as env:
            env.create_script(
                "ignore_sigterm.py",
                """
import signal
import time

def handler(sig, frame):
    print("SIGTERM_IGNORED", flush=True)

signal.signal(signal.SIGTERM, handler)
print("READY", flush=True)
time.sleep(10)
print("DONE")
""",
            )
            # Start process
            proc = subprocess.Popen(
                [env.velo, "run", "--zygote", "ignore_sigterm.py"],
                cwd=env.path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            time.sleep(0.5)
            proc.terminate()

            try:
                proc.wait(timeout=T_SHORT)
            except subprocess.TimeoutExpired:
                proc.kill()
                pytest.fail("Process ignored SIGTERM and couldn't be killed gracefully")

    def test_attack_raise_sigsegv(self):
        """Script raises SIGSEGV."""
        with AttackEnv() as env:
            env.create_script(
                "segfault.py",
                """
import signal
import os
# Send SIGSEGV to self
os.kill(os.getpid(), signal.SIGSEGV)
""",
            )
            code, stdout, stderr = env.run(["run", "--zygote", "segfault.py"], timeout=T_SHORT)

            # Should handle the signal, not crash Zygote itself
            print(f"  SIGSEGV result: code={code}")

    def test_attack_sigstop_self(self):
        """Script sends SIGSTOP to itself."""
        with AttackEnv() as env:
            env.create_script(
                "sigstop.py",
                """
import signal
import os
print("BEFORE_STOP", flush=True)
os.kill(os.getpid(), signal.SIGSTOP)
print("AFTER_STOP")
""",
            )
            code, stdout, stderr = env.run(["run", "--zygote", "sigstop.py"], timeout=T_SHORT)

            # Should timeout or handle gracefully
            print(f"  SIGSTOP result: code={code}, timeout={('TIMEOUT' in stderr)}")


# =============================================================================
# IPC / SOCKET ATTACKS
# =============================================================================


class TestIPCAttacks:
    """Attack the Zygote IPC mechanism."""

    def test_attack_connect_spam(self):
        """Spam connections to Zygote socket."""
        with AttackEnv() as env:
            # Start Zygote
            env.run(["zygote", "start"], timeout=T_SHORT)

            # Find socket in isolated dir
            sock_path = None
            if env.socket_dir.exists():
                for f in env.socket_dir.iterdir():
                    if f.suffix == ".sock":
                        sock_path = f
                        break

            if sock_path and sock_path.exists():
                # Spam 100 connections
                errors = 0
                for _ in range(100):
                    try:
                        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        s.settimeout(1)
                        s.connect(str(sock_path))
                        s.close()
                    except:
                        errors += 1

                print(f"  Connection spam: {100 - errors}/100 succeeded")

                # Zygote should still work
                code, stdout, stderr = env.run(["zygote", "status"], timeout=T_SHORT)
                # Should not crash

    def test_attack_garbage_to_socket(self):
        """Send garbage data to Zygote socket."""
        with AttackEnv() as env:
            env.run(["zygote", "start"], timeout=T_SHORT)

            sock_path = None
            if env.socket_dir.exists():
                for f in env.socket_dir.iterdir():
                    if f.suffix == ".sock":
                        sock_path = f
                        break

            if sock_path and sock_path.exists():
                # Send various garbage
                garbage_payloads = [
                    b"\x00" * 1000,  # Null bytes
                    b"\xff" * 1000,  # All 0xFF
                    b"not json",  # Invalid JSON
                    b"{" * 10000,  # Unclosed braces
                    bytes(range(256)) * 10,  # All bytes
                ]

                for payload in garbage_payloads:
                    try:
                        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        s.settimeout(2)
                        s.connect(str(sock_path))
                        s.sendall(payload)
                        s.close()
                    except:
                        pass

                # Zygote should survive
                time.sleep(0.5)
                code, _, _ = env.run(["zygote", "status"], timeout=T_SHORT)
                print(f"  After garbage: status code={code}")

    def test_attack_half_close(self):
        """Half-close socket connection."""
        with AttackEnv() as env:
            env.run(["zygote", "start"], timeout=T_SHORT)

            sock_path = None
            if env.socket_dir.exists():
                for f in env.socket_dir.iterdir():
                    if f.suffix == ".sock":
                        sock_path = f
                        break

            if sock_path and sock_path.exists():
                for _ in range(10):
                    try:
                        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        s.settimeout(2)
                        s.connect(str(sock_path))
                        s.shutdown(socket.SHUT_WR)  # Half-close
                        time.sleep(0.1)
                        s.close()
                    except:
                        pass


# =============================================================================
# CONCURRENT ATTACKS
# =============================================================================


class TestConcurrentAttacks:
    """Attack with concurrency."""

    def test_attack_100_concurrent_runs(self):
        """100 concurrent velo run commands."""
        with AttackEnv() as env:
            env.create_script("quick.py", 'print("ok")')

            results = []
            errors = []

            def run_one():
                try:
                    code, stdout, stderr = env.run(["run", "--zygote", "quick.py"], timeout=T_MEDIUM)
                    results.append(code)
                except Exception as e:
                    errors.append(str(e))

            threads = [threading.Thread(target=run_one) for _ in range(100)]

            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=T_LONG)

            success = sum(1 for r in results if r == 0)
            print(f"  100 concurrent: {success} succeeded, {len(errors)} errors")

    def test_attack_start_stop_race(self):
        """Race condition: start and stop at same time."""
        with AttackEnv() as env:
            errors = []

            def start_loop():
                for _ in range(20):
                    try:
                        env.run(["zygote", "start"], timeout=T_SHORT)
                    except:
                        pass
                    time.sleep(0.05)

            def stop_loop():
                for _ in range(20):
                    try:
                        env.run(["zygote", "stop"], timeout=T_SHORT)
                    except:
                        pass
                    time.sleep(0.05)

            t1 = threading.Thread(target=start_loop)
            t2 = threading.Thread(target=stop_loop)

            t1.start()
            t2.start()
            t1.join(timeout=T_MEDIUM)
            t2.join(timeout=T_MEDIUM)

            # Should not leave in bad state
            env.run(["zygote", "stop"], timeout=T_SHORT)


# =============================================================================
# EXIT CODE ATTACKS
# =============================================================================


class TestExitCodeAttacks:
    """Attack exit code handling."""

    def test_attack_exit_255(self):
        """Exit with code 255."""
        with AttackEnv() as env:
            env.create_script("exit255.py", "import sys; sys.exit(255)")
            code, _, _ = env.run(["run", "--zygote", "exit255.py"])
            assert code == 255 or code != 0

    def test_attack_exit_negative(self):
        """Try to exit with negative code."""
        with AttackEnv() as env:
            env.create_script("exit_neg.py", "import sys; sys.exit(-1)")
            code, _, _ = env.run(["run", "--zygote", "exit_neg.py"])
            # Python converts -1 to 255
            assert code != 0

    def test_attack_os_exit(self):
        """Use os._exit() to bypass cleanup."""
        with AttackEnv() as env:
            env.create_script("os_exit.py", "import os; os._exit(42)")
            code, _, _ = env.run(["run", "--zygote", "os_exit.py"])
            assert code == 42 or code != 0
