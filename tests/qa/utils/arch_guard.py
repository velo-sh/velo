import platform
import shutil
import subprocess

import pytest


def get_binary_arch(binary_path):
    """Detects the architecture of a binary file using 'file' command."""
    if not shutil.which("file"):
        return "unknown"

    try:
        output = subprocess.check_output(["file", "-b", binary_path]).decode().lower()
        if "arm64" in output and "x86_64" in output:
            return "universal"
        if "arm64" in output:
            return "arm64"
        if "x86_64" in output:
            return "x86_64"
        return "unknown"
    except:
        return "unknown"


def get_python_arch():
    """Returns the architecture of the current running Python."""
    return platform.machine().lower()  # 'arm64' or 'x86_64'


def assert_velo_compatible(velo_bin):
    """
    Checks if the Velo binary and the current Python environment are architecturally compatible.
    Skips the test if a mismatch is detected.
    """
    velo_arch = get_binary_arch(velo_bin)
    python_arch = get_python_arch()

    # Universal binaries are compatible with everything
    if velo_arch == "universal":
        return

    # If Velo is thin bin, it must match Python
    # Note: On macOS with Rosetta, x86_64 python can run on arm64 hardware,
    # but an arm64 Velo cannot load x86_64 libs (which calling python might imply).

    # Case 1: Velo=arm64, Python=x86_64 -> Incompatible (Linker error)
    if velo_arch == "arm64" and python_arch == "x86_64":
        pytest.skip("Arch Mismatch: Velo is arm64 but Python is x86_64. Native loading will fail.")

    # Case 2: Velo=x86_64, Python=arm64 -> Incompatible
    if velo_arch == "x86_64" and python_arch == "arm64":
        pytest.skip("Arch Mismatch: Velo is x86_64 but Python is arm64.")

    # Note: We rely on the test runner's python being representative of what Velo picks up.
    # If Velo picks a different python, we might get false positives/negatives,
    # but this covers the "Automated Test Runner" case where pytest drives execution.
