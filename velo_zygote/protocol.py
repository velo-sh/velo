import asyncio
import struct

try:
    from .serializer import packer, unpacker
except (ImportError, ValueError):
    from serializer import packer, unpacker  # type: ignore[no-redef, import-not-found]

from typing import Dict, List, Optional, Any

try:
    from .constants import PROTOCOL_VERSION, MAX_MESSAGE_SIZE
except (ImportError, ValueError):
    from constants import PROTOCOL_VERSION, MAX_MESSAGE_SIZE  # type: ignore[no-redef, import-not-found]


class ProtocolError(Exception):
    """Raised when an IPC protocol violation occurs."""

    pass


class ZygoteTransport:
    """Layer 1: Transport Layer - Handles asyncio-based MessagePack IO.

    Implements length-prefixed, versioned MessagePack framing:
    [Length 4B LE] [Version 1B] [Payload MsgPack]
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer

    async def recv(self) -> Optional[Dict[str, Any]]:
        """Receive length-prefixed MessagePack message with fail-fast validation."""
        try:
            # 1. Read Length Prefix
            len_data = await self.reader.readexactly(4)
            total_len = struct.unpack("<I", len_data)[0]

            # Fail-Fast: Message Size Validation
            if total_len > MAX_MESSAGE_SIZE:
                raise ProtocolError(
                    f"Oversized payload: {total_len} bytes exceeds MAX_MESSAGE_SIZE ({MAX_MESSAGE_SIZE})"
                )
            if total_len < 1:
                raise ProtocolError(
                    f"Invalid total_len: {total_len} (must be >= 1 for version byte)"
                )

            # 2. Read Version Byte
            version_data = await self.reader.readexactly(1)
            client_version = version_data[0]
            if client_version != PROTOCOL_VERSION:
                raise ProtocolError(
                    f"Protocol version mismatch: got 0x{client_version:02x}, expected 0x{PROTOCOL_VERSION:02x}"
                )

            # 3. Read Payload
            payload_len = total_len - 1
            data = await self.reader.readexactly(payload_len)

            try:
                msg = unpacker(data)
                if not isinstance(msg, dict):
                    raise ProtocolError(
                        f"Malformed payload: expected dict, got {type(msg).__name__}"
                    )
                return msg
            except Exception as e:
                raise ProtocolError(f"Failed to decode MessagePack: {e}")

        except asyncio.IncompleteReadError:
            # Clean disconnect
            return None
        except ProtocolError:
            # Re-raise for upper layer to handle as a hard error
            raise
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception as e:
            raise ProtocolError(f"Unexpected transport error: {e}")

    async def send(self, msg: Dict[str, Any]) -> None:
        """Send length-prefixed MessagePack message."""
        try:
            payload = packer(msg)
            total_len = 1 + len(payload)

            if total_len > MAX_MESSAGE_SIZE:
                # This should not happen on send unless we are sending huge status
                raise ProtocolError(
                    f"Attempted to send oversized message: {total_len} bytes"
                )

            header = struct.pack("<I", total_len)
            version = bytes([PROTOCOL_VERSION])

            self.writer.write(header + version + payload)
            await self.writer.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            raise ProtocolError(f"Failed to send message: {e}")

    async def close(self):
        """Close the underlying streams."""
        try:
            if not self.writer.is_closing():
                self.writer.close()
                await self.writer.wait_closed()
        except:
            pass
