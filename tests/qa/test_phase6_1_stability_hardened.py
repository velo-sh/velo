import os
import pytest
import subprocess
import signal
import time
import psutil
import socket
from pathlib import Path

# QA Agent B: Hardened Stability & Platform Parity
# Requirements: RFC-0010 §4.1, §4.4, §4.6, §4.9

def get_free_port():
    """Get a free port by binding to port 0 and releasing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port

@pytest.mark.tier1
class TestPhase61StabilityHardened:
    
    def test_stab_rs_003_raii_cleanup(self, isolated_env):
        """
        RS-P0-003: RAII Child Cleanup (Drop)
        Goal: Verify child process is killed when parent exits/panics.
        """
        env = isolated_env
        env.create_app("main.py", "app = lambda s, r, se: None\nimport time; time.sleep(60)")
        
        port = get_free_port()
        
        # Start velo serve in a new process group
        proc = subprocess.Popen(
            [env.velo, "serve", "main:app", "--bind", f"127.0.0.1:{port}"],
            cwd=env.path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            preexec_fn=os.setsid
        )
        
        time.sleep(3)
        parent_pid = proc.pid
        
        # Find child (uvicorn/gunicorn)
        children = psutil.Process(parent_pid).children(recursive=True)
        assert len(children) >= 1
        child_pid = children[0].pid
        
        # Terminate parent (causes graceful exit where Drop can run)
        # Note: kill() sends SIGKILL which doesn't give Rust Drop a chance to run
        proc.terminate()  # SIGTERM allows cleanup
        proc.wait(timeout=10)
        
        # Requirement: Child MUST be reaped
        time.sleep(2)
        assert not psutil.pid_exists(child_pid)

    def _read_with_timeout(self, stream, timeout=5):
        import select
        start_time = time.time()
        while time.time() - start_time < timeout:
            r, _, _ = select.select([stream], [], [], 0.1)
            if r:
                line = stream.readline()
                if line:
                    return line
        return None

    def test_stab_rs_002_watcher_debounce(self, isolated_env):
        """
        ENG-P0-002: 300ms Watcher Debounce
        Goal: Rapid file events should trigger only one restart.
        """
        env = isolated_env
        env.create_app("main.py", "app = lambda s, r, se: None\nimport time\nprint(f'START_{time.time()}')")
        
        port = get_free_port()
        
        proc = subprocess.Popen(
            [env.velo, "serve", "main:app", "--reload", "--bind", f"127.0.0.1:{port}"],
            cwd=env.path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            bufsize=1
        )
        
        # Wait for first start
        start_count = 0
        line = self._read_with_timeout(proc.stdout, timeout=10)
        if line and "START_" in line:
            start_count += 1
        
        # Blast 100 events in 200ms
        for _ in range(100):
            (env.path / "main.py").touch()
            time.sleep(0.002)
            
        # Wait and see how many starts
        time.sleep(2)
        while True:
            line = self._read_with_timeout(proc.stdout, timeout=1)
            if not line: break
            if "START_" in line:
                start_count += 1
                
        # Debounce should have merged these into 1 or maybe 2 restarts max 
        # (depending on timing exactness)
        assert start_count <= 2 
        proc.kill()

    def test_stab_rs_002_starvation_vulnerability(self, isolated_env):
        """
        A-EDGE-6.1-001: Debouncer Starvation (Agent A Finding)
        Requirement: Debouncer MUST have a hard-cap (e.g. 2s) to prevent starvation.
        Goal: Continuous events for 3s should still trigger at least one restart.
        """
        env = isolated_env
        env.create_app("main.py", "app = lambda s, r, se: None\nimport time\nprint(f'START_{time.time()}')")
        
        port = get_free_port()
        
        proc = subprocess.Popen(
            [env.velo, "serve", "main:app", "--reload", "--bind", f"127.0.0.1:{port}"],
            cwd=env.path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            bufsize=1
        )
        
        # Wait for first start
        self._read_with_timeout(proc.stdout, timeout=5)
        
        # Continuous events every 200ms for 3 seconds ( > default 300ms debounce)
        start_trigger = time.time()
        while time.time() - start_trigger < 3:
            (env.path / "main.py").touch()
            time.sleep(0.2)
            
        # If implementation is vulnerable, it will NEVER restart during these 3s.
        # Requirement: It MUST restart at least once due to a hard-cap.
        output = ""
        while True:
            line = self._read_with_timeout(proc.stdout, timeout=1)
            if not line: break
            output += line
        
        proc.kill()
        assert "START_" in output, "Vulnerability Detected: Debouncer Starvation (restart never triggered during continuous events)"

    def test_stab_deadlock_pipe_saturation(self, isolated_env):
        """
        B-STAB-6.1-001: Subprocess Pipe Deadlock
        Goal: Parent MUST NOT deadlock when child produces massive output.
        """
        env = isolated_env
        # App that writes 1MB of text and then exits
        env.create_app("main.py", "import sys\nfor i in range(10000):\n    print('X' * 100)\nsys.exit(0)")
        
        # This will time out if Velo deadlocks on pipe read
        result = env.run_velo("run", "main.py", timeout=10)
        assert result.returncode == 0

    @pytest.mark.skipif(os.name != 'posix', reason="SIGTERM forwarding is Unix-specific")
    def test_stab_cn_002_sigterm_forwarding(self, isolated_env):
        """
        CN-P0-002: SIGTERM Forwarding
        Goal: Velo forwards SIGTERM to child and waits for graceful exit.
        """
        env = isolated_env
        env.create_app("main.py", """
app = lambda s, r, se: None
import signal, time, sys
def handler(sig, frame):
    print("CHILD_RECEIVED_SIGTERM")
    time.sleep(1)
    sys.exit(0)
signal.signal(signal.SIGTERM, handler)
print("CHILD_READY")
time.sleep(60)
""")
        
        port = get_free_port()
        
        proc = subprocess.Popen(
            [env.velo, "serve", "main:app", "--bind", f"127.0.0.1:{port}"],
            cwd=env.path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        
        # Wait for child ready
        while "CHILD_READY" not in proc.stdout.readline():
            pass
            
        # Sent SIGTERM to Velo
        proc.terminate()
        
        # Verify child received it
        output = ""
        while True:
            line = self._read_with_timeout(proc.stdout, timeout=5)
            if not line: break
            output += line
            if "CHILD_RECEIVED_SIGTERM" in line:
                break
        
        assert "CHILD_RECEIVED_SIGTERM" in output
        proc.wait(timeout=5)

    def test_stab_zombie_orphan_leak(self, isolated_env):
        """
        D-CHAO-6.1-002: Zombie/Orphan Leak (Agent D Finding)
        Goal: Verify no orphan/zombie processes after graceful shutdown (SIGTERM).
        
        This test verifies that when Velo receives SIGTERM and performs graceful shutdown,
        all child processes (including uvicorn workers) are properly cleaned up.
        """
        env = isolated_env
        env.create_app("main.py", "app = lambda s, r, se: None\nimport time; time.sleep(60)")
        
        port = get_free_port()
        
        # Start server in new session
        proc = subprocess.Popen(
            [env.velo, "serve", "main:app", "--bind", f"127.0.0.1:{port}"],
            cwd=env.path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            preexec_fn=os.setsid
        )
        
        time.sleep(3)
        parent_pid = proc.pid
        children = psutil.Process(parent_pid).children(recursive=True)
        assert len(children) >= 1, "Expected at least one child process (server worker)"
        child_pids = [c.pid for c in children]
        
        # Graceful shutdown with SIGTERM (allows Drop to run)
        proc.terminate()
        proc.wait(timeout=15)  # Allow time for graceful shutdown
        
        time.sleep(2)
        # Requirement: All child processes MUST be cleaned up
        for child_pid in child_pids:
            assert not psutil.pid_exists(child_pid), f"Leak Detected: Child process {child_pid} survived graceful shutdown"

    def test_stab_large_file_write_race(self, isolated_env):
        """
        D-CHAO-6.1-003: Large File Write Race (Agent D Finding)
        Goal: Watcher should NOT trigger restart until file write is complete/stable.
        """
        env = isolated_env
        env.create_app("main.py", "app = lambda s, r, se: None\nprint('READY')")
        
        port = get_free_port()
        
        proc = subprocess.Popen(
            [env.velo, "serve", "main:app", "--reload", "--bind", f"127.0.0.1:{port}"],
            cwd=env.path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        
        # Wait for ready
        line_count = 0
        while line_count < 10:
            line = proc.stdout.readline()
            if "READY" in line: break
            line_count += 1
        
        # Write 5MB file slowly (1MB chunks every 200ms)
        app_file = env.path / "main.py"
        with open(app_file, "w") as f:
            for i in range(5):
                f.write("print('LOADING')\n" * 10000)
                f.flush()
                os.fsync(f.fileno())
                time.sleep(0.5)
            f.write("print('FINAL_READY')\n")
            
        # Requirement: It should only restart once or twice, not for every chunk.
        # And specifically, it should eventually reach FINAL_READY.
        output = ""
        try:
            while True:
                line = self._read_with_timeout(proc.stdout, timeout=5)
                if not line: break
                output += line
        finally:
            proc.kill()
        
        assert "FINAL_READY" in output
        # If it triggers too early, it might fail to import or show partial code errors
        assert "SyntaxError" not in output, "Race Detected: Watcher triggered on partially written file"

    def test_stab_rs_002_starvation_hard_cap(self, isolated_env):
        """
        STB-RS-002 (Hard-Cap): Continuous events MUST trigger a restart after hard-cap (max 5s).
        Proves: Watcher does not reset debouncer indefinitely (Starvation).
        """
        env = isolated_env
        app_code = """
import os
import time
print(f"START_{os.getpid()}")
app = lambda s, r, se: None
"""
        app_file = env.path / "main.py"
        app_file.write_text(app_code)
        
        # Start server
        proc = subprocess.Popen(
            [env.velo, "serve", "main:app", "--reload"],
            cwd=env.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        try:
            # Wait for first start
            time.sleep(2)
            # Continuous events every 150ms for 4 seconds
            # Debounce delay is 300ms. If we send events every 150ms, it should NEVER restart
            # unless a hard-cap (of say 2s or 5s) is implemented.
            for i in range(30):
                with open(app_file, "a") as f:
                    f.write(f"\n# event {i}")
                time.sleep(0.15)
                
            # Now wait a bit for any pending restart to complete
            time.sleep(2)
            
            # Kill and collect
            proc.terminate()
            out, err = proc.communicate(timeout=1)
            starts = out.count("START_")
            # If starvation exists, starts will be 1 (the initial one).
            # If hard-cap exists, starts will be >= 2.
            assert starts >= 2, f"Starvation Detected: Only {starts} starts found after 4s of continuous events. Hard-cap missing in watcher.rs."
        except Exception:
            proc.kill()
            raise
        finally:
            if proc.poll() is None:
                proc.kill()

if __name__ == "__main__":
    pytest.main([__file__])
