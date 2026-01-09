import socket
import os
import time
import subprocess
import struct
import msgpack
import pytest
from pathlib import Path

# Velo Protocol Constants (Sync with constants.py)
PROTOCOL_VERSION = 1
MAX_MESSAGE_SIZE = 10485760

@pytest.fixture
def zygote_process():
    """Start Zygote directly via Python for controlled testing."""
    repo_root = Path(__file__).parent.parent.parent
    sock_path = f"/tmp/velo_test_integrity_{os.getpid()}.sock"
    if os.path.exists(sock_path):
        os.unlink(sock_path)
        
    env = os.environ.copy()
    env["VELO_ENV"] = "dev"
    env["PYTHONPATH"] = str(repo_root)
    
    # Start Zygote Server
    proc = subprocess.Popen(
        ["uv", "run", "python3", "-m", "velo_zygote.main", "--socket", sock_path],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for "Ready" signal in logs or socket to appear
    timeout = 5
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(sock_path):
            break
        time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("Zygote failed to start or create socket within timeout")

    # Give it a tiny bit more to be fully initialized
    time.sleep(0.5)
    
    yield sock_path, proc
    
    # Cleanup
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except:
        proc.kill()
    if os.path.exists(sock_path):
        os.unlink(sock_path)

def send_raw_hostile(sock_path, total_len, version, payload_bytes):
    """Low-level socket injector."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2.0)
    s.connect(sock_path)
    try:
        # 1. Consume Greeting (RFC-0011)
        header = s.recv(5)
        if len(header) == 5:
            l = struct.unpack('<I', header[:4])[0]
            s.recv(l-1)
            
        # 2. Inject Hostile Packet
        header = struct.pack('<I', total_len)
        version_byte = bytes([version])
        s.sendall(header + version_byte + payload_bytes)
        
        # 3. Try to read (optional, usually Zygote closes connection)
        try:
            s.recv(1024)
        except:
            pass
    finally:
        s.close()

def test_sec_p0_007_oversized_payload_rejection(zygote_process):
    """SEC-P0-007: Zygote must reject oversized payloads and log violation."""
    sock_path, proc = zygote_process
    
    # Construct a packet that CLAIMS to be huge
    oversized = MAX_MESSAGE_SIZE + 1024
    dummy_payload = b"\x00" * 100 # We don't actually need to send that much, just the header is enough to trigger rejection
    
    send_raw_hostile(sock_path, oversized, PROTOCOL_VERSION, dummy_payload)
    
    # Wait for logging
    time.sleep(0.5)
    
    # Zygote must NOT crash
    assert proc.poll() is None
    
    # Check stderr for the alert
    # Note: subprocess.PIPE needs careful reading to avoid deadlocks, but for this small output it's fine
    # Actually, we should use communicate() or read non-blocking if possible.
    # Here we just read what's available.
    os.set_blocking(proc.stderr.fileno(), False)
    stderr = proc.stderr.read() or ""
    
    assert "🚨 IPC Protocol Violation: Oversized payload" in stderr
    assert f"limit: {MAX_MESSAGE_SIZE}" in stderr

def test_sec_p0_008_version_mismatch_rejection(zygote_process):
    """SEC-P0-008: Zygote must reject mismatched protocol versions."""
    sock_path, proc = zygote_process
    
    payload = msgpack.packb({"type": "Handshake"})
    total_len = 1 + len(payload)
    bad_version = 254
    
    send_raw_hostile(sock_path, total_len, bad_version, payload)
    
    time.sleep(0.5)
    assert proc.poll() is None
    
    os.set_blocking(proc.stderr.fileno(), False)
    stderr = proc.stderr.read() or ""
    
    assert "🚨 IPC Protocol Violation: Protocol version mismatch" in stderr
    assert f"Client v{bad_version}" in stderr

def test_sec_p0_009_malformed_msgpack_rejection(zygote_process):
    """SEC-P0-009: Zygote must handle malformed MessagePack gracefully."""
    sock_path, proc = zygote_process
    
    # Invalid MessagePack (broken header)
    malformed_payload = b"\xc1\xff\x00" 
    total_len = 1 + len(malformed_payload)
    
    send_raw_hostile(sock_path, total_len, PROTOCOL_VERSION, malformed_payload)
    
    time.sleep(0.5)
    assert proc.poll() is None
    
    os.set_blocking(proc.stderr.fileno(), False)
    stderr = proc.stderr.read() or ""
    
    assert "🚨 IPC Protocol Violation: Failed to unpack MessagePack payload" in stderr

def test_state_visibility_via_status(zygote_process):
    """Verify that ZygoteState enumeration is reflected in Status response."""
    sock_path, proc = zygote_process
    
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock_path)
    try:
        # Read Greeting
        s.recv(1024)
        
        # Send Status Command
        cmd = {"type": "Status"}
        payload = msgpack.packb(cmd)
        header = struct.pack('<I', 1 + len(payload))
        s.sendall(header + bytes([PROTOCOL_VERSION]) + payload)
        
        # Read Response
        resp_header = s.recv(5)
        l = struct.unpack('<I', resp_header[:4])[0]
        resp_payload = s.recv(l-1)
        resp = msgpack.unpackb(resp_payload)
        
        assert resp["type"] == "Status"
        # State should be a valid Enum name (likely READY or PRELOADING)
        assert resp["state"] in ["READY", "PRELOADING", "IDLE"]
    finally:
        s.close()
