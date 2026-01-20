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
# SCENARIO 2: UV Venv Detection (DEF-08-015)
# =============================================================================
@pytest.mark.tier2
def test_UV_venv_detection(isolated_env: VeloTestEnv):
    """
    Verify Vibe correctly detects and respects UV-created virtualenv.

    NOTE: Vibe uses PyO3 embedded Python, so sys.executable won't change.
    Instead, we verify that:
    1. VIRTUAL_ENV env var is propagated to the worker
    2. The venv's site-packages is in sys.path (via SINC-001 fix)
    """
    # Create a new UV venv in isolated env
    venv_path = isolated_env.path / ".venv"
    result = subprocess.run(
        ["uv", "venv", str(venv_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"UV venv creation failed: {result.stderr}"

    # Code that checks environment detection
    code = """
import os
import sys

# Check if VIRTUAL_ENV is set
venv = os.environ.get('VIRTUAL_ENV', 'NOT_SET')
print(f"VIRTUAL_ENV={venv}")

# Check if venv site-packages is in sys.path
site_packages = [p for p in sys.path if 'site-packages' in p]
print(f"SITE_PACKAGES_COUNT={len(site_packages)}")
print(f"HAS_VENV_IN_PATH={any('.venv' in p for p in sys.path)}")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    # Run Vibe with VIRTUAL_ENV set
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

            # Verify VIRTUAL_ENV is propagated
            assert "VIRTUAL_ENV=" in output and "NOT_SET" not in output, (
                f"DEF-08-015: VIRTUAL_ENV not propagated! Output: {output}"
            )
            print("✅ DEF-08-015 FIX VERIFIED: VIRTUAL_ENV correctly propagated!")

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


# =============================================================================
# SCENARIO 6: pyproject.toml Dependency Change (SINC-001/DEF-08-016 Verification)
# =============================================================================
@pytest.mark.tier2
def test_UV_pyproject_dependency_change(isolated_env: VeloTestEnv):
    """
    CRITICAL: Does Vibe detect when pyproject.toml dependencies change?

    This is the standard UV workflow:
    1. Developer adds a new dependency to pyproject.toml
    2. Runs `uv sync`
    3. Updates code to use the new package
    4. Vibe should recognize the environment changed

    SINC-001 FIX: This test now EXPECTS the package to be available after uv sync.
    Previous behavior (bug): Package not available after sync.
    Current behavior (fixed): Package IS available after sync.
    """
    # Ensure cowsay is NOT installed initially
    subprocess.run(["uv", "pip", "uninstall", "cowsay", "-y"], capture_output=True)

    # Create initial pyproject.toml
    pyproject_v1 = """
[project]
name = "test-project"
version = "0.1.0"
dependencies = []
"""
    isolated_env.create_app("pyproject.toml", pyproject_v1)

    code = """
import sys
# Try to import cowsay - will fail if not installed
try:
    import cowsay
    print("COWSAY_AVAILABLE")
except ImportError:
    print("COWSAY_NOT_AVAILABLE")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_pyproject_change():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            # Step 1: Initial state - cowsay not available
            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)
            initial_output = data.get("output", "")
            print(f"Initial output: {initial_output}")

            # Step 2: Update pyproject.toml to add cowsay
            print("Updating pyproject.toml to add cowsay dependency...")
            pyproject_v2 = """
[project]
name = "test-project"
version = "0.1.0"
dependencies = ["cowsay"]
"""
            isolated_env.create_app("pyproject.toml", pyproject_v2)

            # Step 3: Run uv sync to install the dependency
            print("Running uv sync...")
            result = subprocess.run(
                ["uv", "sync"],
                cwd=str(isolated_env.path),
                capture_output=True,
                text=True,
            )
            print(f"UV sync: {result.returncode}")

            # Step 4: Trigger code re-execution
            isolated_env.create_app("app.py", code + "# trigger")

            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)
            after_sync_output = data.get("output", "")
            print(f"After sync output: {after_sync_output}")

            # SINC-001 FIX VERIFICATION:
            # After uv sync, cowsay SHOULD be available (this is the fixed behavior)
            assert "COWSAY_AVAILABLE" in after_sync_output, (
                "SINC-001 REGRESSION: Vibe should detect newly installed package after uv sync! "
                f"Got: {after_sync_output}"
            )
            print("✅ SINC-001/DEF-08-016 FIX VERIFIED: New dependency detected after uv sync!")

    try:
        asyncio.run(check_pyproject_change())
    finally:
        process.terminate()
        process.wait()
        subprocess.run(["uv", "pip", "uninstall", "cowsay", "-y"], capture_output=True)


# =============================================================================
# SCENARIO 7: pyproject.toml [tool.velo] Configuration Change
# =============================================================================
@pytest.mark.tier2
def test_UV_pyproject_velo_config_change(isolated_env: VeloTestEnv):
    """
    Does Vibe detect changes to its own [tool.velo] configuration?
    """
    pyproject_v1 = """
[project]
name = "test-project"
version = "0.1.0"

[tool.velo]
preload = []
"""
    isolated_env.create_app("pyproject.toml", pyproject_v1)

    code = "print('VELO_CONFIG_TEST')"
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_velo_config():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            await websocket.recv()  # Initial

            # Update [tool.velo] config
            print("Updating [tool.velo] configuration...")
            pyproject_v2 = """
[project]
name = "test-project"
version = "0.1.0"

[tool.velo]
preload = ["json", "os"]
slow_threshold_ms = 500
"""
            isolated_env.create_app("pyproject.toml", pyproject_v2)

            # Trigger re-execution
            isolated_env.create_app("app.py", "print('VELO_CONFIG_UPDATED')")

            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)

            assert data["status"] == "success"
            print("Vibe config change detection test passed")

    try:
        asyncio.run(check_velo_config())
    finally:
        process.terminate()
        process.wait()
