import pytest
import os
import subprocess
from pathlib import Path

class TestEnvShield:
    """
    Verification of [DEF-72-S02] Block VELO_UNTRUSTED_* env vars.
    Ensure that any environment variable starting with VELO_UNTRUSTED_
    is NOT passed to the worker process.
    """

    @pytest.mark.tier1
    def test_untrusted_env_shield(self, isolated_env):
        """Verify VELO_UNTRUSTED_SECRET is blocked from workers."""
        # 1. Create a dummy app that prints its environment
        app_code = """
import os
import json
def app(scope, receive, send):
    # For simplicity in this test, we just check env on startup or via a request
    # Since we want to check worker env, we'll have the app write it to a file
    with open("worker_env.json", "w") as f:
        json.dump(dict(os.environ), f)
"""
        isolated_env.create_app("main.py", app_code)
        
        # 2. Set untrusted and trusted env vars
        root_dir = str(Path(__file__).parents[3])
        env = os.environ.copy()
        env["VELO_UNTRUSTED_SECRET"] = "SHHH_SENSITIVE"
        env["VELO_TRUSTED_VAR"] = "VISIBLE_OK"
        env["PYTHONPATH"] = f"{root_dir}:{env.get('PYTHONPATH', '')}"
        
        # 3. Start Velo
        port = isolated_env.next_port()
        # Use no-zygote to ensure we see the direct child env clearly
        proc = isolated_env.spawn_velo("serve", "main:app", "--port", str(port), env=env)
        
        try:
            import time
            import requests
            # Wait for startup
            time.sleep(5)
            
            # Trigger request to ensure worker is alive and has initialized
            try:
                requests.get(f"http://127.0.0.1:{port}/", timeout=2)
            except:
                pass
            
            # 4. Check the captured environment
            env_file = isolated_env.home / "worker_env.json"
            assert env_file.exists(), "Worker failed to write env file"
            
            import json
            worker_env = json.loads(env_file.read_text())
            
            # [DEF-72-S02] Assertion
            assert "VELO_UNTRUSTED_SECRET" not in worker_env, "SECURITY BREACH: VELO_UNTRUSTED_SECRET leaked to worker!"
            assert worker_env.get("VELO_TRUSTED_VAR") == "VISIBLE_OK", "Standard env var missing from worker"
            
        finally:
            proc.terminate()
            proc.wait()
