import os
import signal
import time

import psutil
import pytest
from conftest_utils import VeloTestEnv


@pytest.mark.tier2
@pytest.mark.macos_only
def test_ADVERSARIAL_H5_orphan_race(isolated_env: VeloTestEnv) -> None:
    """
    Challenge H5: Orphan Protection.
    Does the 100ms poll and libc::_exit(0) leave any transient leakage?
    """
    app_py = isolated_env.create_app("app.py", "import time\ntime.sleep(60)")
    port = isolated_env.next_port()
    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    master_pid = process.pid
    master_proc = psutil.Process(master_pid)
    children = master_proc.children(recursive=True)
    assert len(children) > 0
    child_pid = children[0].pid

    print(f"Master: {master_pid}, Child: {child_pid}")

    # KILL MASTER ROUGHLY
    os.kill(master_pid, signal.SIGKILL)
    process.wait()

    # CHECK IMMEDIATELY
    time.sleep(0.05)  # 50ms (Less than the 100ms poll!)
    exists_at_50ms = psutil.pid_exists(child_pid)

    time.sleep(0.1)  # Total 150ms
    exists_at_150ms = psutil.pid_exists(child_pid)

    print(f"Exists at 50ms: {exists_at_50ms}, at 150ms: {exists_at_150ms}")

    # ASSERTION: 100ms is a large window for an 'Industrial' tool.
    # RFC doesn't specify window, but H5 says 'Industrial'
    assert not exists_at_150ms, "Orphan protection failed to kill child within poll window!"
    if exists_at_50ms:
        print("NOTE: 100ms window creates a transient orphan race.")
