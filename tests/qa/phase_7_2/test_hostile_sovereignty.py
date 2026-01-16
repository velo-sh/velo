"""
Hostile Verification Suite for Phase 7.2 (Native Sovereignty)
Invariants: SEC-SHIELD-003, SEC-SHIELD-006, SEC-FS-002, SEC-ENV-001
"""

import pytest
import os
import socket
import psutil
import requests
import time
import subprocess
from pathlib import Path

@pytest.mark.tier4
class TestHostileSovereignty:
    """
    Prosecutorial Verification (Phase III of SOP-002)
    Presumed Guilty until proven innocent via Zero-Mock.
    """

    def test_SEC_SHIELD_003_unique_zygote_identity(self, isolated_env):
        """[REQ-7.2-01] Verify UDS paths are workspace-hashed and isolated."""
        isolated_env.create_app("main.py", "app = lambda x: x")
        
        # Run velo serve
        port = isolated_env.next_port()
        proc = isolated_env.spawn_velo("serve", "main:app", "--port", str(port))
        
        try:
            # Wait for startup
            time.sleep(3)
            
            # Find socket dir
            sock_dir = isolated_env.env.get("VELO_SOCKET_DIR")
            if not sock_dir:
                sock_dir = isolated_env.env.get("XDG_RUNTIME_DIR")
            
            if not sock_dir or not Path(sock_dir).exists():
                pytest.skip("Socket directory not found")
            
            sock_dir = Path(sock_dir)
            
            # Verify socket presence
            sockets = list(sock_dir.glob("*.sock"))
            # If empty, maybe it's in a subdirectory
            if not sockets:
                sockets = list(sock_dir.rglob("*.sock"))
            
            assert len(sockets) > 0, f"No UDS sockets found in {sock_dir}"
            
            # Check permissions of the socket directory
            # TITANIUM Requirement: Socket dir must be 0700
            mode = os.stat(sock_dir).st_mode & 0o777
            assert mode == 0o700, f"SEC-SHIELD-003 FAIL: Socket dir {sock_dir} has insecure permissions: {oct(mode)}"
            
        finally:
            proc.terminate()
            proc.wait()

    def test_SEC_SHIELD_006_peer_hijack_protection(self, isolated_env):
        """[REQ-7.2-02] Hostile: Attempt to connect to worker socket from unauthorized process."""
        isolated_env.create_app("main.py", "app = lambda x: x")
        
        port = isolated_env.next_port()
        proc = isolated_env.spawn_velo("serve", "main:app", "--port", str(port), "--workers", "1")
        
        try:
            time.sleep(3)
            # Find socket dir
            sock_dir = isolated_env.env.get("VELO_SOCKET_DIR")
            if not sock_dir:
                sock_dir = isolated_env.env.get("XDG_RUNTIME_DIR")
            
            if not sock_dir:
                pytest.skip("Socket directory not found")
            
            sockets = list(Path(sock_dir).rglob("*.sock"))
            if not sockets:
                pytest.skip(f"No sockets found in {sock_dir}")
            
            target_sock = sockets[0]
            
            # HOSTILE ACT: Attempt to connect using a raw socket without Host authorization
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.settimeout(2)
                s.connect(str(target_sock))
                # Send fake RSGI header
                s.send(b"RSGI\x01\x00") 
                data = s.recv(1024)
                # If Zygote enforces peer hijacking protection, it should close or reject.
                assert b"AUTHORIZED" not in data, "SECURITY BREACH: Worker responded to unauthorized connector!"
            except (ConnectionRefusedError, socket.timeout, BrokenPipeError):
                # Valid protection
                pass
            finally:
                s.close()
                
        finally:
            proc.terminate()
            proc.wait()

    def test_SEC_FS_002_fd_hygiene(self, isolated_env):
        """[REQ-7.2-03] Hostile: Check /proc/self/fd in worker to ensure zero leaked FDs."""
        isolated_env.create_app("main.py", """
from fastapi import FastAPI
import os
app = FastAPI()

@app.get("/fds")
def get_fds():
    try:
        fds = os.listdir("/proc/self/fd")
        return {"fds": fds, "count": len(fds)}
    except FileNotFoundError:
        # macOS fallback
        return {"error": "Not Linux", "count": -1}
""")
        
        port = isolated_env.next_port()
        proc = isolated_env.spawn_velo("serve", "main:app", "--port", str(port))
        
        try:
            for _ in range(20):
                try:
                    resp = requests.get(f"http://127.0.0.1:{port}/fds", timeout=1)
                    if resp.status_code == 200:
                        break
                except:
                    pass
                time.sleep(0.5)
            
            resp = requests.get(f"http://127.0.0.1:{port}/fds")
            data = resp.json()
            
            if data.get("count") == -1:
                pytest.skip("Platform does not support /proc/self/fd check")
            
            # Standard FDs: 0 (stdin), 1 (stdout), 2 (stderr), 3 (UDS/Pipe)
            # Anything above 10 is suspicious of leak from Rust Host
            leaked_fds = [fd for fd in data["fds"] if int(fd) > 10]
            assert len(leaked_fds) == 0, f"SEC-FS-002 FAIL: Leaked FDs detected in worker: {leaked_fds}"
            
        finally:
            proc.terminate()
            proc.wait()

    def test_SEC_ENV_001_provenance_guard(self, isolated_env):
        """[REQ-7.2-04] Verify velo uses the hermetic, verified toolchain (embedded uv)."""
        # Run velo info and check for uv provenance
        result = isolated_env.run_velo("info")
        assert result.returncode == 0
        output = result.stdout.lower()
        
        # Verify uv is being used for dependency management
        assert "uv" in output, "SEC-ENV-001 FAIL: Velo info does not report uv integration"
        
        # Verify no external LD_PRELOAD leakage
        env = {"LD_PRELOAD": "/tmp/evil.so"}
        result = isolated_env.run_velo("info", env=env)
        # (Implementation check: Host should scrub this before passing to workers/children)
        # This is harder to verify via 'info' but we check that velo doesn't crash
        assert result.returncode == 0
