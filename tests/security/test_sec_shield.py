import os
import sys
import subprocess
import pytest
import time
import socket
import signal
import hashlib
import glob

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
        # Command: velo run -c "import os; print(os.environ['PATH'])"
        result = subprocess.run(
            [VELO_BIN, "run", "-c", "import os; print(os.environ['PATH'])"],
            env=malicious_env,
            capture_output=True,
            text=True
        )

        # 3. Verification
        # Success = Result exists but toxic path is GONE (Surgical Scrubbing mandated by RFC)
        assert result.returncode == 0, f"Velo crashed or failed to start: {result.stderr}"
        assert toxic_path not in result.stdout, \
            f"SECURITY FAILURE: Malicious PATH '{toxic_path}' was not scrubbed by EnvironmentProvenanceGuard!"

    @pytest.mark.skipif(sys.platform != "linux", reason="FD probes via /proc require Linux")
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
        
        # 2. Spawn Velo and probe /proc/self/fd
        probe_script = "import os; print(list(os.listdir('/proc/self/fd')))"
        
        result = subprocess.run(
            [VELO_BIN, "run", "-c", probe_script],
            capture_output=True,
            text=True,
            # Pass the FD to the OS spawn, but Velo's runner.rs should close it manually if not in whitelist
            pass_fds=[sensitive_fd] 
        )
        
        sensitive_file.close()
        
        # 3. Verification
        # The list of FDs should only contain 0, 1, 2, and perhaps the pipe used for communication
        # It MUST NOT contain our sensitive_fd
        worker_fds = result.stdout.strip()
        assert str(sensitive_fd) not in worker_fds, \
            f"SECURITY FAILURE: Sensitive FD {sensitive_fd} leaked into the worker process! FDs detected: {worker_fds}"

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
                # macOS check: Look for the mkdtemp'd path
                # Pattern: /tmp/velo-secure-*/zygote.sock
                matches = glob.glob("/tmp/velo-secure-*/zygote-*.sock") + \
                          glob.glob(os.path.join(os.environ.get("TMPDIR", "/tmp"), "velo-secure-*/zygote-*.sock"))
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
        
        result = subprocess.run(
            [VELO_BIN, "run", "-c", "import os; print(os.environ.get('LD_LIBRARY_PATH', 'CLEAN')); print(os.environ.get('PYTHONHOME', 'CLEAN'))"],
            env=toxin_env,
            capture_output=True,
            text=True
        )
        
        assert "CLEAN" in result.stdout
        assert "/tmp/evil_libs" not in result.stdout
        assert "/tmp/evil_python" not in result.stdout
