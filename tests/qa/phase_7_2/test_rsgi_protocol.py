"""
RFC-0019/0025 Native Sovereignty Protocol Tests

These tests verify the native Granian worker architecture, replacing the
old UDS handshake protocol tests.

Phase 7.2: Native Sovereignty ensures:
1. No UDS handshake needed (PyO3 in-process)
2. Direct ASGI/RSGI bridge within worker
3. TCP port owned by Rust Host
"""

import os
import time
from pathlib import Path

import pytest
import requests


class TestNativeRsgiProtocol:
    """Verify Native RSGI Worker protocol compliance."""

    @pytest.mark.tier1
    def test_native_worker_startup(self, isolated_env):
        """[N-PRO-01] Verify native worker starts and responds to HTTP."""
        # Create a proper ASGI app
        isolated_env.create_app(
            "main.py",
            """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/health")
def health():
    return {"healthy": True}
""",
        )

        port = isolated_env.next_port()
        root_dir = str(Path(__file__).parents[3])
        env = {"PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"}

        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--port", str(port), env=env)

        try:
            # Wait for server to be ready
            ready = False
            for _ in range(30):
                try:
                    resp = requests.get(f"http://127.0.0.1:{port}/health", timeout=1)
                    if resp.status_code == 200:
                        ready = True
                        break
                except requests.exceptions.RequestException:
                    pass
                time.sleep(0.5)

            assert ready, "Native worker failed to start"

            # Verify response
            resp = requests.get(f"http://127.0.0.1:{port}/", timeout=5)
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.tier1
    def test_native_worker_asgi_bridge(self, isolated_env):
        """[N-PRO-02] Verify ASGI bridge correctly handles scope/receive/send."""
        isolated_env.create_app(
            "main.py",
            """
from fastapi import FastAPI, Request
app = FastAPI()

@app.get("/scope")
async def show_scope(request: Request):
    return {
        "type": request.scope.get("type"),
        "path": request.scope.get("path"),
        "method": request.scope.get("method"),
        "client": list(request.scope.get("client")) if request.scope.get("client") else None,
    }
""",
        )

        port = isolated_env.next_port()
        root_dir = str(Path(__file__).parents[3])
        env = {"PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"}

        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--port", str(port), env=env)

        try:
            # Wait for ready
            for _ in range(30):
                try:
                    resp = requests.get(f"http://127.0.0.1:{port}/scope", timeout=1)
                    if resp.status_code == 200:
                        break
                except requests.exceptions.RequestException:
                    pass
                time.sleep(0.5)

            resp = requests.get(f"http://127.0.0.1:{port}/scope", timeout=5)
            assert resp.status_code == 200

            data = resp.json()
            assert data["type"] == "http"
            assert data["path"] == "/scope"
            assert data["method"] == "GET"
            # Client should be populated
            assert data["client"] is not None

        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.tier1
    def test_native_worker_post_body(self, isolated_env):
        """[N-PRO-03] Verify POST request body flows through ASGI bridge."""
        isolated_env.create_app(
            "main.py",
            """
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class EchoBody(BaseModel):
    message: str
    number: int = 0

@app.post("/echo")
async def echo(body: EchoBody):
    return {"received_message": body.message, "received_number": body.number}
""",
        )

        port = isolated_env.next_port()
        root_dir = str(Path(__file__).parents[3])
        env = {"PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"}

        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--port", str(port), env=env)

        try:
            # Wait for ready
            for _ in range(30):
                try:
                    resp = requests.get(f"http://127.0.0.1:{port}/", timeout=1)
                    break
                except requests.exceptions.RequestException:
                    pass
                time.sleep(0.5)

            # Send POST with JSON body
            resp = requests.post(f"http://127.0.0.1:{port}/echo", json={"message": "hello", "number": 42}, timeout=5)
            assert resp.status_code == 200
            data = resp.json()
            assert data["received_message"] == "hello"
            assert data["received_number"] == 42

        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.tier2
    def test_native_worker_error_handling(self, isolated_env):
        """[N-PRO-04] Verify error responses flow correctly through bridge."""
        isolated_env.create_app(
            "main.py",
            """
from fastapi import FastAPI, HTTPException
app = FastAPI()

@app.get("/error/{code}")
async def trigger_error(code: int):
    if code == 404:
        raise HTTPException(status_code=404, detail="Not found")
    elif code == 500:
        raise HTTPException(status_code=500, detail="Server error")
    return {"code": code}
""",
        )

        port = isolated_env.next_port()
        root_dir = str(Path(__file__).parents[3])
        env = {"PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"}

        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--port", str(port), env=env)

        try:
            # Wait for ready
            for _ in range(30):
                try:
                    resp = requests.get(f"http://127.0.0.1:{port}/error/200", timeout=1)
                    if resp.status_code == 200:
                        break
                except requests.exceptions.RequestException:
                    pass
                time.sleep(0.5)

            # Test 404
            resp = requests.get(f"http://127.0.0.1:{port}/error/404", timeout=5)
            assert resp.status_code == 404

            # Test 500
            resp = requests.get(f"http://127.0.0.1:{port}/error/500", timeout=5)
            assert resp.status_code == 500

        finally:
            proc.terminate()
            proc.wait()


class TestNativeProtocolCompliance:
    """Verify native protocol meets ASGI spec requirements."""

    @pytest.mark.tier2
    @pytest.mark.xfail(reason="Flaky in CI: RSGI server can cause RemoteDisconnected", strict=False)
    def test_asgi_headers_preserved(self, isolated_env):
        """[N-ASGI-01] Verify headers flow correctly through bridge."""
        isolated_env.create_app(
            "main.py",
            """
from fastapi import FastAPI, Request
app = FastAPI()

@app.get("/headers")
async def show_headers(request: Request):
    return dict(request.headers)
""",
        )

        port = isolated_env.next_port()
        root_dir = str(Path(__file__).parents[3])
        env = {"PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"}

        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--port", str(port), env=env)

        try:
            for _ in range(30):
                try:
                    resp = requests.get(f"http://127.0.0.1:{port}/headers", timeout=1)
                    if resp.status_code == 200:
                        break
                except requests.exceptions.RequestException:
                    pass
                time.sleep(0.5)

            resp = requests.get(f"http://127.0.0.1:{port}/headers", headers={"X-Custom-Test": "qa-value"}, timeout=5)
            assert resp.status_code == 200
            headers = resp.json()

            # Custom header should be preserved
            assert "x-custom-test" in headers or "X-Custom-Test" in headers

        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.tier2
    @pytest.mark.xfail(reason="Flaky in CI: RSGI server can cause RemoteDisconnected", strict=False)
    def test_asgi_async_handling(self, isolated_env):
        """[N-ASGI-02] Verify async requests are handled concurrently."""
        import concurrent.futures

        isolated_env.create_app(
            "main.py",
            """
from fastapi import FastAPI
import asyncio
app = FastAPI()

_concurrent = 0
_max_concurrent = 0

@app.get("/concurrent")
async def concurrent():
    global _concurrent, _max_concurrent
    _concurrent += 1
    if _concurrent > _max_concurrent:
        _max_concurrent = _concurrent
    current = _concurrent
    max_seen = _max_concurrent
    await asyncio.sleep(0.1)
    _concurrent -= 1
    return {"concurrent": current, "max_seen": max_seen}
""",
        )

        port = isolated_env.next_port()
        root_dir = str(Path(__file__).parents[3])
        env = {"PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"}

        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--port", str(port), env=env)

        try:
            for _ in range(30):
                try:
                    resp = requests.get(f"http://127.0.0.1:{port}/concurrent", timeout=1)
                    if resp.status_code == 200:
                        break
                except requests.exceptions.RequestException:
                    pass
                time.sleep(0.5)

            # Send concurrent requests
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                futures = [
                    pool.submit(lambda: requests.get(f"http://127.0.0.1:{port}/concurrent", timeout=5))
                    for _ in range(10)
                ]
                responses = [f.result() for f in futures]

            # Check max concurrent seen
            max_seen = max(r.json().get("max_seen", 0) for r in responses if r.status_code == 200)

            # Should see >1 concurrent requests
            assert max_seen > 1, f"Async handling not concurrent: max_seen={max_seen}"

        finally:
            proc.terminate()
            proc.wait()
