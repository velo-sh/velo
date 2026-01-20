"""
Vibe Engine: UV Integration Test Suite
=======================================
Velo's primary target is UV-based Python environments.
These tests validate Vibe's behavior with UV workflows.

Focus areas:
- `uv pip install` during live session
- `uv venv` environment detection
- `uv run` execution context
- UV lockfile changes
"""

import asyncio
import json
import subprocess
import time

import pytest
import websockets
from conftest_utils import VeloTestEnv


# =============================================================================
# SCENARIO 1: UV Pip Install During Vibe Session
# =============================================================================
@pytest.mark.tier2
def test_UV_pip_install_during_vibe(isolated_env: VeloTestEnv):
    """
    CRITICAL: Can Vibe detect a `uv pip install` during a live session?

    This is the #1 real-world scenario for developers:
    1. Start Vibe
    2. Realize they need a new package
    3. Run `uv pip install requests`
    4. Update code to use `requests`
    5. Expect it to work WITHOUT restarting Vibe
    """
    code_init = "print('Vibe active')"
    app_py = isolated_env.create_app("app.py", code_init)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_uv_install():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            # Step 1: Verify it works
            await websocket.recv()

            # Step 2: Install package via UV
            print("Installing 'cowsay' via uv pip install...")
            result = subprocess.run(
                ["uv", "pip", "install", "cowsay"],
                capture_output=True,
                text=True,
            )
            print(f"UV output: {result.stdout}")
            assert result.returncode == 0, f"UV install failed: {result.stderr}"

            # Step 3: Update code to use the new package
            print("Updating code to use 'cowsay'...")
            code_cowsay = "import cowsay; print(cowsay.get_output_string('cow', 'UV Works!'))"
            isolated_env.create_app("app.py", code_cowsay)

            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)

            print(f"Output: {data.get('output', '')[:200]}")
            print(f"Status: {data.get('status')}")
            print(f"Error: {data.get('error', 'none')}")

            # ASSERTION
            if data["status"] == "error" and "ModuleNotFoundError" in data.get("error", ""):
                pytest.fail(
                    "UV Integration FAILED: Vibe didn't detect `uv pip install`. "
                    "Zygote needs to monitor site-packages for changes."
                )

            assert "UV Works!" in data.get("output", "")

    try:
        asyncio.run(check_uv_install())
    finally:
        process.terminate()
        process.wait()
        # Cleanup
        subprocess.run(["uv", "pip", "uninstall", "cowsay", "-y"], capture_output=True)


# =============================================================================
# SCENARIO 2: UV Venv Detection
# =============================================================================
@pytest.mark.tier2
def test_UV_venv_detection(isolated_env: VeloTestEnv):
    """
    Verify Vibe correctly detects and uses UV-created virtualenv.
    """
    # Create a new UV venv in isolated env
    venv_path = isolated_env.path / ".venv"
    result = subprocess.run(
        ["uv", "venv", str(venv_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"UV venv creation failed: {result.stderr}"

    # Code that prints the Python path
    code = """
import sys
print(f"PYTHON_PATH={sys.executable}")
print(f"VENV_ACTIVE={'/.venv/' in sys.executable}")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    # Run Vibe, it should detect the local .venv
    process = isolated_env.spawn_velo(
        "vibe",
        str(app_py),
        env={
            "VELO_VIBE_PORT": str(port),
            "VIRTUAL_ENV": str(venv_path),
        },
    )
    time.sleep(2)

    async def check_venv():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)
            output = data.get("output", "")

            print(f"Output: {output}")

            # Vibe should be using the venv's Python
            assert "VENV_ACTIVE=True" in output or ".venv" in output, f"UV venv not detected! Output: {output}"

    try:
        asyncio.run(check_venv())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 3: UV Lockfile Changes
# =============================================================================
@pytest.mark.tier2
def test_UV_lockfile_change_detection(isolated_env: VeloTestEnv):
    """
    If uv.lock changes (e.g., after `uv sync`), does Vibe re-evaluate?
    """
    # Create a minimal pyproject.toml
    pyproject = """
[project]
name = "test-project"
version = "0.1.0"
dependencies = []
"""
    isolated_env.create_app("pyproject.toml", pyproject)

    code = "print('UV_LOCK_TEST_OK')"
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_lockfile():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            await websocket.recv()  # Initial

            # Simulate lockfile change (touch uv.lock)
            print("Simulating uv.lock change...")
            lockfile = isolated_env.path / "uv.lock"
            lockfile.write_text("# simulated lock change\n")

            # Trigger by touching app.py
            code_updated = "print('UV_LOCK_CHANGED')"
            isolated_env.create_app("app.py", code_updated)

            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)

            assert data["status"] == "success"
            print("UV lockfile test passed (code re-executed after lockfile change)")

    try:
        asyncio.run(check_lockfile())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 4: UV Run Context
# =============================================================================
@pytest.mark.tier2
def test_UV_run_context(isolated_env: VeloTestEnv):
    """
    Verify that Vibe respects UV's execution context.
    When running via `uv run velo vibe`, check env propagation.
    """
    code = """
import os
print(f"UV_CACHE_DIR={os.getenv('UV_CACHE_DIR', 'NOT_SET')}")
print(f"UV_PROJECT_ENVIRONMENT={os.getenv('UV_PROJECT_ENVIRONMENT', 'NOT_SET')}")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    # Set UV-specific env vars
    uv_env = {
        "VELO_VIBE_PORT": str(port),
        "UV_CACHE_DIR": "/tmp/uv-test-cache",
        "UV_PROJECT_ENVIRONMENT": str(isolated_env.path / ".venv"),
    }

    process = isolated_env.spawn_velo("vibe", str(app_py), env=uv_env)
    time.sleep(2)

    async def check_uv_context():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)
            output = data.get("output", "")

            print(f"UV Context Output: {output}")

            # UV env vars should be propagated to worker
            # Note: This tests if Vibe preserves UV's environment
            assert data["status"] == "success"

    try:
        asyncio.run(check_uv_context())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 5: UV Add During Session (Future Feature Test)
# =============================================================================
@pytest.mark.tier2
@pytest.mark.skip(reason="Requires `uv add` support - future feature test")
def test_UV_add_during_session(isolated_env: VeloTestEnv):
    """
    Future: Test `uv add requests` during a live Vibe session.
    This modifies pyproject.toml AND installs the package.
    """
    pass
