import os
import signal
import time
from pathlib import Path

import pytest


class TestWebSocketSubprotocol:
    @pytest.mark.tier1
    def test_ws_subprotocol_negotiation(self, isolated_env):
        """
        Verify subprotocol negotiation: ASGI app selects a subprotocol, client receives it.
        """
        isolated_env.create_app(
            "main.py",
            """
async def app(scope, receive, send):
    if scope['type'] == 'websocket':
        while True:
            message = await receive()
            if message['type'] == 'websocket.connect':
                # ASGI spec: subprotocols is a list of strings
                subprotocols = scope.get('subprotocols', [])
                selected = 'v1.velo' if 'v1.velo' in subprotocols else None
                await send({
                    'type': 'websocket.accept',
                    'subprotocol': selected
                })
            elif message['type'] == 'websocket.receive':
                await send({
                    'type': 'websocket.send',
                    'text': f"selected:{scope.get('subprotocols')}"
                })
            elif message['type'] == 'websocket.disconnect':
                break
""",
        )
        port = isolated_env.next_port()
        env = os.environ.copy()
        project_root = Path(__file__).parents[4]
        env["PYTHONPATH"] = str(project_root)

        proc = isolated_env.spawn_velo(
            "serve", "main:app", "--rsgi", "--port", str(port), env=env, start_new_session=True
        )

        try:
            import websocket

            time.sleep(5)

            # Request subprotocols
            ws = websocket.create_connection(f"ws://127.0.0.1:{port}/", subprotocols=["v1.velo", "v2.velo"])

            # Verify selected subprotocol in handshake response
            assert ws.subprotocol == "v1.velo", f"Expected v1.velo, got {ws.subprotocol}"

            # Verify scope contents via echo
            ws.send("hello")
            msg = ws.recv()
            assert "v1.velo" in msg and "v2.velo" in msg

            ws.close()
            print("VERIFIED: Subprotocol negotiation successful")
        finally:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
            proc.wait()
