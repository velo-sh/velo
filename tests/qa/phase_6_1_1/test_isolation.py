import pytest
import requests
import time
import os

class TestIsolation:
    """Tests for ImportShield isolation logic."""

    def test_ISOLATION_1_block_internal_framework(self, velo_serve_fixture):
        """Verify that user app cannot import velo_zygote."""
        # Create an app that tries to import velo_zygote
        app_path = velo_serve_fixture.tmp_path / "isolated_app.py"
        app_path.write_text("""
from fastapi import FastAPI
import sys
app = FastAPI()

@app.get("/")
def read_root():
    try:
        import velo_zygote.main
        return {"status": "LEAK", "error": "Import succeeded"}
    except ImportError as e:
        return {"status": "SHIELDED", "error": str(e)}
""")
        
        try:
            proc = velo_serve_fixture.start("isolated_app:app", workers=2, zygote=True)
            # proc.port is the L7 Proxy port
            url = f"http://127.0.0.1:{proc.port}/"
            
            # Give it a moment to start
            time.sleep(3)
            
            resp = requests.get(url)
            print(f"DEBUG: Response body: {resp.text}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "SHIELDED"
            # Accept either ImportShield message or path-sanitization message.
            # Both indicate the security mechanism is working correctly.
            assert ("Unauthorized access" in data["error"] or
                    "No module named" in data["error"]), f"Unexpected error: {data['error']}"
        finally:
            if os.path.exists("isolated_app.py"):
                os.remove("isolated_app.py")

    def test_ISOLATION_2_shadowing_protection(self, velo_serve_fixture):
        """Verify that a user module named 'main.py' is not shadowed."""
        # Overwrite the default main.py in tmp_path
        app_path = velo_serve_fixture.tmp_path / "main.py"
        app_path.write_text("""
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def read_root():
    return {"source": "user_main"}
""")
        
        try:
            proc = velo_serve_fixture.start("main:app", workers=2, zygote=True)
            url = f"http://127.0.0.1:{proc.port}/"
            
            time.sleep(3)
            
            resp = requests.get(url)
            print(f"DEBUG: Shadowing test response body: {resp.text}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["source"] == "user_main"
        finally:
            if os.path.exists("main.py"):
                os.remove("main.py")
            if os.path.exists("main.py.bak"):
                os.rename("main.py.bak", "main.py")
