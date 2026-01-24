"""
Velo RSGI Bridge (Python Side)
RFC-0019: Native Sovereignty bridge implementation.
"""

import asyncio
import os
import struct
import sys
import traceback
from asyncio import StreamReader, StreamWriter
from typing import Any

import msgpack

from velo_zygote.utils import LogUtils

# Gate O/P: Pre-intern common header names for performance (RFC-0019 Section 5)
_INTERNED_HEADERS = {
    sys.intern(h)
    for h in [
        "content-type",
        "content-length",
        "accept",
        "accept-encoding",
        "host",
        "user-agent",
        "authorization",
        "cookie",
        "cache-control",
        "connection",
        "transfer-encoding",
        "x-forwarded-for",
        "x-real-ip",
        "x-velo-trace-id",
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
TYPE_LIFESPAN_SHUTDOWN = 0x20
# Gate J: Graceful shutdown
TYPE_LIFESPAN_SHUTDOWN = 0x20


class RSGIWorker:
    def __init__(self, app: Any, socket_path: str):
        self.app = app
        self.socket_path = socket_path
        self.worker_id = f"worker-{os.getpid()}"

    async def run(self) -> None:
        """Main RSGI loop."""
        LogUtils.debug_log(f"RSGI Worker starting server on {self.socket_path}...")

        # TITANIUM: Unlink if exists to prevent "Address already in use" (RFC-0012)
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

        server = await asyncio.start_unix_server(self.handle_connection, self.socket_path)
        LogUtils.debug_log(f"RSGI Worker listening on {self.socket_path}")
        async with server:
            await server.serve_forever()

    async def send_msg(self, writer: StreamWriter, msg: list[Any]) -> None:
        payload = msgpack.packb(msg)
        writer.write(struct.pack(">I", len(payload)))
        writer.write(payload)
        # DEF-72-C05: Ensure immediate flush for streaming (SSE Optimization)
        await writer.drain()

    async def recv_msg(self, reader: StreamReader) -> Any:
        """Receive and decode MessagePack message.

        Gate O: Use memoryview to avoid bytes slice copy.
        """
        len_data = await reader.readexactly(4)
        length = struct.unpack(">I", len_data)[0]
        payload = await reader.readexactly(length)
        # Gate O: memoryview for zero-copy slice (RFC-0019 Section 5.3)
        view = memoryview(payload)
        return msgpack.unpackb(view, raw=False, use_list=False)

    async def handle_connection(self, reader: StreamReader, writer: StreamWriter) -> None:
        """Handle an incoming RSGI connection from the Rust Host."""
        try:
            # Gate H (DEF-72-H01): Peer PID Authentication
            # Validate that the connecting process is from our authorized parent (Rust Host)
            sock = writer.get_extra_info("socket")
            if sock is not None:
                authorized_host_pid = os.environ.get("VELO_HOST_PID")
                try:
                    import socket
                    import struct as _struct

                    # SO_PEERCRED returns (pid, uid, gid) on Linux
                    SO_PEERCRED = getattr(socket, "SO_PEERCRED", 17)  # 17 on Linux
                    creds = sock.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, _struct.calcsize("3i"))
                    peer_pid, peer_uid, peer_gid = _struct.unpack("3i", creds)

                    # Validate UID matches (same user)
                    my_uid = os.getuid()
                    if peer_uid != my_uid:
                        print(
                            f"RSGI Gate H: Rejected connection from UID {peer_uid} (expected {my_uid})", file=sys.stderr
                        )
                        writer.close()
                        await writer.wait_closed()
                        return

                    # Validate PID is our parent process (the Rust Host that spawned us)
                    if authorized_host_pid:
                        if str(peer_pid) != authorized_host_pid:
                            print(
                                f"RSGI Gate H: Rejected connection from unauthorized PID {peer_pid} (authorized: {authorized_host_pid})",
                                file=sys.stderr,
                            )
                            writer.close()
                            await writer.wait_closed()
                            return
                except (OSError, AttributeError):
                    # macOS Fallback: LOCAL_PEERPID (0x002) + LOCAL_PEERCRED (0x001)
                    try:
                        # 1. Try to get PID (LOCAL_PEERPID = 0x002)
                        creds_pid = sock.getsockopt(0, 0x002, 4)
                        peer_pid = _struct.unpack("i", creds_pid)[0]

                        # 2. Try to get UID (LOCAL_PEERCRED = 0x001)
                        # On macOS, xucred is 76 bytes.
                        # struct xucred { u_short cr_version; uid_t cr_uid; ... }
                        # Offset 0: cr_version (2)
                        # Offset 2: padding (2)
                        # Offset 4: cr_uid (4)
                        creds_u = sock.getsockopt(0, 0x001, 76)
                        if len(creds_u) >= 8:
                            peer_uid = _struct.unpack("I", creds_u[4:8])[0]
                        else:
                            raise ValueError(f"xucred too short: {len(creds_u)}")

                        # Validate UID matches (Same-User isolation)
                        my_uid = os.getuid()
                        if peer_uid != my_uid:
                            print(
                                f"RSGI Gate H (macOS): Rejected connection from UID {peer_uid} (expected {my_uid})",
                                file=sys.stderr,
                            )
                            writer.close()
                            await writer.wait_closed()
                            return

                        if authorized_host_pid:
                            if str(peer_pid) != authorized_host_pid:
                                print(
                                    f"RSGI Gate H (macOS): Rejected connection from unauthorized PID {peer_pid} (authorized: {authorized_host_pid})",
                                    file=sys.stderr,
                                )
                                writer.close()
                                await writer.wait_closed()
                                return
                        elif peer_pid == 0:
                            # TITANIUM RULE: No 0-PID broad acceptance.
                            print(
                                "RSGI Gate H (macOS): Rejected connection - Peer PID is 0 and no authorized Host PID provided",
                                file=sys.stderr,
                            )
                            writer.close()
                            await writer.wait_closed()
                            return
                    except Exception as e:
                        print(f"RSGI Gate H: Could not retrieve peer credentials on macOS: {e}", file=sys.stderr)
                        writer.close()
                        await writer.wait_closed()
                        return

            # 1. Send READY
            ready_msg = [
                TYPE_READY,
                "1.0.0",
                self.worker_id,
                {"streaming": True, "protocols": ["rsgi/1.0", "asgi/3.0"]},
                {"zero_copy_views": True},  # Granian compatibility (RFC-0019)
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
                elif msg[0] == TYPE_LIFESPAN_SHUTDOWN:
                    # Gate J: Graceful Host-initiated shutdown
                    LogUtils.debug_log("RSGI: Received LifespanShutdown, exiting loop.")
                    break
                else:
                    print(f"RSGI Warning: Unexpected message type {msg[0]}")

        except Exception as e:
            print(f"RSGI Connection Error: {e}")
            traceback.print_exc()
        finally:
            writer.close()
            await writer.wait_closed()

    async def process_request(self, req_start: list[Any], reader: StreamReader, writer: StreamWriter) -> None:
        """Bridge RSGI request to ASGI application."""
        # req_start: [type, req_id, method, path, headers, has_body, client]
        _, req_id, method, path, headers, has_body, client = req_start

        # Gate P: Intern header names only, not values (RFC-0019 Section 5.4)
        # Convert headers to ASGI format (list of tuples of bytes)
        asgi_headers = [(sys.intern(k.lower()).encode("latin-1"), v.encode("latin-1")) for k, v in headers]

        # DEF-72-C01: Query String Preservation - robust splitting
        path_parts = path.split("?", 1)
        clean_path = path_parts[0]
        query_string = path_parts[1] if len(path_parts) > 1 else ""

        LogUtils.debug_log(f"RSGI Request: {method} {clean_path} (Query: {query_string})")

        # RFC-0011: Recover client information from proxy headers
        client_host = "127.0.0.1"
        scheme = "http"
        for k, v in headers:
            k_lower = k.lower()
            if k_lower == "x-forwarded-for":
                try:
                    client_host = v.split(",")[0].strip()
                except Exception:
                    pass
            elif k_lower == "x-forwarded-proto":
                try:
                    scheme = v.strip()
                except Exception:
                    pass
            elif k_lower == "x-velo-trace-id":
                trace_id = v.strip()
            else:
                trace_id = None

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": scheme,
            "path": clean_path,
            "raw_path": clean_path.encode("ascii", errors="replace"),
            "query_string": query_string.encode("ascii", errors="replace"),
            "headers": asgi_headers,
            "client": (client_host, 0),
            "server": None,
            "rsgi.id": req_id,
            "velo.trace_id": trace_id,
        }

        # Request Body Buffer
        body_buffer = bytearray()
        body_complete = asyncio.Event()
        body_delivered = False  # DEF-72-C06: Ensure receive() only returns body once

        async def receive() -> dict[str, Any]:
            """ASGI receive callable - reads streamed request body from Host."""
            nonlocal body_delivered
            if body_delivered:
                return {"type": "http.disconnect"}

            await body_complete.wait()
            body_delivered = True
            return {"type": "http.request", "body": bytes(body_buffer), "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            """ASGI send callable - sends response back to Host."""
            if message["type"] == "http.response.start":
                res_start = [
                    TYPE_RES_START,
                    req_id,
                    message["status"],
                    [(k.decode("latin-1"), v.decode("latin-1")) for k, v in message.get("headers", [])],
                ]
                await self.send_msg(writer, res_start)
            elif message["type"] == "http.response.body":
                res_body = [TYPE_RES_BODY, req_id, message.get("body", b""), not message.get("more_body", False)]
                await self.send_msg(writer, res_body)

        async def read_body_task() -> None:
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


def run_rsgi(app_str: str, uds_path: str) -> None:
    """Entry point for RSGI worker."""
    import importlib
    import random

    # P0-2 (RFC-0019): Taint Re-randomization Contract
    # MUST be executed immediately before sending READY
    random.seed()
    os.urandom(16)  # Force kernel entropy refresh

    # Import app
    LogUtils.debug_log(f"RSGI Worker importing app: {app_str}")
    module_name, app_name = app_str.split(":")
    module = importlib.import_module(module_name)
    app = getattr(module, app_name)
    LogUtils.debug_log("RSGI Worker app imported successfully")

    worker = RSGIWorker(app, uds_path)
    LogUtils.debug_log("RSGI Worker entering event loop")
    asyncio.run(worker.run())
