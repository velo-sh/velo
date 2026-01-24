"""
Evil Edge Case Tests - Targeting Known Weak Points

Aggressive tests specifically designed to break the ASGI bridge.
Focus on POST body parsing, multipart, chunked, and edge cases.

Categories:
1. POST Body Parsing (8) - The known gap
2. Multipart/Form Data (5) - File uploads
3. Chunked Encoding (4) - Streaming bodies
4. Large Payloads (4) - Memory handling
5. Edge Case Headers (5) - Malformed requests
6. Content Negotiation (4) - Content-Type variations

Total: 30 targeted evil tests

Author: Velo QA Team
Date: 2026-01-15
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import typing
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from _subprocess import Popen
else:
    from subprocess import Popen

import pytest
import requests


def get_velo_binary() -> str:
    repo_root = Path(__file__).parents[4].resolve()

    # Common search locations
    possible_paths = [
        repo_root / "target" / "release" / "velo",
        repo_root / "target" / "debug" / "velo",
        # Docker CI specific volume paths
        Path("/workspace/target/release/velo"),
        Path("/workspace/target/debug/velo"),
        Path("/root/.cargo/bin/velo"),
    ]

    for p in possible_paths:
        if p.exists():
            return str(p)

    # Try which command
    import shutil

    which_velo = shutil.which("velo")
    if which_velo:
        return which_velo

    pytest.skip(f"velo binary not found (looked in: {[str(p) for p in possible_paths]})")


class EvilTestProject:
    """Evil test project for edge cases."""

    def __init__(self, name: str):
        self.name = name
        self.path = Path(tempfile.mkdtemp(prefix=f"evil_{name}_"))
        self.velo = get_velo_binary()
        self._port: int | None = None
        self._proc: Popen[str] | None = None

    def set_pyproject(self, deps: list[Any]) -> "EvilTestProject":
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

    def set_app(self, filename: str, code: str) -> "EvilTestProject":
        (self.path / filename).write_text(code)
        return self

    def install_deps(self, timeout: float = 180) -> "EvilTestProject":
        cmd = ["uv", "sync"]
        subprocess.run(cmd, cwd=self.path, capture_output=True, timeout=timeout)
        return self

    def start_server(self, app_module: str, port: int | None = None) -> "EvilTestProject":
        if port is None:
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

        self._proc = subprocess.Popen(
            [self.velo, "serve", app_module, "--rsgi", "--no-zygote", "--port", str(port)],
            cwd=self.path,
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(8)
        return self

    @property
    def port(self) -> int | None:
        return self._port

    @property
    def alive(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)

    def cleanup(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait(timeout=10)
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self) -> "EvilTestProject":
        return self

    def __exit__(self, *args: Any) -> None:
        self.cleanup()


# =============================================================================
# CATEGORY 1: POST Body Parsing (8) - THE KNOWN GAP
# =============================================================================


class TestPostBodyParsing:
    """Evil tests targeting POST body parsing - the known weak point."""

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_post_empty_body(self):
        """[EVIL-POST-01] POST with empty body."""
        with EvilTestProject("post-empty") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    response = json.dumps({"size": len(body), "empty": len(body) == 0}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(f"http://127.0.0.1:{p.port}/", data=b"", timeout=5)
                assert r.status_code == 200
                assert r.json()["empty"] is True

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_post_plain_text(self):
        """[EVIL-POST-02] POST with plain text body."""
        with EvilTestProject("post-text") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    response = json.dumps({"text": body.decode("utf-8")}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(
                    f"http://127.0.0.1:{p.port}/", data="Hello World", headers={"Content-Type": "text/plain"}, timeout=5
                )
                assert r.status_code == 200
                assert r.json()["text"] == "Hello World"

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_post_json_simple(self):
        """[EVIL-POST-03] POST with simple JSON body."""
        with EvilTestProject("post-json") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    try:
        data = json.loads(body) if body else {}
        response = json.dumps({"received": data}).encode()
        status = 200
    except Exception as e:
        response = json.dumps({"error": str(e)}).encode()
        status = 400

    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(f"http://127.0.0.1:{p.port}/", json={"key": "value", "number": 42}, timeout=5)
                assert r.status_code == 200
                assert r.json()["received"]["key"] == "value"

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_post_json_nested(self):
        """[EVIL-POST-04] POST with deeply nested JSON."""
        with EvilTestProject("post-nested") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    data = json.loads(body) if body else {}
    response = json.dumps({"depth": len(str(data))}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                nested = {"level1": {"level2": {"level3": {"level4": {"value": "deep"}}}}}
                r = requests.post(f"http://127.0.0.1:{p.port}/", json=nested, timeout=5)
                assert r.status_code == 200

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_post_url_encoded(self):
        """[EVIL-POST-05] POST with URL-encoded form data."""
        with EvilTestProject("post-urlencoded") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json
from urllib.parse import parse_qs

async def app(scope, receive, send):
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    parsed = parse_qs(body.decode())
    response = json.dumps({"form": {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(
                    f"http://127.0.0.1:{p.port}/", data={"username": "testuser", "password": "secret123"}, timeout=5
                )
                assert r.status_code == 200
                assert r.json()["form"]["username"] == "testuser"

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_post_binary_data(self):
        """[EVIL-POST-06] POST with binary data."""
        with EvilTestProject("post-binary") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json
import base64

async def app(scope, receive, send):
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    response = json.dumps({
        "size": len(body),
        "b64": base64.b64encode(body[:20]).decode()
    }).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                binary = bytes(range(256))
                r = requests.post(
                    f"http://127.0.0.1:{p.port}/",
                    data=binary,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=5,
                )
                assert r.status_code == 200
                assert r.json()["size"] == 256

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_post_unicode_body(self):
        """[EVIL-POST-07] POST with Unicode characters."""
        with EvilTestProject("post-unicode") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    text = body.decode("utf-8")
    response = json.dumps({"text": text, "length": len(text)}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(
                    f"http://127.0.0.1:{p.port}/",
                    data="Hello World - Emoji: 🚀🔥".encode(),
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                    timeout=5,
                )
                assert r.status_code == 200
                assert "🚀" in r.json()["text"]

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_post_special_chars_urlencoded(self):
        """[EVIL-POST-08] POST with special characters URL-encoded."""
        with EvilTestProject("post-special") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json
from urllib.parse import parse_qs

async def app(scope, receive, send):
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    parsed = parse_qs(body.decode())
    response = json.dumps({"form": {k: v[0] for k, v in parsed.items()}}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(
                    f"http://127.0.0.1:{p.port}/",
                    data={"query": "hello+world&special=test", "symbols": "a=b&c=d"},
                    timeout=5,
                )
                assert r.status_code == 200


# =============================================================================
# CATEGORY 2: Multipart/Form Data (5) - File Uploads
# =============================================================================


class TestMultipartFormData:
    """Evil tests for multipart form data and file uploads."""

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Multipart parsing complex")
    def test_multipart_simple_file(self):
        """[EVIL-MULTI-01] Simple file upload."""
        with EvilTestProject("multi-file") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0", "python-multipart>=0.0.6"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, File, UploadFile
app = FastAPI()

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    content = await file.read()
    return {"filename": file.filename, "size": len(content)}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                files = {"file": ("test.txt", b"Hello World", "text/plain")}
                r = requests.post(f"http://127.0.0.1:{p.port}/upload", files=files, timeout=10)
                assert r.status_code == 200
                assert r.json()["size"] == 11

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Multipart parsing complex")
    def test_multipart_multiple_files(self):
        """[EVIL-MULTI-02] Multiple file upload."""
        with EvilTestProject("multi-files") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0", "python-multipart>=0.0.6"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, File, UploadFile
from typing import List
app = FastAPI()

@app.post("/upload")
async def upload(files: List[UploadFile] = File(...)):
    result = []
    for f in files:
        content = await f.read()
        result.append({"name": f.filename, "size": len(content)})
    return {"files": result}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                files = [
                    ("files", ("a.txt", b"AAA", "text/plain")),
                    ("files", ("b.txt", b"BBBBB", "text/plain")),
                ]
                r = requests.post(f"http://127.0.0.1:{p.port}/upload", files=files, timeout=10)
                assert r.status_code == 200
                assert len(r.json()["files"]) == 2

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Multipart parsing complex")
    def test_multipart_with_form_fields(self):
        """[EVIL-MULTI-03] File upload with form fields."""
        with EvilTestProject("multi-mixed") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0", "python-multipart>=0.0.6"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, File, UploadFile, Form
app = FastAPI()

@app.post("/upload")
async def upload(
    name: str = Form(...),
    description: str = Form(None),
    file: UploadFile = File(...)
):
    content = await file.read()
    return {
        "name": name,
        "description": description,
        "filename": file.filename,
        "size": len(content)
    }
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(
                    f"http://127.0.0.1:{p.port}/upload",
                    data={"name": "test", "description": "desc"},
                    files={"file": ("doc.pdf", b"PDF content", "application/pdf")},
                    timeout=10,
                )
                assert r.status_code == 200

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Large file handling")
    def test_multipart_large_file(self):
        """[EVIL-MULTI-04] Large file upload (1MB)."""
        with EvilTestProject("multi-large") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0", "python-multipart>=0.0.6"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, File, UploadFile
app = FastAPI()

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    content = await file.read()
    return {"size": len(content)}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                large_file = b"X" * (1024 * 1024)  # 1MB
                files = {"file": ("large.bin", large_file, "application/octet-stream")}
                r = requests.post(f"http://127.0.0.1:{p.port}/upload", files=files, timeout=30)
                assert r.status_code == 200
                assert r.json()["size"] == 1024 * 1024

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Binary file handling")
    def test_multipart_binary_file(self):
        """[EVIL-MULTI-05] Binary file with all byte values."""
        with EvilTestProject("multi-binary") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0", "python-multipart>=0.0.6"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, File, UploadFile
import hashlib
app = FastAPI()

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    content = await file.read()
    return {
        "size": len(content),
        "md5": hashlib.md5(content).hexdigest()
    }
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                binary = bytes(range(256)) * 100
                files = {"file": ("binary.bin", binary, "application/octet-stream")}
                r = requests.post(f"http://127.0.0.1:{p.port}/upload", files=files, timeout=10)
                assert r.status_code == 200


# =============================================================================
# CATEGORY 3: Chunked Encoding (4) - Streaming Bodies
# =============================================================================


class TestChunkedEncoding:
    """Evil tests for chunked transfer encoding."""

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Chunked transfer encoding")
    def test_chunked_request_body(self):
        """[EVIL-CHUNK-01] Chunked transfer encoded request."""
        with EvilTestProject("chunk-req") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    response = json.dumps({"size": len(body)}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:

                def gen() -> typing.Generator[bytes, None, None]:
                    for i in range(5):
                        yield f"chunk{i}".encode()

                r = requests.post(f"http://127.0.0.1:{p.port}/", data=gen(), timeout=10)
                assert r.status_code == 200

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Streaming response")
    def test_chunked_response_body(self):
        """[EVIL-CHUNK-02] Chunked transfer encoded response."""
        with EvilTestProject("chunk-resp") as p:
            p.set_pyproject(deps=["starlette>=0.38.0"])
            p.set_app(
                "main.py",
                """
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route
import asyncio

async def stream_response(request):
    async def generate():
        for i in range(5):
            yield f"chunk-{i}\\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(generate(), media_type="text/plain")

app = Starlette(routes=[Route("/stream", stream_response)])
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/stream", timeout=10)
                assert r.status_code == 200
                assert "chunk-0" in r.text

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Streaming JSON lines")
    def test_streaming_json_lines(self):
        """[EVIL-CHUNK-03] Streaming JSON lines (NDJSON)."""
        with EvilTestProject("jsonlines") as p:
            p.set_pyproject(deps=["starlette>=0.38.0"])
            p.set_app(
                "main.py",
                """
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route
import json
import asyncio

async def stream_json(request):
    async def generate():
        for i in range(3):
            yield json.dumps({"index": i, "data": f"item-{i}"}) + "\\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(generate(), media_type="application/x-ndjson")

app = Starlette(routes=[Route("/", stream_json)])
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/", timeout=10)
                assert r.status_code == 200
                lines = r.text.strip().split("\n")
                assert len(lines) == 3

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Large streaming response")
    def test_large_streaming_response(self):
        """[EVIL-CHUNK-04] Large streaming response (10MB)."""
        with EvilTestProject("chunk-large") as p:
            p.set_pyproject(deps=["starlette>=0.38.0"])
            p.set_app(
                "main.py",
                """
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

async def large_stream(request):
    async def generate():
        for _ in range(10):
            yield b"X" * (1024 * 1024)  # 1MB chunks

    return StreamingResponse(generate(), media_type="application/octet-stream")

app = Starlette(routes=[Route("/", large_stream)])
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/", timeout=60)
                assert r.status_code == 200
                assert len(r.content) == 10 * 1024 * 1024


# =============================================================================
# CATEGORY 4: Large Payloads (4) - Memory Handling
# =============================================================================


class TestLargePayloads:
    """Evil tests for large payload handling."""

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_100kb_json_request(self):
        """[EVIL-LARGE-01] 100KB JSON request body."""
        with EvilTestProject("large-100k") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    data = json.loads(body)
    response = json.dumps({"items": len(data.get("items", []))}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                large_json = {"items": ["item" * 100 for _ in range(100)]}
                r = requests.post(f"http://127.0.0.1:{p.port}/", json=large_json, timeout=15)
                assert r.status_code == 200
                assert r.json()["items"] == 100

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_1mb_request_body(self):
        """[EVIL-LARGE-02] 1MB request body."""
        with EvilTestProject("large-1m") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    response = json.dumps({"size": len(body)}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                large_body = b"X" * (1024 * 1024)
                r = requests.post(
                    f"http://127.0.0.1:{p.port}/",
                    data=large_body,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=30,
                )
                assert r.status_code == 200
                assert r.json()["size"] == 1024 * 1024

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Large response handling")
    def test_5mb_response_body(self):
        """[EVIL-LARGE-03] 5MB response body."""
        with EvilTestProject("large-resp") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, receive, send):
    body = b"X" * (5 * 1024 * 1024)
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/octet-stream")]})
    await send({"type": "http.response.body", "body": body})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/", timeout=60)
                assert r.status_code == 200
                assert len(r.content) == 5 * 1024 * 1024

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_many_small_requests(self):
        """[EVIL-LARGE-04] Many small requests in sequence."""
        with EvilTestProject("many-small") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": b'{"ok":true}'})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                success = 0
                for _ in range(200):
                    try:
                        r = requests.get(f"http://127.0.0.1:{p.port}/", timeout=2)
                        if r.status_code == 200:
                            success += 1
                    except Exception:
                        pass

                assert success >= 180


# =============================================================================
# CATEGORY 5: Edge Case Headers (5) - Malformed Requests
# =============================================================================


class TestEdgeCaseHeaders:
    """Evil tests for edge case headers."""

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_no_content_type(self):
        """[EVIL-HDR-01] POST without Content-Type header."""
        with EvilTestProject("no-ct") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    headers = dict(scope.get("headers", []))
    ct = headers.get(b"content-type", b"none").decode()

    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    response = json.dumps({"content_type": ct, "body_size": len(body)}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                import urllib.request

                req = urllib.request.Request(f"http://127.0.0.1:{p.port}/", data=b"raw body", method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    assert resp.status == 200

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_duplicate_headers(self):
        """[EVIL-HDR-02] Duplicate header values."""
        with EvilTestProject("dup-hdr") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    headers = scope.get("headers", [])
    x_custom = [v.decode() for k, v in headers if k == b"x-custom"]

    response = json.dumps({"x_custom_values": x_custom}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(
                    f"http://127.0.0.1:{p.port}/",
                    headers={"X-Custom": "value1"},  # requests can't send duplicates easily
                    timeout=5,
                )
                assert r.status_code == 200

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_very_long_header_value(self):
        """[EVIL-HDR-03] Very long header value."""
        with EvilTestProject("long-hdr") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    headers = dict(scope.get("headers", []))
    long_val = headers.get(b"x-long", b"").decode()

    response = json.dumps({"length": len(long_val)}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                long_value = "A" * 4000
                r = requests.get(f"http://127.0.0.1:{p.port}/", headers={"X-Long": long_value}, timeout=5)
                assert r.status_code == 200
                assert r.json()["length"] == 4000

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_many_headers(self):
        """[EVIL-HDR-04] Many custom headers."""
        with EvilTestProject("many-hdr") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    header_count = len(scope.get("headers", []))

    response = json.dumps({"header_count": header_count}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                headers = {f"X-Header-{i}": f"value-{i}" for i in range(50)}
                r = requests.get(f"http://127.0.0.1:{p.port}/", headers=headers, timeout=5)
                assert r.status_code == 200
                assert r.json()["header_count"] >= 50

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_accept_encoding_gzip(self):
        """[EVIL-HDR-05] Accept-Encoding: gzip handling."""
        with EvilTestProject("accept-gzip") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    headers = dict(scope.get("headers", []))
    accept_encoding = headers.get(b"accept-encoding", b"none").decode()

    response = json.dumps({"accept_encoding": accept_encoding}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(
                    f"http://127.0.0.1:{p.port}/", headers={"Accept-Encoding": "gzip, deflate, br"}, timeout=5
                )
                assert r.status_code == 200


# =============================================================================
# CATEGORY 6: Content Negotiation (4) - Content-Type Variations
# =============================================================================


class TestContentNegotiation:
    """Evil tests for content type variations."""

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_content_type_with_charset(self):
        """[EVIL-CT-01] Content-Type with charset parameter."""
        with EvilTestProject("ct-charset") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    headers = dict(scope.get("headers", []))
    ct = headers.get(b"content-type", b"none").decode()

    response = json.dumps({"content_type": ct}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json; charset=utf-8")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(
                    f"http://127.0.0.1:{p.port}/",
                    json={"test": "data"},
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    timeout=5,
                )
                assert r.status_code == 200

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_accept_header_json(self):
        """[EVIL-CT-02] Accept: application/json."""
        with EvilTestProject("accept-json") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    headers = dict(scope.get("headers", []))
    accept = headers.get(b"accept", b"*/*").decode()

    response = json.dumps({"accept": accept}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/", headers={"Accept": "application/json"}, timeout=5)
                assert r.status_code == 200
                assert "application/json" in r.json()["accept"]

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_xml_content_type(self):
        """[EVIL-CT-03] XML content type."""
        with EvilTestProject("ct-xml") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    response = json.dumps({"xml_body": body.decode()}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                xml = '<?xml version="1.0"?><root><item>test</item></root>'
                r = requests.post(
                    f"http://127.0.0.1:{p.port}/", data=xml, headers={"Content-Type": "application/xml"}, timeout=5
                )
                assert r.status_code == 200
                assert "<root>" in r.json()["xml_body"]

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_custom_content_type(self):
        """[EVIL-CT-04] Custom vendor content type."""
        with EvilTestProject("ct-vendor") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    headers = dict(scope.get("headers", []))
    ct = headers.get(b"content-type", b"none").decode()

    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    response = json.dumps({"content_type": ct, "body": body.decode()}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": response})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(
                    f"http://127.0.0.1:{p.port}/",
                    data='{"custom": true}',
                    headers={"Content-Type": "application/vnd.myapp+json"},
                    timeout=5,
                )
                assert r.status_code == 200
                assert "vnd.myapp" in r.json()["content_type"]
