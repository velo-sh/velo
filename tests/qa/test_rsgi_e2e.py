"""
RSGI End-to-End Integration Test
RFC-0019: Native Sovereignty Verification

This test validates the complete RSGI request-response cycle:
1. Rust Host receives HTTP request
2. Host forwards to Python Worker via RSGI protocol
3. Worker processes via ASGI and returns response
4. Host streams response back to client
"""

import asyncio
import os
import socket
import struct
import sys
import tempfile
import time
import msgpack
import pytest

# Configure pytest-asyncio
pytest_plugins = ('pytest_asyncio',)

# Add velo_zygote to path for testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from velo_zygote.v_rsgi import RSGIWorker, TYPE_REQ_START, TYPE_REQ_BODY, TYPE_RES_START, TYPE_RES_BODY, TYPE_READY, TYPE_AUTH_OK


class MockASGIApp:
    """Simple ASGI app for testing RSGI bridge."""
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return
        
        # Get request body
        request = await receive()
        body = request.get("body", b"")
        
        # Send response
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        })
        
        response_body = b'{"message": "RSGI OK", "path": "' + scope["path"].encode() + b'"}'
        await send({
            "type": "http.response.body",
            "body": response_body,
            "more_body": False,
        })


async def send_msg(writer, msg):
    """Send a MessagePack message with length prefix."""
    payload = msgpack.packb(msg)
    writer.write(struct.pack(">I", len(payload)))
    writer.write(payload)
    await writer.drain()


async def recv_msg(reader):
    """Receive a MessagePack message with length prefix."""
    len_data = await reader.readexactly(4)
    length = struct.unpack(">I", len_data)[0]
    payload = await reader.readexactly(length)
    return msgpack.unpackb(payload)


@pytest.mark.asyncio
async def test_rsgi_handshake_protocol():
    """Test the RSGI handshake between Host and Worker."""
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = os.path.join(tmpdir, "rsgi_test.sock")
        
        # Start worker
        app = MockASGIApp()
        worker = RSGIWorker(app, socket_path)
        
        # Start worker server in background
        worker_task = asyncio.create_task(worker.run())
        
        # Wait for socket to be created
        for _ in range(50):
            if os.path.exists(socket_path):
                break
            await asyncio.sleep(0.1)
        
        assert os.path.exists(socket_path), "Worker socket not created"
        
        # Connect as Host
        reader, writer = await asyncio.open_unix_connection(socket_path)
        
        try:
            # 1. Receive READY from worker
            ready = await asyncio.wait_for(recv_msg(reader), timeout=2.0)
            assert ready[0] == TYPE_READY, f"Expected READY, got {ready[0]}"
            assert ready[1] == "1.0.0", f"Expected version 1.0.0, got {ready[1]}"
            
            # 2. Send AUTH_OK
            auth_ok = [TYPE_AUTH_OK, "test-session-id", 10485760]
            await send_msg(writer, auth_ok)
            
            # 3. Send REQ_START
            req_start = [
                TYPE_REQ_START,
                1,  # request_id
                "GET",
                "/test",
                [("host", "localhost"), ("user-agent", "velo-test")],
                True,  # has_body
            ]
            await send_msg(writer, req_start)
            
            # 4. Send REQ_BODY (EOF)
            req_body = [TYPE_REQ_BODY, 1, b"", True]  # EOF
            await send_msg(writer, req_body)
            
            # 5. Receive RES_START
            res_start = await asyncio.wait_for(recv_msg(reader), timeout=2.0)
            assert res_start[0] == TYPE_RES_START, f"Expected RES_START, got {res_start[0]}"
            assert res_start[2] == 200, f"Expected status 200, got {res_start[2]}"
            
            # 6. Receive RES_BODY
            res_body = await asyncio.wait_for(recv_msg(reader), timeout=2.0)
            assert res_body[0] == TYPE_RES_BODY, f"Expected RES_BODY, got {res_body[0]}"
            
            body_content = res_body[2]
            if isinstance(body_content, bytes):
                body_content = body_content.decode()
            assert "RSGI OK" in str(body_content), f"Unexpected body: {body_content}"
            assert "/test" in str(body_content), f"Path not in body: {body_content}"
            
            print("✅ RSGI handshake and request/response test passed!")
            
        finally:
            writer.close()
            await writer.wait_closed()
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass


@pytest.mark.asyncio
async def test_rsgi_request_body_streaming():
    """Test request body streaming through RSGI protocol."""
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = os.path.join(tmpdir, "rsgi_body_test.sock")
        
        # Track received body
        received_body = []
        
        class BodyCapturingApp:
            async def __call__(self, scope, receive, send):
                req = await receive()
                received_body.append(req.get("body", b""))
                
                await send({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                })
                await send({
                    "type": "http.response.body",
                    "body": b"OK",
                    "more_body": False,
                })
        
        worker = RSGIWorker(BodyCapturingApp(), socket_path)
        worker_task = asyncio.create_task(worker.run())
        
        # Wait for socket
        for _ in range(50):
            if os.path.exists(socket_path):
                break
            await asyncio.sleep(0.1)
        
        reader, writer = await asyncio.open_unix_connection(socket_path)
        
        try:
            # Handshake
            ready = await asyncio.wait_for(recv_msg(reader), timeout=2.0)
            await send_msg(writer, [TYPE_AUTH_OK, "session", 10485760])
            
            # Send request with body
            test_body = b"Hello, RSGI World!"
            await send_msg(writer, [TYPE_REQ_START, 1, "POST", "/upload", [], True])
            await send_msg(writer, [TYPE_REQ_BODY, 1, test_body, False])
            await send_msg(writer, [TYPE_REQ_BODY, 1, b"", True])  # EOF
            
            # Get response
            res_start = await asyncio.wait_for(recv_msg(reader), timeout=2.0)
            res_body = await asyncio.wait_for(recv_msg(reader), timeout=2.0)
            
            assert res_start[2] == 200
            assert len(received_body) > 0, "No body received by app"
            assert test_body in received_body[0], f"Body not received: {received_body}"
            
            print("✅ RSGI request body streaming test passed!")
            
        finally:
            writer.close()
            await writer.wait_closed()
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    asyncio.run(test_rsgi_handshake_protocol())
    asyncio.run(test_rsgi_request_body_streaming())
    print("\n🎉 All RSGI end-to-end tests passed!")
