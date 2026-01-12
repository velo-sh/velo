"""
Velo RSGI Bridge (Python Side)
RFC-0019: Native Sovereignty bridge implementation.
"""

import asyncio
import msgpack
import os
import struct
import sys
import traceback
from typing import Any, Dict, List, Tuple

# Gate O/P: Pre-intern common header names for performance (RFC-0019 Section 5)
_INTERNED_HEADERS = {
    sys.intern(h) for h in [
        "content-type", "content-length", "accept", "accept-encoding",
        "host", "user-agent", "authorization", "cookie", "cache-control",
        "connection", "transfer-encoding", "x-forwarded-for", "x-real-ip"
    ]
}

# RSGI Message Types (RFC-0019)
TYPE_REQ_START = 0x01
TYPE_REQ_BODY = 0x02
TYPE_RES_START = 0x03
TYPE_RES_BODY = 0x04
TYPE_KEEPALIVE = 0x09
TYPE_READY = 0x10
TYPE_AUTH_OK = 0x11
# Gate J: Graceful shutdown
TYPE_LIFESPAN_SHUTDOWN = 0x20

class RSGIWorker:
    def __init__(self, app: Any, socket_path: str):
        self.app = app
        self.socket_path = socket_path
        self.worker_id = f"worker-{os.getpid()}"

    async def run(self):
        """Main RSGI loop."""
        server = await asyncio.start_unix_server(
            self.handle_connection, self.socket_path
        )
        print(f"RSGI Worker listening on {self.socket_path}")
        async with server:
            await server.serve_forever()

    async def send_msg(self, writer, msg):
        payload = msgpack.packb(msg)
        writer.write(struct.pack(">I", len(payload)))
        writer.write(payload)
        await writer.drain()

    async def recv_msg(self, reader):
        """Receive and decode MessagePack message.
        
        Gate O: Use memoryview to avoid bytes slice copy.
        """
        len_data = await reader.readexactly(4)
        length = struct.unpack(">I", len_data)[0]
        payload = await reader.readexactly(length)
        # Gate O: memoryview for zero-copy slice (RFC-0019 Section 5.3)
        view = memoryview(payload)
        return msgpack.unpackb(view, raw=False, use_list=False)

    async def handle_connection(self, reader, writer):
        """Handle an incoming RSGI connection from the Rust Host."""
        try:
            # 1. Send READY
            ready_msg = [
                TYPE_READY,
                "1.0.0",
                self.worker_id,
                {"streaming": True, "protocols": ["rsgi/1.0", "asgi/3.0"]},
                {"zero_copy_views": True}  # Granian compatibility (RFC-0019)
            ]
            await self.send_msg(writer, ready_msg)

            # 2. Receive AUTH_OK
            auth_ok = await self.recv_msg(reader)
            if auth_ok[0] != TYPE_AUTH_OK:
                print(f"RSGI Handshake Error: Expected AUTH_OK, got {auth_ok[0]}")
                return

            # 3. Request Loop
            while True:
                msg = await self.recv_msg(reader)
                if msg[0] == TYPE_REQ_START:
                    await self.process_request(msg, reader, writer)
                elif msg[0] == TYPE_KEEPALIVE:
                    continue
                else:
                    print(f"RSGI Warning: Unexpected message type {msg[0]}")

        except Exception as e:
            print(f"RSGI Connection Error: {e}")
            traceback.print_exc()
        finally:
            writer.close()
            await writer.wait_closed()

    async def process_request(self, req_start, reader, writer):
        """Bridge RSGI request to ASGI application."""
        _, req_id, method, path, headers, has_body = req_start
        
        # Gate P: Intern header names only, not values (RFC-0019 Section 5.4)
        # Convert headers to ASGI format (list of tuples of bytes)
        asgi_headers = [
            (sys.intern(k.lower()).encode("latin-1"), v.encode("latin-1"))
            for k, v in headers
        ]

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"", # TODO: parse from path
            "headers": asgi_headers,
            "client": None,
            "server": None,
            "rsgi.id": req_id,
        }

        # Request Body Buffer
        body_buffer = bytearray()
        body_complete = asyncio.Event()

        async def receive():
            """ASGI receive callable - reads streamed request body from Host."""
            await body_complete.wait()
            return {"type": "http.request", "body": bytes(body_buffer), "more_body": False}

        async def send(message):
            """ASGI send callable - sends response back to Host."""
            if message["type"] == "http.response.start":
                res_start = [
                    TYPE_RES_START,
                    req_id,
                    message["status"],
                    [(k.decode("latin-1"), v.decode("latin-1")) for k, v in message.get("headers", [])]
                ]
                await self.send_msg(writer, res_start)
            elif message["type"] == "http.response.body":
                res_body = [
                    TYPE_RES_BODY,
                    req_id,
                    message.get("body", b""),
                    not message.get("more_body", False)
                ]
                await self.send_msg(writer, res_body)

        # Receive request body from Host
        async def read_body_task():
            try:
                while True:
                    msg = await self.recv_msg(reader)
                    if msg[0] == TYPE_REQ_BODY:
                        _, _, chunk, is_eof = msg
                        if chunk:
                            body_buffer.extend(chunk)
                        if is_eof:
                            break
                    else:
                        print(f"RSGI Warning: Unexpected message in body stream: {msg[0]}")
                        break
            finally:
                body_complete.set()

        # Start body reading task
        body_task = asyncio.create_task(read_body_task())

        try:
            await self.app(scope, receive, send)
        except Exception as e:
            print(f"ASGI App Error: {e}")
            traceback.print_exc()
        finally:
            body_task.cancel()
            try:
                await body_task
            except asyncio.CancelledError:
                pass

def run_rsgi(app_str: str, uds_path: str):
    """Entry point for RSGI worker."""
    import importlib
    import random

    # P0-2 (RFC-0019): Taint Re-randomization Contract
    # MUST be executed immediately before sending READY
    random.seed()
    os.urandom(16)  # Force kernel entropy refresh
    
    # Import app
    module_name, app_name = app_str.split(":")
    module = importlib.import_module(module_name)
    app = getattr(module, app_name)

    worker = RSGIWorker(app, uds_path)
    asyncio.run(worker.run())
