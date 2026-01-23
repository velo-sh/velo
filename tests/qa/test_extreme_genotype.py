import asyncio
import json
import subprocess
import time

import pytest
import websockets
from conftest_utils import VeloTestEnv


@pytest.mark.tier2
def test_EXTREME_SINCERITY_genotype_aging(isolated_env: VeloTestEnv) -> None:
    """
    Challenge: The "Toy" Test (Genotype Aging).
    If I pip install 'cowsay' while Vibe is running, can I use it?
    A 'Sincere' engine would detect the environment change and re-fertilize.
    """
    code_init = "print('Vibe active')"
    app_py = isolated_env.create_app("app.py", code_init)
    port = isolated_env.next_port()

    # Start Vibe
    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_aging() -> None:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            # Step 1: Verify it works
            await websocket.recv()  # Consume initial msg

            # Step 2: Install package 'cowsay'
            print("Installing 'cowsay' while Vibe is running...")
            subprocess.run(["uv", "pip", "install", "cowsay"], check=True)

            # Step 3: Update code to use cowsay
            print("Updating code to use 'cowsay'...")
            code_cowsay = "import cowsay; print(cowsay.get_output_string('cow', 'Moo!'))"
            isolated_env.create_app("app.py", code_cowsay)

            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)

            # ASSERTION: If it says 'ModuleNotFoundError', it's a TOY engine.
            if data["status"] == "error" and "ModuleNotFoundError" in data.get("error", ""):
                print("!!! AUDIT FINDING: Genotype Aging detected. Vibe is a 'Toy' (Environmentally unaware).")
                pytest.fail("Genotype Aging: Vibe failed to detect new package installation.")

            assert "Moo!" in data.get("output", "")
            print("Journey Complete: Sincere engine detected environment drift.")

    try:
        asyncio.run(check_aging())
    finally:
        process.terminate()
        process.wait()
        # Clean up
        subprocess.run(["uv", "pip", "uninstall", "cowsay"], check=False)
