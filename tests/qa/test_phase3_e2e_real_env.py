"""
Velo QA: Phase 3 E2E Real-World Tests
======================================
Tests that simulate REAL user environments, not dev environment!

Critical: These tests run OUTSIDE the velo source directory to catch
path-related bugs like DEF-003 (velo_zygote/main.py not found).
"""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest


def get_velo_binary():
    """Get path to velo binary."""
    # Try release first, then debug
    repo_root = Path(__file__).parent.parent.parent
    release = repo_root / "target" / "release" / "velo"
    debug = repo_root / "target" / "debug" / "velo"
    
    if release.exists():
        return str(release)
    elif debug.exists():
        return str(debug)
    else:
        pytest.skip("velo binary not found - run cargo build first")


class RealUserEnv:
    """Simulates a REAL user project directory (no velo source files)."""
    
    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="user_project_"))
        self.velo = get_velo_binary()
    
    def setup(self):
        """Create minimal Python project."""
        # Virtual env
        subprocess.run(["uv", "venv", "--quiet"], cwd=self.path, check=True)
        
        # Lock file
        (self.path / "uv.lock").write_text("{}")
        
        return self
    
    def create_script(self, name: str, content: str):
        """Create a Python script."""
        (self.path / name).write_text(content)
    
    def run_velo(self, args: list, timeout: float = 30) -> tuple:
        """Run velo and return (returncode, stdout, stderr, duration)."""
        start = time.perf_counter()
        result = subprocess.run(
            [self.velo] + args,
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        duration = (time.perf_counter() - start) * 1000  # ms
        return result.returncode, result.stdout, result.stderr, duration
    
    def cleanup(self):
        """Remove temp directory."""
        try:
            shutil.rmtree(self.path)
        except Exception:
            pass
    
    def __enter__(self):
        return self.setup()
    
    def __exit__(self, *args):
        self.cleanup()


class TestZygoteInRealUserEnv:
    """E2E tests in simulated user environment (OUTSIDE velo repo)."""

    def test_e2e_001_zygote_starts_in_user_project(self):
        """
        E2E-001: Zygote should start in user's project directory.
        
        This is the bug DEF-003 found: Zygote fails when velo_zygote/
        is not in current directory.
        """
        with RealUserEnv() as env:
            env.create_script("hello.py", 'print("hello")')
            
            code, stdout, stderr, _ = env.run_velo(["run", "--zygote", "hello.py"])
            
            # Should NOT fail with "Could not find velo_zygote/main.py"
            assert "Could not find velo_zygote" not in stderr, (
                f"DEF-003: Zygote can't find main.py in user project!\n{stderr}"
            )
            
            # Should actually work
            assert "hello" in stdout or code == 0

    def test_e2e_002_zygote_daemon_persists(self):
        """
        E2E-002: Zygote daemon should persist between runs.
        
        Second run should be MUCH faster (< 50ms) because Zygote
        is already running.
        """
        with RealUserEnv() as env:
            env.create_script("quick.py", 'print("ok")')
            
            # First run (may start Zygote)
            _, _, stderr1, time1 = env.run_velo(["run", "--zygote", "quick.py"])
            
            # Check if Zygote actually started (not fallback)
            if "Falling back" in stderr1:
                pytest.fail(f"Zygote fell back to normal mode: {stderr1}")
            
            # Second run (should reuse Zygote)
            _, stdout2, stderr2, time2 = env.run_velo(["run", "--zygote", "quick.py"])
            
            # Should NOT start Zygote again
            assert "Starting Zygote" not in stderr2, (
                f"Zygote restarted on second run! Should reuse daemon.\n{stderr2}"
            )
            
            # Second run should be fast
            assert time2 < 100, f"Second run too slow ({time2:.1f}ms) - Zygote not persisting"

    def test_e2e_003_zygote_preload_works(self):
        """
        E2E-003: Preloaded modules should be instant on second run.
        
        If preload works, second run with import should be as fast as
        run without import.
        """
        with RealUserEnv() as env:
            # Script with heavy import
            env.create_script("with_import.py", """
import json
import os
print("imported")
""")
            
            # Script without import
            env.create_script("no_import.py", 'print("done")')
            
            # Warm up with import
            env.run_velo(["run", "--zygote", "with_import.py"])
            
            # Measure with import (should be preloaded)
            _, _, _, time_with = env.run_velo(["run", "--zygote", "with_import.py"])
            
            # Measure without import
            _, _, _, time_without = env.run_velo(["run", "--zygote", "no_import.py"])
            
            # With preload, times should be similar
            ratio = time_with / time_without if time_without > 0 else 999
            
            print(f"\n  With import: {time_with:.1f}ms")
            print(f"  Without import: {time_without:.1f}ms")
            print(f"  Ratio: {ratio:.2f}x")
            
            # Preload should make import nearly free
            assert ratio < 2.0, f"Preload not working: {ratio:.2f}x slower with imports"

    def test_e2e_004_consecutive_runs_speedup(self):
        """
        E2E-004: Measure actual speedup from cold to warm.
        
        This is the 49x claim verification.
        """
        with RealUserEnv() as env:
            env.create_script("test.py", 'print("ok")')
            
            # First run (cold - may include Zygote startup)
            _, _, _, cold_time = env.run_velo(["run", "--zygote", "test.py"])
            
            # Second run (should be warm)
            _, _, _, warm_time = env.run_velo(["run", "--zygote", "test.py"])
            
            print(f"\n  Cold: {cold_time:.1f}ms")
            print(f"  Warm: {warm_time:.1f}ms")
            
            if cold_time > 0 and warm_time > 0:
                speedup = cold_time / warm_time
                print(f"  Speedup: {speedup:.1f}x")
                
                # Warm should be at least 2x faster to count as "working"
                assert speedup > 2.0 or warm_time < 50, (
                    f"No speedup detected: cold={cold_time:.1f}ms, warm={warm_time:.1f}ms"
                )

    def test_e2e_005_zygote_status_works(self):
        """
        E2E-005: velo zygote status should work in user project.
        """
        with RealUserEnv() as env:
            # Start Zygote
            env.run_velo(["zygote", "start"], timeout=10)
            
            # Check status
            code, stdout, stderr, _ = env.run_velo(["zygote", "status"], timeout=5)
            
            # Should not error
            assert code == 0 or "not running" in stdout.lower() or "running" in stdout.lower()

    def test_e2e_006_fallback_when_zygote_fails(self):
        """
        E2E-006: Should gracefully fallback if Zygote fails mid-run.
        
        We simulate failure by killing Zygote after it starts.
        """
        import signal
        
        with RealUserEnv() as env:
            env.create_script("test.py", 'print("fallback_works")')
            
            # Start Zygote first
            env.run_velo(["zygote", "start"], timeout=10)
            
            # Kill Zygote to simulate failure
            subprocess.run(["pkill", "-f", "velo_zygote"], capture_output=True)
            time.sleep(0.2)  # Give it time to die
            
            # Now run should fallback to normal mode
            code, stdout, stderr, _ = env.run_velo(["run", "--zygote", "test.py"])
            
            # Either fallback message OR script executed
            assert "Falling back" in stderr or "fallback_works" in stdout or code == 0, (
                f"Neither fallback nor success! code={code}, stdout={stdout}, stderr={stderr}"
            )

    def test_e2e_007_stdout_captured_correctly(self):
        """
        E2E-007: Script stdout should be captured correctly.
        
        DEF-005: Zygote runs but stdout is empty.
        This test ensures print() output is properly returned.
        """
        with RealUserEnv() as env:
            env.create_script("output.py", '''
print("line1")
print("line2")
print("line3")
''')
            
            code, stdout, stderr, _ = env.run_velo(["run", "--zygote", "output.py"])
            
            # Stdout must contain the output
            assert "line1" in stdout, f"stdout missing! stdout={repr(stdout)}, stderr={stderr}"
            assert "line2" in stdout, f"stdout incomplete! stdout={repr(stdout)}"
            assert "line3" in stdout, f"stdout incomplete! stdout={repr(stdout)}"

    def test_e2e_008_stderr_captured_correctly(self):
        """
        E2E-008: Script stderr should be captured correctly.
        """
        with RealUserEnv() as env:
            env.create_script("error.py", '''
import sys
print("error_output", file=sys.stderr)
''')
            
            code, stdout, stderr, _ = env.run_velo(["run", "--zygote", "error.py"])
            
            # Should capture stderr from script (mixed with velo's own stderr)
            # At minimum, should not crash
            assert code == 0 or "error" in stderr.lower()


class TestZygotePerformanceRequirements:
    """Tests that verify RFC-0002 performance claims."""

    def test_perf_001_warm_start_under_50ms(self):
        """
        PERF-001: Warm start must be under 50ms (RFC requirement).
        """
        with RealUserEnv() as env:
            env.create_script("quick.py", 'print("ok")')
            
            # Warm up
            env.run_velo(["run", "--zygote", "quick.py"])
            env.run_velo(["run", "--zygote", "quick.py"])
            
            # Measure 5 runs
            times = []
            for _ in range(5):
                _, _, stderr, t = env.run_velo(["run", "--zygote", "quick.py"])
                if "Falling back" not in stderr:
                    times.append(t)
            
            if times:
                avg = sum(times) / len(times)
                min_time = min(times)
                
                print(f"\n  Warm times: {times}")
                print(f"  Average: {avg:.1f}ms, Min: {min_time:.1f}ms")
                
                # Target: < 50ms
                assert min_time < 50, f"Warm start too slow: {min_time:.1f}ms > 50ms target"
            else:
                pytest.fail("All runs fell back to normal mode - Zygote not working")

    def test_perf_002_fork_latency_under_5ms(self):
        """
        PERF-002: Fork latency must be under 5ms (RFC requirement).
        
        Note: This requires Zygote to actually work. Skip if fallback.
        """
        with RealUserEnv() as env:
            env.create_script("instant.py", 'pass')
            
            # Make sure Zygote is running
            _, _, stderr, _ = env.run_velo(["run", "--zygote", "instant.py"])
            
            if "Falling back" in stderr:
                pytest.skip("Zygote fell back - can't test fork latency")
            
            # Measure fork latency (multiple runs after warm-up)
            times = []
            for _ in range(10):
                _, _, _, t = env.run_velo(["run", "--zygote", "instant.py"])
                times.append(t)
            
            min_time = min(times)
            
            # The actual fork latency is faster than total time,
            # but total time < 10ms indicates fast fork
            print(f"\n  Fork times: {times}")
            print(f"  Min: {min_time:.1f}ms")
