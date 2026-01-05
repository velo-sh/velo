#!/usr/bin/env python3
"""
Velo Top 100 Benchmark Runner (RFC-0012 v2)

Executes benchmarks defined in benchmarks/top100/<category>/<package>/benchmark.toml
"""

import argparse
import json
import logging
import platform
import re
import shutil
import subprocess
import sys
import time
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Any

# Try to import tomllib (Python 3.11+) or tomli
try:
    import tomllib as toml
except ImportError:
    try:
        import tomli as toml
    except ImportError:
        sys.exit("Error: 'tomllib' (Python 3.11+) or 'tomli' is required. Please install it.")

# Constants
ROOT_DIR = Path(__file__).parent.parent.parent.parent
BENCHMARKS_DIR = ROOT_DIR / "benchmarks" / "top100"
RESULTS_FILE = BENCHMARKS_DIR / "top100_v2_results.json"
VELO_BIN = ROOT_DIR / "target/release/velo"

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("runner")

class BenchmarkRunner:
    def __init__(self, limit: int = None, keep_env: bool = False, target_pkg: str = None):
        self.limit = limit
        self.keep_env = keep_env
        self.target_pkg = target_pkg
        self.results = []
        self.success_count = 0
        self.fail_count = 0

    def discover(self) -> List[Path]:
        """Find all benchmark.toml files."""
        candidates = list(BENCHMARKS_DIR.glob("*/*/benchmark.toml"))
        # Sort by category then package
        candidates.sort(key=lambda p: (p.parent.parent.name, p.parent.name))
        
        if self.target_pkg:
            candidates = [p for p in candidates if p.parent.name == self.target_pkg]
        elif self.limit:
            candidates = candidates[:self.limit]
            
        return candidates

    def run_command(self, cmd: List[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
        """Run a command with timeout."""
        return subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )

    def measure(self, cmd: List[str], cwd: Path, timeout: int, runs: int = 3, warmup_runs: int = 0) -> List[float]:
        """Measure execution time of a command."""
        times = []
        
        # Warmup (discard results)
        for _ in range(warmup_runs):
            try:
                subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                pass

        # Measurement
        for _ in range(runs):
            start = time.perf_counter()
            try:
                proc = self.run_command(cmd, cwd, timeout)
                duration = (time.perf_counter() - start) * 1000
                
                if proc.returncode != 0:
                    raise RuntimeError(f"Exit code {proc.returncode}: {proc.stderr}")
                
                times.append(duration)
            except subprocess.TimeoutExpired:
                raise TimeoutError(f"Timeout after {timeout}s")
                
        return times

    def run_benchmark(self, config_path: Path):
        """Run a single benchmark."""
        pkg_dir = config_path.parent
        category = pkg_dir.parent.name
        pkg_name = pkg_dir.name
        
        logger.info(f"👉 [{category}/{pkg_name}] Preparing...")
        
        try:
            with open(config_path, "rb") as f:
                config = toml.load(f)
            
            test_cfg = config["test"]
            entry_point = test_cfg["entry_point"]
            expected_regex = test_cfg["expected_output"]
            timeout = test_cfg.get("timeout", 30)
            
            # Setup Environment using UV
            venv_dir = pkg_dir / ".venv"
            if venv_dir.exists():
                shutil.rmtree(venv_dir)
            
            # Create venv and install package
            self.run_command(["uv", "venv"], pkg_dir, 30)
            
            # Install package (assume package name matches folder name unless specified)
            # Future: Allow specifying package name in toml
            install_pkg = config.get("meta", {}).get("package", pkg_name)
            
            install_cmd = ["uv", "pip", "install", install_pkg]
            proc = self.run_command(install_cmd, pkg_dir, 120)
            if proc.returncode != 0:
                raise RuntimeError(f"Install failed: {proc.stderr}")
            
            # Resolve Entry Point
            # Case A: Script in local folder
            local_script = pkg_dir / entry_point
            # Case B: Binary in venv/bin
            venv_bin_script = venv_dir / "bin" / entry_point
            
            target_path = None
            is_python_script = False
            
            if local_script.exists():
                target_path = local_script
                is_python_script = local_script.suffix == ".py"
            elif venv_bin_script.exists():
                target_path = venv_bin_script
                # Binaries in venv are usually python scripts with shebang
                is_python_script = True 
            else:
                 raise FileNotFoundError(f"Entry point {entry_point} not found in {pkg_dir} or {venv_dir}/bin")
            
            # Build Commands
            args = test_cfg.get("args", [])
            python_bin = venv_dir / "bin" / "python"
            
            if is_python_script:
                # Case A: Local .py script -> run via python executable
                # Case B: Binary that happens to be a python script -> run directly (if executable) or via python
                # Since black in venv/bin usually has shebang+chmod, direct execution works for CPython.
                # BUT local hello.py needs explicit python.
                
                if local_script.exists():
                     # Local script: needs explicit python
                     base_cmd_cpython = [str(python_bin), str(target_path)] + args
                else:
                     # Venv binary: run directly
                     base_cmd_cpython = [str(target_path)] + args
                
                # Velo: `velo run <path> -- <args>`
                # We add `--` before args to prevent Velo from eating flags like --version
                velo_args = ["--"] + args if args else []
                base_cmd_velo = [str(VELO_BIN), "run", str(target_path)] + velo_args
                base_cmd_zygote = [str(VELO_BIN), "run", "--zygote", str(target_path)] + velo_args
            else:
                 # Non-python script
                 base_cmd_cpython = [str(target_path)] + args
                 base_cmd_velo = None
                 base_cmd_zygote = None

            # --- Execution ---
            
            # 1. CPython (System Warmup + Measure)
            cpython_times = self.measure(base_cmd_cpython, pkg_dir, timeout, runs=3, warmup_runs=1)
            
            # Verify Output (on verification run)
            verify_proc = self.run_command(base_cmd_cpython, pkg_dir, timeout)
            # Combine stdout and stderr for checking
            output = verify_proc.stdout + verify_proc.stderr
            if not re.search(expected_regex, output, re.MULTILINE):
                 logger.error(f"Output mismatch for {pkg_name}")
                 logger.error(f"Expected: {expected_regex}")
                 logger.error(f"Actual: {output}")
                 raise RuntimeError(f"Output regex mismatch")

            if base_cmd_velo:
                # 2. Velo Cold
                velo_cache = pkg_dir / ".velo_cache"
                if velo_cache.exists():
                    shutil.rmtree(velo_cache)
                
                velo_cold_times = self.measure(base_cmd_velo, pkg_dir, timeout, runs=3, warmup_runs=0)
                
                # 3. Velo Zygote
                subprocess.run([str(VELO_BIN), "zygote", "stop"], capture_output=True)
                velo_zygote_times = self.measure(base_cmd_zygote, pkg_dir, timeout, runs=3, warmup_runs=1)
                
                vc_mean = statistics.mean(velo_cold_times)
                vz_mean = statistics.mean(velo_zygote_times)
            else:
                vc_mean = 0
                vz_mean = 0
            
            cp_mean = statistics.mean(cpython_times)
            
            # Record
            result = {
                "package": pkg_name,
                "category": category,
                "cpython": cp_mean,
                "velo_cold": vc_mean,
                "velo_zygote": vz_mean,
                "cpython_stdev": statistics.stdev(cpython_times) if len(cpython_times) > 1 else 0,
                "status": "PASS"
            }
            self.results.append(result)
            self.success_count += 1
            
            logger.info(f"   ✅ PASS | CP: {cp_mean:.1f}ms | VC: {vc_mean:.1f}ms | VZ: {vz_mean:.1f}ms")

        except Exception as e:
            logger.error(f"   ❌ FAIL: {e}")
            self.results.append({
                "package": pkg_name,
                "category": category,
                "status": "FAIL",
                "error": str(e)
            })
            self.fail_count += 1
        finally:
            if not self.keep_env:
                venv_dir = pkg_dir / ".venv"
                if venv_dir.exists():
                    shutil.rmtree(venv_dir)

    def save_report(self):
        """Save results to JSON."""
        sys_info = {
            "os": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "date": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        report = {
            "system": sys_info,
            "summary": {
                "total": self.success_count + self.fail_count,
                "passed": self.success_count,
                "failed": self.fail_count
            },
            "results": self.results
        }
        
        with open(RESULTS_FILE, "w") as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"\n📊 Report saved to {RESULTS_FILE}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Limit number of benchmarks")
    parser.add_argument("--keep-env", action="store_true", help="Don't clean venvs")
    parser.add_argument("--package", type=str, help="Run specific package")
    args = parser.parse_args()
    
    if not VELO_BIN.exists():
        sys.exit(f"❌ Velo binary not found at {VELO_BIN}. Build it first!")

    runner = BenchmarkRunner(limit=args.limit, keep_env=args.keep_env, target_pkg=args.package)
    configs = runner.discover()
    
    logger.info(f"Found {len(configs)} benchmarks.")
    
    for cfg in configs:
        runner.run_benchmark(cfg)
    
    runner.save_report()

if __name__ == "__main__":
    main()
