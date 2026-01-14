import pytest
import os
import signal
import psutil
import socket
import struct
import msgpack
import requests
from pathlib import Path

class TestSovereigntyForensics:
    """
    Forensic Prosecution Suite targeting the core architectural claims of Phase 7.2.
    Uses White-box (Process/FD) and Black-box (Network/Protocol) validation.
    """

    @pytest.mark.tier4
    def test_forensic_process_tree_purity(self, isolated_env):
        """
        [FP-01] Identity Invariant: No Uvicorn presence.
        If Native Sovereignty is implemented, Velo must use Granian/RSGI, not Uvicorn.
        """
        isolated_env.create_app("main.py", "app = lambda x: x")
        port = isolated_env.next_port()
        
        root_dir = str(Path(__file__).parents[3])
        env = {"PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"}
        
        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--no-zygote", "--port", str(port), env=env)
        
        try:
            import time
            # Wait for workers to spawn
            for _ in range(10):
                parent = psutil.Process(proc.pid)
                if len(parent.children()) > 0:
                    break
                time.sleep(0.5)
            
            children = parent.children(recursive=True)
            
            # Forensic Check A: No 'uvicorn' in any command line or process name
            all_procs = [parent] + children
            for p in all_procs:
                try:
                    cmdline = " ".join(p.cmdline()).lower()
                    name = p.name().lower()
                    assert "uvicorn" not in cmdline, f"ARCHITECTURAL DRIFT: Found 'uvicorn' in cmdline of PID {p.pid}: {cmdline}"
                    assert "uvicorn" not in name, f"ARCHITECTURAL DRIFT: Found 'uvicorn' in name of PID {p.pid}: {name}"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                
            # Forensic Check B: Worker must be a direct python process (Zygote or Direct)
            worker_found = False
            for child in children:
                try:
                    cmdline = " ".join(child.cmdline())
                    if "python" in cmdline.lower() or "velo" in cmdline.lower():
                        worker_found = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            assert worker_found, "Worker process not identified in process tree."

        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.tier4
    def test_forensic_fd_ownership(self, isolated_env):
        """
        [FP-02] Resource Invariant: Rust Root Sovereignty (FD Ownership).
        TCP 0.0.0.0:[PORT] must be owned by the Rust parent, NEVER by Python workers.
        """
        isolated_env.create_app("main.py", "app = lambda x: x")
        port = isolated_env.next_port()
        
        root_dir = str(Path(__file__).parents[3])
        env = {"PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"}
        
        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--no-zygote", "--port", str(port), env=env)
        
        try:
            import time
            time.sleep(3)
            
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)
            
            # White-box check: Find the process listening on the port
            # We use process.connections() instead of global psutil.net_connections() for permission safety
            try:
                parent_conns = parent.connections(kind='tcp')
                listening_on_port = any(c.laddr.port == port and c.status == 'LISTEN' for c in parent_conns)
                assert listening_on_port, f"Rust Host (PID {proc.pid}) is NOT listening on port {port}. Conns: {parent_conns}"
            except psutil.AccessDenied:
                # Fallback to checking if the process exists and we can reach it
                resp = requests.get(f"http://127.0.0.1:{port}", timeout=2)
                assert resp.status_code == 200
            
            # Critical Assertion: NO Python worker should have this port in LISTEN state
            for child in children:
                try:
                    child_conns = child.connections(kind='tcp')
                    for c in child_conns:
                        if c.laddr.port == port and c.status == 'LISTEN':
                            pytest.fail(f"SOVEREIGNTY BREACH: Worker (PID {child.pid}) is holding the listening port {port}!")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        
        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.tier4
    def test_forensic_environment_black_hole(self, isolated_env):
        """
        [FP-03] Security Invariant: Environment Shield Absolute Isolation.
        Un-whitelisted variables must be invisible to the Python runtime.
        """
        # Create an app that returns all environment variables
        isolated_env.create_app("main.py", """
import os, json
async def app(scope, receive, send):
    if scope['type'] == 'http':
        # Filter for our test keys
        env_dict = {k: v for k, v in os.environ.items() if 'VELO_FORENSIC' in k}
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [[b'content-type', b'application/json']]
        })
        await send({
            'type': 'http.response.body',
            'body': json.dumps(env_dict).encode()
        })
""")
        
        secret_key = "VELO_FORENSIC_SECRET_DO_NOT_LEAK"
        secret_val = "CLEAN_ROOM_VERIFIED"
        
        # Build environment with required PYTHONPATH
        root_dir = str(Path(__file__).parents[3])
        env = os.environ.copy()
        env[secret_key] = secret_val
        env["PYTHONPATH"] = f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"
        
        port = isolated_env.next_port()
        # Start Velo. It should NOT leak this env var to the worker.
        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--no-zygote", "--port", str(port), env=env)
        
        try:
            import time
            time.sleep(3)
            resp = requests.get(f"http://127.0.0.1:{port}", timeout=5)
            worker_env = resp.json()
            
            assert secret_key not in worker_env, f"SECURITY LEAK: Forbidden environment variable '{secret_key}' found in worker!"
            
        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.tier4
    def test_forensic_rsgi_protocol_integrity(self, isolated_env):
        """
        [FP-04] Protocol Invariant: RSGI State Machine Poisoning.
        Host must reject multiple READY messages or interleaved garbage.
        """
        isolated_env.create_app("main.py", "app = lambda x: x")
        vdir = Path(f"/tmp/v{os.getpid()}_rsgi_fp")
        vdir.mkdir(parents=True, exist_ok=True)
        
        root_dir = str(Path(__file__).parents[3])
        env = {
            "VELO_SOCKET_DIR": str(vdir),
            "PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"
        }
        port = isolated_env.next_port()
        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--no-zygote", "--port", str(port), env=env)
        
        try:
            import time
            time.sleep(2)
            
            # Find the socket
            sockets = list(vdir.glob("v-worker-*.sock"))
            assert len(sockets) > 0
            socket_path = str(sockets[0])
            
            # Scenario: Multiple READY messages from the SAME connection
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(socket_path)
            
            # 1. Send first valid READY (fake PID)
            # Use valid PID to pass initial check if it was fixed
            my_pid = os.getpid()
            payload = msgpack.packb([0x10, "1.0.0", str(my_pid), {}, {}])
            s.sendall(struct.pack(">I", len(payload)) + payload)
            
            # 2. Wait for response (might be AUTH_OK or connection close if PID auth is working)
            data = s.recv(1024)
            if not data:
                return # Host correctly rejected unknown PID connection
                
            # 3. If connection stayed open, send SECOND READY (State Poisoning)
            # According to RSGI spec, only ONE READY is allowed per session.
            s.sendall(struct.pack(">I", len(payload)) + payload)
            
            # Expect: Host should Sever the connection for protocol violation
            time.sleep(0.5)
            s.setblocking(False)
            try:
                extra = s.recv(1024)
                if extra:
                    # If we get more data instead of a close, it's a protocol violation
                    pytest.fail("PROTOCOL WEAKNESS: Host accepted duplicate READY message without closing connection.")
            except (BlockingIOError, ConnectionResetError, BrokenPipeError):
                pass # Good
                
        finally:
            proc.terminate()
            proc.wait()
