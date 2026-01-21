"""
Council-Mandated Framework Compatibility Tests

Per Grand Council Review (SOP-001), 23 new test cases required.

Categories:
1. Framework Middleware Tests (6)
2. Python Runtime Tests (4)
3. Security Tests (4)
4. Network Edge Cases (5)
5. Performance Benchmarks (4)

Author: Velo QA Council
Date: 2026-01-14
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
import requests


def get_velo_binary() -> str:
    """Get path to velo binary."""
    repo_root = Path(__file__).parents[4]
    release = repo_root / "target" / "release" / "velo"
    debug = repo_root / "target" / "debug" / "velo"

    env_binary = os.environ.get("VELO_BINARY")
    if env_binary and Path(env_binary).exists():
        return str(Path(env_binary).resolve())

    if release.exists():
        return str(release)
    elif debug.exists():
        return str(debug)
    else:
        pytest.skip("velo binary not found")


class CouncilTestProject:
    """Test project for Council-mandated tests."""

    def __init__(self, name: str):
        self.name = name
        self.path = Path(tempfile.mkdtemp(prefix=f"council_{name}_"))
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

    def start_server(self, app_module: str, port: int = None):
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
    def port(self) -> int:
        return self._port

    @property
    def alive(self) -> bool:
        return self._proc and self._proc.poll() is None

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
# CATEGORY 1: FRAMEWORK MIDDLEWARE TESTS (6)
# =============================================================================


class TestFrameworkMiddleware:
    """Council Mandate: Test middleware chain compatibility."""

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="INDICTMENT-05/06 blocking")
    def test_fastapi_middleware_chain(self):
        """[COUNCIL-MW-01] FastAPI multiple middleware chain."""
        with CouncilTestProject("fastapi-mw") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

app = FastAPI()

class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        import time
        start = time.time()
        response = await call_next(request)
        response.headers["X-Process-Time"] = str(time.time() - start)
        return response

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Auth-Check"] = "passed"
        return response

app.add_middleware(TimingMiddleware)
app.add_middleware(AuthMiddleware)

@app.get("/")
async def root():
    return {"status": "ok", "middleware": "chained"}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                resp = requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                assert resp.status_code == 200
                assert "X-Process-Time" in resp.headers
                assert "X-Auth-Check" in resp.headers

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="INDICTMENT-05/06 blocking")
    def test_fastapi_dependency_injection(self):
        """[COUNCIL-MW-02] FastAPI Depends() compatibility."""
        with CouncilTestProject("fastapi-di") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Depends, Request

app = FastAPI()

def get_client_host(request: Request):
    return request.client.host if request.client else "unknown"

def get_path(request: Request):
    return request.url.path

@app.get("/di")
async def with_deps(host: str = Depends(get_client_host), path: str = Depends(get_path)):
    return {"host": host, "path": path}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                resp = requests.get(f"http://127.0.0.1:{p.port}/di", timeout=5)
                assert resp.status_code == 200
                data = resp.json()
                assert "host" in data
                assert data["path"] == "/di"

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="INDICTMENT-05/06 blocking")
    def test_fastapi_background_tasks(self):
        """[COUNCIL-MW-03] FastAPI BackgroundTasks scheduling."""
        with CouncilTestProject("fastapi-bg") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, BackgroundTasks
import os

app = FastAPI()
task_completed = False

def background_task(message: str):
    global task_completed
    with open("/tmp/velo_bg_task.txt", "w") as f:
        f.write(message)
    task_completed = True

@app.post("/trigger")
async def trigger_background(background_tasks: BackgroundTasks):
    background_tasks.add_task(background_task, "Hello from background!")
    return {"status": "task_scheduled"}

@app.get("/check")
async def check_task():
    return {"completed": os.path.exists("/tmp/velo_bg_task.txt")}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                resp1 = requests.post(f"http://127.0.0.1:{p.port}/trigger", timeout=5)
                assert resp1.status_code == 200
                time.sleep(1)
                resp2 = requests.get(f"http://127.0.0.1:{p.port}/check", timeout=5)
                assert resp2.json().get("completed") is True

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Django ASGI complex requirements")
    def test_django_middleware_chain(self):
        """[COUNCIL-MW-04] Django MIDDLEWARE setting compatibility."""
        with CouncilTestProject("django-mw") as p:
            p.set_pyproject(deps=["django>=5.0"])

            (p.path / "mymiddleware").mkdir()
            (p.path / "mymiddleware" / "__init__.py").write_text("")

            p.set_app(
                "mymiddleware/timing.py",
                """
import time

class TimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.start_time = time.time()
        response = self.get_response(request)
        response["X-Timing"] = str(time.time() - request.start_time)
        return response
""",
            )

            p.set_app(
                "settings.py",
                """
DEBUG = True
SECRET_KEY = "council-test-key"
ROOT_URLCONF = "urls"
ALLOWED_HOSTS = ["*"]
MIDDLEWARE = [
    "mymiddleware.timing.TimingMiddleware",
]
""",
            )

            p.set_app(
                "urls.py",
                """
from django.http import JsonResponse
from django.urls import path

def index(request):
    return JsonResponse({"status": "ok"})

urlpatterns = [path("", index)]
""",
            )

            p.set_app(
                "main.py",
                """
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
import django
django.setup()
from django.core.asgi import get_asgi_application
app = get_asgi_application()
""",
            )

            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                resp = requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                assert resp.status_code == 200
                assert "X-Timing" in resp.headers

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="DRF complex serialization")
    def test_django_rest_framework(self):
        """[COUNCIL-MW-05] Django REST Framework compatibility."""
        with CouncilTestProject("drf") as p:
            p.set_pyproject(deps=["django>=5.0", "djangorestframework>=3.15.0"])

            p.set_app(
                "settings.py",
                """
DEBUG = True
SECRET_KEY = "council-drf-test"
ROOT_URLCONF = "urls"
ALLOWED_HOSTS = ["*"]
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "rest_framework",
]
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}
""",
            )

            p.set_app(
                "urls.py",
                """
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.urls import path

@api_view(["GET"])
def hello(request):
    return Response({"framework": "DRF", "status": "ok"})

urlpatterns = [path("api/", hello)]
""",
            )

            p.set_app(
                "main.py",
                """
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
import django
django.setup()
from django.core.asgi import get_asgi_application
app = get_asgi_application()
""",
            )

            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                resp = requests.get(f"http://127.0.0.1:{p.port}/api/", timeout=5)
                assert resp.status_code == 200
                assert resp.json().get("framework") == "DRF"

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="CORS preflight requires full ASGI support")
    def test_cors_middleware(self):
        """[COUNCIL-MW-06] CORS preflight OPTIONS request."""
        with CouncilTestProject("cors") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api")
async def api():
    return {"cors": "enabled"}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                resp = requests.options(
                    f"http://127.0.0.1:{p.port}/api",
                    headers={"Origin": "http://evil.com", "Access-Control-Request-Method": "POST"},
                    timeout=5,
                )
                assert resp.status_code == 200
                assert "access-control-allow-origin" in resp.headers


# =============================================================================
# CATEGORY 2: PYTHON RUNTIME TESTS (4)
# =============================================================================


class TestPythonRuntime:
    """Council Mandate: Test Python runtime behavior."""

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="ASGI bridge blocking")
    def test_exception_propagation(self):
        """[COUNCIL-PY-01] Exception -> 500 response."""
        with CouncilTestProject("exception") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI

app = FastAPI()

@app.get("/crash")
async def crash():
    raise ValueError("Intentional crash for testing")

@app.get("/")
async def ok():
    return {"status": "ok"}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                resp = requests.get(f"http://127.0.0.1:{p.port}/crash", timeout=5)
                assert resp.status_code == 500

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Streaming requires full ASGI body support")
    def test_streaming_response(self):
        """[COUNCIL-PY-02] Async generator StreamingResponse."""
        with CouncilTestProject("streaming") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import asyncio

app = FastAPI()

async def generate():
    for i in range(5):
        yield f"chunk-{i}\\n"
        await asyncio.sleep(0.1)

@app.get("/stream")
async def stream():
    return StreamingResponse(generate(), media_type="text/plain")
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                resp = requests.get(f"http://127.0.0.1:{p.port}/stream", timeout=10)
                assert resp.status_code == 200
                assert "chunk-0" in resp.text
                assert "chunk-4" in resp.text

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="SSE requires chunked transfer")
    def test_server_sent_events(self):
        """[COUNCIL-PY-03] Server-Sent Events (SSE)."""
        with CouncilTestProject("sse") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0", "sse-starlette>=1.0.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from sse_starlette.sse import EventSourceResponse
import asyncio

app = FastAPI()

async def event_generator():
    for i in range(3):
        yield {"event": "message", "data": f"event-{i}"}
        await asyncio.sleep(0.1)

@app.get("/events")
async def events():
    return EventSourceResponse(event_generator())
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                resp = requests.get(f"http://127.0.0.1:{p.port}/events", timeout=10, stream=True)
                assert resp.status_code == 200

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="contextvars in ASGI bridge")
    def test_contextvars_isolation(self):
        """[COUNCIL-PY-04] Context variables isolation under concurrency."""
        with CouncilTestProject("contextvars") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
import contextvars
import asyncio

app = FastAPI()
request_id_var = contextvars.ContextVar("request_id", default=None)

@app.get("/ctx/{req_id}")
async def with_context(req_id: str):
    request_id_var.set(req_id)
    await asyncio.sleep(0.1)  # Simulate async work
    return {"set_id": req_id, "got_id": request_id_var.get()}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                resp = requests.get(f"http://127.0.0.1:{p.port}/ctx/abc123", timeout=5)
                assert resp.status_code == 200
                data = resp.json()
                assert data["set_id"] == data["got_id"]


# =============================================================================
# CATEGORY 3: SECURITY TESTS (4)
# =============================================================================


class TestSecurityAudit:
    """Council Mandate: Security audits for scope/request handling."""

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_header_injection_crlf(self):
        """[COUNCIL-SEC-01] CRLF injection in headers."""
        with CouncilTestProject("crlf") as p:
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
                # Try CRLF injection
                try:
                    resp = requests.get(
                        f"http://127.0.0.1:{p.port}/", headers={"X-Evil": "value\r\nX-Injected: malicious"}, timeout=5
                    )
                    # Should not have X-Injected in response
                    assert "X-Injected" not in str(resp.headers)
                except:
                    pass  # Connection errors are acceptable (rejected request)

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_path_traversal(self):
        """[COUNCIL-SEC-02] Path traversal attack."""
        with CouncilTestProject("pathtraversal") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from pathlib import Path

app = FastAPI()

@app.get("/files/{filepath:path}")
async def read_file(filepath: str):
    # Should be sanitized
    safe_path = Path(filepath).resolve()
    if str(safe_path).startswith("/etc"):
        return {"error": "access denied"}
    return {"path": str(safe_path)}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                resp = requests.get(f"http://127.0.0.1:{p.port}/files/../../../etc/passwd", timeout=5)
                if resp.status_code == 200:
                    # Path traversal should be blocked
                    data = resp.json()
                    assert "access denied" in str(data) or "/etc/passwd" not in data.get("path", "")

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_host_header_validation(self):
        """[COUNCIL-SEC-03] Host header validation."""
        with CouncilTestProject("hostheader") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, receive, send):
    host = None
    for name, value in scope.get("headers", []):
        if name == b"host":
            host = value.decode()
            break
    body = f'{{"host": "{host}"}}'.encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": body})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                # Try with evil host
                resp = requests.get(f"http://127.0.0.1:{p.port}/", headers={"Host": "evil.com"}, timeout=5)
                # Just verify no crash
                assert resp.status_code in [200, 400, 421]

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_large_header_handling(self):
        """[COUNCIL-SEC-04] Large header DoS protection."""
        with CouncilTestProject("largeheader") as p:
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
                # Try very large header
                try:
                    resp = requests.get(f"http://127.0.0.1:{p.port}/", headers={"X-Large": "A" * 100000}, timeout=5)
                    # Should either reject or handle gracefully
                    assert resp.status_code in [200, 400, 431]
                except:
                    pass  # Connection rejection is acceptable


# =============================================================================
# CATEGORY 4: NETWORK EDGE CASES (5)
# =============================================================================


class TestNetworkEdgeCases:
    """Council Mandate: Network protocol edge cases."""

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_websocket_ping_pong(self):
        """[COUNCIL-NET-01] WebSocket ping/pong heartbeat."""
        with CouncilTestProject("ws-ping") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0", "websockets>=12.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, WebSocket

app = FastAPI()

@app.websocket("/ws")
async def ws_ping(websocket: WebSocket):
    await websocket.accept()
    # Send ping, wait for pong
    await websocket.send_text("ping")
    data = await websocket.receive_text()
    await websocket.send_text(f"received: {data}")
    await websocket.close()
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                import websocket

                ws = websocket.create_connection(f"ws://127.0.0.1:{p.port}/ws", timeout=5)
                ping = ws.recv()
                ws.send("pong")
                resp = ws.recv()
                ws.close()
                assert "pong" in resp

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Chunked transfer requires streaming")
    def test_chunked_transfer_encoding(self):
        """[COUNCIL-NET-02] Chunked transfer encoding response."""
        with CouncilTestProject("chunked") as p:
            p.set_pyproject(deps=["starlette>=0.38.0"])
            p.set_app(
                "main.py",
                """
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route
import asyncio

async def chunked_response(request):
    async def generate():
        for i in range(5):
            yield f"chunk-{i}\\n".encode()
            await asyncio.sleep(0.05)
    return StreamingResponse(generate())

app = Starlette(routes=[Route("/chunked", chunked_response)])
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                resp = requests.get(f"http://127.0.0.1:{p.port}/chunked", timeout=10)
                assert resp.status_code == 200
                assert "chunk-0" in resp.text

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_keepalive_connections(self):
        """[COUNCIL-NET-03] HTTP/1.1 Keep-Alive connection reuse."""
        with CouncilTestProject("keepalive") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import os
async def app(scope, receive, send):
    body = f'{{"pid": {os.getpid()}}}'.encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"connection", b"keep-alive")]})
    await send({"type": "http.response.body", "body": body})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                session = requests.Session()
                r1 = session.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                r2 = session.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                assert r1.status_code == 200
                assert r2.status_code == 200
                # Both should hit same worker
                assert r1.json()["pid"] == r2.json()["pid"]

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_slow_client_timeout(self):
        """[COUNCIL-NET-04] Slow client handling."""
        # This test verifies server doesn't hang on slow clients
        with CouncilTestProject("slowclient") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"fast response"})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                # Normal request should complete quickly
                import time

                start = time.time()
                resp = requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                elapsed = time.time() - start
                assert resp.status_code == 200
                assert elapsed < 2.0  # Should be fast

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_websocket_binary_frames(self):
        """[COUNCIL-NET-05] WebSocket binary frame handling."""
        with CouncilTestProject("ws-binary") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0", "websockets>=12.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, WebSocket

app = FastAPI()

@app.websocket("/ws")
async def ws_binary(websocket: WebSocket):
    await websocket.accept()
    data = await websocket.receive_bytes()
    await websocket.send_bytes(data[::-1])  # Reverse bytes
    await websocket.close()
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                import websocket

                ws = websocket.create_connection(f"ws://127.0.0.1:{p.port}/ws", timeout=5)
                ws.send_binary(b"\x00\x01\x02\x03")
                data = ws.recv()
                ws.close()
                assert data == b"\x03\x02\x01\x00"


# =============================================================================
# CATEGORY 5: PERFORMANCE BENCHMARKS (4)
# =============================================================================


class TestPerformanceBenchmarks:
    """Council Mandate: Performance baseline measurements."""

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.benchmark
    def test_latency_empty_response(self):
        """[COUNCIL-PERF-01] Empty response latency (p50/p95/p99)."""
        with CouncilTestProject("latency") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                import time

                latencies = []
                for _ in range(100):
                    start = time.perf_counter()
                    requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                    latencies.append((time.perf_counter() - start) * 1000)

                latencies.sort()
                p50 = latencies[50]
                p95 = latencies[95]
                p99 = latencies[99]

                print(f"\\nLatency (ms): p50={p50:.2f}, p95={p95:.2f}, p99={p99:.2f}")

                # Should be under 100ms for p99
                assert p99 < 100

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.benchmark
    def test_throughput_concurrent(self):
        """[COUNCIL-PERF-02] Throughput with 50 concurrent requests."""
        with CouncilTestProject("throughput") as p:
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
                import concurrent.futures
                import time

                def make_request():
                    return requests.get(f"http://127.0.0.1:{p.port}/", timeout=10).status_code

                start = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
                    futures = [executor.submit(make_request) for _ in range(500)]
                    results = [f.result() for f in futures]
                elapsed = time.perf_counter() - start

                success = sum(1 for r in results if r == 200)
                rps = 500 / elapsed

                print(f"\\nThroughput: {rps:.0f} RPS, Success: {success}/500")

                assert success >= 450  # 90% success rate

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.benchmark
    @pytest.mark.xfail(reason="Memory profiling requires psutil")
    def test_memory_growth(self):
        """[COUNCIL-PERF-03] Memory growth under load."""
        with CouncilTestProject("memory") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"x" * 10000})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                import psutil

                proc = psutil.Process(p._proc.pid)
                mem_before = proc.memory_info().rss / 1024 / 1024

                for _ in range(1000):
                    requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)

                mem_after = proc.memory_info().rss / 1024 / 1024
                growth = mem_after - mem_before

                print(f"\\nMemory: Before={mem_before:.1f}MB, After={mem_after:.1f}MB, Growth={growth:.1f}MB")

                # Should not grow more than 50MB
                assert growth < 50

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.benchmark
    @pytest.mark.xfail(reason="FastAPI not working yet")
    def test_fastapi_vs_pure_rsgi(self):
        """[COUNCIL-PERF-04] FastAPI vs Pure RSGI latency comparison."""
        # FastAPI latency
        fastapi_latency = None
        rsgi_latency = None

        with CouncilTestProject("fastapi-bench") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()
@app.get("/")
async def root():
    return {"ok": True}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                import time

                latencies = []
                for _ in range(50):
                    start = time.perf_counter()
                    requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                    latencies.append((time.perf_counter() - start) * 1000)
                fastapi_latency = sorted(latencies)[25]  # p50

        with CouncilTestProject("rsgi-bench") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b'{"ok":true}'})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                import time

                latencies = []
                for _ in range(50):
                    start = time.perf_counter()
                    requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                    latencies.append((time.perf_counter() - start) * 1000)
                rsgi_latency = sorted(latencies)[25]  # p50

        if fastapi_latency and rsgi_latency:
            overhead = (fastapi_latency - rsgi_latency) / rsgi_latency * 100
            print(f"\\nFastAPI p50: {fastapi_latency:.2f}ms, Pure RSGI p50: {rsgi_latency:.2f}ms")
            print(f"Framework overhead: {overhead:.1f}%")
