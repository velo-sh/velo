"""
Velo Synchronous Transport
"""
import socket
import struct
import traceback
from typing import Dict, Optional
try:
    from .serializer import packer, unpacker
    from .constants import PROTOCOL_VERSION, MAX_MESSAGE_SIZE
except (ImportError, ValueError):
    from serializer import packer, unpacker
    from constants import PROTOCOL_VERSION, MAX_MESSAGE_SIZE

class ProtocolError(Exception):
    """Raised when an IPC protocol violation occurs."""
    pass

class ZygoteTransport:
    """Layer 1: Transport Layer - Handles raw socket IO with recvmsg support."""
    
    def __init__(self, sock: socket.socket):
        self.sock = sock

    def recv(self) -> Optional[Dict]:
        """Receive length-prefixed MessagePack message + optional FD."""
        try:
            # 1. Read Length Prefix (4B) + Version Byte (1B)
            # Use recvmsg to potentially receive FDs
            # We need to read exactly 5 bytes first
            header_data, ancdata, flags, addr = self.sock.recvmsg(5)
            if not header_data:
                return None
            
            if len(header_data) < 5:
                # Need to read the rest
                remaining = 5 - len(header_data)
                header_data += self._read_exactly(remaining)
            
            total_len = struct.unpack('<I', header_data[:4])[0]
            client_version = header_data[4]
            
            if total_len > MAX_MESSAGE_SIZE:
                raise ProtocolError(f"Oversized payload: {total_len}")
            if client_version != PROTOCOL_VERSION:
                raise ProtocolError(f"Version mismatch")
            
            # 2. Read Payload
            payload_len = total_len - 1
            data = self._read_exactly(payload_len)
            
            msg = unpacker(data)
            
            # 3. Handle Ancillary Data (FDs)
            if ancdata:
                for cmsg_level, cmsg_type, cmsg_data in ancdata:
                    if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                        # Extract FD
                        import array
                        fds = array.array("i")
                        fds.frombytes(cmsg_data[: len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
                        if fds:
                            msg['shm_fd'] = fds[0]
            
            return msg
        except (EOFError, ConnectionResetError, BrokenPipeError):
            return None
        except Exception as e:
            raise ProtocolError(f"Transport error: {e}")

    def _read_exactly(self, n: int) -> bytes:
        data = b''
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise EOFError()
            data += chunk
        return data

    def send(self, msg: Dict):
        """Send length-prefixed MessagePack message."""
        payload = packer(msg)
        total_len = 1 + len(payload)
        header = struct.pack('<I', total_len)
        version = bytes([PROTOCOL_VERSION])
        self.sock.sendall(header + version + payload)

    def close(self):
        try:
            self.sock.close()
        except:
            pass
