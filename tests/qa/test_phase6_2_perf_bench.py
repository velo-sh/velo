import os
import time
import pytest
import subprocess
from pathlib import Path

# TITANIUM Grade: L5 Performance Benchmarks
# Based on QA-SOP §14 (Performance & Benchmark Standards)

import signal

def measure_startup_phases(velo_cmd: list, env_vars: dict, cwd: str = None) -> tuple[float, float]:
    start = time.perf_counter()
    proc = subprocess.Popen(
        velo_cmd,
        env=env_vars,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    arch_latency = None
    total_latency = None
    
    try:
        while True:
            line = proc.stdout.readline()
            if not line: break
            
            # Phase 1: Architecture Ready (Rust overhead + IPC + Fork)
            # Only present in Kinetic/Zygote mode
            if "Worker 1 (PID:" in line and arch_latency is None:
                arch_latency = (time.perf_counter() - start) * 1000
                
            # Phase 2: Application Ready (Python Import + Uvicorn Start)
            if "Server ready" in line:
                total_latency = (time.perf_counter() - start) * 1000
                return (arch_latency, total_latency)
                
            if (time.perf_counter() - start) > 15.0:
                 raise TimeoutError(f"Server failed to start. Last log: {line.strip()}")
    finally:
        try:
            os.kill(proc.pid, signal.SIGKILL)
            proc.wait()
        except: pass
    return (None, 99999.0)

@pytest.mark.tier5
@pytest.mark.heavy
def test_PERF_621_kinetic_speedup(isolated_env):
    """Verify >2x speedup over Cold Start (Real Execution)."""
    env = isolated_env
    socket_path = Path("/tmp") / f"perf_zygote_speedup_{os.getpid()}.sock"
    app_dir = env.path / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text("import fastapi; import pandas; app = fastapi.FastAPI()")
    (app_dir / "pyproject.toml").write_text('[project]\nname = "perf-app"\nversion = "0.1.0"\ndependencies = ["fastapi", "pandas"]')
    (app_dir / "uv.lock").write_text("{}") 
    
    # 1. Measure Cold Start (Real Execution, pays import cost)
    # Cold start doesn't have architecture phase log
    _, cold_latency = measure_startup_phases(
        [env.velo, "serve", "main:app", "--no-zygote"],
        os.environ.copy(),
        cwd=str(app_dir)
    )
    
    # 2. Start Zygote and Measure Kinetic
    if socket_path.exists(): os.unlink(socket_path)
    cmd_env = os.environ.copy()
    cmd_env["VELO_ZYGOTE_SOCKET"] = str(socket_path)

    # Preload modules to skip import cost
    proc = subprocess.Popen(
        [env.velo, "zygote", "start", "--preload", "pandas,fastapi"],
        env=cmd_env,
        cwd=app_dir
    )
    
    # Wait for socket
    timeout = time.time() + 15
    while not socket_path.exists() and time.time() < timeout:
        time.sleep(0.1)
    
    assert socket_path.exists(), "Zygote failed to start"
    
    try:
        arch_latency, kinetic_latency = measure_startup_phases(
            [env.velo, "serve", "main:app"],
            cmd_env,
            cwd=str(app_dir)
        )
        
        speedup = cold_latency / kinetic_latency
        print(f"Cold: {cold_latency:.2f}ms | Kinetic: {kinetic_latency:.2f}ms (Arch: {arch_latency:.2f}ms) | Speedup: {speedup:.2f}x")
        
        # RFC-0013 Standard: Phase-Separated Asserts
        # 1. Architecture Latency (Rust -> Zygote Fork): STRICT < 50ms
        if arch_latency is not None:
             assert arch_latency < 50, f"Architecture latency too high: {arch_latency:.2f}ms"
             
        # 2. Total Latency (E2E): User Experience < 300ms (Loose due to Python overhead)
        assert kinetic_latency < 300, f"Total startup too slow: {kinetic_latency:.2f}ms"
        
        # 3. Speedup: > 2x
        assert speedup > 2, f"Kinetic speedup insufficient: {speedup:.2f}x"
        
    finally:
        proc.terminate()

@pytest.mark.tier5
@pytest.mark.heavy
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
    app_dir = env.path / "app"
    if not app_dir.exists():
        app_dir.mkdir()
    (app_dir / "main.py").write_text("import fastapi; app = fastapi.FastAPI()")
    (app_dir / "pyproject.toml").write_text('[project]\nname = "scale-app"\nversion = "0.1.0"\ndependencies = ["fastapi"]')
    
    try:
        for _ in range(20):
            _, lat = measure_startup_phases(
                [env.velo, "serve", "main:app"],
                cmd_env,
                cwd=str(app_dir)
            )
            latencies.append(lat)
        
        avg_lat = sum(latencies) / len(latencies)
        max_lat = max(latencies)
        print(f"Avg: {avg_lat:.2f}ms | Max: {max_lat:.2f}ms")
        
        # Verify stability
        assert max_lat < avg_lat * 2, "Spawning latency exhibits significant jitter/degradation"
        
    finally:
        proc.terminate()
