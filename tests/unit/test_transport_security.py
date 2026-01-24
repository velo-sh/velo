"""
Unit tests for transport_sync.py - Protocol Security Vulnerabilities
DEF-72-FLOOD: ZygoteTransport lacks timeout protection
"""

import socket
import struct

import pytest


def test_zygote_transport_sets_timeout():
    """
    DEF-72-FLOOD FIX: Verify ZygoteTransport sets socket timeout.

    This test verifies that:
    1. ZygoteTransport sets a 30s timeout on the socket
    2. Partial data attack is handled gracefully (timeout, not hang)
    """
    # Create a socket pair for testing
    server_sock, client_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)

    try:
        import os
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from velo_zygote.transport_sync import ZygoteTransport

        # Verify ZygoteTransport sets timeout
        transport = ZygoteTransport(server_sock)

        assert server_sock.gettimeout() == 30.0, (
            f"ZygoteTransport should set 30s timeout, got {server_sock.gettimeout()}"
        )

        # Send a malformed message: claim length is 64KB but only send header
        fake_length = 65536  # 64KB (within limit, but we won't send the data)
        version_byte = 1
        client_sock.sendall(struct.pack("<I", fake_length))
        client_sock.sendall(bytes([version_byte]))
        # DON'T send the payload - simulating attack

        # With timeout set, recv should timeout instead of blocking forever
        try:
            # Reduce timeout for faster test
            server_sock.settimeout(0.5)
            transport.recv()
            pytest.fail("recv() should have timed out on partial data")
        except TimeoutError:
            # Expected: timeout instead of indefinite blocking
            pass
        except Exception as e:
            # Protocol error from incomplete read is also acceptable
            assert "EOF" in str(e) or "transport" in str(e).lower() or "timeout" in str(e).lower()

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
        import os
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from velo_zygote.constants import MAX_MESSAGE_SIZE
        from velo_zygote.transport_sync import ProtocolError, ZygoteTransport

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


def test_max_message_size_is_64kb():
    """
    Verify MAX_MESSAGE_SIZE is 64KB (65536 bytes).

    This test prevents accidental changes to the limit.
    64KB is sufficient for all IPC commands (typically < 10KB).
    Large data should use SHM (shared memory) via file descriptors.
    """
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from velo_zygote.constants import MAX_MESSAGE_SIZE

    SIXTY_FOUR_KB = 65536  # 64 * 1024

    assert MAX_MESSAGE_SIZE == SIXTY_FOUR_KB, (
        f"MAX_MESSAGE_SIZE should be 64KB (65536), got {MAX_MESSAGE_SIZE} bytes "
        f"({MAX_MESSAGE_SIZE / 1024:.1f}KB). "
        "If you need to change this, update config/constants.toml and this test."
    )
