import os
import sys
import subprocess
import pytest
import time
import socket
import signal
import hashlib
import glob
import tempfile

# Path to the compiled binary - adjusted to be relative to project root or absolute
# For CI/Local, we assume it's in target/debug/velo
VELO_BIN = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../target/debug/velo"))

class TestSecurityShieldIntegration:
    """
    The 'Real' Executioner Suite: Integration tests for RFC-0012.
    No mocks. Directly attacks the compiled Rust binary to verify security invariants.
    """

    @pytest.mark.skipif(not os.path.exists(VELO_BIN), reason=f"Velo binary not found at {VELO_BIN}. Run 'cargo build' first.")
    def test_sec_shield_005_env_provenance_enforcement(self):
        """
        SEC-SHIELD-005: Attack Test - Inject malicious PATH.
        Velo must either block startup or surgically scrub the toxic entry.
        """
        # 1. Setup malicious environment
        malicious_env = os.environ.copy()
        # Inject a dangerous path that RFC-0012 must intercept
        toxic_path = "/tmp/hackers_bin"
        if not os.path.exists(toxic_path):
            os.makedirs(toxic_path, exist_ok=True)
            
        malicious_env["PATH"] = f"{toxic_path}:" + malicious_env.get("PATH", "")
        
        # 2. Run Velo to probe its own environment
        # Command: velo run probe.py
        probe_file = os.path.join(toxic_path, "probe.py")
        with open(probe_file, "w") as f:
            f.write("import os; print(os.environ['PATH'])")
            
        result = subprocess.run(
            [VELO_BIN, "run", probe_file],
            env=malicious_env,
            capture_output=True,
            text=True
        )

        # 3. Verification
        # Success = Result exists but toxic path is GONE (Surgical Scrubbing mandated by RFC)
        assert result.returncode == 0, f"Velo crashed or failed to start: {result.stderr}"
        assert toxic_path not in result.stdout, \
            f"SECURITY FAILURE: Malicious PATH '{toxic_path}' was not scrubbed by EnvironmentProvenanceGuard!"

    @pytest.mark.skipif(not os.path.exists(VELO_BIN), reason="Binary missing")
    def test_sec_shield_004_fd_leakage_real(self):
        """
        SEC-SHIELD-004: FD Leakage Test.
        Verify that workers do NOT inherit sensitive parent FDs.
        """
        # 1. Parent process opens a sensitive file
        sensitive_file = open("Cargo.toml", "r")
        sensitive_fd = sensitive_file.fileno()
        
        # Ensuring we have a high FD to test the hygiene loop
        assert sensitive_fd > 2
        
        # 2. Spawn Velo and probe FDs (/proc/self/fd on Linux, /dev/fd on macOS)
        fd_path = '/proc/self/fd' if sys.platform == 'linux' else '/dev/fd'
        probe_script_content = f"import os; print(list(os.listdir('{fd_path}')))"
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp_script:
            tmp_script.write(probe_script_content)
            tmp_script_path = tmp_script.name

        try:
            result = subprocess.run(
                [VELO_BIN, "run", tmp_script_path],
                capture_output=True,
                text=True,
                # Pass the FD to the OS spawn, but Velo's runner.rs should close it manually if not in whitelist
                pass_fds=[sensitive_fd] 
            )
        finally:
            if os.path.exists(tmp_script_path):
                os.remove(tmp_script_path)
        
        sensitive_file.close()
        
        # 3. Verification
        # The list of FDs should only contain 0, 1, 2, and perhaps the pipe used for communication
        # It MUST NOT contain our sensitive_fd
        worker_fds_raw = result.stdout.strip()
        # Find the list in the output (in case there are warnings/logs)
        import re
        match = re.search(r'\[(.*?)\]', worker_fds_raw)
        if match:
            worker_fds = [f.strip(" '\"") for f in match.group(1).split(',')]
            assert str(sensitive_fd) not in worker_fds, \
                f"SECURITY FAILURE: Sensitive FD {sensitive_fd} leaked into the worker process! FDs detected: {worker_fds}"
        else:
            # Fallback for unexpected format, but alert if sensitive_fd is in the list-like part
            assert f"'{sensitive_fd}'" not in worker_fds_raw and f'"{sensitive_fd}"' not in worker_fds_raw, \
                f"SECURITY FAILURE: Sensitive FD {sensitive_fd} suspected in worker output: {worker_fds_raw}"

    @pytest.mark.skipif(not os.path.exists(VELO_BIN), reason="Binary missing")
    def test_sec_shield_003_zygote_isolation_real(self, tmp_path):
        """
        SEC-SHIELD-003: Zygote Isolation Verification.
        Verify that Zygote uses either Abstract Namespace (Linux) or Atomic Temp Dirs (macOS).
        """
        # 1. Start a Zygote server in the background
        # We use a dummy project root to ensure hashing/naming works
        proc = subprocess.Popen(
            [VELO_BIN, "serve", "--zygote"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=tmp_path
        )
        
        try:
            time.sleep(1.5) # Give it time to bind
            
            if sys.platform == "linux":
                # Check /proc/net/unix for the abstract socket
                with open("/proc/net/unix", "r") as f:
                    unix_sockets = f.read()
                    # Abstract sockets start with @ or are shown as @... or \0...
                    assert "@velo-zygote-" in unix_sockets or "velo-zygote-" in unix_sockets, \
                        "SECURITY FAILURE: Abstract Zygote socket not detected in /proc/net/unix"
            else:
                # macOS check: Look for the secure randomized path
                # Pattern: /tmp/velo-secure-*/velo-zygote-v*.sock
                matches = glob.glob("/tmp/velo-secure-*/velo-zygote-v*.sock") + \
                          glob.glob(os.path.join(os.environ.get("TMPDIR", "/tmp"), "velo-secure-*/velo-zygote-v*.sock"))
                assert len(matches) > 0, "SECURITY FAILURE: Atomic randomized Zygote socket not found on macOS"
                
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    @pytest.mark.skipif(not os.path.exists(VELO_BIN), reason="Binary missing")
    def test_sec_shield_001_toxin_blocking(self):
        """
        SEC-SHIELD-001: Blocking toxins like LD_LIBRARY_PATH and PYTHONHOME.
        """
        toxin_env = os.environ.copy()
        toxin_env["LD_LIBRARY_PATH"] = "/tmp/evil_libs"
        toxin_env["PYTHONHOME"] = "/tmp/evil_python"
        
        probe_file = os.path.join(tempfile.gettempdir(), "probe_toxin.py")
        with open(probe_file, "w") as f:
            f.write("import os; print(os.environ.get('LD_LIBRARY_PATH', 'CLEAN')); print(os.environ.get('PYTHONHOME', 'CLEAN'))")
            
        result = subprocess.run(
            [VELO_BIN, "run", probe_file],
            env=toxin_env,
            capture_output=True,
            text=True
        )
        
        assert "CLEAN" in result.stdout
        assert "/tmp/evil_libs" not in result.stdout
        assert "/tmp/evil_python" not in result.stdout
