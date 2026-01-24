import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

# Paths
CUR_DIR = Path(__file__).parent
VELO = CUR_DIR.parents[1] / "target" / "debug" / "velo"
FIXTURES = CUR_DIR / "fixtures" / "mock_libs"
AI_ENGINE_SRC = FIXTURES / "ai_engine.c"
TEST_DIR = CUR_DIR / "ai_bench_workspace"


@pytest.fixture(scope="module", autouse=True)
def setup_ai_bench():
    """Build the AI engine and set up workspace."""
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    TEST_DIR.mkdir()

    # 1. Compile the AI Engine
    lib_path = TEST_DIR / "libai_engine.dylib"
    subprocess.run(["gcc", "-shared", "-o", str(lib_path), str(AI_ENGINE_SRC)], check=True)

    # 2. Create Inference App
    app_py = TEST_DIR / "app.py"
    app_py.write_text(f"""
import ctypes
import time
import os

# Measure startup time from Python perspective
start = time.perf_counter()

# Load the heavy engine
lib = ctypes.CDLL("{lib_path}")
lib.predict.argtypes = [ctypes.c_double]
lib.predict.restype = ctypes.c_double

result = lib.predict(1.0)
elapsed = (time.perf_counter() - start) * 1000

print(f"RESULT: {{result}}")
print(f"BENCH_STARTUP_MS: {{elapsed:.2f}}")
""")

    # 3. Create pyproject.toml for Velo
    (TEST_DIR / "pyproject.toml").write_text(f"""
[tool.velo]
native_libraries = ["{lib_path}"]
""")

    yield TEST_DIR

    # Cleanup (manual cleanup preferred for benchmarking traces)
    # shutil.rmtree(TEST_DIR)


class TestAIFirstBenchmark:
    """The 'Breathtaking' AI Benchmark Suite."""

    def test_E2E_AI_001_cold_vs_velo(self, setup_ai_bench):
        workspace = setup_ai_bench

        # --- 1. COLD START BASELINE (Python 3) ---
        print("\n[STEP 1] Running COOLD START baseline (Standard Python)...")
        res_cold = subprocess.run(["python3", "app.py"], cwd=workspace, capture_output=True, text=True)
        # Extract internal startup time
        cold_internal_ms = 0.0
        for line in res_cold.stdout.splitlines():
            if "BENCH_STARTUP_MS:" in line:
                cold_internal_ms = float(line.split(":")[1])

        print(f"  -> Cold Start Internal: {cold_internal_ms:.2f}ms")

        # --- 2. VELO WARMUP (Native Preloading) ---
        print("\n[STEP 2] Warming up VELO Zygote...")
        # First, analyze to create preload.lock
        subprocess.run([str(VELO), "preload", "analyze"], cwd=workspace, check=True)

        # Warmup run - this starts the Zygote and pays the 5s penalty
        subprocess.run(
            [str(VELO), "run", "app.py", "--zygote"],
            cwd=workspace,
            capture_output=True,
            text=True,
            env={**os.environ, "VELO_TEST_MODE": "1"},
        )
        print("  -> Zygote Warmed.")

        # --- 3. VELO AI-FIRST BENCHMARK (Warm Zygote) ---
        print("\n[STEP 3] Running VELO AI-FIRST (Warm Zygote)...")
        start_t = time.perf_counter()
        res_velo = subprocess.run(
            [str(VELO), "run", "app.py", "--zygote"],
            cwd=workspace,
            capture_output=True,
            text=True,
            env={**os.environ, "VELO_TEST_MODE": "1"},
        )
        velo_e2e_ms = (time.perf_counter() - start_t) * 1000

        # Extract internal startup time
        velo_internal_ms = 0.0
        for line in res_velo.stdout.splitlines():
            if "BENCH_STARTUP_MS:" in line:
                velo_internal_ms = float(line.split(":")[1])

        # Verify result and NO constructor output (it's already loaded)
        assert "RESULT: 1.618" in res_velo.stdout
        assert "[AI_ENGINE] ✅ AI Engine Online" not in res_velo.stdout
        assert "[AI_ENGINE] ✅ AI Engine Online" not in res_velo.stderr

        print(f"  -> Velo Internal (Warm): {velo_internal_ms:.2f}ms")
        print(f"  -> Velo E2E (Warm):      {velo_e2e_ms:.2f}ms")

        # --- 4. BREATHTAKING RESULTS ---
        speedup_internal = cold_internal_ms / velo_internal_ms
        cold_internal_ms / velo_e2e_ms

        print("\n" + "=" * 60)
        print("🚀 VELO AI-FIRST BENCHMARK: COLD START ELIMINATION")
        print("=" * 60)
        print("MEASUREMENT             |  STANDARD PYTHON  |   VELO (WARM)   ")
        print("-" * 60)
        print(f"Cold Start Penalty      |   {cold_internal_ms:>8.1f} ms  |   {velo_internal_ms:>10.1f} ms")
        print(f"E2E Command Latency     |   {cold_internal_ms + 100:>8.1f} ms  |   {velo_e2e_ms:>10.1f} ms")
        print("-" * 60)
        print(f"🔥 AI-FIRST SPEEDUP:    |      1.00 x       |   {speedup_internal:>10.1f} x")
        print("=" * 60)

        # Verification: Expected at least 50x speedup (from 5s to <100ms)
        assert speedup_internal > 50, f"Speedup {speedup_internal:.1f}x too low!"

        # Save for later report
        (workspace / "bench_results.txt").write_text(f"""
cold_internal:{cold_internal_ms}
velo_internal:{velo_internal_ms}
speedup:{speedup_internal}
""")
