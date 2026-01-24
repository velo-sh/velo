import os
import socket
import struct
import threading
import time
from pathlib import Path
from typing import Any

import pytest


def send_msgpack(conn: socket.socket, data: dict[str, Any]) -> None:
    import msgpack

    payload = msgpack.packb(data, use_bin_type=True)
    version = b"\x01"
    total_len = len(version) + len(payload)
    header = struct.pack("<I", total_len)
    conn.sendall(header + version + payload)


def start_fake_zygote(socket_path: Path, delay: float = 0.05) -> threading.Thread:
    """Starts a fake zygote that delays its 'Ready' greeting."""

    def run():
        if os.path.exists(socket_path):
            os.unlink(socket_path)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(socket_path))
        server.listen(5)

        try:
            while True:
                conn, _ = server.accept()
                if delay:
                    time.sleep(delay)
                send_msgpack(conn, {"type": "Ready"})
                conn.close()
        except Exception:
            pass
        finally:
            server.close()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


@pytest.mark.tier1
def test_kinetic_handshake_timeout_fallback(isolated_env):
    """RFC-0013: Verify CLI drops to Cold Start if Zygote handshake > 10ms."""
    env = isolated_env
    socket_path = Path("/tmp") / f"fake_zygote_{os.getpid()}.sock"

    # 1. Start a slow Zygote (50ms delay, exceeds 10ms budget)
    start_fake_zygote(socket_path, delay=0.05)

    for _ in range(20):
        if socket_path.exists():
            break
        time.sleep(0.1)

    # 2. Setup app
    env.create_app("main.py", "from fastapi import FastAPI\napp = FastAPI()")
    (env.path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]')

    cmd_env = os.environ.copy()
    cmd_env["VELO_ZYGOTE_SOCKET"] = str(socket_path)
    repo_root = Path(__file__).parents[4]
    env.velo = str(repo_root / "target" / "debug" / "velo")

    # Run velo serve
    proc = env.run_velo("serve", "main:app", "--workers", "1", env=cmd_env, timeout=5)

    if socket_path.exists():
        socket_path.unlink()

    # 3. Assertions
    # We check for "Zygote" and some form of failure or fallback
    # The exact message might be split or wrapped, so we check for key terms
    assert "Zygote" in proc.stderr
    assert any(term in proc.stderr for term in ["failed", "timed out", "fallback", "without Zygote"])
    assert "Server ready" in proc.stderr or "Uvicorn running on" in proc.stderr


@pytest.mark.tier1
def test_kinetic_silent_fallback_on_connection_refused(isolated_env):
    """RFC-0013: Verify CLI drops to Cold Start if Zygote socket is dead."""
    env = isolated_env
    socket_path = Path("/tmp") / f"dead_zygote_{os.getpid()}.sock"
    if socket_path.exists():
        socket_path.unlink()

    env.create_app("main.py", "from fastapi import FastAPI\napp = FastAPI()")
    (env.path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]')

    cmd_env = os.environ.copy()
    cmd_env["VELO_ZYGOTE_SOCKET"] = str(socket_path)
    repo_root = Path(__file__).parents[4]
    env.velo = str(repo_root / "target" / "debug" / "velo")

    proc = env.run_velo("serve", "main:app", "--workers", "1", env=cmd_env, timeout=5)

    assert "Server ready" in proc.stderr
    assert "Zygote" in proc.stderr
