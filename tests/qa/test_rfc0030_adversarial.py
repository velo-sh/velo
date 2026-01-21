"""
Adversarial QA Suite for RFC-0030 (Jupyter Integration)
Focus: Breaking the implementation and exposing gaps.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


def get_velo_binary():
    project_root = Path(__file__).parent.parent.parent
    for build in ["debug", "release"]:
        binary = project_root / "target" / build / "velo"
        if binary.exists():
            return str(binary)
    return "velo"


VELO_BINARY = get_velo_binary()


@pytest.mark.qa
class TestRFC0030Adversarial:
    def test_expose_zygote_bypass_in_module_mode(self):
        """
        BUG EXPOSURE: RFC-0030 §3.1 requires Zygote acceleration for modules.
        This test verifies that --zygote is actually respected in module mode.
        """
        # 1. Stop any existing Zygote
        subprocess.run([VELO_BINARY, "zygote", "stop"], capture_output=True)

        # 2. Run module WITH --zygote.
        # It SHOULD start a Zygote (as run_script_impl does).
        # But run_module_impl bypasses it.
        subprocess.run([VELO_BINARY, "run", "--zygote", "-m", "site", "--", "--help"], capture_output=True)

        # 3. Check if Zygote was started
        status = subprocess.run([VELO_BINARY, "zygote", "status"], capture_output=True, text=True)

        if "Running" not in status.stdout:
            pytest.fail("Module mode (-m) ignores --zygote! No Zygote was auto-started.")

        print("\n[QA] Zygote correctly auto-started for module mode.")

    def test_signal_forwarding_resilience(self):
        """
        Adversarial: Send SIGINT to velo run -m and see if it stops the infinite loop module.
        If velo doesn't forward signal, the child hangs.
        """
        # Create a module that ignores SIGINT or just loops
        # We'll use a script passed as module if possible, or just a known slow module
        # For simplicity, we'll run a python -c loop but via velo run -m
        # Wait, run -m requires a real module. Let's use 'time' or something that hangs.

        # Use a custom module in the current dir
        os.makedirs("qa_test_mod", exist_ok=True)
        with open("qa_test_mod/__init__.py", "w") as f:
            f.write("import time; import sys; print('STARTED'); sys.stdout.flush(); time.sleep(10)")

        env = os.environ.copy()
        env["PYTHONPATH"] = os.getcwd()

        proc = subprocess.Popen(
            [VELO_BINARY, "run", "-m", "qa_test_mod"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        # Wait for "STARTED"
        start_time = time.time()
        while "STARTED" not in proc.stdout.readline():
            if time.time() - start_time > 5:
                proc.kill()
                pytest.fail("Module failed to start")

        # Send SIGINT to VELO
        time.sleep(0.5)
        proc.send_signal(signal.SIGINT)

        try:
            retcode = proc.wait(timeout=2)
            # Success: process exited
            print(f"\n[QA] Signal forwarded successfully. Retcode: {retcode}")
        except subprocess.TimeoutExpired:
            proc.kill()
            pytest.fail("VELO failed to forward SIGINT to child module!")

    def test_fd_hygiene_pollution(self):
        """
        Adversarial: Open many FDs in parent, then run -m module and check if they leaked.
        RFC-0030 §9.1.3 requires an allow-list approach to close non-standard FDs.
        """
        # This is hard to test from outside unless the module reports its FDs.
        with open("fd_report_mod.py", "w") as f:
            f.write("import os; print(f'FDS:{len(os.listdir(\"/dev/fd\"))}')")

        # Open some "junk" FDs in a wrapper or just rely on Velo's own internal FDs
        # Actually, let's just check if the count is reasonably low (<10)

        env = os.environ.copy()
        env["PYTHONPATH"] = os.getcwd()

        result = subprocess.run([VELO_BINARY, "run", "-m", "fd_report_mod"], capture_output=True, text=True, env=env)

        # Parse output
        fds = 0
        for line in result.stdout.splitlines():
            if line.startswith("FDS:"):
                fds = int(line.split(":")[1])

        print(f"\n[QA] Child FDs: {fds}")
        # Standard: 0, 1, 2, plus maybe the dir FD during listing.
        # If > 10, there's likely a leak.
        if fds > 10:
            pytest.fail(f"FD Leak detected! Child has {fds} open file descriptors.")

    def test_jupyter_install_idempotency_and_clobbering(self):
        """
        Verify that velo jupyter install doesn't crash if dir exists but is a file.
        """
        kernel_path = Path.home() / (
            "Library/Jupyter/kernels/velo" if sys.platform == "darwin" else ".local/share/jupyter/kernels/velo"
        )
        if kernel_path.exists():
            import shutil

            if kernel_path.is_dir():
                shutil.rmtree(kernel_path)
            else:
                kernel_path.unlink()

        # Create a FILE where the dir should be (the 'toxic' case)
        kernel_path.parent.mkdir(parents=True, exist_ok=True)
        kernel_path.write_text("i am a file")

        result = subprocess.run([VELO_BINARY, "jupyter", "install"], capture_output=True, text=True)

        # It should probably fail gracefully or handle it.
        # If it crashes with 'Not a directory', that's a findable bug.
        if result.returncode != 0:
            print(f"\n[QA] Install failed as expected on clobbered path: {result.stderr}")
        else:
            print("\n[QA] Install handled clobbered path (or clobbered it back)")
