from __future__ import annotations

"""
Velo QA: Phase 3 Zygote Test Infrastructure
============================================
Extended test harness for Zygote mode testing.
"""

import os
import signal
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from test_harness import VeloTestEnv, run_velo


@dataclass
class ZygoteTestEnv(VeloTestEnv):
    """Extended environment for Zygote testing with daemon control."""

    zygote_pid: int | None = None
    socket_name: str = "velo-zygote.sock"

    @property
    def socket_path(self) -> Path:
        """Return the Zygote socket path."""
        return self.path / ".velo_cache" / self.socket_name

    def start_zygote(self, timeout: float = 5.0) -> int | None:
        """
        Start Zygote daemon and return PID.

        Returns None if start fails.
        """
        result = run_velo(["zygote", "start"], cwd=self.path, timeout=timeout)

        if result.success:
            # Try to get PID from status
            status = run_velo(["zygote", "status"], cwd=self.path, timeout=2)
            if status.success:
                # Parse PID from output (format: "PID: 12345")
                for line in status.stdout.split("\n"):
                    if "PID" in line or "pid" in line:
                        parts = line.split(":")
                        if len(parts) >= 2:
                            try:
                                self.zygote_pid = int(parts[1].strip())
                                return self.zygote_pid
                            except ValueError:
                                pass
        return None

    def stop_zygote(self, force: bool = False) -> bool:
        """
        Stop Zygote daemon.

        Args:
            force: If True, use SIGKILL instead of graceful shutdown.
        """
        if force and self.zygote_pid:
            try:
                os.kill(self.zygote_pid, signal.SIGKILL)
                self.zygote_pid = None
                return True
            except ProcessLookupError:
                return True
            except Exception:
                return False

        result = run_velo(["zygote", "stop"], cwd=self.path, timeout=5)
        if result.success:
            self.zygote_pid = None
        return result.success

    def is_zygote_running(self) -> bool:
        """Check if Zygote daemon is running."""
        if self.zygote_pid:
            try:
                os.kill(self.zygote_pid, 0)  # Signal 0 = check existence
                return True
            except ProcessLookupError:
                self.zygote_pid = None
                return False

        # Check via status command
        result = run_velo(["zygote", "status"], cwd=self.path, timeout=2)
        return result.success and "running" in result.stdout.lower()

    def send_raw_ipc(self, data: bytes, timeout: float = 2.0) -> bytes | None:
        """
        Send raw data to Zygote socket for fuzzing.

        Returns response bytes or None on error.
        """
        if not self.socket_path.exists():
            return None

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(str(self.socket_path))
            sock.sendall(data)
            response = sock.recv(4096)
            sock.close()
            return response
        except Exception:
            return None

    def create_velo_config(self, preload: list[str]) -> None:
        """Add [tool.velo] configuration to pyproject.toml."""
        pyproject_path = self.path / "pyproject.toml"
        if pyproject_path.exists():
            content = pyproject_path.read_text()
            if "[tool.velo]" not in content:
                preload_str = ", ".join(f'"{m}"' for m in preload)
                content += f"\n[tool.velo]\npreload = [{preload_str}]\n"
                pyproject_path.write_text(content)
        else:
            preload_str = ", ".join(f'"{m}"' for m in preload)
            pyproject_path.write_text(f"[tool.velo]\npreload = [{preload_str}]\n")

    def cleanup(self) -> None:
        """Extended cleanup that stops Zygote."""
        # Force stop Zygote if running
        if self.zygote_pid:
            try:
                os.kill(self.zygote_pid, signal.SIGKILL)
            except Exception:
                pass

        # Try graceful stop
        try:
            run_velo(["zygote", "stop"], cwd=self.path, timeout=2)
        except Exception:
            pass

        # Clean socket if exists
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except Exception:
                pass

        # Parent cleanup
        super().cleanup()


def count_zombie_processes() -> int:
    """Count zombie processes owned by current user."""
    try:
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=5)
        return sum(1 for line in result.stdout.split("\n") if " Z " in line)
    except Exception:
        return 0


def count_child_processes(parent_pid: int) -> int:
    """Count child processes of a given PID."""
    try:
        result = subprocess.run(["pgrep", "-P", str(parent_pid)], capture_output=True, text=True, timeout=5)
        return len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
    except Exception:
        return 0


def get_socket_connections(socket_path: Path) -> int:
    """Count connections to a Unix socket (approximate via lsof)."""
    try:
        result = subprocess.run(["lsof", str(socket_path)], capture_output=True, text=True, timeout=5)
        # Count lines minus header
        lines = result.stdout.strip().split("\n")
        return max(0, len(lines) - 1)
    except Exception:
        return 0
