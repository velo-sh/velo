#!/usr/bin/env python3
"""
Velo Top 100 Benchmark Runner (RFC-0013 v2)

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
    def __init__(self, limit: int = None, keep_env: bool = False, target_pkg: str = None, runs: int = 3, drop_cache: bool = False):
        self.limit = limit
        self.keep_env = keep_env
        self.target_pkg = target_pkg or []
        self.runs = runs
        self.drop_cache = drop_cache
        self.results = []
        self.success_count = 0
        self.fail_count = 0

    def discover(self) -> List[Path]:
        """Find all benchmark.toml files."""
        candidates = list(BENCHMARKS_DIR.glob("*/*/benchmark.toml"))
        # Sort by category then package
        candidates.sort(key=lambda p: (p.parent.parent.name, p.parent.name))
        if self.target_pkg:
            candidates = [p for p in candidates if p.parent.name in self.target_pkg]
        elif self.limit:
            candidates = candidates[:self.limit]
            
        return candidates

    def run_command(self, cmd: List[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
        """Run a command with timeout."""
        return subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )

    def measure(self, cmd: List[str], cwd: Path, timeout: int, runs: int = 3, warmup_runs: int = 0, drop_cache: bool = False) -> List[float]:
        """Measure execution time of a command."""
        times = []
        
        # Warmup (discard results)
        for i in range(warmup_runs):
            try:
                subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                pass

        # Measurement
        for i in range(runs):
            if drop_cache:
                print(f"      ❄️  Dropping Cache (Run {i+1})...", end="\r")
                subprocess.run([sys.executable, str(ROOT_DIR / "benchmarks/top100/_runner/drop_cache.py")], 
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
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

    def ensure_builder_deps(self, pkg_dir: Path):
        """Ensure bundle builder dependencies (blake3) are installed."""
        self.run_command(["uv", "pip", "install", "blake3"], pkg_dir, 60)

    def build_bundle(self, pkg_dir: Path):
        """Build .veloc bundle for the project."""
        builder_script = ROOT_DIR / "python" / "bundle_builder.py"
        if not builder_script.exists():
            raise FileNotFoundError("bundle_builder.py not found")
        
        venv_python = pkg_dir / ".venv" / "bin" / "python"
        
        cmd = [str(venv_python), str(builder_script), str(pkg_dir)]
        proc = self.run_command(cmd, pkg_dir, 60)
        if proc.returncode != 0:
            raise RuntimeError(f"Bundle build failed: {proc.stderr}")
            
    def inject_preload(self, pkg_dir: Path, modules: List[str]):
        """Inject preload config into pyproject.toml."""
        config_path = pkg_dir / "pyproject.toml"
        
        # Read existing content if file exists
        existing_content = ""
        if config_path.exists():
            with open(config_path, "r") as f:
                existing_content = f.read()
        
        # Check if [tool.velo] already exists
        if "[tool.velo]" in existing_content:
            # Replace existing [tool.velo] section
            import re
            pattern = r'\[tool\.velo\][^\[]*'
            replacement = f"[tool.velo]\npreload = {json.dumps(modules)}\n"
            new_content = re.sub(pattern, replacement, existing_content)
        else:
            # Append new [tool.velo] section
            new_content = existing_content.rstrip() + f"\n\n[tool.velo]\npreload = {json.dumps(modules)}\n"
        
        with open(config_path, "w") as f:
            f.write(new_content)

    def run_benchmark(self, config_path: Path):
        """Run a single benchmark across all 4 levels."""
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
            preload_modules = test_cfg.get("preload_modules", [])
            timeout = test_cfg.get("timeout", 30)
            
            # --- Setup Phase ---
            venv_dir = pkg_dir / ".venv"
            if venv_dir.exists():
                shutil.rmtree(venv_dir)
            
            # 1. Install Project & Deps
            if self.run_command(["uv", "venv"], pkg_dir, 30).returncode != 0:
                raise RuntimeError("Failed to create venv")

            install_pkg = config.get("meta", {}).get("package", pkg_name)
            pkgs = install_pkg.split()
            install_cmd = ["uv", "pip", "install"] + pkgs
            if self.run_command(install_cmd, pkg_dir, 120).returncode != 0:
                raise RuntimeError("Install failed")
                
            # 2. Env Prep for Advanced Modes
            self.ensure_builder_deps(pkg_dir)
            
            # Resolve Entry Points
            local_script = pkg_dir / entry_point
            venv_bin_script = venv_dir / "bin" / entry_point
            
            target_path = None
            is_python_script = False
            
            if local_script.exists():
                target_path = local_script
                is_python_script = local_script.suffix == ".py"
            elif venv_bin_script.exists():
                target_path = venv_bin_script
                is_python_script = True 
            else:
                 raise FileNotFoundError(f"Entry point {entry_point} not found")
            
            args = test_cfg.get("args", [])
            python_bin = venv_dir / "bin" / "python"
            
            # --- Measurement Matrix ---
            results = {
                "package": pkg_name,
                "category": category,
                "L1_cpython": 0.0,
                "L2_velo_zero": 0.0,
                "L3_bundle": 0.0,
                "L4_instant": 0.0,
                "status": "PASS"
            }
            
            # Command Construction Helpers
            def get_cmd(mode: str):
                if not is_python_script: return None
                
                # Base args
                velo_args = ["--"] + args if args else []
                script_args = args if args else []
                
                if mode == "cpython":
                    if local_script.exists(): return [str(python_bin), str(target_path)] + script_args
                    else: return [str(target_path)] + script_args
                
                elif mode == "velo_zero":
                    return [str(VELO_BIN), "run", "--zygote", str(target_path)] + velo_args
                elif mode == "velo_bundle":
                    return [str(VELO_BIN), "run", "--zygote", "--fast", str(target_path)] + velo_args
                elif mode == "velo_instant":
                    return [str(VELO_BIN), "run", "--zygote", "--fast", str(target_path)] + velo_args
                return None

            # === L1: CPython (Baseline) ===
            cmd = get_cmd("cpython")
            if not cmd:
                raise RuntimeError("Non-python benchmarks not supported in multi-level runner yet")

            l1_times = self.measure(cmd, pkg_dir, timeout, runs=3, warmup_runs=1, drop_cache=self.drop_cache)
            results["L1_cpython"] = statistics.mean(l1_times)
            
            # Verify Output (L1 is the truth)
            verify_proc = self.run_command(cmd, pkg_dir, timeout)
            output = verify_proc.stdout + verify_proc.stderr
            if not re.search(expected_regex, output, re.MULTILINE):
                 logger.error(f"L1 Verification Failed. Output:\n{output}")
                 raise RuntimeError(f"Output regex mismatch in L1")

            # === L2: Velo Zero (Zygote Only) ===
            # Ensure no bundle, no preload config
            for b in pkg_dir.glob("*.veloc"): b.unlink()
            if (pkg_dir / "pyproject.toml").exists(): (pkg_dir / "pyproject.toml").unlink()
            
            subprocess.run([str(VELO_BIN), "zygote", "stop"], capture_output=True)
            l2_times = self.measure(get_cmd("velo_zero"), pkg_dir, timeout, runs=3, warmup_runs=1, drop_cache=self.drop_cache)
            results["L2_velo_zero"] = statistics.mean(l2_times)

            # === L3: Velo Bundle (Zygote + Bundle) ===
            self.build_bundle(pkg_dir)
            subprocess.run([str(VELO_BIN), "zygote", "stop"], capture_output=True)
            l3_times = self.measure(get_cmd("velo_bundle"), pkg_dir, timeout, runs=3, warmup_runs=1, drop_cache=self.drop_cache)
            results["L3_bundle"] = statistics.mean(l3_times)

            # === L4: Instant (Zygote + Bundle + Preload) ===
            if preload_modules:
                self.inject_preload(pkg_dir, preload_modules)
                subprocess.run([str(VELO_BIN), "zygote", "stop"], capture_output=True)
                
                # Warmup crucial for Preload to take effect in Zygote
                # The first run might be slow as Zygote initializes.
                # We'll use 2 warmup runs to ensure stability.
                l4_times = self.measure(get_cmd("velo_instant"), pkg_dir, timeout, runs=3, warmup_runs=2, drop_cache=self.drop_cache)
                results["L4_instant"] = statistics.mean(l4_times)
            else:
                l4_times = l3_times
                results["L4_instant"] = results["L3_bundle"]
            
            self.results.append(results)
            self.success_count += 1
            
            # Logging
            l1, l2 = results["L1_cpython"], results["L2_velo_zero"]
            l3, l4 = results["L3_bundle"], results["L4_instant"]
            
            logger.info(f"   ✅ PASS | L1: {l1:.1f}ms | L2: {l2:.1f}ms (x{l1/l2:.1f}) | L3: {l3:.1f}ms | L4: {l4:.1f}ms (x{l1/l4:.1f} 🚀)")

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
                if (pkg_dir / ".venv").exists(): shutil.rmtree(pkg_dir / ".venv")
                if (pkg_dir / ".velo_cache").exists(): shutil.rmtree(pkg_dir / ".velo_cache")
                if (pkg_dir / "pyproject.toml").exists(): (pkg_dir / "pyproject.toml").unlink()
                for b in pkg_dir.glob("*.veloc"): b.unlink()

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
    parser.add_argument("--package", type=str, action="append", help="Run specific package")
    parser.add_argument("--runs", type=int, default=3, help="Number of runs per level")
    parser.add_argument("--drop-cache", action="store_true", help="Drop OS page cache before L1 runs")
    args = parser.parse_args()
    
    if not VELO_BIN.exists():
        sys.exit(f"❌ Velo binary not found at {VELO_BIN}. Build it first!")

    runner = BenchmarkRunner(limit=args.limit, keep_env=args.keep_env, target_pkg=args.package, runs=args.runs, drop_cache=args.drop_cache)
    configs = runner.discover()
    
    logger.info(f"Found {len(configs)} benchmarks.")
    
    for cfg in configs:
        runner.run_benchmark(cfg)
    
    runner.save_report()

if __name__ == "__main__":
    main()
