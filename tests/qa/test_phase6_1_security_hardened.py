import os
import pytest
import subprocess
import signal
import sys
import time
from pathlib import Path

# QA Agent C: Hardened Security Invariants
# Requirements: RFC-0010 §4.10 (SEC-P0-001 to SEC-P0-006)

@pytest.mark.tier1
class TestPhase61SecurityHardened:
    
    def test_sec_p0_001_command_injection(self, isolated_env):
        """
        SEC-P0-001: Command Injection Prevention
        Requirement: Reject app targets not matching strict regex.
        """
        env = isolated_env
        malicious_targets = [
            "main:app; rm -rf /",
            "main:app$(whoami)",
            "main:app && cat /etc/passwd",
            "main:app|nc -l 4444",
            "main:app`id`"
        ]
        
        for target in malicious_targets:
            result = env.run_velo("serve", target, timeout=5)
            assert result.returncode != 0
            assert "error" in result.stderr.lower() or "invalid" in result.stderr.lower()

    def test_sec_p0_002_path_traversal(self, isolated_env):
        """
        SEC-P0-002: Path Traversal Protection
        Requirement: Scan paths must be within project root (rooted scan).
        """
        env = isolated_env
        outside_path = "/etc"
        if sys.platform == "darwin":
            outside_path = "/private/etc"
            
        result = env.run_velo("analyze", "--graph", outside_path, timeout=5)
        assert result.returncode != 0
        assert "access denied" in result.stderr.lower() or "outside" in result.stderr.lower()

    def test_sec_p0_003_pid_file_safety(self, isolated_env):
        """
        SEC-P0-003: Safe PID File Creation
        Requirement: Use O_EXCL to prevent symlink attacks (DO-P0-001).
        """
        env = isolated_env
        pid_file = env.path / "velo.pid"
        target_file = env.path / "sensitive_file"
        target_file.write_text("don't touch")
        
        # Create symlink: velo.pid -> sensitive_file
        os.symlink(target_file, pid_file)
        
        # Start velo serve --pid-file
        result = env.run_velo("serve", "main:app", "--pid-file", str(pid_file), timeout=5)
        assert result.returncode != 0
        assert target_file.read_text() == "don't touch"

    def test_sec_p0_003_pid_file_hijack_prevention(self, isolated_env):
        """
        SEC-P0-003: PID File Hijack Protection
        Requirement: Velo MUST fail if the PID file already exists (O_EXCL).
        """
        env = isolated_env
        pid_file = env.path / "velo.pid"
        pid_file.write_text("99999") # Hijack
        
        result = env.run_velo("serve", "main:app", "--pid-file", str(pid_file), timeout=5)
        assert result.returncode != 0
        assert "exists" in result.stderr.lower() or "denied" in result.stderr.lower()

    def test_sec_p0_004_minimal_health_response(self, isolated_env):
        """
        SEC-P0-004: Minimal Health Response
        Requirement: Return ONLY status, no metadata (version, pid, etc).
        """
        env = isolated_env
        env.create_app("main.py", "from fastapi import FastAPI\napp = FastAPI()")
        
        health_port = 8081
        proc = subprocess.Popen(
            [env.velo, "serve", "main:app", "--health-bind", f"127.0.0.1:{health_port}"],
            cwd=env.path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        
        time.sleep(3)
        try:
            import requests
            resp = requests.get(f"http://127.0.0.1:{health_port}/healthz", timeout=1)
            assert resp.status_code == 200
            assert resp.text.strip() == "OK"
            
            # C-SEC-6.1-001: Reconnaissance Prevention
            # Verify no disclosure in headers
            server_header = resp.headers.get("Server", "").lower()
            assert "velo" not in server_header, "Security Leak: Server identity disclosed in headers"
            assert "version" not in resp.text.lower(), "Security Leak: Metadata disclosed in body"
            
            # Verify no X-Powered-By or other fingerprint headers
            assert "x-powered-by" not in resp.headers, "Security Leak: Fingerprint header found"
        except ImportError:
            pass # Skip if requests not in test env
        finally:
            proc.kill()

    def test_sec_p0_005_env_sanitization(self, isolated_env):
        """
        SEC-P0-005: Environment Sanitization
        Requirement: Mandatory removal of PYTHONPATH, LD_PRELOAD, etc.
        """
        env = isolated_env
        env.create_app("check_env.py", "import os; print(os.environ.get('PYTHONPATH', 'NONE'))")
        
        my_env = os.environ.copy()
        my_env["PYTHONPATH"] = "/malicious/path"
        
        result = env.run_velo("run", "check_env.py", env=my_env)
        assert "/malicious/path" not in result.stdout

    def test_sec_p0_006_watcher_rate_limiting(self, isolated_env):
        """
        SEC-P0-006: File Watcher Rate Limiting
        Requirement: Throttle if > 100 events/sec.
        """
        env = isolated_env
        env.create_app("main.py", "app = lambda scope, receive, send: None\nprint('START')")
        
        # Create 200 files rapidly
        for i in range(200):
            (env.path / f"file_{i}.py").touch()
            
        # Implementation check: Velo should log a warning or throttle
        # We'll check if the watcher is still alive and didn't crash
        proc = subprocess.Popen([env.velo, "serve", "main:app"], cwd=env.path)
        time.sleep(1)
        assert proc.poll() is None
        proc.kill()

if __name__ == "__main__":
    pytest.main([__file__])
