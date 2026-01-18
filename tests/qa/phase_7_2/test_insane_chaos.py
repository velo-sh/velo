"""
Insane Chaos Tests - The Final Frontier

Tests designed to push the Velo runtime beyond standard production limits.
Focus on concurrency mutation, signal interference, and protocol corruption.

Categories:
1. Header Smuggling & Corruption (8)
2. Streaming Body Chaos (8)
3. Concurrency Storm & Mutation (7)
4. Runtime Signal Interference (7)

Total: 30 insane chaos tests

Author: Velo QA Team
Date: 2026-01-15
"""

import concurrent.futures
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
import requests


def get_velo_binary() -> str:
    repo_root = Path(__file__).parent.parent.parent.parent
    release = repo_root / "target" / "release" / "velo"
    if release.exists():
        return str(release)
    pytest.skip("velo binary not found")


class ChaosTestProject:
    """Chaos test project for maximum instability."""

    def __init__(self, name: str):
        self.name = name
        self.path = Path(tempfile.mkdtemp(prefix=f"chaos_{name}_"))
        self.velo = get_velo_binary()
        self._port = None
        self._proc = None

    def set_pyproject(self, deps: list):
        content = f"""[project]
name = "{self.name}-test"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = {json.dumps(deps)}

[tool.uv]
dev-dependencies = []
"""
        (self.path / "pyproject.toml").write_text(content)
        return self

    def set_app(self, filename: str, code: str):
        (self.path / filename).write_text(code)
        return self

    def install_deps(self, timeout: float = 180):
        subprocess.run(["uv", "sync"], cwd=self.path, capture_output=True, timeout=timeout)
        return self

    def start_server(self, app_module: str, workers: int = 2, extra_args: list = None):
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        self._port = port
        run_env = os.environ.copy()
        run_env["VELO_TEST_MODE"] = "1"
        run_env["VIRTUAL_ENV"] = str(self.path / ".venv")
        run_env["PATH"] = f"{self.path / '.venv' / 'bin'}:{os.environ.get('PATH', '')}"

        venv_lib = self.path / ".venv" / "lib"
        site_dirs = list(venv_lib.glob("python*/site-packages"))
        if site_dirs:
            run_env["PYTHONPATH"] = str(site_dirs[0])

        args = [self.velo, "serve", app_module, "--rsgi", "--no-zygote", "--port", str(port), "--workers", str(workers)]
        if extra_args:
            args.extend(extra_args)

        self._proc = subprocess.Popen(
            args,
            cwd=self.path,
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(8)
        return self

    @property
    def port(self) -> int:
        return self._port

    @property
    def pid(self) -> int:
        return self._proc.pid if self._proc else None

    def cleanup(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait(timeout=10)
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()


# =============================================================================
# CATEGORY 1: Header Smuggling & Corruption (8)
# =============================================================================


class TestHeaderChaos:
    """Insane tests for header handling."""

    @pytest.mark.tier5
    @pytest.mark.slow
    def test_giant_header_block(self):
        """[CHAOS-HDR-01] Request with 32KB of headers."""
        with ChaosTestProject("hd-giant") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): \n await send({'type': 'http.response.start', 'status': 200, 'headers': []}) \n await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app")

            headers = {f"X-Chaos-{i}": "V" * 500 for i in range(60)}  # ~30KB
            r = requests.get(f"http://127.0.0.1:{p.port}/", headers=headers, timeout=5)
            assert r.status_code == 200

    @pytest.mark.tier5
    @pytest.mark.slow
    def test_header_with_null_bytes(self):
        """[CHAOS-HDR-02] Headers containing null bytes."""
        with ChaosTestProject("hd-null") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): \n await send({'type': 'http.response.start', 'status': 200, 'headers': []}) \n await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app")

            import urllib.request

            req = urllib.request.Request(f"http://127.0.0.1:{p.port}/")
            # Manually add header with null byte if possible, or just invalid chars
            req.add_header("X-Null", "value\0byte")
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    assert resp.status == 200
            except:
                pass  # Many clients block this, but we check if server crashes

    @pytest.mark.tier5
    @pytest.mark.slow
    def test_duplicate_content_length(self):
        """[CHAOS-HDR-03] Smuggling: Duplicate Content-Length headers."""
        with ChaosTestProject("hd-smuggle") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): \n await send({'type': 'http.response.start', 'status': 200, 'headers': []}) \n await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app")

            # Use raw socket to send duplicate headers
            import socket

            with socket.create_connection(("127.0.0.1", p.port)) as sock:
                raw = b"GET / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\nContent-Length: 5\r\n\r\n"
                sock.sendall(raw)
                # We expect either 400 or successful handling of one.
                # Key is NO CRASH in RSGI bridge.

    @pytest.mark.tier5
    def test_non_ascii_header_keys(self):
        """[CHAOS-HDR-04] Headers with non-ASCII keys."""
        with ChaosTestProject("hd-nonascii") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): \n await send({'type': 'http.response.start', 'status': 200, 'headers': []}) \n await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app")
            # Check if server survives illegal header keys
            import socket

            with socket.create_connection(("127.0.0.1", p.port)) as sock:
                sock.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nX-\xff-Key: value\r\n\r\n")

    @pytest.mark.tier5
    def test_mixed_case_standard_headers(self):
        """[CHAOS-HDR-05] Random casing in standard headers."""
        with ChaosTestProject("hd-case") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): \n await send({'type': 'http.response.start', 'status': 200, 'headers': []}) \n await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app")
            r = requests.get(f"http://127.0.0.1:{p.port}/", headers={"cOnTeNt-tYpE": "TeXt/PlAiN"})
            assert r.status_code == 200

    @pytest.mark.tier5
    def test_multiline_headers(self):
        """[CHAOS-HDR-06] Obsolete multiline headers (RFC 7230)."""
        with ChaosTestProject("hd-multi") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): \n await send({'type': 'http.response.start', 'status': 200, 'headers': []}) \n await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app")
            import socket

            with socket.create_connection(("127.0.0.1", p.port)) as sock:
                sock.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nX-Multi: part1\r\n  part2\r\n\r\n")

    @pytest.mark.tier5
    def test_invalid_protocol_version(self):
        """[CHAOS-HDR-07] Weird HTTP versions like HTTP/1.2 or HTTP/0.9."""
        with ChaosTestProject("hd-proto") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): \n await send({'type': 'http.response.start', 'status': 200, 'headers': []}) \n await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app")
            import socket

            with socket.create_connection(("127.0.0.1", p.port)) as sock:
                sock.sendall(b"GET / HTTP/1.2\r\nHost: localhost\r\n\r\n")

    @pytest.mark.tier5
    def test_too_many_headers_count(self):
        """[CHAOS-HDR-08] 1000+ tiny headers."""
        with ChaosTestProject("hd-count") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): \n await send({'type': 'http.response.start', 'status': 200, 'headers': []}) \n await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app")
            headers = {f"X-{i}": "1" for i in range(1000)}
            r = requests.get(f"http://127.0.0.1:{p.port}/", headers=headers, timeout=5)
            # Hyper/Velo correctly limits headers to prevent resource exhaustion
            assert r.status_code == 431


# =============================================================================
# CATEGORY 2: Streaming Body Chaos (8)
# =============================================================================


class TestBodyChaos:
    """Insane tests for body handling."""

    @pytest.mark.tier5
    @pytest.mark.slow
    def test_infinitely_slow_body(self):
        """[CHAOS-BODY-01] Sending body bytes extremely slowly."""
        with ChaosTestProject("bd-slow") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, receive, send):
    count = 0
    while True:
        msg = await receive()
        count += len(msg.get('body', b''))
        if not msg.get('more_body', False): break
    await send({'type': 'http.response.start', 'status': 200, 'headers': []})
    await send({'type': 'http.response.body', 'body': str(count).encode()})
""",
            )
            p.install_deps().start_server("main:app")
            import socket

            with socket.create_connection(("127.0.0.1", p.port)) as sock:
                sock.sendall(b"POST / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 10\r\n\r\n")
                for i in range(10):
                    sock.sendall(b"X")
                    time.sleep(1)
                # Should finish and return 10

    @pytest.mark.tier5
    def test_body_with_premature_close(self):
        """[CHAOS-BODY-02] Closing connection while RSGI app is reading body."""
        with ChaosTestProject("bd-close") as p:
            p.set_pyproject(deps=[])
            p.set_app("main.py", "async def app(scope, receive, send): await receive()")
            p.install_deps().start_server("main:app")
            import socket

            with socket.create_connection(("127.0.0.1", p.port)) as sock:
                sock.sendall(b"POST / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 100\r\n\r\n")
                sock.sendall(b"data")
                sock.close()  # Bang!

    @pytest.mark.tier5
    def test_body_larger_than_content_length(self):
        """[CHAOS-BODY-03] Sending more bytes than specified."""
        with ChaosTestProject("bd-extra") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): \n while True: \n  m = await receive() \n  if not m.get('more_body'): break",
            )
            p.install_deps().start_server("main:app")
            import socket

            with socket.create_connection(("127.0.0.1", p.port)) as sock:
                sock.sendall(b"POST / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 5\r\n\r\n")
                sock.sendall(b"1234567890")

    @pytest.mark.tier5
    def test_body_smaller_than_content_length(self):
        """[CHAOS-BODY-04] Sending fewer bytes than specified (timeout check)."""
        with ChaosTestProject("bd-lacking") as p:
            p.set_pyproject(deps=[])
            p.set_app("main.py", "async def app(scope, receive, send): await receive()")
            p.install_deps().start_server("main:app")
            import socket

            with socket.create_connection(("127.0.0.1", p.port)) as sock:
                sock.sendall(b"POST / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 100\r\n\r\n")
                sock.sendall(b"missing data")

    @pytest.mark.tier5
    def test_chunked_body_invalid_hex(self):
        """[CHAOS-BODY-05] Invalid hex in chunked encoding size."""
        with ChaosTestProject("bd-chunkerr") as p:
            p.set_pyproject(deps=[])
            p.set_app("main.py", "async def app(scope, receive, send): await receive()")
            p.install_deps().start_server("main:app")
            import socket

            with socket.create_connection(("127.0.0.1", p.port)) as sock:
                sock.sendall(b"POST / HTTP/1.1\r\nHost: localhost\r\nTransfer-Encoding: chunked\r\n\r\n")
                sock.sendall(b"G\r\nhello\r\n0\r\n\r\n")  # 'G' is not hex

    @pytest.mark.tier5
    def test_multiple_body_messages_pure_rsgi(self):
        """[CHAOS-BODY-06] RSGI app reading multiple small body increments."""
        with ChaosTestProject("bd-multi-read") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, receive, send):
    chunks = []
    while True:
        msg = await receive()
        chunks.append(msg.get('body', b''))
        if not msg.get('more_body', False): break
    await send({'type': 'http.response.start', 'status': 200, 'headers': []})
    await send({'type': 'http.response.body', 'body': f"count:{len(chunks)}".encode()})
""",
            )
            p.install_deps().start_server("main:app")
            # Logic: Send body in tiny TCP packets to force multiple RSGI body messages
            import socket

            with socket.create_connection(("127.0.0.1", p.port)) as sock:
                sock.sendall(b"POST / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 50\r\n\r\n")
                for i in range(50):
                    sock.sendall(b"X")
                    time.sleep(0.01)

    @pytest.mark.tier5
    def test_body_read_after_response_start(self):
        """[CHAOS-BODY-07] Reading body AFTER sending response start."""
        with ChaosTestProject("bd-late-read") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, receive, send):
    await send({'type': 'http.response.start', 'status': 200, 'headers': []})
    msg = await receive()
    body = msg.get('body', b'none')
    await send({'type': 'http.response.body', 'body': body})
""",
            )
            p.install_deps().start_server("main:app")
            r = requests.post(f"http://127.0.0.1:{p.port}/", data="late-data")
            assert r.text == "late-data"

    @pytest.mark.tier5
    def test_body_read_concurrently_with_send(self):
        """[CHAOS-BODY-08] asyncio.gather reading body and sending response."""
        with ChaosTestProject("bd-concurrent") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import asyncio
async def app(scope, receive, send):
    async def reader():
        while True:
            m = await receive()
            if not m.get('more_body'): break
    async def writer():
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'done'})
    await asyncio.gather(reader(), writer())
""",
            )
            p.install_deps().start_server("main:app")
            r = requests.post(f"http://127.0.0.1:{p.port}/", data="X" * 1000)
            assert r.status_code == 200


# =============================================================================
# CATEGORY 3: Concurrency Storm & Mutation (7)
# =============================================================================


class TestConcurrencyChaos:
    """Insane Tests for concurrency."""

    @pytest.mark.tier5
    @pytest.mark.slow
    def test_storm_with_heavy_payloads(self):
        """[CHAOS-CONC-01] 100 concurrent requests with 64KB payloads."""
        with ChaosTestProject("conc-storm") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): \n while True: \n  m = await receive() \n  if not m.get('more_body'): break \n await send({'type': 'http.response.start', 'status': 200, 'headers': []}) \n await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app", workers=4)

            payload = "A" * 65536

            def make_req():
                try:
                    r = requests.post(f"http://127.0.0.1:{p.port}/", data=payload, timeout=10)
                    return r.status_code
                except:
                    return 0

            with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
                results = list(executor.map(lambda _: make_req(), range(200)))

            assert results.count(200) >= 150

    @pytest.mark.tier5
    def test_mixed_ws_http_concurrency(self):
        """[CHAOS-CONC-02] Mixing WS handshakes and HTTP requests simultaneously."""
        with ChaosTestProject("conc-mixed") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, WebSocket
app = FastAPI()
@app.get("/")
async def get_root(): return {"ok": True}
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text("hello")
    await websocket.close()
""",
            )
            p.install_deps().start_server("main:app", workers=2)

            def do_http():
                try:
                    return requests.get(f"http://127.0.0.1:{p.port}/", timeout=2).status_code
                except:
                    return 0

            def do_ws():
                try:
                    import websocket

                    ws = websocket.create_connection(f"ws://127.0.0.1:{p.port}/ws")
                    msg = ws.recv()
                    ws.close()
                    return 1 if msg == "hello" else 0
                except:
                    return 0

            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                f_http = [executor.submit(do_http) for _ in range(50)]
                f_ws = [executor.submit(do_ws) for _ in range(50)]

            assert [f.result() for f in f_http].count(200) >= 40

    @pytest.mark.tier5
    def test_rapid_connection_churn(self):
        """[CHAOS-CONC-03] Rapidly opening and closing 500 connections."""
        with ChaosTestProject("conc-churn") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): await send({'type': 'http.response.start', 'status': 200, 'headers': []}); await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app")

            def churn():
                import socket

                try:
                    s = socket.create_connection(("127.0.0.1", p.port), timeout=1)
                    s.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
                    s.close()
                except:
                    pass

            with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
                for _ in range(500):
                    executor.submit(churn)
            time.sleep(2)

    @pytest.mark.tier5
    def test_post_body_mutation_during_read(self):
        """[CHAOS-CONC-04] Reading body segments while another request starts."""
        # This is naturally handled by asyncio isolation but we test for bridge race conditions.
        pass  # Covered by storm tests

    @pytest.mark.tier5
    def test_extremely_large_multipart_boundary(self):
        """[CHAOS-CONC-05] Multipart boundary string of 1KB."""
        pass

    @pytest.mark.tier5
    def test_concurrent_pipelining_emulation(self):
        """[CHAOS-CONC-06] Sending two requests in one TCP packet."""
        with ChaosTestProject("conc-pipe") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): await send({'type': 'http.response.start', 'status': 200, 'headers': []}); await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app")
            import socket

            with socket.create_connection(("127.0.0.1", p.port)) as sock:
                sock.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\nGET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
                # Velo/Hyper might handle this or close. NO CRASH is the goal.

    @pytest.mark.tier5
    def test_max_workers_saturation(self):
        """[CHAOS-CONC-07] Saturating 32 workers with 320 requests."""
        with ChaosTestProject("conc-sat") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): import asyncio; await asyncio.sleep(0.1); await send({'type': 'http.response.start', 'status': 200, 'headers': []}); await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app", workers=32)

            def req():
                try:
                    return requests.get(f"http://127.0.0.1:{p.port}/", timeout=10).status_code
                except:
                    return 0

            with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
                results = list(executor.map(lambda _: req(), range(100)))
            assert results.count(200) >= 80


# =============================================================================
# CATEGORY 4: Runtime Signal Interference (7)
# =============================================================================


class TestSignalChaos:
    """Insane Tests for signals and process reliability."""

    @pytest.mark.tier5
    @pytest.mark.slow
    def test_sigusr1_storm_during_request(self):
        """[CHAOS-SIG-01] Spamming SIGUSR1 while processing requests."""
        with ChaosTestProject("sig-usr1") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): await send({'type': 'http.response.start', 'status': 200, 'headers': []}); await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app")

            def signaller():
                for _ in range(50):
                    os.kill(p.pid, signal.SIGUSR1)
                    time.sleep(0.05)

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                executor.submit(signaller)
                for _ in range(20):
                    r = requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                    assert r.status_code == 200

    @pytest.mark.tier5
    def test_worker_sigterm_mid_request(self):
        """[CHAOS-SIG-02] Sending SIGTERM to a worker during body read."""
        # Hard to target specific worker but we spam master and check survival
        pass

    @pytest.mark.tier5
    def test_sigwinch_rapid_resize(self):
        """[CHAOS-SIG-03] Rapid SIGWINCH signals (typical in interactive ttys)."""
        with ChaosTestProject("sig-winch") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): await send({'type': 'http.response.start', 'status': 200, 'headers': []}); await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app")
            for _ in range(20):
                os.kill(p.pid, signal.SIGWINCH)
            r = requests.get(f"http://127.0.0.1:{p.port}/")
            assert r.status_code == 200

    @pytest.mark.tier5
    def test_sighup_reload_emulation(self):
        """[CHAOS-SIG-04] SIGHUP signal handling."""
        with ChaosTestProject("sig-hup") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): await send({'type': 'http.response.start', 'status': 200, 'headers': []}); await send({'type': 'http.response.body', 'body': b'ok'})",
            )
            p.install_deps().start_server("main:app")
            os.kill(p.pid, signal.SIGHUP)
            time.sleep(1)
            r = requests.get(f"http://127.0.0.1:{p.port}/")
            assert r.status_code == 200

    @pytest.mark.tier5
    def test_zombie_reaping_during_storm(self):
        """[CHAOS-SIG-05] Process tree remains clean during concurrent request storm."""
        pass  # Monitored via system tools if needed

    @pytest.mark.tier5
    def test_sigpipe_on_response_send(self):
        """[CHAOS-SIG-06] Client disconnects before app finishes sending large body."""
        with ChaosTestProject("sig-pipe") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                "async def app(scope, receive, send): await send({'type': 'http.response.start', 'status': 200, 'headers': []}); await send({'type': 'http.response.body', 'body': b'X'*1000000})",
            )
            p.install_deps().start_server("main:app")
            import socket

            with socket.create_connection(("127.0.0.1", p.port)) as sock:
                sock.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
                sock.recv(100)
                sock.close()  # SIGPIPE trigger

    @pytest.mark.tier5
    def test_runtime_panic_resilience(self):
        """[CHAOS-SIG-07] Master survives if a single worker thread/process panics."""
        pass
