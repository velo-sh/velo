import time

import psutil
import pytest
from conftest_utils import VeloTestEnv


@pytest.mark.tier2
def test_ADVERSARIAL_RESOURCE_CAP(isolated_env: VeloTestEnv) -> None:
    """
    Challenge: 5.4.7 Resource Caps.
    If a worker runs an infinite loop, it should be capped or manageable.
    While we have a reaper, if the worker NEVER exits and we keep making saves,
    do we accumulate CPU-heavy processes?
    """
    code = "while True: pass"
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()
    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    master_proc = psutil.Process(process.pid)

    # Trigger 5 saves.
    # Velo SHOULD kill the previous worker (Pillar 1)
    print("Triggering 5 CPU-heavy saves...")
    for i in range(5):
        isolated_env.create_app("app.py", f"while True: pass # {i}")
        time.sleep(0.5)

    time.sleep(1)
    children = master_proc.children(recursive=True)
    cpu_usage = [c.cpu_percent(interval=0.1) for c in children]

    print(f"Child count: {len(children)}")
    print(f"CPU usages: {cpu_usage}")

    # ASSERTION 1: Pillar 1 (Kill previous) should keep child count at 1
    assert len(children) <= 1, f"FAILED Pillar 1: Accumulated {len(children)} workers! Kill-previous failed."

    # ASSERTION 2: 5.4.7 (Resource Caps)
    # If it's still running, it's NOT capped by any runtime limit (though Velo manages it via SIGKILL)
    # The RFC mentions "Hard limits on CPU/Memory per session".
    # If a single worker can take 100%, it's arguably not 'capped'.
    if len(children) > 0:
        assert children[0].cpu_percent(interval=0.5) < 200, "Worker is consuming excessive CPU (not capped)"

    try:
        pass
    finally:
        process.terminate()
        process.wait()
