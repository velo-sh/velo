"""
RFC-0019 ASGI Bridge Compatibility Test Suite (uv-Isolated Environment)

This suite uses uv to create FULLY ISOLATED user project environments.
Velo acts as the RUNTIME, and user projects are strictly separated.

Best Practice Pattern (from test_phase4_integration.py):
1. Create pyproject.toml with explicit dependencies
2. Run `uv sync` to install into isolated .venv
3. Test Velo serve in that environment

Author: Velo Forensic AI (QA Role)
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
    """Get path to velo binary (release preferred)."""
    repo_root = Path(__file__).parent.parent.parent.parent
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


class IsolatedUserProject:
    """
    A fully isolated user project environment managed by uv.

    This simulates a real user project where:
    - Velo is the RUNTIME (not touched by uv)
    - User project has its own .venv created by uv sync
    - Dependencies are strictly isolated

    WARNING: These tests are SLOW because they install real packages.
    """

    def __init__(self, name: str):
        self.name = name
        self.path = Path(tempfile.mkdtemp(prefix=f"velo_{name}_"))
        self.velo = get_velo_binary()
        self._setup_done = False

    def set_pyproject(self, deps: list):
        """Create pyproject.toml with real dependencies."""
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
        """Create application file."""
        (self.path / filename).write_text(code)
        return self

    def setup(self, timeout: float = 120):
        """Run uv sync to install REAL dependencies (slow!)."""
        if self._setup_done:
            return self

        result = subprocess.run(
            ["uv", "sync"],
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            pytest.fail(f"uv sync failed: {result.stderr}")
        self._setup_done = True
        return self

    def serve(self, app_module: str, *extra_args, port: int = None, env: dict = None) -> subprocess.Popen:
        """Start Velo serve with the isolated project environment."""
        if port is None:
            import socket

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", 0))
                port = s.getsockname()[1]

        self._port = port

        # Build environment that activates the isolated .venv
        run_env = os.environ.copy()
        venv_python = self.path / ".venv" / "bin" / "python"
        venv_site = self.path / ".venv" / "lib"

        # Find actual site-packages path
        site_packages_dirs = list(venv_site.glob("python*/site-packages"))
        if site_packages_dirs:
            run_env["PYTHONPATH"] = str(site_packages_dirs[0])

        run_env["VIRTUAL_ENV"] = str(self.path / ".venv")
        run_env["PATH"] = f"{self.path / '.venv' / 'bin'}:{os.environ.get('PATH', '')}"

        if env:
            run_env.update(env)

        cmd = [self.velo, "serve", app_module, "--rsgi", "--no-zygote", "--port", str(port), *extra_args]

        return subprocess.Popen(
            cmd,
            cwd=self.path,
            env=run_env,
            text=True,
        )

    @property
    def port(self) -> int:
        return self._port

    def cleanup(self):
        """Remove temp directory."""
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()


class TestFrameworkCompatibilityIsolated:
    """
    Framework compatibility tests using uv-isolated environments.

    These tests document INDICTMENT-03: ASGI Protocol Regression.
    When fixed, these should pass.
    """

    @pytest.mark.tier3
    @pytest.mark.slow
    # INDICTMENT-03 RESOLVED: ASGI Bridge now converts (scope, receive, send) to native RSGI
    def test_fastapi_isolated_compatibility(self):
        """
        [COMPAT-ISOLATED-01] FastAPI in uv-isolated environment.

        Environment: Fully isolated via uv sync.
        Expected: FAIL due to ASGI signature mismatch until INDICTMENT-03 is fixed.
        """
        with IsolatedUserProject("fastapi-isolated") as p:
            p.set_pyproject(
                deps=[
                    "fastapi>=0.115.0",
                    "starlette>=0.38.0",
                ]
            )
            p.set_app(
                "main.py",
                """
from fastapi import FastAPI, Request

app = FastAPI()

@app.get("/health")
async def health(request: Request):
    return {
        "framework": "FastAPI",
        "status": "healthy",
        "scope_type": request.scope.get("type"),
    }
""",
            )
            p.setup()

            proc = p.serve("main:app")
            try:
                time.sleep(5)
                resp = requests.get(f"http://127.0.0.1:{p.port}/health", timeout=5)
                assert resp.status_code == 200
                data = resp.json()
                assert data["framework"] == "FastAPI"
                print("[COMPAT-ISOLATED-01 PASSED]: FastAPI works in isolated Native RSGI mode!")
            finally:
                proc.terminate()
                proc.wait()

    @pytest.mark.tier3
    @pytest.mark.slow
    # INDICTMENT-03 RESOLVED: ASGI Bridge now converts (scope, receive, send) to native RSGI
    def test_starlette_isolated_compatibility(self):
        """
        [COMPAT-ISOLATED-02] Starlette in uv-isolated environment.

        Environment: Fully isolated via uv sync.
        Expected: FAIL due to ASGI signature mismatch until INDICTMENT-03 is fixed.
        """
        with IsolatedUserProject("starlette-isolated") as p:
            p.set_pyproject(
                deps=[
                    "starlette>=0.38.0",
                ]
            )
            p.set_app(
                "main.py",
                """
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

async def homepage(request):
    return JSONResponse({
        "framework": "Starlette",
        "status": "healthy",
    })

app = Starlette(routes=[Route("/health", homepage)])
""",
            )
            p.setup()

            proc = p.serve("main:app")
            try:
                time.sleep(5)
                resp = requests.get(f"http://127.0.0.1:{p.port}/health", timeout=5)
                assert resp.status_code == 200
                data = resp.json()
                assert data["framework"] == "Starlette"
                print("[COMPAT-ISOLATED-02 PASSED]: Starlette works in isolated Native RSGI mode!")
            finally:
                proc.terminate()
                proc.wait()

    @pytest.mark.tier3
    @pytest.mark.slow
    def test_pure_rsgi_isolated_compatibility(self):
        """
        [COMPAT-ISOLATED-03] Pure RSGI App in isolated environment.

        This is the ONLY currently supported signature in Native RSGI mode.
        Expected: PASS (200 OK).
        """
        with IsolatedUserProject("rsgi-isolated") as p:
            # No external deps needed for pure RSGI
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, proto):
    '''Pure RSGI app with (scope, proto) signature.'''
    proto.response_str(200, [], "RSGI Native: OK")
""",
            )
            p.setup()

            proc = p.serve("main:app")
            try:
                time.sleep(5)
                resp = requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                assert resp.status_code == 200
                assert "RSGI Native: OK" in resp.text
                print("[COMPAT-ISOLATED-03 PASSED]: Pure RSGI app works correctly!")
            finally:
                proc.terminate()
                proc.wait()

    @pytest.mark.tier3
    @pytest.mark.slow
    @pytest.mark.skip(reason="Flask WSGI requires a2wsgi bridge - out of scope for Phase 7.2")
    def test_flask_isolated_compatibility(self):
        """
        [COMPAT-ISOLATED-04] Flask (WSGI) in uv-isolated environment.

        WSGI apps cannot run directly on RSGI - they need a2wsgi bridge.
        This is documented for roadmap purposes.
        """
        with IsolatedUserProject("flask-isolated") as p:
            p.set_pyproject(
                deps=[
                    "flask>=3.0.0",
                ]
            )
            p.set_app(
                "main.py",
                """
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/health")
def health():
    return jsonify({
        "framework": "Flask",
        "status": "healthy",
    })
""",
            )
            p.setup()

            proc = p.serve("main:app")
            try:
                time.sleep(5)
                resp = requests.get(f"http://127.0.0.1:{p.port}/health", timeout=5)
                assert resp.status_code == 200
                data = resp.json()
                assert data["framework"] == "Flask"
                print("[COMPAT-ISOLATED-04 PASSED]: Flask WSGI works via bridge!")
            finally:
                proc.terminate()
                proc.wait()


class TestASGISignatureEvidenceIsolated:
    """
    Tests that explicitly document the ASGI signature incompatibility.
    These serve as "forensic evidence" for INDICTMENT-03.
    """

    @pytest.mark.tier2
    @pytest.mark.slow
    @pytest.mark.skip(reason="INDICTMENT-03 RESOLVED: ASGI signature mismatch fixed in Phase 7.3")
    def test_asgi_signature_mismatch_evidence(self):
        """
        [EVIDENCE-ISOLATED-01] Direct evidence of signature mismatch.

        This test VERIFIES that the bug exists.
        When INDICTMENT-03 is fixed, this test should FAIL (and be removed).
        """
        with IsolatedUserProject("asgi-evidence") as p:
            p.set_pyproject(deps=[])
            p.set_app(
                "main.py",
                """
async def app(scope, receive, send):
    '''Standard ASGI signature - currently broken in Native RSGI.'''
    await send({
        'type': 'http.response.start',
        'status': 200,
        'headers': []
    })
    await send({
        'type': 'http.response.body',
        'body': b'ASGI Standard: OK'
    })
""",
            )
            p.setup()

            proc = p.serve("main:app")
            try:
                time.sleep(5)

                # This SHOULD timeout/fail due to the TypeError
                try:
                    resp = requests.get(f"http://127.0.0.1:{p.port}/", timeout=5)
                    if resp.status_code == 200:
                        # If this succeeds, the bug is FIXED!
                        pytest.fail(
                            "INDICTMENT-03 RESOLVED: Standard ASGI signature now works! "
                            "Remove this evidence test and enable framework tests."
                        )
                except requests.exceptions.RequestException:
                    # Expected: timeout/connection error due to signature mismatch
                    print(
                        "[EVIDENCE-ISOLATED-01 VERIFIED]: Standard ASGI signature fails as expected (INDICTMENT-03 confirmed)"
                    )

            finally:
                proc.terminate()
                proc.wait()
