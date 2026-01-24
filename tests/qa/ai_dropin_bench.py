import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Constants
CUR_DIR = Path(__file__).parent
PROJECT_ROOT = CUR_DIR.parents[1]
VELO = PROJECT_ROOT / "target" / "debug" / "velo"
AI_APP = CUR_DIR / "ai_app.py"
WORKSPACE = CUR_DIR / "ai_dropin_workspace"


@pytest.fixture(scope="module", autouse=True)
def setup_workspace():
    """Set up the AI profiling workspace."""
    # 🚨 FORCE ENVIRONMENT SYNC
    subprocess.run(["uv", "sync"], cwd=PROJECT_ROOT, check=True)

    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)
    WORKSPACE.mkdir()

    # Symlink .venv
    real_venv = PROJECT_ROOT / ".venv"
    (WORKSPACE / ".venv").symlink_to(real_venv)

    # Copy app.py
    shutil.copy(AI_APP, WORKSPACE / "app.py")

    # --- PHYSICAL DISCOVERY ---
    # Try multiple common site-packages layouts
    site_packages = real_venv / "lib" / "python3.11" / "site-packages"
    if not site_packages.exists():
        # Fallback for generic python3
        for p in (real_venv / "lib").glob("python3.*/site-packages"):
            site_packages = p
            break

    torch_lib = site_packages / "torch" / "lib"
    numpy_lib = site_packages / "numpy"
    pandas_lib = site_packages / "pandas"

    libs = []
    if torch_lib.exists():
        libs.extend([str(p) for p in torch_lib.glob("*.dylib")])
    if numpy_lib.exists():
        libs.extend([str(p) for p in numpy_lib.rglob("*.so")])
    if pandas_lib.exists():
        libs.extend([str(p) for p in pandas_lib.rglob("*.so")])

    if not libs:
        print(f"⚠️ WARNING: No native libs found in {site_packages}")
        # Emergency backup: just add the directory itself to trigger recursive lookup if supported
        libs = [str(torch_lib)]

    libs_str = ",\n    ".join([f'"{lib}"' for lib in libs])
    print(f"📦 Discovered {len(libs)} native libraries for preloading.")

    # Create pyproject.toml
    (WORKSPACE / "pyproject.toml").write_text(f"""
[tool.velo]
native_libraries = [
    {libs_str}
]
""")

    os.environ["VIRTUAL_ENV"] = str(real_venv)
    os.environ["PYTHONPATH"] = str(site_packages)

    yield WORKSPACE


class TestAIDropinBenchmark:
    """Zero-Code-Change AI Acceleration Benchmark."""

    def test_BENCH_AI_035_dropin(self, setup_workspace):
        workspace = setup_workspace

        print("\n" + "=" * 60)
        print("🔍 PHASE 1: STANDARD PYTHON COLD START (Baseline)")
        print("=" * 60)

        start_t = time.perf_counter()
        res_cold = subprocess.run([sys.executable, "app.py"], cwd=workspace, capture_output=True, text=True)
        cold_e2e_ms = (time.perf_counter() - start_t) * 1000

        if res_cold.returncode != 0:
            print(f"❌ COLD START FAILED (Exit {res_cold.returncode})")
            print(f"STDOUT:\n{res_cold.stdout}")
            print(f"STDERR:\n{res_cold.stderr}")
            pytest.fail("Cold start baseline failed")

        cold_tti = 0.0
        for line in res_cold.stdout.splitlines():
            if "TTI_MS:" in line:
                cold_tti = float(line.split(":")[1])

        print(f"  -> Cold TTI: {cold_tti:.2f}ms")
        print(f"  -> Cold E2E: {cold_e2e_ms:.2f}ms")

        print("\n" + "=" * 60)
        print("🔍 PHASE 2: VELO DROP-IN ACCELERATION")
        print("=" * 60)

        # 0. ENSURE FRESH START
        subprocess.run([str(VELO), "zygote", "stop"], check=False, capture_output=True)

        # 1. Analyze (Prepare the 'Brain')
        print("[Velo] Analyzing AI dependencies...")
        subprocess.run([str(VELO), "preload", "analyze"], cwd=workspace, check=True)

        # Verify lock is NOT empty
        lock_path = workspace / "preload.lock"
        if not lock_path.exists() or '"fingerprints":[]' in lock_path.read_text():
            print(
                f"❌ ERROR: preload.lock is empty or missing! Content:\n{lock_path.read_text() if lock_path.exists() else 'N/A'}"
            )
            pytest.fail("Failed to generate valid preload.lock")

        # 2. Warmup (Payment of the 'Initial Tax' in Zygote)
        print("[Velo] Warming up Zygote with PyTorch/NumPy pre-load...")
        subprocess.run(
            [str(VELO), "run", "app.py", "--zygote"],
            cwd=workspace,
            capture_output=True,
            text=True,
            env={**os.environ, "VELO_TEST_MODE": "1"},
        )

        # 3. Benchmark (The 'AI-First' Experience)
        print("[Velo] Running benchmark (Warm Zygote)...")
        start_t = time.perf_counter()
        # Propagate ALL critical environment variables
        env = {
            **os.environ,
            "VELO_TEST_MODE": "1",
            "VELO_PYTHON": sys.executable,
            "VIRTUAL_ENV": os.environ["VIRTUAL_ENV"],
            "PYTHONPATH": os.environ["PYTHONPATH"],
        }
        res_velo = subprocess.run(
            [str(VELO), "run", "app.py", "--zygote"], cwd=workspace, capture_output=True, text=True, env=env
        )
        velo_e2e_ms = (time.perf_counter() - start_t) * 1000

        if res_velo.returncode != 0:
            print(f"❌ VELO RUN FAILED (Exit {res_velo.returncode})")
            print(f"STDOUT:\n{res_velo.stdout}")
            print(f"STDERR:\n{res_velo.stderr}")
            pytest.fail("Velo acceleration run failed")

        velo_tti = 0.0
        for line in res_velo.stdout.splitlines():
            if "TTI_MS:" in line:
                velo_tti = float(line.split(":")[1])

        print(f"  -> Velo TTI: {velo_tti:.2f}ms")
        print(f"  -> Velo E2E: {velo_e2e_ms:.2f}ms")

        # --- FINAL ANALYSIS ---
        # Prevent division by zero for near-instantaneous Velo startup
        effective_velo_tti = max(0.1, velo_tti)
        speedup = cold_tti / effective_velo_tti

        print("\n" + "🌟" * 15)
        print("   AI DROP-IN RESULTS")
        print("🌟" * 15)
        print(f"COLD START TTI:     {cold_tti:>8.1f} ms")
        print(f"VELO WARM TTI:      {velo_tti:>8.1f} ms")
        print("-" * 30)
        print(f"🚀 SPEEDUP:       {speedup:>8.1f} x")
        print("=" * 30)

        # Write data for report
        (workspace / "final_stats.txt").write_text(f"""
cold_tti:{cold_tti}
velo_tti:{velo_tti}
speedup:{speedup}
""")

        assert speedup > 5.0, f"Expected at least 5x speedup for PyTorch, got {speedup:.2f}x"
        assert velo_tti < 250, f"Velo TTI {velo_tti}ms is too slow for warmed zygote"
