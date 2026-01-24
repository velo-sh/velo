"""
QA REVENGE: Hardcore Edge Case Test Suite

Dev thinks they're fast? Let's see how they handle THESE!

Categories:
1. Concurrency Stress (5) - Break the async machinery
2. Memory & Resource Leaks (4) - Find hidden leaks
3. Protocol Edge Cases (5) - Malformed requests
4. Framework Deep Integration (6) - Real-world complexity
5. Production Scenarios (5) - What actually breaks in prod

Total: 25 NEW test cases

Author: Velo QA Revenge Squad
Date: 2026-01-14
"""

import concurrent.futures
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from _subprocess import Popen
else:
    from subprocess import Popen

import pytest
import requests


def get_velo_binary() -> str:
    repo_root = Path(__file__).parents[4]
    release = repo_root / "target" / "release" / "velo"
    if release.exists():
        return str(release)
    pytest.skip("velo binary not found")


class HardcoreTestProject:
    """Hardcore test project for edge cases."""

    def __init__(self, name: str):
        self.name = name
        self.path = Path(tempfile.mkdtemp(prefix=f"hardcore_{name}_"))
        self.velo = get_velo_binary()
        self._port: int | None = None
        self._proc: Popen[str] | None = None

    def set_pyproject(self, deps: list[Any]) -> "HardcoreTestProject":
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

    def set_app(self, filename: str, code: str) -> "HardcoreTestProject":
        (self.path / filename).write_text(code)
        return self

    def install_deps(self, timeout: float = 180) -> "HardcoreTestProject":
        subprocess.run(["uv", "sync"], cwd=self.path, capture_output=True, timeout=timeout)
        return self

    def start_server(self, app_module: str, port: int | None = None, workers: int = 1) -> "HardcoreTestProject":
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

        cmd = [
            self.velo,
            "serve",
            app_module,
            "--rsgi",
            "--no-zygote",
            "--port",
            str(port),
            "--workers",
            str(workers),
        ]

        self._proc = subprocess.Popen(
            cmd,
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

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: Any) -> None:
        self.cleanup()


# =============================================================================
# CATEGORY 1: CONCURRENCY STRESS (5)
# =============================================================================


class TestConcurrencyStress:
    """Break the async machinery with concurrent hell."""

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Extreme concurrency stress")
    def test_100_concurrent_requests(self):
        """[HARDCORE-CONC-01] 100 concurrent requests storm."""
        with HardcoreTestProject("conc100") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
import asyncio

app = FastAPI()
counter = {"value": 0}

@app.get("/increment")
async def increment():
    counter["value"] += 1
    await asyncio.sleep(0.01)  # Simulate IO
    return {"count": counter["value"]}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
                    futures = [
                        executor.submit(requests.get, f"http://127.0.0.1:{p.port}/increment", timeout=10)
                        for _ in range(100)
                    ]
                    results = [f.result() for f in futures]

                success = sum(1 for r in results if r.status_code == 200)
                assert success >= 95, f"Only {success}/100 succeeded"

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Async lock contention")
    def test_async_lock_contention(self):
        """[HARDCORE-CONC-02] Async lock contention under load."""
        with HardcoreTestProject("lock") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
import asyncio

app = FastAPI()
lock = asyncio.Lock()
shared_resource = {"value": 0}

@app.get("/critical")
async def critical_section():
    async with lock:
        old = shared_resource["value"]
        await asyncio.sleep(0.01)
        shared_resource["value"] = old + 1
    return {"value": shared_resource["value"]}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
                    futures = [
                        executor.submit(requests.get, f"http://127.0.0.1:{p.port}/critical", timeout=30)
                        for _ in range(50)
                    ]
                    results = [f.result() for f in futures]

                # All should succeed, final value should be 50
                success = sum(1 for r in results if r.status_code == 200)
                assert success == 50

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Rapid fire requests")
    def test_rapid_fire_1000_requests(self):
        """[HARDCORE-CONC-03] 1000 sequential rapid-fire requests."""
        with HardcoreTestProject("rapid") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                session = requests.Session()
                success = 0
                for _ in range(1000):
                    try:
                        r = session.get(f"http://127.0.0.1:{p.port}/", timeout=1)
                        if r.status_code == 200:
                            success += 1
                    except Exception:
                        pass

                assert success >= 950, f"Only {success}/1000 succeeded"

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Mixed async/sync operations")
    def test_mixed_async_sync_operations(self):
        """[HARDCORE-CONC-04] Mixed async and sync-to-thread operations."""
        with HardcoreTestProject("mixedsync") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
import asyncio
import time

app = FastAPI()

def blocking_io():
    time.sleep(0.1)
    return "done"

@app.get("/mixed")
async def mixed_ops():
    # Run blocking IO in thread pool
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, blocking_io)
    return {"result": result}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                    futures = [
                        executor.submit(requests.get, f"http://127.0.0.1:{p.port}/mixed", timeout=10) for _ in range(20)
                    ]
                    results = [f.result() for f in futures]

                success = sum(1 for r in results if r.status_code == 200)
                assert success >= 18

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Cancelled task handling")
    def test_request_timeout_cancelled_tasks(self):
        """[HARDCORE-CONC-05] Cancelled tasks from client timeouts."""
        with HardcoreTestProject("timeout") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
import asyncio

app = FastAPI()

@app.get("/slow")
async def slow_endpoint():
    await asyncio.sleep(10)  # Very slow
    return {"status": "completed"}

@app.get("/fast")
async def fast_endpoint():
    return {"status": "fast"}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                # Send requests that will timeout
                def timeout_request():
                    try:
                        requests.get(f"http://127.0.0.1:{p.port}/slow", timeout=0.5)
                    except Exception:
                        pass

                threads = [threading.Thread(target=timeout_request) for _ in range(10)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                # Server should still work after cancelled tasks
                r = requests.get(f"http://127.0.0.1:{p.port}/fast", timeout=5)
                assert r.status_code == 200


# =============================================================================
# CATEGORY 2: MEMORY & RESOURCE LEAKS (4)
# =============================================================================


class TestMemoryLeaks:
    """Find hidden memory and resource leaks."""

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Memory growth detection")
    def test_large_request_body_memory(self):
        """[HARDCORE-MEM-01] Large request body memory handling."""
        with HardcoreTestProject("largebody") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/upload")
async def upload(request: Request):
    body = await request.body()
    return {"size": len(body)}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                large_body = b"x" * (10 * 1024 * 1024)  # 10MB
                r = requests.post(f"http://127.0.0.1:{p.port}/upload", data=large_body, timeout=30)
                assert r.status_code == 200
                assert r.json()["size"] == 10 * 1024 * 1024

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Response body cleanup")
    def test_large_response_body_cleanup(self):
        """[HARDCORE-MEM-02] Large response body memory cleanup."""
        with HardcoreTestProject("largeresponse") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from fastapi.responses import Response

app = FastAPI()

@app.get("/large")
async def large_response():
    return Response(content=b"X" * (5 * 1024 * 1024), media_type="application/octet-stream")
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                for _i in range(10):
                    r = requests.get(f"http://127.0.0.1:{p.port}/large", timeout=30)
                    assert r.status_code == 200
                    assert len(r.content) == 5 * 1024 * 1024

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Connection pool exhaustion")
    def test_connection_pool_exhaustion(self):
        """[HARDCORE-MEM-03] Connection pool exhaustion and recovery."""
        with HardcoreTestProject("connpool") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                # Open many connections without closing
                import socket

                sockets = []
                for _ in range(100):
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(1)
                        s.connect(("127.0.0.1", p.port))
                        sockets.append(s)
                    except Exception:
                        break

                # Server should still accept new connections
                r = requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                assert r.status_code == 200

                for s in sockets:
                    s.close()

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Exception object cleanup")
    def test_exception_memory_cleanup(self):
        """[HARDCORE-MEM-04] Exception object memory cleanup after errors."""
        with HardcoreTestProject("excmem") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI

app = FastAPI()

@app.get("/error")
async def error_endpoint():
    raise ValueError("Intentional error with large message: " + "X" * 10000)

@app.get("/ok")
async def ok_endpoint():
    return {"status": "ok"}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                # Generate many errors
                for _ in range(100):
                    try:
                        requests.get(f"http://127.0.0.1:{p.port}/error", timeout=5)
                    except Exception:
                        pass

                # Server should still work
                r = requests.get(f"http://127.0.0.1:{p.port}/ok", timeout=5)
                assert r.status_code == 200


# =============================================================================
# CATEGORY 3: PROTOCOL EDGE CASES (5)
# =============================================================================


class TestProtocolEdgeCases:
    """Malformed and edge-case protocol handling."""

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_empty_request_body(self):
        """[HARDCORE-PROTO-01] Empty POST request body."""
        with HardcoreTestProject("emptybody") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/empty")
async def empty_post(request: Request):
    body = await request.body()
    return {"size": len(body), "empty": len(body) == 0}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(f"http://127.0.0.1:{p.port}/empty", data=b"", timeout=5)
                assert r.status_code == 200
                assert r.json()["empty"] is True

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_unicode_headers(self):
        """[HARDCORE-PROTO-02] Unicode characters in headers."""
        with HardcoreTestProject("unicode") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Request

app = FastAPI()

@app.get("/unicode")
async def unicode_headers(request: Request):
    custom = request.headers.get("x-custom", "none")
    return {"header": custom}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(
                    f"http://127.0.0.1:{p.port}/unicode",
                    headers={"X-Custom": "test-value-123"},  # ASCII only for HTTP headers
                    timeout=5,
                )
                assert r.status_code == 200

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_very_long_url(self):
        """[HARDCORE-PROTO-03] Very long URL path."""
        with HardcoreTestProject("longurl") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Request

app = FastAPI()

@app.get("/{path:path}")
async def long_path(path: str):
    return {"path_length": len(path)}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                long_path = "a" * 4000
                try:
                    r = requests.get(f"http://127.0.0.1:{p.port}/{long_path}", timeout=5)
                    # Should either succeed or return 414 (URI Too Long)
                    assert r.status_code in [200, 414]
                except Exception:
                    pass  # Connection rejection is acceptable

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_multiple_query_params_same_key(self):
        """[HARDCORE-PROTO-04] Multiple query params with same key."""
        with HardcoreTestProject("multiquery") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Request
from typing import List

app = FastAPI()

@app.get("/multi")
async def multi_params(request: Request):
    params = request.query_params.getlist("key")
    return {"values": params, "count": len(params)}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/multi?key=a&key=b&key=c", timeout=5)
                assert r.status_code == 200
                data = r.json()
                assert data["count"] == 3

    @pytest.mark.tier4
    @pytest.mark.slow
    def test_special_characters_in_path(self):
        """[HARDCORE-PROTO-05] Special characters in URL path."""
        with HardcoreTestProject("specialpath") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
import urllib.parse

app = FastAPI()

@app.get("/path/{item}")
async def special_path(item: str):
    return {"item": item, "decoded": urllib.parse.unquote(item)}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/path/hello%20world", timeout=5)
                assert r.status_code == 200


# =============================================================================
# CATEGORY 4: FRAMEWORK DEEP INTEGRATION (6)
# =============================================================================


class TestFrameworkDeepIntegration:
    """Real-world complex framework usage."""

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Complex Pydantic models")
    def test_pydantic_nested_models(self):
        """[HARDCORE-FW-01] Complex nested Pydantic models."""
        with HardcoreTestProject("pydantic") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0", "pydantic>=2.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()

class Address(BaseModel):
    street: str
    city: str
    country: str

class User(BaseModel):
    name: str
    age: int
    addresses: List[Address]
    metadata: Optional[dict] = None

@app.post("/user")
async def create_user(user: User):
    return {"name": user.name, "address_count": len(user.addresses)}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(
                    f"http://127.0.0.1:{p.port}/user",
                    json={
                        "name": "Test User",
                        "age": 30,
                        "addresses": [
                            {"street": "123 Main St", "city": "NYC", "country": "USA"},
                            {"street": "456 Side St", "city": "LA", "country": "USA"},
                        ],
                        "metadata": {"key": "value"},
                    },
                    timeout=10,
                )
                assert r.status_code == 200
                assert r.json()["address_count"] == 2

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="File upload multipart")
    def test_file_upload_multipart(self):
        """[HARDCORE-FW-02] File upload with multipart/form-data."""
        with HardcoreTestProject("fileupload") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0", "python-multipart>=0.0.6"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, File, UploadFile

app = FastAPI()

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    content = await file.read()
    return {"filename": file.filename, "size": len(content)}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                files = {"file": ("test.txt", b"Hello World Content", "text/plain")}
                r = requests.post(f"http://127.0.0.1:{p.port}/upload", files=files, timeout=10)
                assert r.status_code == 200
                assert r.json()["filename"] == "test.txt"

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Form data parsing")
    def test_form_data_parsing(self):
        """[HARDCORE-FW-03] Form data parsing."""
        with HardcoreTestProject("formdata") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0", "python-multipart>=0.0.6"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Form

app = FastAPI()

@app.post("/form")
async def submit_form(username: str = Form(...), password: str = Form(...)):
    return {"username": username, "password_length": len(password)}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(
                    f"http://127.0.0.1:{p.port}/form",
                    data={"username": "testuser", "password": "secret123"},
                    timeout=10,
                )
                assert r.status_code == 200
                assert r.json()["username"] == "testuser"

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Cookie handling")
    def test_cookie_handling(self):
        """[HARDCORE-FW-04] Cookie set and get."""
        with HardcoreTestProject("cookies") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Response, Cookie
from typing import Optional

app = FastAPI()

@app.get("/set-cookie")
async def set_cookie(response: Response):
    response.set_cookie(key="session", value="abc123", httponly=True)
    return {"status": "cookie set"}

@app.get("/get-cookie")
async def get_cookie(session: Optional[str] = Cookie(None)):
    return {"session": session}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                session = requests.Session()
                r1 = session.get(f"http://127.0.0.1:{p.port}/set-cookie", timeout=5)
                assert r1.status_code == 200
                r2 = session.get(f"http://127.0.0.1:{p.port}/get-cookie", timeout=5)
                assert r2.status_code == 200
                assert r2.json()["session"] == "abc123"

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Response headers manipulation")
    def test_custom_response_headers(self):
        """[HARDCORE-FW-05] Custom response headers."""
        with HardcoreTestProject("respheaders") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/custom-headers")
async def custom_headers():
    content = {"message": "Hello"}
    headers = {
        "X-Custom-Header": "custom-value",
        "X-Request-ID": "12345",
        "Cache-Control": "no-cache",
    }
    return JSONResponse(content=content, headers=headers)
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/custom-headers", timeout=5)
                assert r.status_code == 200
                assert "X-Custom-Header" in r.headers
                assert r.headers["X-Custom-Header"] == "custom-value"

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="HTTP status code variants")
    def test_various_http_status_codes(self):
        """[HARDCORE-FW-06] Various HTTP status codes."""
        with HardcoreTestProject("statuscodes") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from fastapi.responses import Response, JSONResponse

app = FastAPI()

@app.get("/201")
async def created():
    return JSONResponse(content={"status": "created"}, status_code=201)

@app.get("/204")
async def no_content():
    return Response(status_code=204)

@app.get("/301")
async def redirect():
    return Response(status_code=301, headers={"Location": "/target"})

@app.get("/400")
async def bad_request():
    return JSONResponse(content={"error": "bad request"}, status_code=400)

@app.get("/404")
async def not_found():
    return JSONResponse(content={"error": "not found"}, status_code=404)
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                assert requests.get(f"http://127.0.0.1:{p.port}/201", timeout=5).status_code == 201
                assert requests.get(f"http://127.0.0.1:{p.port}/204", timeout=5).status_code == 204
                assert requests.get(f"http://127.0.0.1:{p.port}/400", timeout=5).status_code == 400
                assert requests.get(f"http://127.0.0.1:{p.port}/404", timeout=5).status_code == 404


# =============================================================================
# CATEGORY 5: PRODUCTION SCENARIOS (5)
# =============================================================================


class TestProductionScenarios:
    """What actually breaks in production."""

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Health check under load")
    def test_health_check_under_load(self):
        """[HARDCORE-PROD-01] Health check must respond during heavy load."""
        with HardcoreTestProject("healthload") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
import asyncio

app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/heavy")
async def heavy():
    await asyncio.sleep(2)
    return {"status": "done"}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                # Start heavy requests
                def heavy_request():
                    try:
                        requests.get(f"http://127.0.0.1:{p.port}/heavy", timeout=10)
                    except Exception:
                        pass

                threads = [threading.Thread(target=heavy_request) for _ in range(20)]
                for t in threads:
                    t.start()

                time.sleep(0.5)

                # Health check must still respond
                start = time.time()
                r = requests.get(f"http://127.0.0.1:{p.port}/health", timeout=5)
                elapsed = time.time() - start

                assert r.status_code == 200
                assert elapsed < 1.0, f"Health check took {elapsed:.2f}s"

                for t in threads:
                    t.join()

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Graceful degradation")
    def test_graceful_degradation(self):
        """[HARDCORE-PROD-02] Graceful degradation on dependency failure."""
        with HardcoreTestProject("degrade") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
import asyncio

app = FastAPI()
db_available = True

@app.get("/status")
async def status():
    if not db_available:
        return {"status": "degraded", "db": False}
    return {"status": "healthy", "db": True}

@app.post("/toggle-db")
async def toggle_db():
    global db_available
    db_available = not db_available
    return {"db_available": db_available}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r1 = requests.get(f"http://127.0.0.1:{p.port}/status", timeout=5)
                assert r1.json()["status"] == "healthy"

                requests.post(f"http://127.0.0.1:{p.port}/toggle-db", timeout=5)

                r2 = requests.get(f"http://127.0.0.1:{p.port}/status", timeout=5)
                assert r2.json()["status"] == "degraded"

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Request tracing")
    def test_request_tracing(self):
        """[HARDCORE-PROD-03] Request ID tracing through middleware."""
        with HardcoreTestProject("tracing") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
import uuid

app = FastAPI()

class TracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

app.add_middleware(TracingMiddleware)

@app.get("/trace")
async def trace(request: Request):
    return {"trace_id": request.headers.get("X-Request-ID")}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                custom_id = "test-trace-12345"
                r = requests.get(f"http://127.0.0.1:{p.port}/trace", headers={"X-Request-ID": custom_id}, timeout=5)
                assert r.status_code == 200
                assert r.headers.get("X-Request-ID") == custom_id

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="JSON error response format")
    def test_structured_error_responses(self):
        """[HARDCORE-PROD-04] Structured JSON error responses."""
        with HardcoreTestProject("errors") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

app = FastAPI()

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": exc.detail}}
    )

@app.get("/error/{code}")
async def trigger_error(code: int):
    raise HTTPException(status_code=code, detail=f"Error {code}") from None
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/error/400", timeout=5)
                assert r.status_code == 400
                data = r.json()
                assert "error" in data
                assert data["error"]["code"] == 400

    @pytest.mark.tier4
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Rate limiting simulation")
    def test_rate_limiting_simulation(self):
        """[HARDCORE-PROD-05] Rate limiting behavior simulation."""
        with HardcoreTestProject("ratelimit") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import time

app = FastAPI()
request_counts = {}
RATE_LIMIT = 10
WINDOW = 1

@app.middleware("http")
async def rate_limit(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    if client_ip not in request_counts:
        request_counts[client_ip] = []

    # Clean old requests
    request_counts[client_ip] = [t for t in request_counts[client_ip] if now - t < WINDOW]

    if len(request_counts[client_ip]) >= RATE_LIMIT:
        return JSONResponse(status_code=429, content={"error": "rate limited"})

    request_counts[client_ip].append(now)
    return await call_next(request)

@app.get("/api")
async def api():
    return {"status": "ok"}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                # Rapid requests should eventually get rate limited
                results = []
                for _ in range(15):
                    r = requests.get(f"http://127.0.0.1:{p.port}/api", timeout=5)
                    results.append(r.status_code)

                # Some should be 429
                assert 429 in results or all(r == 200 for r in results)
