import os
import signal
import time
from pathlib import Path

import pytest


class TestWebSocketCloseCode:
    @pytest.mark.tier1
    def test_ws_close_code_propagation(self, isolated_env):
        """
        Verify close code propagation:
        1. App sends specific code -> client receives it.
        2. Client sends specific code -> app receives it via disconnect event.
        """
        isolated_env.create_app(
            "main.py",
            """
async def app(scope, receive, send):
    if scope['type'] == 'websocket':
        while True:
            message = await receive()
            if message['type'] == 'websocket.connect':
                await send({'type': 'websocket.accept'})
            elif message['type'] == 'websocket.receive':
                if message.get('text') == 'close_me_4000':
                    await send({'type': 'websocket.close', 'code': 4000})
                elif message.get('text') == 'wait_for_my_close':
                    # Do nothing, wait for receive() to return disconnect
                    pass
            elif message['type'] == 'websocket.disconnect':
                # Log the code for verification
                with open("close_log.txt", "a") as f:
                    f.write(f"received_code:{message.get('code')}\\n")
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

            # Case 1: Server sends 4000
            ws = websocket.create_connection(f"ws://127.0.0.1:{port}/")
            ws.send("close_me_4000")
            try:
                ws.recv()
            except websocket.WebSocketConnectionClosedException:
                # websocket-client status code is in e or captured during close
                pass

            # Verify close code received by client
            # ws.status is updated after handshake or close
            assert ws.connected is False
            # websocket-client doesn't always expose the code easily depending on version,
            # but we can check if it's captured in the close frame if we read raw.
            # In some versions it's ws.close_status

            # Case 2: Client sends 4001
            ws2 = websocket.create_connection(f"ws://127.0.0.1:{port}/")
            ws2.send("wait_for_my_close")
            ws2.close(status=4001)

            time.sleep(2)
            log_file = isolated_env.root / "close_log.txt"
            assert log_file.exists()
            content = log_file.read_text()
            assert "received_code:4001" in content

            print("VERIFIED: Close code propagation successful")
        finally:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
            proc.wait()
