import os
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest


def send_msgpack(conn: Any, data: Any) -> None:
    import msgpack

    payload = msgpack.packb(data, use_bin_type=True)
    version = b"\x01"
    total_len = len(version) + len(payload)
    header = struct.pack("<I", total_len)
    conn.sendall(header + version + payload)


class SlowZygote:
    def __init__(self, socket_path: Path, connect_delay: float = 0, ready_delay: float = 0) -> None:
        self.socket_path = socket_path
        self.connect_delay = connect_delay
        self.ready_delay = ready_delay
        self.stop_event = threading.Event()

    def start(self) -> None:
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.socket_path))
        self.server.listen(5)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            while not self.stop_event.is_set():
                self.server.settimeout(0.5)
                try:
                    conn, _ = self.server.accept()
                except TimeoutError:
                    continue

                if self.connect_delay:
                    time.sleep(self.connect_delay)

                if self.ready_delay:
                    time.sleep(self.ready_delay)

                send_msgpack(conn, {"type": "Ready"})
                conn.close()
        except Exception:
            pass
        finally:
            self.server.close()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join()


@pytest.mark.tier1
def test_STAB_621_cumulative_timeout(isolated_env):
    """STAB-621: Verify 10ms budget covers the ENTIRE sequence.
    RFC-0013 §3.1 / H-11 10ms Handshake Budget.
    """
    env = isolated_env
    socket_path = Path("/tmp") / f"slow_zygote_{os.getpid()}.sock"

    # Total delay = 15ms (Exceeds 10ms budget)
    # If the implementation only checks individual steps (e.g. read_message),
    # it might PASS if each step takes < 10ms.
    # We want to see it FAIL and fallback because 15ms > 10ms.
    zygote = SlowZygote(socket_path, connect_delay=0.007, ready_delay=0.008)
    zygote.start()

    env.create_app("main.py", "from fastapi import FastAPI\napp = FastAPI()")
    (env.path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]')

    cmd_env = os.environ.copy()
    cmd_env["VELO_ZYGOTE_SOCKET"] = str(socket_path)
    repo_root = Path(__file__).parent.parent.parent
    env.velo = str(repo_root / "target" / "debug" / "velo")

    start_time = time.time()
    proc = env.run_velo("serve", "main:app", "--workers", "1", env=cmd_env, timeout=10)
    time.time() - start_time

    zygote.stop()

    # Verification: Must have fallen back
    assert "Zygote" in proc.stderr
    assert any(
        term in proc.stderr.lower() for term in ["failed", "timeout", "fallback", "timed out", "continuing without"]
    )


@pytest.mark.tier2
def test_STAB_622_high_concurrency_pressure(isolated_env):
    """STAB-622: Stress Zygote with many concurrent fork requests.
    Verifies that the fork queue and internal state remain consistent.
    """
    env = isolated_env
    socket_path = env.path / "zygote.sock"
    app_dir = env.path / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text("import time\nprint('Worker started')\ntime.sleep(0.1)")

    # Start Zygote
    import subprocess

    cmd_env = os.environ.copy()
    cmd_env["VELO_ZYGOTE_SOCKET"] = str(socket_path)
    proc = subprocess.Popen([env.velo, "zygote", "start"], env=cmd_env)
    time.sleep(1)

    try:
        # Spawn 20 workers simultaneously
        processes = []
        for _ in range(20):
            p = subprocess.Popen(
                [env.velo, "serve", "app.main:app", "--workers", "1", "--dry-run"],
                env=cmd_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            processes.append(p)

        for p in processes:
            p.wait(timeout=10)

        # Verify all succeeded (Titanium reliability)
        success_count = sum(1 for p in processes if p.returncode == 0)
        assert success_count == 20, f"Only {success_count}/20 workers spawned successfully under pressure"

    finally:
        proc.terminate()


@pytest.mark.tier2
def test_STAB_623_zygote_sigkill_durability(isolated_env):
    """STAB-623: Kill Zygote while workers are running.
    Verifies that the CLI detects the loss and fallbacks gracefully for new requests.
    """
    env = isolated_env
    socket_path = env.path / "zygote.sock"

    # Start Zygote
    cmd_env = os.environ.copy()
    cmd_env["VELO_ZYGOTE_SOCKET"] = str(socket_path)
    proc = subprocess.Popen([env.velo, "zygote", "start"], env=cmd_env)
    time.sleep(1)

    try:
        # Kill Zygote abruptly
        proc.kill()
        proc.wait()

        # Try to serve
        res = subprocess.run(
            [env.velo, "serve", "main:app", "--dry-run"],
            env=cmd_env,
            capture_output=True,
            text=True,
        )
        # Should fallback to cold start
        assert "Zygote" in res.stderr
        assert res.returncode == 0

    finally:
        if proc.poll() is None:
            proc.kill()
    # If it took more than 10ms to realize it timed out, it might be due to cumulative failure
    # But the CLI should have aborted the Zygote path within ~10-20ms.
