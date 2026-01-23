import os
import uuid
from pathlib import Path

import pytest

# Mark entire module as CI flaky - skip in CI due to env isolation issues
pytestmark = [pytest.mark.ci_flaky, pytest.mark.tier1]


class TestEnvShield:
    """
    Verification of [DEF-72-S02] Block VELO_UNTRUSTED_* env vars.
    Ensure that any environment variable starting with VELO_UNTRUSTED_
    is NOT passed to the worker process.
    """

    @pytest.mark.tier1
    def test_untrusted_env_shield(self, isolated_env):
        """Verify VELO_UNTRUSTED_SECRET is blocked from workers."""
        # Use a globally unique path in /tmp to avoid any CWD/IsolatedEnv discrepancies
        env_file_path = f"/tmp/velo_test_env_{uuid.uuid4()}.json"

        # 1. Create a dummy app that prints its environment
        app_code = """
import os
import json

async def app(scope, receive, send):
    if scope["type"] == "http":
        # Carrier: VELO_WORKER_DEBUG_LOG is whitelisted
        filepath = os.environ.get("VELO_WORKER_DEBUG_LOG", "/tmp/worker_env_fallback.json")
        try:
            if not os.path.exists(filepath):
                with open(filepath, "w") as f:
                    # Capture the ACTUAL process environment
                    json.dump(dict(os.environ), f)
        except Exception as e:
            with open("/tmp/worker_err.log", "a") as f:
                f.write(f"Failed to write env to {filepath}: {e}\\n")
                
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
"""
        isolated_env.create_app("main.py", app_code)

        # 2. Set untrusted and trusted env vars
        root_dir = os.getcwd()
        env = os.environ.copy()
        # This SHOULD be blocked (Starts with VELO_UNTRUSTED_)
        env["VELO_UNTRUSTED_SECRET"] = "SHHH_SENSITIVE"
        # We use VELO_WORKER_DEBUG_LOG to pass the path because it's whitelisted
        env["VELO_WORKER_DEBUG_LOG"] = env_file_path
        # Ensure we can import velo_zygote
        env["PYTHONPATH"] = f"{root_dir}:{env.get('PYTHONPATH', '')}"

        # 3. Start Velo
        port = isolated_env.next_port()
        proc = isolated_env.spawn_velo("serve", "main:app", "--port", str(port), env=env)

        try:
            import time

            import requests

            # Wait for startup
            time.sleep(5)

            # Trigger request to ensure worker is alive and has initialized its environment dump
            timeout = 10
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    res = requests.get(f"http://127.0.0.1:{port}/", timeout=2)
                    if res.status_code == 200:
                        break
                except:
                    time.sleep(0.5)

            # 4. Check the captured environment
            env_file = Path(env_file_path)
            assert env_file.exists(), f"Worker failed to write env file at {env_file_path}. Check /tmp/worker_err.log."

            import json

            worker_env = json.loads(env_file.read_text())

            # [DEF-72-S02] Assertion
            assert "VELO_UNTRUSTED_SECRET" not in worker_env, (
                f"SECURITY BREACH: VELO_UNTRUSTED_SECRET leaked to worker! Env keys: {list(worker_env.keys())}"
            )
            assert worker_env.get("VELO_WORKER_DEBUG_LOG") == env_file_path, (
                "Whitelisted env var (carrier) was lost or corrupted"
            )

        finally:
            if os.path.exists(env_file_path):
                try:
                    os.remove(env_file_path)
                except:
                    pass
            proc.terminate()
            proc.wait()
