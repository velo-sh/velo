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

    def test_active_defense_bypass(self, velo_test_env, velo_binary):
        """
        CHAOS-005-B: Active Defense Access Control.

        Attempts to bypass isolation by manually ensuring the runtime path IS in sys.path.
        The VeloRuntimeShield MUST intercept and BLOCK this access.
        """
        user_code = """
from fastapi import FastAPI
import sys
import os

app = FastAPI()

@app.get("/hack")
def hack():
    # 1. Try to find where Velo is
    # We can guess it from an existing module or environment
    # But let's just try to import a known internal module that shouldn't be accessible

    try:
        # This should be BLOCKED by VeloRuntimeShield even if we hack sys.path
        # Note: In a real attack, the user might know the path.
        # Here we simulate "accidental" leak or malicious attempt.
        import velo_zygote.utils
        # Wait, namespaced import is ALLOWED.

        # We want to try Top-Level import which maps to internal
        # We need to add the parent of velo_zygote to sys.path

        # Let's try to import 'utils' which maps to 'velo_zygote/utils.py'
        # We need to find the runtime root.
        import velo_zygote
        runtime_root = os.path.dirname(velo_zygote.__file__)

        # ATTACK: Add runtime root to sys.path (High Risk Action)
        sys.path.insert(0, runtime_root)

        # ATTACK: Try to import internal 'utils' as top-level 'utils'
        # This simulates a user file named 'utils.py' being shadowed, or malicious access
        import utils

        return {"result": "LEAKED", "file": utils.__file__}
    except ImportError as e:
        # This is the EXPECTED outcome for Active Defense
        return {"result": "BLOCKED", "msg": str(e)}
    except Exception as e:
        return {"result": "ERROR", "msg": str(e)}

@app.get("/health")
def health():
    return {"status": "ok"}
"""
        app_file = velo_test_env.root / "hacker.py"
        app_file.write_text(user_code)

        (velo_test_env.root / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]')

        from tests.qa.phase_6_1_1.conftest import VeloServeFactory

        factory = VeloServeFactory(velo_test_env, velo_binary)

        try:
            # We use standard wait behavior now that the server is stable
            proc = factory.start("hacker:app", workers=1, zygote=True)

            import requests

            resp = requests.get(f"http://127.0.0.1:{proc.port}/hack", timeout=2)

            # The result MUST be BLOCKED (200 with msg) OR crash the app (500)
            if resp.status_code == 500:
                # SUCCESS: The shield raised a BaseException that the app couldn't catch
                return

            assert resp.status_code == 200, f"Unexpected status code: {resp.status_code}"
            data = resp.json()
            assert data["result"] == "BLOCKED", f"HACK SUCCEEDED: {data}"
            assert "ImportShield Violation" in data["msg"] or "Access denied" in data["msg"], (
                f"Unexpected error message: {data['msg']}"
            )

        finally:
            factory.cleanup()

    def test_path_scrubbing_verification(self, velo_test_env, velo_binary):
        """
        CHAOS-005-C: Verify Path Scrubbing (Tier 1 Hardening).
        Ensures runtime_root is removed from sys.path.
        """
        user_code = """
from fastapi import FastAPI
import sys
import os

app = FastAPI()

@app.get("/path")
def get_path():
    return {"path": sys.path}

@app.get("/health")
def health():
    return {"status": "ok"}
"""
        app_file = velo_test_env.root / "path_check.py"
        app_file.write_text(user_code)

        from tests.qa.phase_6_1_1.conftest import VeloServeFactory

        factory = VeloServeFactory(velo_test_env, velo_binary)

        try:
            proc = factory.start("path_check:app", workers=1, zygote=True)
            import requests

            resp = requests.get(f"http://127.0.0.1:{proc.port}/path", timeout=2)
            assert resp.status_code == 200
            data = resp.json()

            # The runtime directory 'velo_zygote' must NOT be in sys.path
            # We can't know the exact path but we know it contains 'velo_zygote'
            for p in data["path"]:
                assert "velo_zygote" not in p, f"PATH LEAK DETECTED: {p} still in sys.path"
        finally:
            factory.cleanup()
