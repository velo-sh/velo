import asyncio
import pytest
import struct
import msgpack
from velo_zygote.protocol import ZygoteTransport, ProtocolError
from velo_zygote.constants import PROTOCOL_VERSION, MAX_MESSAGE_SIZE

class MockStream:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    async def readexactly(self, n):
        if len(self.data) < n:
            raise asyncio.IncompleteReadError(self.data, n)
        chunk = self.data[:n]
        self.data = self.data[n:]
        return bytes(chunk)

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    def is_closing(self):
        return self.closed

    async def wait_closed(self):
        pass

@pytest.mark.anyio
async def test_protocol_success():
    stream = MockStream()
    transport = ZygoteTransport(stream, stream)
    
    test_msg = {"type": "Test", "data": "Hello"}
    await transport.send(test_msg)
    
    # Received back in mock stream
    received = await transport.recv()
    assert received == test_msg

@pytest.mark.anyio
async def test_protocol_version_mismatch():
    stream = MockStream()
    transport = ZygoteTransport(stream, stream)
    
    # Manual craft message with WRONG version
    payload = msgpack.packb({"foo": "bar"})
    total_len = 1 + len(payload)
    header = struct.pack('<I', total_len)
    version = bytes([0xFF]) # Wrong version
    
    stream.write(header + version + payload)
    
    with pytest.raises(ProtocolError, match="Protocol version mismatch"):
        await transport.recv()

@pytest.mark.anyio
async def test_protocol_oversized_payload():
    stream = MockStream()
    transport = ZygoteTransport(stream, stream)
    
    # Manual craft message with HUGE length
    header = struct.pack('<I', MAX_MESSAGE_SIZE + 1)
    stream.write(header)
    
    with pytest.raises(ProtocolError, match="Oversized payload"):
        await transport.recv()

@pytest.mark.anyio
async def test_protocol_malformed_msgpack():
    stream = MockStream()
    transport = ZygoteTransport(stream, stream)
    
    total_len = 5
    header = struct.pack('<I', total_len)
    version = bytes([PROTOCOL_VERSION])
    garbage = b"\xff\xff\xff\xff"
    
    stream.write(header + version + garbage)
    
    with pytest.raises(ProtocolError, match="Failed to decode MessagePack"):
        await transport.recv()

@pytest.mark.anyio
async def test_protocol_not_a_dict():
    stream = MockStream()
    transport = ZygoteTransport(stream, stream)
    
    payload = msgpack.packb(["not", "a", "dict"])
    total_len = 1 + len(payload)
    header = struct.pack('<I', total_len)
    version = bytes([PROTOCOL_VERSION])
    
    stream.write(header + version + payload)
    
    with pytest.raises(ProtocolError, match="Malformed payload: expected dict"):
        await transport.recv()
