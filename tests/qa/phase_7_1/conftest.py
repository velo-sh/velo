"""
Phase 7.1 QA Test Configuration

Provides shared fixtures for RFC-0018 Integrated Custody tests.
Includes architecture detection to skip tests when binary is incompatible.
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "tier2: RFC-0017 Tier 2 E2E tests (>100ms, <10s)")
    config.addinivalue_line("markers", "requires_velo: Test requires velo binary execution")


def _get_binary_arch(binary_path: str) -> str:
    """Detect the architecture of a binary file."""
    try:
        # Use 'file' command on Unix-like systems
        result = subprocess.run(
            ["file", binary_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout.lower()

        if "arm64" in output or "aarch64" in output:
            return "arm64"
        elif "x86_64" in output or "x86-64" in output:
            return "x86_64"
        else:
            return "unknown"
    except Exception:
        return "unknown"


def _get_system_arch() -> str:
    """Get the current system architecture, handling Rosetta 2."""
    machine = platform.machine().lower()

    # On macOS, if we're running under Rosetta, machine will be x86_64
    # but the system might actually support arm64.
    if sys.platform == "darwin" and machine == "x86_64":
        try:
            # sysctl -n hw.optional.arm64 returns 1 on Apple Silicon
            result = subprocess.run(
                ["sysctl", "-n", "hw.optional.arm64"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.stdout.strip() == "1":
                return "arm64"
        except Exception:
            pass

    if machine in ("arm64", "aarch64"):
        return "arm64"
    elif machine in ("x86_64", "amd64"):
        return "x86_64"
    return machine


@pytest.fixture(scope="session")
def workspace_root():
    """Get the workspace root directory."""
    return Path(__file__).parent.parent.parent.parent


@pytest.fixture(scope="session")
def velo_binary(workspace_root):
    """Get path to velo binary, skip if architecture mismatch."""
    release = workspace_root / "target" / "release" / "velo"
    debug = workspace_root / "target" / "debug" / "velo"

    binary_path = None
    if release.exists():
        binary_path = str(release)
    elif debug.exists():
        binary_path = str(debug)
    else:
        pytest.skip("velo binary not found - run 'cargo build' first")

    # Check architecture compatibility
    system_arch = _get_system_arch()
    binary_arch = _get_binary_arch(binary_path)

    if binary_arch != "unknown" and system_arch != binary_arch:
        pytest.skip(
            f"Binary architecture mismatch: binary={binary_arch}, system={system_arch}. "
            f"Rebuild velo for this platform: 'cargo build --release'"
        )

    return binary_path


@pytest.fixture(autouse=True)
def cleanup_stale_zygote():
    """Clean up any stale Zygote sockets before each test."""
    import shutil

    # Common socket locations
    socket_paths = [
        Path.home() / ".local" / "state" / "velo" / "zygote.sock",
        Path("/tmp") / f"velo-{os.getuid()}" / "zygote.sock",
    ]

    for sock in socket_paths:
        if sock.exists():
            try:
                sock.unlink()
            except OSError:
                pass
        # Also try removing parent if it's a stale socket dir
        parent = sock.parent
        if parent.name.startswith("velo-") and parent.exists():
            try:
                shutil.rmtree(parent, ignore_errors=True)
            except OSError:
                pass

    yield  # Run test

    # Cleanup after test too
    for sock in socket_paths:
        if sock.exists():
            try:
                sock.unlink()
            except OSError:
                pass
