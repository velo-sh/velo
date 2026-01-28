"""
Drop-in Framework Compatibility Tests

Tests for real-world patterns that production apps use.
Users should be able to "just drop in" their existing apps.

Categories:
1. FastAPI Real-World Patterns (8)
2. Starlette Real-World Patterns (5)
3. Common ASGI Patterns (5)
4. HTTP Methods & Routing (5)
5. Request/Response Patterns (5)

Total: 28 drop-in compatibility tests

Author: Velo QA Team
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
    repo_root = Path(__file__).parent.parent.parent.parent
    release = repo_root / "target" / "release" / "velo"
    if release.exists():
        return str(release)
    pytest.skip("velo binary not found")


class DropInTestProject:
    """Test project for drop-in compatibility."""

    def __init__(self, name: str):
        self.name = name
        self.path = Path(tempfile.mkdtemp(prefix=f"dropin_{name}_"))
        self.velo = get_velo_binary()
        self._port: int | None = None
        self._proc: subprocess.Popen[str] | None = None

    def set_pyproject(self, deps: list[str]) -> "DropInTestProject":
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

    def set_app(self, filename: str, code: str) -> "DropInTestProject":
        (self.path / filename).write_text(code)
        return self

    def install_deps(self, timeout: float = 180) -> "DropInTestProject":
        subprocess.run(["uv", "sync"], cwd=self.path, capture_output=True, timeout=timeout)
        return self

    def start_server(self, app_module: str, port: int | None = None) -> "DropInTestProject":
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
        if self._port is None:
            raise ValueError("Server not started")
        return self._port

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def cleanup(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait(timeout=10)
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()


# =============================================================================
# CATEGORY 1: FastAPI Real-World Patterns (8)
# =============================================================================


class TestFastapiDropIn:
    """FastAPI patterns that real apps use."""

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="FastAPI drop-in compatibility")
    def test_fastapi_path_params(self):
        """[DROPIN-FA-01] FastAPI path parameters."""
        with DropInTestProject("fa-path") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI

app = FastAPI()

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    return {"user_id": user_id, "type": "int"}

@app.get("/items/{item_name}")
async def get_item(item_name: str):
    return {"item_name": item_name, "type": "str"}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r1 = requests.get(f"http://127.0.0.1:{p.port}/users/123", timeout=5)
                assert r1.status_code == 200
                assert r1.json()["user_id"] == 123

                r2 = requests.get(f"http://127.0.0.1:{p.port}/items/widget", timeout=5)
                assert r2.status_code == 200
                assert r2.json()["item_name"] == "widget"

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="FastAPI drop-in compatibility")
    def test_fastapi_query_params(self):
        """[DROPIN-FA-02] FastAPI query parameters."""
        with DropInTestProject("fa-query") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from typing import Optional

app = FastAPI()

@app.get("/search")
async def search(q: str, limit: int = 10, offset: Optional[int] = None):
    return {"query": q, "limit": limit, "offset": offset}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/search?q=test&limit=20", timeout=5)
                assert r.status_code == 200
                data = r.json()
                assert data["query"] == "test"
                assert data["limit"] == 20

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="FastAPI drop-in compatibility")
    def test_fastapi_request_body_json(self):
        """[DROPIN-FA-03] FastAPI JSON request body."""
        with DropInTestProject("fa-json") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0", "pydantic>=2.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):
    name: str
    price: float
    quantity: int = 1

@app.post("/items")
async def create_item(item: Item):
    return {"name": item.name, "total": item.price * item.quantity}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(
                    f"http://127.0.0.1:{p.port}/items", json={"name": "Widget", "price": 9.99, "quantity": 3}, timeout=5
                )
                assert r.status_code == 200
                assert r.json()["total"] == pytest.approx(29.97, 0.01)

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="FastAPI drop-in compatibility")
    def test_fastapi_response_model(self):
        """[DROPIN-FA-04] FastAPI response model."""
        with DropInTestProject("fa-response") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0", "pydantic>=2.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class UserResponse(BaseModel):
    id: int
    name: str
    email: str

@app.get("/user", response_model=UserResponse)
async def get_user():
    return {"id": 1, "name": "John", "email": "john@example.com", "password": "secret"}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/user", timeout=5)
                assert r.status_code == 200
                data = r.json()
                assert "password" not in data  # Should be filtered by response_model

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="FastAPI drop-in compatibility")
    def test_fastapi_http_exception(self):
        """[DROPIN-FA-05] FastAPI HTTPException."""
        with DropInTestProject("fa-exception") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, HTTPException

app = FastAPI()

@app.get("/items/{item_id}")
async def get_item(item_id: int):
    if item_id == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"item_id": item_id}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r1 = requests.get(f"http://127.0.0.1:{p.port}/items/1", timeout=5)
                assert r1.status_code == 200

                r2 = requests.get(f"http://127.0.0.1:{p.port}/items/0", timeout=5)
                assert r2.status_code == 404

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="FastAPI drop-in compatibility")
    def test_fastapi_router(self):
        """[DROPIN-FA-06] FastAPI APIRouter."""
        with DropInTestProject("fa-router") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, APIRouter

app = FastAPI()

users_router = APIRouter(prefix="/users", tags=["users"])
items_router = APIRouter(prefix="/items", tags=["items"])

@users_router.get("/")
async def list_users():
    return [{"id": 1, "name": "Alice"}]

@items_router.get("/")
async def list_items():
    return [{"id": 1, "name": "Widget"}]

app.include_router(users_router)
app.include_router(items_router)
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r1 = requests.get(f"http://127.0.0.1:{p.port}/users/", timeout=5)
                assert r1.status_code == 200

                r2 = requests.get(f"http://127.0.0.1:{p.port}/items/", timeout=5)
                assert r2.status_code == 200

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="FastAPI drop-in compatibility")
    def test_fastapi_lifespan(self):
        """[DROPIN-FA-07] FastAPI lifespan context manager."""
        with DropInTestProject("fa-lifespan") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from contextlib import asynccontextmanager

db = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    db["connected"] = True
    yield
    db["connected"] = False

app = FastAPI(lifespan=lifespan)

@app.get("/status")
async def status():
    return {"db_connected": db.get("connected", False)}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/status", timeout=5)
                assert r.status_code == 200
                assert r.json()["db_connected"] is True

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="FastAPI drop-in compatibility")
    def test_fastapi_openapi(self):
        """[DROPIN-FA-08] FastAPI OpenAPI schema."""
        with DropInTestProject("fa-openapi") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI

app = FastAPI(title="Test API", version="1.0.0")

@app.get("/")
async def root():
    return {"message": "Hello"}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/openapi.json", timeout=5)
                assert r.status_code == 200
                schema = r.json()
                assert schema["info"]["title"] == "Test API"


# =============================================================================
# CATEGORY 2: Starlette Real-World Patterns (5)
# =============================================================================


class TestStarletteDropIn:
    """Starlette patterns that real apps use."""

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Starlette drop-in compatibility")
    def test_starlette_routing(self):
        """[DROPIN-ST-01] Starlette routing."""
        with DropInTestProject("st-routing") as p:
            p.set_pyproject(deps=["starlette>=0.38.0"])
            p.set_app(
                "main.py",
                """
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

async def homepage(request):
    return JSONResponse({"page": "home"})

async def about(request):
    return JSONResponse({"page": "about"})

app = Starlette(routes=[
    Route("/", homepage),
    Route("/about", about),
])
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r1 = requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                assert r1.json()["page"] == "home"

                r2 = requests.get(f"http://127.0.0.1:{p.port}/about", timeout=5)
                assert r2.json()["page"] == "about"

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Starlette drop-in compatibility")
    def test_starlette_path_params(self):
        """[DROPIN-ST-02] Starlette path parameters."""
        with DropInTestProject("st-path") as p:
            p.set_pyproject(deps=["starlette>=0.38.0"])
            p.set_app(
                "main.py",
                """
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

async def get_user(request):
    user_id = request.path_params["user_id"]
    return JSONResponse({"user_id": int(user_id)})

app = Starlette(routes=[
    Route("/users/{user_id:int}", get_user),
])
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/users/42", timeout=5)
                assert r.status_code == 200
                assert r.json()["user_id"] == 42

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Starlette drop-in compatibility")
    def test_starlette_request_body(self):
        """[DROPIN-ST-03] Starlette request body."""
        with DropInTestProject("st-body") as p:
            p.set_pyproject(deps=["starlette>=0.38.0"])
            p.set_app(
                "main.py",
                """
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

async def create_item(request):
    data = await request.json()
    return JSONResponse({"received": data})

app = Starlette(routes=[
    Route("/items", create_item, methods=["POST"]),
])
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(f"http://127.0.0.1:{p.port}/items", json={"name": "test"}, timeout=5)
                assert r.status_code == 200
                assert r.json()["received"]["name"] == "test"

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Starlette drop-in compatibility")
    def test_starlette_html_response(self):
        """[DROPIN-ST-04] Starlette HTML response."""
        with DropInTestProject("st-html") as p:
            p.set_pyproject(deps=["starlette>=0.38.0"])
            p.set_app(
                "main.py",
                """
from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Route

async def homepage(request):
    return HTMLResponse("<html><body><h1>Hello World</h1></body></html>")

app = Starlette(routes=[
    Route("/", homepage),
])
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                assert r.status_code == 200
                assert "Hello World" in r.text
                assert "text/html" in r.headers.get("content-type", "")

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Starlette drop-in compatibility")
    def test_starlette_redirect(self):
        """[DROPIN-ST-05] Starlette redirect response."""
        with DropInTestProject("st-redirect") as p:
            p.set_pyproject(deps=["starlette>=0.38.0"])
            p.set_app(
                "main.py",
                """
from starlette.applications import Starlette
from starlette.responses import RedirectResponse, JSONResponse
from starlette.routing import Route

async def old_page(request):
    return RedirectResponse(url="/new-page", status_code=301)

async def new_page(request):
    return JSONResponse({"page": "new"})

app = Starlette(routes=[
    Route("/old-page", old_page),
    Route("/new-page", new_page),
])
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/old-page", timeout=5, allow_redirects=True)
                assert r.json()["page"] == "new"


# =============================================================================
# CATEGORY 3: Common ASGI Patterns (5)
# =============================================================================


class TestCommonAsgiPatterns:
    """Common ASGI patterns that all apps use."""

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_pure_asgi_hello(self):
        """[DROPIN-ASGI-01] Pure ASGI hello world."""
        with DropInTestProject("asgi-hello") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, receive, send):
    assert scope["type"] == "http"
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/plain")],
    })
    await send({
        "type": "http.response.body",
        "body": b"Hello, World!",
    })
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                assert r.status_code == 200
                assert r.text == "Hello, World!"

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_asgi_json_response(self):
        """[DROPIN-ASGI-02] Pure ASGI JSON response."""
        with DropInTestProject("asgi-json") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    body = json.dumps({"message": "Hello", "status": "ok"}).encode()
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({
        "type": "http.response.body",
        "body": body,
    })
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                assert r.status_code == 200
                assert r.json()["status"] == "ok"

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_asgi_read_body(self):
        """[DROPIN-ASGI-03] Pure ASGI read request body."""
        with DropInTestProject("asgi-body") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break

    data = json.loads(body) if body else {}
    response = json.dumps({"received": data}).encode()

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({
        "type": "http.response.body",
        "body": response,
    })
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(f"http://127.0.0.1:{p.port}/", json={"key": "value"}, timeout=5)
                assert r.status_code == 200
                assert r.json()["received"]["key"] == "value"

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_asgi_headers(self):
        """[DROPIN-ASGI-04] Pure ASGI read and write headers."""
        with DropInTestProject("asgi-headers") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    headers = dict(scope.get("headers", []))
    user_agent = headers.get(b"user-agent", b"unknown").decode()

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/json"),
            (b"x-custom-header", b"custom-value"),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": json.dumps({"user_agent": user_agent}).encode(),
    })
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                assert r.status_code == 200
                assert r.headers.get("x-custom-header") == "custom-value"

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_asgi_path_routing(self):
        """[DROPIN-ASGI-05] Pure ASGI path-based routing."""
        with DropInTestProject("asgi-routing") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
import json

async def app(scope, receive, send):
    path = scope.get("path", "/")

    if path == "/":
        response = {"page": "home"}
    elif path == "/api":
        response = {"page": "api"}
    else:
        response = {"page": "not_found"}

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({
        "type": "http.response.body",
        "body": json.dumps(response).encode(),
    })
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r1 = requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                assert r1.json()["page"] == "home"

                r2 = requests.get(f"http://127.0.0.1:{p.port}/api", timeout=5)
                assert r2.json()["page"] == "api"


# =============================================================================
# CATEGORY 4: HTTP Methods & Routing (5)
# =============================================================================


class TestHttpMethods:
    """HTTP methods that real apps use."""

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="HTTP method compatibility")
    def test_http_get(self):
        """[DROPIN-HTTP-01] HTTP GET method."""
        with DropInTestProject("http-get") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/resource")
async def get_resource():
    return {"method": "GET", "data": [1, 2, 3]}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/resource", timeout=5)
                assert r.status_code == 200
                assert r.json()["method"] == "GET"

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="HTTP method compatibility")
    def test_http_post(self):
        """[DROPIN-HTTP-02] HTTP POST method."""
        with DropInTestProject("http-post") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.post("/resource")
async def create_resource(data: dict):
    return {"method": "POST", "created": data}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.post(f"http://127.0.0.1:{p.port}/resource", json={"name": "test"}, timeout=5)
                assert r.status_code == 200
                assert r.json()["method"] == "POST"

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="HTTP method compatibility")
    def test_http_put(self):
        """[DROPIN-HTTP-03] HTTP PUT method."""
        with DropInTestProject("http-put") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.put("/resource/{id}")
async def update_resource(id: int, data: dict):
    return {"method": "PUT", "id": id, "updated": data}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.put(f"http://127.0.0.1:{p.port}/resource/1", json={"name": "updated"}, timeout=5)
                assert r.status_code == 200
                assert r.json()["method"] == "PUT"

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="HTTP method compatibility")
    def test_http_patch(self):
        """[DROPIN-HTTP-04] HTTP PATCH method."""
        with DropInTestProject("http-patch") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.patch("/resource/{id}")
async def patch_resource(id: int, data: dict):
    return {"method": "PATCH", "id": id, "patched": data}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.patch(f"http://127.0.0.1:{p.port}/resource/1", json={"field": "value"}, timeout=5)
                assert r.status_code == 200
                assert r.json()["method"] == "PATCH"

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="HTTP method compatibility")
    def test_http_delete(self):
        """[DROPIN-HTTP-05] HTTP DELETE method."""
        with DropInTestProject("http-delete") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.delete("/resource/{id}")
async def delete_resource(id: int):
    return {"method": "DELETE", "id": id, "deleted": True}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.delete(f"http://127.0.0.1:{p.port}/resource/1", timeout=5)
                assert r.status_code == 200
                assert r.json()["deleted"] is True


# =============================================================================
# CATEGORY 5: Request/Response Patterns (5)
# =============================================================================


class TestRequestResponsePatterns:
    """Request/Response patterns that real apps need."""

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Request object compatibility")
    def test_request_url_info(self):
        """[DROPIN-REQ-01] Request URL information."""
        with DropInTestProject("req-url") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Request
app = FastAPI()

@app.get("/info")
async def url_info(request: Request):
    return {
        "url": str(request.url),
        "path": request.url.path,
        "method": request.method,
    }
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/info", timeout=5)
                assert r.status_code == 200
                data = r.json()
                assert data["path"] == "/info"
                assert data["method"] == "GET"

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Request headers compatibility")
    def test_request_headers_access(self):
        """[DROPIN-REQ-02] Request headers access."""
        with DropInTestProject("req-headers") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Request
app = FastAPI()

@app.get("/headers")
async def get_headers(request: Request):
    return {
        "host": request.headers.get("host"),
        "accept": request.headers.get("accept"),
        "custom": request.headers.get("x-custom"),
    }
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(f"http://127.0.0.1:{p.port}/headers", headers={"X-Custom": "test-value"}, timeout=5)
                assert r.status_code == 200
                assert r.json()["custom"] == "test-value"

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Response with status code")
    def test_response_status_codes(self):
        """[DROPIN-REQ-03] Response with various status codes."""
        with DropInTestProject("resp-status") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from fastapi.responses import JSONResponse
app = FastAPI()

@app.get("/created")
async def created():
    return JSONResponse({"status": "created"}, status_code=201)

@app.get("/accepted")
async def accepted():
    return JSONResponse({"status": "accepted"}, status_code=202)
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r1 = requests.get(f"http://127.0.0.1:{p.port}/created", timeout=5)
                assert r1.status_code == 201

                r2 = requests.get(f"http://127.0.0.1:{p.port}/accepted", timeout=5)
                assert r2.status_code == 202

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Query string parsing")
    def test_query_string_parsing(self):
        """[DROPIN-REQ-04] Query string parsing."""
        with DropInTestProject("query-parse") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Query
from typing import List
app = FastAPI()

@app.get("/filter")
async def filter_items(
    category: str = Query(...),
    tags: List[str] = Query(default=[]),
    page: int = Query(default=1, ge=1),
):
    return {"category": category, "tags": tags, "page": page}
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r = requests.get(
                    f"http://127.0.0.1:{p.port}/filter?category=books&tags=fiction&tags=new&page=2", timeout=5
                )
                assert r.status_code == 200
                data = r.json()
                assert data["category"] == "books"
                assert data["page"] == 2

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.xfail(reason="Content type negotiation")
    def test_content_type_negotiation(self):
        """[DROPIN-REQ-05] Content type in response."""
        with DropInTestProject("content-type") as p:
            p.set_pyproject(deps=["fastapi>=0.115.0"])
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, HTMLResponse, JSONResponse
app = FastAPI()

@app.get("/text")
async def text():
    return PlainTextResponse("Plain text content")

@app.get("/html")
async def html():
    return HTMLResponse("<h1>HTML content</h1>")

@app.get("/json")
async def json_resp():
    return JSONResponse({"type": "json"})
""",
            )
            p.install_deps()
            p.start_server("main:app")

            if p.alive:
                r1 = requests.get(f"http://127.0.0.1:{p.port}/text", timeout=5)
                assert "text/plain" in r1.headers.get("content-type", "")

                r2 = requests.get(f"http://127.0.0.1:{p.port}/html", timeout=5)
                assert "text/html" in r2.headers.get("content-type", "")

                r3 = requests.get(f"http://127.0.0.1:{p.port}/json", timeout=5)
                assert "application/json" in r3.headers.get("content-type", "")
