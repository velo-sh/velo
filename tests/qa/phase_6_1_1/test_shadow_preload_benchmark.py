"""
Shadow Preloading Benchmark Test

This test demonstrates the performance improvement from Shadow Preloading:
- Before: Socket ready AFTER preload (~500ms)
- After: Socket ready IMMEDIATELY, preload async (~10ms)

Run with: uv run python tests/qa/phase_6_1_1/test_shadow_preload_benchmark.py
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

# Mark entire module as Zygote flaky - skip in CI due to timing/resource issues
pytestmark = [pytest.mark.zygote_flaky, pytest.mark.perf]

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def find_socket_path() -> str:
    """Find the Zygote socket path."""
    import hashlib

    uid = os.getuid()
    cwd_hash = hashlib.md5(str(PROJECT_ROOT).encode()).hexdigest()[:8]
    # Protocol version 0x01
    return f"/tmp/velo-zygote-{uid}-{cwd_hash}-v01.sock"


def wait_for_socket(socket_path: str, timeout: float = 10.0) -> float:
    """Wait for socket to become available and return time taken."""
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        if Path(socket_path).exists():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(0.1)
                    s.connect(socket_path)
                    return time.perf_counter() - start
            except (TimeoutError, ConnectionRefusedError):
                pass
        time.sleep(0.01)
    raise TimeoutError(f"Socket {socket_path} not ready after {timeout}s")


def send_handshake(socket_path: str) -> dict[str, Any]:
    """Send handshake and return response with preload state."""
    import msgpack

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(5.0)
        s.connect(socket_path)

        # Read Ready
        length_bytes = s.recv(4)
        length = int.from_bytes(length_bytes, "little")  # P1 FIX: Match Rust little-endian
        data = s.recv(length)
        msgpack.unpackb(data, raw=False)

        # Send Handshake
        handshake = {"type": "Handshake", "version": 0x01, "capabilities": []}
        packed = msgpack.packb(handshake)
        s.sendall(len(packed).to_bytes(4, "little") + packed)  # P1 FIX: Match Rust little-endian

        # Read response
        length_bytes = s.recv(4)
        length = int.from_bytes(length_bytes, "little")  # P1 FIX: Match Rust little-endian
        data = s.recv(length)
        response = msgpack.unpackb(data, raw=False)

        return dict(response)


def wait_for_preload_ready(socket_path: str, timeout: float = 30.0) -> float:
    """Wait for preload to complete and return total time."""
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        try:
            response = send_handshake(socket_path)
            caps = response.get("capabilities", [])
            preload_caps = [c for c in caps if c.startswith("preload:")]
            if preload_caps and preload_caps[0] == "preload:ready":
                return time.perf_counter() - start
        except Exception:
            pass
        time.sleep(0.05)
    raise TimeoutError(f"Preload not ready after {timeout}s")


def measure_preload_time(modules: list[str]) -> float:
    """Measure actual preload time for comparison."""
    import importlib

    start = time.perf_counter()
    for mod in modules:
        try:
            importlib.import_module(mod)
        except ImportError:
            pass
    return time.perf_counter() - start


def run_benchmark() -> None:
    """Run the Shadow Preloading benchmark."""
    print("=" * 60)
    print("Shadow Preloading Performance Benchmark")
    print("=" * 60)

    preload_modules = ["fastapi", "uvicorn", "starlette"]

    # Step 1: Measure actual preload time (baseline)
    print(f"\n📦 Preload modules: {preload_modules}")
    print("📏 Measuring baseline preload time...")
    preload_time = measure_preload_time(preload_modules)
    print(f"   Baseline: {preload_time * 1000:.1f}ms")

    # Clean up any existing socket
    socket_path = find_socket_path()
    if Path(socket_path).exists():
        Path(socket_path).unlink()

    # Step 2: Start Zygote and measure socket ready time
    python_path = sys.executable
    zygote_script = PROJECT_ROOT / "velo_zygote" / "main.py"

    print("\n� Starting Zygote with Shadow Preloading...")

    cmd = [
        python_path,
        str(zygote_script),
        "--socket",
        socket_path,
        "--preload",
        *preload_modules,
    ]

    time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        socket_ready_time = wait_for_socket(socket_path)
        print(f"✅ Socket Ready:    {socket_ready_time * 1000:.1f}ms")

        # Summary
        print("\n" + "=" * 60)
        print("📈 RESULTS")
        print("=" * 60)
        print(f"  Preload Time (baseline):  {preload_time * 1000:>8.1f}ms")
        print(f"  Socket Ready (shadow):    {socket_ready_time * 1000:>8.1f}ms")
        print()

        saved = preload_time - socket_ready_time
        if saved > 0:
            improvement = preload_time / socket_ready_time
            print(f"  💡 Saved: {saved * 1000:.0f}ms ({improvement:.1f}x faster socket ready)")
        else:
            print("  ℹ️  Preload faster than socket setup")

        print("=" * 60)

    finally:
        proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        if Path(socket_path).exists():
            Path(socket_path).unlink()


if __name__ == "__main__":
    run_benchmark()
