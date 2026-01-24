import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Paths
PROJECT_ROOT = Path("/Users/antigravity/rust_source/velo_test")
VELO = PROJECT_ROOT / "target" / "debug" / "velo"
WORKSPACE = PROJECT_ROOT / "tests" / "qa" / "ai_dropin_workspace"
SITE_PACKAGES = PROJECT_ROOT / ".venv" / "lib" / "python3.11" / "site-packages"


def run_bench():
    print("🚀 VELO AI-FIRST BENCHMARK ORCHESTRATOR")
    print("=" * 60)

    # 1. Setup Workspace
    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)
    WORKSPACE.mkdir(parents=True)

    app_py = WORKSPACE / "app.py"
    app_py.write_text("""
import time
import os
import sys

tti_start = time.perf_counter()
import torch
import numpy as np

# Simulate a real AI workload
model = torch.nn.Linear(128, 128)
input_t = torch.randn(1, 128)
output = model(input_t)

tti_elapsed = (time.perf_counter() - tti_start) * 1000
print(f"TTI_MS: {tti_elapsed:.2f}")
print(f"PID: {os.getpid()}")
""")

    # 2. Discover Natives
    print("[1/4] Discovering native libraries...")
    libs = []
    # Force exact paths for preloading
    torch_lib = SITE_PACKAGES / "torch" / "lib"
    if torch_lib.exists():
        libs.extend([str(p) for p in torch_lib.glob("*.dylib")])

    libs_str = ",\n    ".join([f'"{l}"' for l in libs])

    (WORKSPACE / "pyproject.toml").write_text(f"""
[tool.velo]
native_libraries = [
    {libs_str}
]
""")
    print(f"  -> Found {len(libs)} critical native libraries.")

    # 3. Baseline: Cold Start
    print("[2/4] Running COLD START baseline (Standard Python)...")
    start_t = time.perf_counter()
    res_cold = subprocess.run(
        [sys.executable, str(app_py)],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(SITE_PACKAGES)},
    )
    cold_e2e_ms = (time.perf_counter() - start_t) * 1000

    cold_tti = 0.0
    for line in res_cold.stdout.splitlines():
        if "TTI_MS:" in line:
            cold_tti = float(line.split(":")[1])

    print(f"  -> Cold TTI: {cold_tti:.2f}ms")

    # 4. Acceleration: Velo
    print("[3/4] Preparing Velo Acceleration...")
    subprocess.run([str(VELO), "zygote", "stop"], check=False, capture_output=True)
    subprocess.run([str(VELO), "preload", "analyze"], cwd=WORKSPACE, check=True)

    # Warmup
    subprocess.run(
        [str(VELO), "run", "app.py", "--zygote"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        env={**os.environ, "VELO_PYTHON": sys.executable, "PYTHONPATH": str(SITE_PACKAGES), "VELO_TEST_MODE": "1"},
    )

    # Bench
    print("[4/4] Running VELO AI-FIRST benchmark...")
    start_t = time.perf_counter()
    res_velo = subprocess.run(
        [str(VELO), "run", "app.py", "--zygote"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        env={**os.environ, "VELO_PYTHON": sys.executable, "PYTHONPATH": str(SITE_PACKAGES), "VELO_TEST_MODE": "1"},
    )
    velo_e2e_ms = (time.perf_counter() - start_t) * 1000

    if res_velo.returncode != 0:
        print(f"❌ Velo Run Failed!\n{res_velo.stderr}")
        return

    velo_tti = 0.0
    for line in res_velo.stdout.splitlines():
        if "TTI_MS:" in line:
            velo_tti = float(line.split(":")[1])

    print(f"  -> Velo TTI: {velo_tti:.2f}ms")

    # 5. Results
    effective_velo_tti = max(0.1, velo_tti)
    speedup = cold_tti / effective_velo_tti

    print("\n" + "🌟" * 15)
    print("   FINAL AI RESULTS")
    print("🌟" * 15)
    print(f"Baseline (Cold):  {cold_tti:>8.1f} ms")
    print(f"Velo (Warm):      {velo_tti:>8.1f} ms")
    print("-" * 30)
    print(f"🚀 SPEEDUP:     {speedup:>8.1f} x")
    print("=" * 30)


if __name__ == "__main__":
    run_bench()
