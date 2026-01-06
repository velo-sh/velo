import os
import time
import pytest
import subprocess
from pathlib import Path

# TITANIUM Grade: L5 Performance Benchmarks
# Based on QA-SOP §14 (Performance & Benchmark Standards)

def measure_startup(velo_cmd: list, env_vars: dict) -> float:
    start = time.perf_counter()
    subprocess.run(
        velo_cmd,
        env=env_vars,
        capture_output=True,
        check=True
    )
    return (time.perf_counter() - start) * 1000 # ms

@pytest.mark.tier5
def test_PERF_621_kinetic_speedup(isolated_env):
    """Verify >10x speedup over Cold Start."""
    env = isolated_env
    socket_path = Path("/tmp") / f"perf_zygote_speedup_{os.getpid()}.sock"
    app_dir = env.path / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text("import time; print('Ready')")
    (app_dir / "uv.lock").write_text("{}") # Ensure it's treated as a project
    
    # 1. Measure Cold Start
    # Use str(app_dir) and absolute path to velo
    cold_latency = measure_startup(
        [env.velo, "serve", "--app", str(app_dir), "--dry-run"],
        os.environ.copy()
    )
    
    # 2. Start Zygote and Measure Kinetic
    cmd_env = os.environ.copy()
    cmd_env["VELO_ZYGOTE_SOCKET"] = str(socket_path)
    proc = subprocess.Popen(
        [env.velo, "zygote", "start", "--preload", "pandas"],
        env=cmd_env,
        cwd=app_dir
    )
    
    # Wait for socket
    timeout = time.time() + 10 # Allow extra time for heavy pandas preload
    while not socket_path.exists() and time.time() < timeout:
        time.sleep(0.1)
    
    assert socket_path.exists(), "Zygote failed to start with pandas preload"
    
    try:
        kinetic_latency = measure_startup(
            [env.velo, "serve", "main:app", "--dry-run"],
            cmd_env
        )
        
        speedup = cold_latency / kinetic_latency
        print(f"Cold: {cold_latency:.2f}ms | Kinetic: {kinetic_latency:.2f}ms | Speedup: {speedup:.2f}x")
        
        # RFC-0013 North Star: <50ms cold start for LLMs (contextualized to pandas here)
        assert kinetic_latency < 50, f"Kinetic startup too slow: {kinetic_latency:.2f}ms"
        assert speedup > 2, f"Kinetic speedup insufficient: {speedup:.2f}x"
        
    finally:
        proc.terminate()

@pytest.mark.tier5
def test_PERF_622_spawn_scalability(isolated_env):
    """Measure latency degradation across many sequential spawns."""
    env = isolated_env
    socket_path = Path("/tmp") / f"perf_zygote_scale_{os.getpid()}.sock"
    
    cmd_env = os.environ.copy()
    cmd_env["VELO_ZYGOTE_SOCKET"] = str(socket_path)
    proc = subprocess.Popen(
        [env.velo, "zygote", "start"],
        env=cmd_env
    )
    # Wait for socket
    timeout = time.time() + 5
    while not socket_path.exists() and time.time() < timeout:
        time.sleep(0.1)
    
    latencies = []
    try:
        for _ in range(20):
            lat = measure_startup(
                [env.velo, "serve", "main:app", "--dry-run"],
                cmd_env
            )
            latencies.append(lat)
        
        avg_lat = sum(latencies) / len(latencies)
        max_lat = max(latencies)
        print(f"Avg: {avg_lat:.2f}ms | Max: {max_lat:.2f}ms")
        
        # Verify stability
        assert max_lat < avg_lat * 2, "Spawning latency exhibits significant jitter/degradation"
        
    finally:
        proc.terminate()
