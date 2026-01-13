import pytest
import subprocess
import time
import socket
import os
import msgpack
import sys
from pathlib import Path
import contextlib
import textwrap
import signal

@pytest.fixture
def run_velo_with_mock_worker(isolated_env):
    """Utility to run velo with a mock python interpreter."""
    @contextlib.contextmanager
    def _run(worker_logic_path, env=None):
        # Create a "fake" python script that runs our mock worker
        fake_python = isolated_env.home / "bin" / "python3"
        fake_python.parent.mkdir(parents=True, exist_ok=True)
        
        python_exe = sys.executable
        with open(fake_python, "w") as f:
            f.write("#!/bin/bash\n")
            f.write("echo \"Wrapper called with args: $@\" >> /tmp/wrapper.log\n")
            f.write("if [[ \"$*\" == *\"--uds\"* ]]; then\n")
            f.write("    echo \"Intercepting worker spawn\" >> /tmp/wrapper.log\n")
            # We MUST use exec so the PID matches what Velo expects (Gate H)
            f.write(f"    exec {python_exe} {worker_logic_path} \"$@\" 2>> /tmp/worker_err.log\n")
            f.write("else\n")
            f.write(f"    exec {python_exe} \"$@\"\n")
            f.write("fi\n")
        
        fake_python.chmod(0o755)
        
        # Point VELO_PYTHON to our fake one and set socket dir
        env_vars = os.environ.copy()
        env_vars.pop("VIRTUAL_ENV", None)
        env_vars.pop("PYTHONHOME", None)
        env_vars["VELO_PYTHON"] = str(fake_python)
        
        # macOS has 104 char limit for UDS. pytest tmp dirs are too long.
        short_socket_dir = Path("/tmp") / f"v{os.getpid()}"
        short_socket_dir.mkdir(parents=True, exist_ok=True)
        env_vars["VELO_SOCKET_DIR"] = str(short_socket_dir)
        # Ensure PYTHONPATH includes project root for velo_zygote
        root_dir = str(Path(__file__).parents[3])
        env_vars["PYTHONPATH"] = f"{root_dir}:{env_vars.get('PYTHONPATH', '')}"
        
        # Create a dummy module to satisfy early validation
        (isolated_env.home / "dummy.py").write_text("app = lambda x: x")
        
        if env:
            env_vars.update(env)
        
        # Start velo serve with a dynamic port
        port = isolated_env.next_port()
        cmd = [isolated_env.velo, "serve", "dummy:app", "--rsgi", "--no-zygote", "--verbose", "--port", str(port)]
        import signal
        proc = subprocess.Popen(
            cmd,
            cwd=isolated_env.home,
            env=env_vars,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True
        )
        try:
            yield proc, port
        finally:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except:
                pass
            proc.wait()

    return _run

@pytest.fixture
def mock_worker_logic(tmp_path):
    """Creates a worker logic script that parses --uds and performs protocol actions."""
    def _create(logic_snippet):
        indented_logic = textwrap.indent(textwrap.dedent(logic_snippet), " " * 20)
        path = tmp_path / "logic.py"
        template = r"""
import socket
import msgpack
import sys
import argparse
import struct
import os
import traceback

def send_msg(s, msg):
    payload = msgpack.packb(msg)
    s.sendall(struct.pack(">I", len(payload)) + payload)

def recv_msg(s):
    len_data = s.recv(4)
    if not len_data: return None
    length = struct.unpack(">I", len_data)[0]
    return msgpack.unpackb(s.recv(length))

def main():
    log_path = os.environ.get("VELO_WORKER_DEBUG_LOG", "/tmp/velo_worker_debug.log")
    with open(log_path, "a") as log:
        try:
            parser = argparse.ArgumentParser()
            parser.add_argument("--uds")
            args, _ = parser.parse_known_args()
            
            log.write(f"Worker started with args: {sys.argv}\n")
            log.write(f"CWD: {os.getcwd()}\n")
            
            if not args.uds:
                log.write("ERROR: No UDS path provided\n")
                sys.exit(1)
            
            if os.path.exists(args.uds):
                log.write(f"Unlinking existing socket: {args.uds}\n")
                os.unlink(args.uds)
                
            ls = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            ls.bind(args.uds)
            ls.listen(5)
            log.write(f"Bound to {args.uds}, waiting for connections...\n")
            
            while True:
                conn, _ = ls.accept()
                log.write("Connection accepted!\n")
                
                try:
{indented_logic}
                    conn.close()
                    log.write("Handshake logic completed successfully\n")
                    break
                except (BrokenPipeError, ConnectionResetError) as e:
                    log.write(f"Transient connection error: {e}. Retrying...\n")
                    conn.close()
                    continue
                except Exception as e:
                    log.write(f"LOGIC EXCEPTION: {e}\n")
                    with open(log_path, "a") as log_err:
                        traceback.print_exc(file=log_err)
                    sys.exit(1)
            ls.close()
        except Exception as e:
            log.write(f"MAIN EXCEPTION: {e}\n")
            with open(log_path, "a") as log_err:
                traceback.print_exc(file=log_err)
            sys.exit(1)

if __name__ == "__main__":
    main()
"""
        path.write_text(template.replace("{indented_logic}", indented_logic))
        return path
    return _create

class TestRsgiProtocol:
    """Prosecutor Suite for RSGI Protocol Handshake."""

    def wait_for_port(self, port, timeout=10):
        import time
        start = time.time()
        while time.time() - start < timeout:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return True
            except (socket.error, ConnectionRefusedError):
                time.sleep(0.1)
        return False

    def trigger_request(self, port):
        import urllib.request
        import threading
        def _req():
            try:
                # Use a larger timeout to avoid client-side timeout before Host-side error
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5)
            except:
                pass
        t = threading.Thread(target=_req)
        t.start()
        return t

    def terminate_and_communicate(self, proc, timeout=10):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except:
            pass
        try:
            return proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except:
                pass
            return proc.communicate()

    @pytest.mark.tier1
    def test_handshake_success(self, isolated_env, mock_worker_logic, run_velo_with_mock_worker):
        """[H-PRO-01] Verify valid READY -> AUTH_OK handshake."""
        logic = """
# 1. Send READY
send_msg(conn, [0x10, "1.0.0", "worker-1", None, None])

# 2. Recv AUTH_OK
resp = recv_msg(conn)
if resp and resp[0] == 0x11:
    log.write("HANDSHAKE_SUCCESS\\n")
else:
    log.write(f"HANDSHAKE_FAILED: {resp}\\n")
log.flush()
"""
        debug_log = Path(isolated_env.home / "worker_success.log")
        logic_path = mock_worker_logic(logic)
        env = {"VELO_WORKER_DEBUG_LOG": str(debug_log)}

        with run_velo_with_mock_worker(logic_path, env=env) as (proc, port):
            if not self.wait_for_port(port): pytest.fail("Velo failed to start")
            t = self.trigger_request(port)
            
            # Poll for success message in log
            found = False
            for _ in range(20):
                if debug_log.exists() and "HANDSHAKE_SUCCESS" in debug_log.read_text():
                    found = True
                    break
                time.sleep(0.5)
            
            stdout, stderr = self.terminate_and_communicate(proc)
            t.join(timeout=1)
            
        assert found, f"HANDSHAKE_SUCCESS not found in {debug_log}. Log: {debug_log.read_text() if debug_log.exists() else 'EMPTY'}"

    @pytest.mark.tier1
    def test_handshake_malformed_ready(self, isolated_env, mock_worker_logic, run_velo_with_mock_worker):
        """[H-PRO-02] Verify Host rejects malformed READY (wrong type)."""
        logic = """
# Send wrong message type (0x01 instead of 0x10)
send_msg(conn, [0x01, "garbage"])
"""
        logic_path = mock_worker_logic(logic)
        with run_velo_with_mock_worker(logic_path) as (proc, port):
            if not self.wait_for_port(port): pytest.fail("Velo failed to start")
            t = self.trigger_request(port)
            stdout, stderr = self.terminate_and_communicate(proc)
            t.join(timeout=1)
            
        # PROSECUTOR NOTE: If this fails, dev is swallowing protocol errors in Host!
        assert "Expected READY, got type 1" in stderr

    @pytest.mark.tier1
    def test_handshake_timeout(self, isolated_env, mock_worker_logic, run_velo_with_mock_worker):
        """[H-PRO-03] Verify Host enforces 500ms handshake timeout."""
        logic = """
# Just sleep to trigger timeout
import time
time.sleep(1.0)
"""
        logic_path = mock_worker_logic(logic)
        with run_velo_with_mock_worker(logic_path) as (proc, port):
            if not self.wait_for_port(port): pytest.fail("Velo failed to start")
            t = self.trigger_request(port)
            stdout, stderr = self.terminate_and_communicate(proc)
            t.join(timeout=1)
            
        # PROSECUTOR NOTE: If this fails, dev is missing the Gate E timeout logic!
        assert "Handshake timed out after 500ms" in stderr
