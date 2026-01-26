# tests/qa/heavy/chaos/test_sin_of_collision.py
from pathlib import Path

import pytest

# List of Velo internal modules that might be shadowed
COLLISION_TARGETS = [
    # Core Infrastructure
    "bootstrap.py",
    "lifecycle.py",
    "paths.py",
    "settings.py",
    "utils.py",
    "constants.py",
    # Logic Modules
    "routing.py",
    "protocol.py",
    "v_fork.py",
    "v_shield.py",
    "worker_launcher.py",  # The launcher itself
]


@pytest.mark.heavy
class TestSinOfCollision:
    """
    CHAOS-005: The "Sin of Collision" Suite.

    Demonstrates architectural failure in Environment Isolation.
    We deliberately create user applications named identically to Velo's internal
    modules. If Velo's environment is truly isolated, these should ALL work.

    If Velo crashes or imports the internal module instead of the user one,
    IT IS A FATAL ISOLATION FAILURE.
    """

    @pytest.mark.parametrize("filename", COLLISION_TARGETS)
    def test_collision_leakage_audit(self, velo_test_env, velo_binary, filename):
        """
        Dynamically create an app with a colliding filename and try to run it.
        """
        module_name = filename.replace(".py", "")

        # 1. Create the colliding file in the user workspace
        # This file exports 'app' so it validly looks like an ASGI app
        user_code = f'''
# User's {filename} - SHOULD BE LOADED
from fastapi import FastAPI
import sys
import os

app = FastAPI()

@app.get("/identity")
def identity():
    return {{
        "module": "{module_name}", 
        "file": __file__,
        "cwd": os.getcwd()
    }}

@app.get("/health")
def health():
    return {{"status": "ok"}}
'''
        app_file = velo_test_env.root / filename
        app_file.write_text(user_code)

        # 2. Also ensure pyproject.toml exists for Zygote detection
        (velo_test_env.root / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]')

        # 3. Explicitly construct the CLI command to run THIS file
        # We use a custom factory logic here or re-use VeloServeFactory if possible via fixture
        # But we need to instantiate it specifically for this test case
        from tests.qa.phase_6_1_1.conftest import VeloServeFactory

        factory = VeloServeFactory(velo_test_env, velo_binary)

        try:
            # Try to start it.
            # If isolation is broken, one of two things happens:
            # A) AttributeError: module 'xxx' has no attribute 'app' (Loaded internal Velo module)
            # B) ImportError / Crash during Velo startup (Velo loaded user module instead of internal)
            proc = factory.start(f"{module_name}:app", workers=1, zygote=True)
            proc.wait_ready(timeout=10.0)  # Short timeout, should be fast

            # 4. Verify the identity
            # The app MUST return that it was loaded from the USER directory, NOT velo_zygote
            import requests

            resp = requests.get(f"http://127.0.0.1:{proc.port}/identity", timeout=2)
            assert resp.status_code == 200
            data = resp.json()

            loaded_path = Path(data["file"]).resolve()
            expected_path = app_file.resolve()

            assert loaded_path == expected_path, (
                f"ISOLATION FAILURE: Loaded {loaded_path} instead of user code {expected_path}"
            )

        except Exception as e:
            pytest.fail(f"CRASHED on collision with {filename}: {e}")
        finally:
            factory.cleanup()
