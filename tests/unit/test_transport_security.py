"""
Unit tests for transport_sync.py - Protocol Security Vulnerabilities
DEF-72-FLOOD: ZygoteTransport lacks timeout protection
"""
import socket
import struct
import pytest
import threading
import time


def test_read_exactly_blocks_indefinitely_on_partial_data():
    """
    DEF-72-FLOOD: _read_exactly blocks forever when data never arrives.
    
    Attack scenario:
    1. Attacker sends garbage data that parses as a large length prefix
    2. _read_exactly tries to read that many bytes
    3. Attacker only sent a small amount, so _read_exactly blocks forever
    4. This ties up a worker thread and potentially causes resource exhaustion
    
    This test verifies that ZygoteTransport does NOT set socket timeout internally.
    The fix should add internal timeout protection.
    """
    # Create a socket pair for testing
    server_sock, client_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    
    try:
        # Import the transport class
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from velo_zygote.transport_sync import ZygoteTransport
        
        transport = ZygoteTransport(server_sock)
        
        # Verify socket has NO timeout set (this is the vulnerability!)
        # ZygoteTransport should set its own timeout but it doesn't
        assert server_sock.gettimeout() is None, \
            "Socket should have no timeout initially"
        
        # Send a malformed message: claim length is 1MB but only send header
        fake_length = 1024 * 1024  # 1MB
        version_byte = 1
        client_sock.sendall(struct.pack("<I", fake_length))
        client_sock.sendall(bytes([version_byte]))
        # DON'T send the payload - this is the attack
        
        # Manually set timeout for test (simulating what SHOULD be done internally)
        server_sock.settimeout(2.0)
        
        # Now recv - with external timeout it will fail with socket.timeout
        # The DEFECT is that this timeout is NOT set by ZygoteTransport itself
        try:
            msg = transport.recv()
            pytest.fail("recv() should have timed out or raised error")
        except socket.timeout:
            # This is expected with external timeout
            pass
        except Exception as e:
            # Protocol error from incomplete read is also acceptable
            assert "EOF" in str(e) or "transport" in str(e).lower()
        
        # THE REAL TEST: Verify ZygoteTransport.__init__ does NOT set timeout
        # This is the vulnerability we need to fix
        server_sock2, client_sock2 = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        transport2 = ZygoteTransport(server_sock2)
        
        # VULNERABILITY CHECK: ZygoteTransport SHOULD set a timeout but it doesn't
        # This test FAILS until the vulnerability is fixed
        timeout = server_sock2.gettimeout()
        server_sock2.close()
        client_sock2.close()
        
        assert timeout is not None, \
            "DEF-72-FLOOD: ZygoteTransport does not set socket timeout! " \
            "An attacker can cause indefinite blocking by sending partial data. " \
            "Fix: Add self.sock.settimeout(X) in ZygoteTransport.__init__()"
        
    finally:
        server_sock.close()
        client_sock.close()


def test_oversized_length_prefix_is_rejected():
    """
    DEF-72-FLOOD: Verify that oversized length prefix is rejected.
    
    This should already pass because MAX_MESSAGE_SIZE check exists.
    """
    server_sock, client_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from velo_zygote.transport_sync import ZygoteTransport, ProtocolError
        from velo_zygote.constants import MAX_MESSAGE_SIZE
        
        transport = ZygoteTransport(server_sock)
        
        # Send a message claiming to be larger than MAX_MESSAGE_SIZE
        fake_length = MAX_MESSAGE_SIZE + 1000
        version_byte = 1
        client_sock.sendall(struct.pack("<I", fake_length))
        client_sock.sendall(bytes([version_byte]))
        
        # This should raise ProtocolError, not try to allocate huge buffer
        with pytest.raises(ProtocolError) as exc_info:
            transport.recv()
        
        assert "Oversized" in str(exc_info.value) or "too large" in str(exc_info.value).lower()
        
    finally:
        server_sock.close()
        client_sock.close()
