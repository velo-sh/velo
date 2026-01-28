"""
Velo QA: Phase 3 IPC Security Tests
====================================
GOAL: Find security vulnerabilities in Zygote IPC mechanism.

Attack vectors:
- Socket permissions (who can connect?)
- Path traversal (escape project directory)
- Symlink attacks (TOCTOU race conditions)
- Malicious payloads (DoS, injection)
- Information disclosure (error messages)
"""

import json
import os
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import pytest

# Import CI-aware timeout constants
from conftest_utils import T_MEDIUM, T_SHORT


def get_velo_binary() -> str:
    repo_root = Path(__file__).parent.parent.parent
    release = repo_root / "target" / "release" / "velo"
    if release.exists():
        return str(release)
    pytest.skip("velo binary not found")


class SecurityEnv:
    """Environment for security testing."""

    def __init__(self) -> None:
        self.path = Path(tempfile.mkdtemp(prefix="security_"))
        self.velo = get_velo_binary()
        self.socket_path: Path | None = None

    def setup(self) -> "SecurityEnv":
        subprocess.run(["uv", "venv", "--quiet"], cwd=self.path, capture_output=True)
        (self.path / "uv.lock").write_text("{}")
        return self

    def start_zygote(self, timeout: float | None = None) -> str | None:
        """Start Zygote and return socket path."""
        if timeout is None:
            timeout = T_MEDIUM  # CI-aware timeout
        subprocess.run(
            [self.velo, "zygote", "start"],
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        # Find socket - check multiple locations
        # 1. /tmp/velo-zygote.sock (global socket)
        global_sock = Path("/tmp/velo-zygote.sock")
        if global_sock.exists():
            self.socket_path = global_sock
            return str(global_sock)

        # 2. .velo_cache/*.sock (project-local socket)
        cache_dir = self.path / ".velo_cache"
        if cache_dir.exists():
            for f in cache_dir.iterdir():
                if f.suffix == ".sock":
                    self.socket_path = f
                    return str(f)

        return None

    def stop_zygote(self) -> None:
        subprocess.run(
            [self.velo, "zygote", "stop"],
            cwd=self.path,
            capture_output=True,
            timeout=T_SHORT,  # CI-aware timeout
        )

    def send_raw(self, data: bytes) -> bytes:
        """Send raw bytes to socket."""
        if not self.socket_path:
            return b""

        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect(str(self.socket_path))

            # Read Ready message first
            s.recv(1024)

            s.sendall(data)
            response = s.recv(4096)
            s.close()
            return response
        except Exception as e:
            return str(e).encode()

    def send_command(self, cmd: dict[str, Any]) -> dict[str, Any]:
        """Send JSON command and get response."""
        data = (json.dumps(cmd) + "\n").encode()
        response = self.send_raw(data)
        try:
            lines = response.decode().strip().split("\n")
            return json.loads(lines[-1]) if lines else {}
        except Exception:
            return {"raw": response.decode()}

    def create_script(self, name: str, content: str) -> None:
        (self.path / name).write_text(content)

    def cleanup(self) -> None:
        subprocess.run(["pkill", "-f", "velo_zygote"], capture_output=True)
        try:
            shutil.rmtree(self.path)
        except Exception:
            pass

    def __enter__(self) -> "SecurityEnv":
        return self.setup()

    def __exit__(self, *args: Any) -> None:
        self.cleanup()


# =============================================================================
# SOCKET PERMISSION ATTACKS
# =============================================================================


class TestSocketPermissions:
    """Test socket file permissions."""

    def test_sec_001_socket_permissions(self):
        """
        SEC-001: Socket should have restrictive permissions.

        Default umask might create 0666 socket - anyone can connect!
        """
        with SecurityEnv() as env:
            sock_path = env.start_zygote()

            if sock_path:
                sock_stat = os.stat(sock_path)
                mode = stat.S_IMODE(sock_stat.st_mode)

                # Check if world-readable/writable
                world_read = mode & stat.S_IROTH
                world_write = mode & stat.S_IWOTH

                print(f"  Socket mode: {oct(mode)}")
                print(f"  World readable: {bool(world_read)}")
                print(f"  World writable: {bool(world_write)}")

                # Security: Should NOT be world accessible
                # This test documents current behavior
                if world_read or world_write:
                    print("  ⚠️ SECURITY: Socket is world accessible!")

    def test_sec_002_socket_owner(self):
        """
        SEC-002: Socket should be owned by current user.
        """
        with SecurityEnv() as env:
            sock_path = env.start_zygote()

            if sock_path:
                sock_stat = os.stat(sock_path)
                owner_uid = sock_stat.st_uid
                current_uid = os.getuid()

                assert owner_uid == current_uid, f"Socket owned by UID {owner_uid}, not current user {current_uid}"


# =============================================================================
# PATH TRAVERSAL ATTACKS
# =============================================================================


class TestPathTraversal:
    """Test path traversal / injection attacks."""

    def test_sec_003_path_traversal_basic(self):
        """
        SEC-003: Path traversal with ../

        Try to escape project directory and execute /etc/passwd
        Security check is in CLI layer, not IPC layer.
        """
        with SecurityEnv() as env:
            # Try to execute file outside project via CLI
            result = subprocess.run(
                [env.velo, "run", "--zygote", "../../../etc/passwd"],
                cwd=env.path,
                capture_output=True,
                text=True,
                timeout=10,
            )

            # Should fail with security error
            assert result.returncode != 0 or "Access denied" in result.stderr or "protected" in result.stderr.lower(), (
                f"Path traversal not blocked! code={result.returncode}, stderr={result.stderr}"
            )

    def test_sec_004_absolute_path_outside_project(self):
        """
        SEC-004: Absolute path to file outside project.
        """
        with SecurityEnv() as env:
            env.start_zygote()

            # Try absolute path
            response = env.send_command({"type": "Fork", "script_path": "/etc/passwd", "args": []})

            # This might succeed if no path validation!
            if response.get("type") == "Forked":
                print("  ⚠️ SECURITY: Arbitrary path execution allowed!")

            # Document behavior
            print(f"  Response: {response}")

    def test_sec_005_path_with_null_byte(self):
        """
        SEC-005: Null byte injection in path.

        Some systems truncate at null byte: "/legit.py\x00/evil"
        """
        with SecurityEnv() as env:
            env.start_zygote()
            env.create_script("legit.py", 'print("legit")')

            response = env.send_command(
                {
                    "type": "Fork",
                    "script_path": str(env.path / "legit.py") + "\x00ignored",
                    "args": [],
                }
            )

            print(f"  Null byte response: {response}")

    def test_sec_006_path_with_unicode_tricks(self):
        """
        SEC-006: Unicode path normalization tricks.
        """
        with SecurityEnv() as env:
            env.start_zygote()

            # Various unicode tricks
            paths = [
                "/etc\uff0fpasswd",  # Fullwidth slash
                "/etc\u2215passwd",  # Division slash
                "..\\..\\etc\\passwd",  # Windows path sep
            ]

            for evil_path in paths:
                response = env.send_command({"type": "Fork", "script_path": evil_path, "args": []})
                print(f"  {repr(evil_path)}: {response.get('type')}")


# =============================================================================
# SYMLINK ATTACKS
# =============================================================================


class TestSymlinkAttacks:
    """Test symlink/TOCTOU race condition attacks."""

    def test_sec_007_symlink_to_outside_file(self):
        """
        SEC-007: Symlink pointing outside project directory.
        """
        with SecurityEnv() as env:
            env.start_zygote()

            # Create symlink to /etc/passwd
            evil_link = env.path / "evil.py"
            evil_link.symlink_to("/etc/passwd")

            response = env.send_command({"type": "Fork", "script_path": str(evil_link), "args": []})

            # Should this be allowed?
            print(f"  Symlink to /etc/passwd: {response}")

    def test_sec_008_toctou_race(self):
        """
        SEC-008: Time-of-check to time-of-use race.

        1. Script exists and is checked
        2. Script is replaced with symlink to evil file
        3. Evil file gets executed
        """
        with SecurityEnv() as env:
            env.start_zygote()

            legit_script = env.path / "legit.py"
            legit_script.write_text('print("legit")')

            race_won = False

            def replace_with_symlink():
                nonlocal race_won
                for _ in range(100):
                    try:
                        legit_script.unlink()
                        legit_script.symlink_to("/etc/passwd")
                        race_won = True
                        break
                    except Exception:
                        pass
                    time.sleep(0.001)

            # Start replacement thread
            t = threading.Thread(target=replace_with_symlink)
            t.start()

            # Try to execute
            response = env.send_command({"type": "Fork", "script_path": str(legit_script), "args": []})

            t.join(timeout=1)

            if race_won:
                print(f"  TOCTOU race attempted, response: {response}")


# =============================================================================
# MALICIOUS PAYLOAD ATTACKS
# =============================================================================


class TestMaliciousPayloads:
    """Test malicious IPC payloads."""

    def test_sec_009_json_bomb(self):
        """
        SEC-009: JSON bomb (deeply nested objects).
        """
        with SecurityEnv() as env:
            env.start_zygote()

            # Create deeply nested JSON
            bomb: dict[str, Any] = {"a": None}
            current = bomb
            for _ in range(1000):
                current["a"] = {"a": None}
                current = current["a"]

            try:
                response = env.send_command(bomb)
                print(f"  JSON bomb response: {response}")
            except Exception as e:
                print(f"  JSON bomb error: {e}")

    def test_sec_010_huge_payload(self):
        """
        SEC-010: Very large payload (DoS).
        """
        with SecurityEnv() as env:
            env.start_zygote()

            # 10MB payload
            huge_payload = {
                "type": "Fork",
                "script_path": "x" * (10 * 1024 * 1024),
                "args": [],
            }

            try:
                response = env.send_command(huge_payload)
                print(f"  Huge payload response: {response}")
            except Exception as e:
                print(f"  Huge payload error: {type(e).__name__}")

    def test_sec_011_unicode_overflow(self):
        """
        SEC-011: Unicode string that expands when encoded.
        """
        with SecurityEnv() as env:
            env.start_zygote()

            # This character expands significantly in some encodings
            payload = {"type": "Fork", "script_path": "\U0010ffff" * 100000, "args": []}

            try:
                response = env.send_command(payload)
                print(f"  Unicode overflow: {response.get('type', 'error')}")
            except Exception as e:
                print(f"  Unicode overflow error: {type(e).__name__}")

    def test_sec_012_command_injection_in_args(self):
        """
        SEC-012: Command injection via args.
        """
        with SecurityEnv() as env:
            env.start_zygote()
            env.create_script(
                "echo.py",
                """
import sys
print(sys.argv)
""",
            )

            # Try to inject shell commands
            evil_args = [
                "; cat /etc/passwd",
                "| cat /etc/passwd",
                "$(cat /etc/passwd)",
                "`cat /etc/passwd`",
                "--flag=value; rm -rf /",
            ]

            for arg in evil_args:
                response = env.send_command(
                    {
                        "type": "Fork",
                        "script_path": str(env.path / "echo.py"),
                        "args": [arg],
                    }
                )
                print(f"  Arg {repr(arg[:20])}: {response.get('type')}")


# =============================================================================
# INFORMATION DISCLOSURE
# =============================================================================


class TestInfoDisclosure:
    """Test information disclosure vulnerabilities."""

    def test_sec_013_error_message_disclosure(self):
        """
        SEC-013: Error messages might reveal sensitive info.
        """
        with SecurityEnv() as env:
            env.start_zygote()

            # Request nonexistent file with sensitive-looking path
            response = env.send_command({"type": "Fork", "script_path": "/home/user/.ssh/id_rsa", "args": []})

            error_msg = response.get("message", "")

            # Check if error reveals full path
            if "/home/" in error_msg or "id_rsa" in error_msg:
                print(f"  ⚠️ Error reveals path: {error_msg}")

            print(f"  Error response: {response}")

    def test_sec_014_stack_trace_disclosure(self):
        """
        SEC-014: Stack traces might reveal internal details.
        """
        with SecurityEnv() as env:
            env.start_zygote()

            # Send malformed data to trigger error
            response = env.send_raw(b"\xff\xfe\x00\x01")

            # Check for stack trace indicators
            response_str = response.decode(errors="ignore")
            if "Traceback" in response_str or 'File "' in response_str:
                print("  ⚠️ Stack trace in response!")
                print(f"  {response_str[:200]}")


# =============================================================================
# DENIAL OF SERVICE
# =============================================================================


class TestDoS:
    """Test denial of service attacks."""

    def test_sec_015_connection_exhaustion(self):
        """
        SEC-015: Exhaust connection limit.
        """
        with SecurityEnv() as env:
            env.start_zygote()

            if not env.socket_path:
                pytest.skip("No socket")

            # Hold many connections open
            sockets = []
            for _i in range(20):
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.settimeout(1)
                    s.connect(str(env.socket_path))
                    sockets.append(s)
                except Exception:
                    break

            print(f"  Held {len(sockets)} connections open")

            # Can we still get a new connection?
            try:
                test = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                test.settimeout(2)
                test.connect(str(env.socket_path))
                print("  Still accepting connections: Yes")
                test.close()
            except Exception:
                print("  ⚠️ DoS: No new connections accepted!")

            # Cleanup
            for s in sockets:
                try:
                    s.close()
                except Exception:
                    pass

    def test_sec_016_fork_bomb_via_ipc(self):
        """
        SEC-016: Request unlimited forks via IPC.
        """
        with SecurityEnv() as env:
            env.start_zygote()
            env.create_script("sleep.py", "import time; time.sleep(100)")

            # Request many forks
            pids = []
            for _ in range(50):
                response = env.send_command(
                    {
                        "type": "Fork",
                        "script_path": str(env.path / "sleep.py"),
                        "args": [],
                    }
                )
                if response.get("worker_pid"):
                    pids.append(response["worker_pid"])

            print(f"  Forked {len(pids)} workers")

            # Check if there's any limit
            if len(pids) >= 50:
                print("  ⚠️ No fork limit! Potential fork bomb via IPC")

            # Cleanup
            for pid in pids:
                try:
                    os.kill(pid, 9)
                except Exception:
                    pass

    def test_sec_017_slowloris_style(self):
        """
        SEC-017: Slowloris-style attack (slow data send).
        """
        with SecurityEnv() as env:
            env.start_zygote()

            if not env.socket_path:
                pytest.skip("No socket")

            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(30)
                s.connect(str(env.socket_path))

                # Read Ready
                s.recv(1024)

                # Send data very slowly
                partial = b'{"type": "For'
                s.sendall(partial)

                time.sleep(2)

                # Does connection stay open?
                s.sendall(b'k", "script": "x"}\n')

                response = s.recv(1024)
                print(f"  Slowloris response: {response[:50]!r}")
                s.close()
            except TimeoutError:
                print("  Server timed out slow connection (good!)")
            except Exception as e:
                print(f"  Slowloris error: {e}")
