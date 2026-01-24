"""
RFC-0035 Native Library Preload Performance Benchmarks

Acceptance Criteria:
- PyTorch import time < 500ms
- NumPy import time < 50ms
- Speedup ratio > 1.0x (Preload vs Cold)
"""

import subprocess
import time
from pathlib import Path

import pytest

VELO = Path(__file__).parents[2] / "target" / "debug" / "velo"
PROJECT_ROOT = Path(__file__).parents[2]

pytestmark = pytest.mark.skipif(
    not VELO.exists(),
    reason="velo binary not found. Run 'cargo build' first.",
)


def run_bench(lib_name: str, use_preload: bool) -> float:
    """Run import benchmark for a given library."""
    script_content = f"""
import time
start = time.perf_counter()
import {lib_name}
elapsed = (time.perf_counter() - start) * 1000
print(f"ELAPSED:{{elapsed:.2f}}")
"""
    script_path = PROJECT_ROOT / f"bench_{lib_name}.py"
    script_path.write_text(script_content)

    try:
        if use_preload:
            # Generate lock
            subprocess.run([str(VELO), "preload", "analyze"], check=True, capture_output=True)
            cmd = [str(VELO), "run", str(script_path)]
        else:
            # Bypass velo and use system python for baseline
            cmd = ["python3", str(script_path)]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        script_path.unlink()

        if result.returncode != 0:
            return -1.0

        for line in result.stdout.splitlines():
            if line.startswith("ELAPSED:"):
                return float(line.split(":")[1])
    except Exception:
        if script_path.exists():
            script_path.unlink()
    return -1.0


class TestRFC0035Performance:
    """L5: Performance benchmarks."""

    def test_PERF_035_001_pytorch_import_speed(self) -> None:
        """Verify PyTorch import < 500ms with preload."""
        # Check if torch is installed
        try:
            import torch  # noqa: F401
        except ImportError:
            pytest.skip("PyTorch not installed in environment")

        preload_ms = run_bench("torch", use_preload=True)
        cold_ms = run_bench("torch", use_preload=False)

        assert preload_ms > 0, "Preload benchmark failed"
        assert preload_ms < 500, f"PyTorch preload took {preload_ms}ms, expected < 500ms"

        if cold_ms > 0:
            speedup = cold_ms / preload_ms
            print(f"\nPyTorch Speedup: {speedup:.2f}x (Cold: {cold_ms:.1f}ms, Preload: {preload_ms:.1f}ms)")
            assert speedup > 1.0, f"No speedup observed: {speedup:.2f}x"

    def test_PERF_035_002_numpy_import_speed(self) -> None:
        """Verify NumPy import < 50ms with preload."""
        try:
            import numpy  # noqa: F401
        except ImportError:
            pytest.skip("NumPy not installed in environment")

        preload_ms = run_bench("numpy", use_preload=True)
        cold_ms = run_bench("numpy", use_preload=False)

        assert preload_ms > 0, "Preload benchmark failed"
        assert preload_ms < 50, f"NumPy preload took {preload_ms}ms, expected < 50ms"

        if cold_ms > 0:
            speedup = cold_ms / preload_ms
            print(f"\nNumPy Speedup: {speedup:.2f}x (Cold: {cold_ms:.1f}ms, Preload: {preload_ms:.1f}ms)")
            assert speedup > 1.0, f"No speedup observed: {speedup:.2f}x"

    def test_PERF_035_003_analyze_overhead(self) -> None:
        """Verify analyze command overhead < 2s."""
        start = time.perf_counter()
        subprocess.run([str(VELO), "preload", "analyze"], check=True, capture_output=True)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"Analyze took {elapsed:.2f}s, expected < 2s"
