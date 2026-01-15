import pytest
import os
import socket
from pathlib import Path

class TestNativeSecurity:
    """
    Verification of Security Invariants for Phase 7.2.
    - [H-SEC-01] Atomic IPC Isolation
    - [H-SEC-02] Peer Authentication
    """

    @pytest.mark.tier4
    def test_uds_isolation_permissions(self, isolated_env):
        """[H-SEC-01] Verify UDS socket directory has 0o700 permissions."""
        vdir = Path(f"/tmp/v{os.getpid()}")
        vdir.mkdir(parents=True, exist_ok=True)
        isolated_env.create_app("main.py", "app = lambda x: x")
        
        # Ensure PYTHONPATH includes project root for velo_zygote
        root_dir = os.getcwd()
        env = {"VELO_SOCKET_DIR": str(vdir)}
        env["PYTHONPATH"] = f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"
        
        port = isolated_env.next_port()
        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--no-zygote", "--port", str(port), env=env)
        
        try:
            import time
            time.sleep(2)
            
            # When VELO_SOCKET_DIR is set, VeloPaths returns it directly (no velo-uid append)
            socket_dir = vdir
            
            assert socket_dir.exists(), f"Socket directory {socket_dir} should exist"
            
            mode = os.stat(socket_dir).st_mode & 0o777
            assert mode == 0o700, f"Directory {socket_dir} should have 0o700 permissions, got {oct(mode)}"
                
        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.tier4
    def test_peer_authentication_enforcement(self, isolated_env):
        """[H-SEC-02] Verify Host rejects UDS connection from unauthorized UID."""
        isolated_env.create_app("main.py", "app = lambda x: x")
        vdir = Path(f"/tmp/v{os.getpid()}_peer")
        vdir.mkdir(parents=True, exist_ok=True)
        root_dir = str(Path(__file__).parents[3])
        env = {
            "VELO_SOCKET_DIR": str(vdir),
            "PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"
        }
        port = isolated_env.next_port()
        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--no-zygote", "--verbose", "--port", str(port), env=env)
        
        try:
            import time
            time.sleep(2)
            
            # 2. Find the worker socket
            # When VELO_SOCKET_DIR is set, VeloPaths returns it directly
            socket_dir = vdir
            sockets = list(socket_dir.glob("v-worker-*.sock"))
            assert len(sockets) > 0, f"No sockets found in {socket_dir}"
            
            # 3. Attempt to connect from the test process (which has the same UID but DIFFERENT PID)
            # The Host should reject it because the PID doesn't match the launched worker.
            socket_path = sockets[0]
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(str(socket_path))
            
            # 4. Try to send a READY message
            import struct
            import msgpack
            payload = msgpack.packb([0x10, "1.0.0", "hijacker", {}, {}])
            try:
                s.sendall(struct.pack(">I", len(payload)) + payload)
                
                # 5. Receive Response
                data = s.recv(1024)
                if data:
                    # If we get AUTH_OK (type 0x11), security is BREACHED
                    try:
                        # RSGI-Velo framing: 4 bytes length + msgpack
                        msg_len = struct.unpack(">I", data[:4])[0]
                        msg = msgpack.unpackb(data[4:4+msg_len])
                        if msg[0] == 0x11:
                            pytest.fail(f"SECURITY BREACH: Host accepted connection from unauthorized PID {os.getpid()}! Gate H (Peer PID Auth) is MISSING in Host.")
                        else:
                            pytest.fail(f"SECURITY BREACH: Host sent unexpected message {msg[0]} instead of closing connection.")
                    except Exception as e:
                        pytest.fail(f"SECURITY BREACH: Host sent garbage {data!r} instead of closing connection. Error: {e}")
                else:
                    # If data is empty, the Host (correctly) closed it.
                    pass
            except (ConnectionResetError, BrokenPipeError):
                # Correct behavior: Host immediately severed the connection due to Gate H failure
                pass
            
        finally:
            proc.terminate()
            proc.wait()
