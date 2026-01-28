import os
import socket
import struct
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


class DeletingZygote:
    def __init__(self, socket_path: Path) -> None:
        self.socket_path: Path = socket_path
        self.stop_event: threading.Event = threading.Event()

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

                # Delete socket path immediately upon connection
                if os.path.exists(self.socket_path):
                    os.unlink(self.socket_path)

                # Delay slightly before sending Ready
                time.sleep(0.01)
                send_msgpack(conn, {"type": "Ready"})
                conn.close()
        except Exception:
            pass
        finally:
            self.server.close()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join()


@pytest.mark.tier2
def test_EDGE_621_socket_deleted_mid_handshake(isolated_env):
    """EDGE-621: Verify resilience when socket is deleted mid-handshake.
    RFC-0013 §3.1 / Silent Fallback Invariant.
    """
    env = isolated_env
    socket_path = Path("/tmp") / f"deleting_zygote_{os.getpid()}.sock"

    zygote = DeletingZygote(socket_path)
    zygote.start()

    env.create_app("main.py", "from fastapi import FastAPI\napp = FastAPI()")
    (env.path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]')

    cmd_env = os.environ.copy()
    cmd_env["VELO_ZYGOTE_SOCKET"] = str(socket_path)
    repo_root = Path(__file__).parent.parent.parent
    env.velo = str(repo_root / "target" / "debug" / "velo")

    proc = env.run_velo("serve", "main:app", "--workers", "1", env=cmd_env, timeout=10)

    zygote.stop()

    # Verification: Must have fallen back and started the server
    assert "Zygote" in proc.stderr
    assert "Server ready" in proc.stderr or "Uvicorn running on" in proc.stderr
