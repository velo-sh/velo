#!/usr/bin/env python3
"""
Velo Top 100 Baseline Benchmark

Runs "Hello World" (import test) for the top 100 most-downloaded PyPI packages.
Implements RFC-0012 requirements:
- Isolated uv environments per package
- 30-second timeout per test
- IMPORT_SUCCESS marker verification
- Auto-cleanup of .venv directories
- Results persisted to benchmarks/top100_baseline.json
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Constants
VELO_BIN = Path(__file__).parent.parent / "target/release/velo"
ROOT_DIR = Path(__file__).parent.parent
BENCHMARKS_DIR = ROOT_DIR / "benchmarks"
TOP100_DIR = BENCHMARKS_DIR / "top100"
LIST_FILE = BENCHMARKS_DIR / "top100_list.json"
RESULTS_FILE = BENCHMARKS_DIR / "top100_baseline.json"
FAILURES_LOG = BENCHMARKS_DIR / "top100_failures.log"

TIMEOUT_SECS = 30
ITERATIONS = 3


class PackageBenchmark:
    """Manages benchmarking for a single package."""
    
    def __init__(self, package_name: str, keep_env: bool = False):
        self.package_name = package_name
        self.keep_env = keep_env
        self.project_dir = TOP100_DIR / package_name
        self.test_script = self.project_dir / "hello.py"
        
    def setup(self) -> bool:
        """Create isolated environment for this package."""
        try:
            if self.project_dir.exists():
                shutil.rmtree(self.project_dir)
            
            self.project_dir.mkdir(parents=True, exist_ok=True)
            
            # Initialize uv project
            subprocess.run(
                ["uv", "init", "--no-workspace", "--name", f"test-{self.package_name}"],
                cwd=self.project_dir,
                capture_output=True,
                check=True,
                timeout=30
            )
            
            # Pin Python version
            (self.project_dir / ".python-version").write_text("3.11\n")
            
            # Add the package
            result = subprocess.run(
                ["uv", "add", self.package_name],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode != 0:
                self._log_failure(f"Installation failed: {result.stderr}")
                return False
            
            # Create test script
            # Normalize package name for import (e.g., typing-extensions -> typing_extensions)
            import_name = self.package_name.replace("-", "_")
            self.test_script.write_text(
                f'import {import_name}\n'
                f'print("IMPORT_SUCCESS")\n'
            )
            
            # Symlink velo_zygote
            zygote_src = ROOT_DIR / "velo_zygote"
            zygote_link = self.project_dir / "velo_zygote"
            if zygote_src.exists() and not zygote_link.exists():
                zygote_link.symlink_to(zygote_src)
            
            return True
            
        except Exception as e:
            self._log_failure(f"Setup error: {e}")
            return False
    
    def run_test(self, mode: str) -> Optional[float]:
        """
        Run test in specified mode.
        
        Args:
            mode: "cpython", "velo_cold", or "velo_zygote"
        
        Returns:
            Execution time in milliseconds, or None if failed
        """
        try:
            if mode == "cpython":
                cmd = [str(self.project_dir / ".venv/bin/python"), str(self.test_script)]
            elif mode == "velo_cold":
                # Clear cache first
                cache_dir = self.project_dir / ".velo_cache"
                if cache_dir.exists():
                    shutil.rmtree(cache_dir)
                cmd = [str(VELO_BIN), "run", str(self.test_script)]
            elif mode == "velo_zygote":
                cmd = [str(VELO_BIN), "run", "--zygote", str(self.test_script)]
            else:
                raise ValueError(f"Unknown mode: {mode}")
            
            start = time.perf_counter()
            result = subprocess.run(
                cmd,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECS
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            
            # Verify success
            if result.returncode != 0:
                self._log_failure(f"{mode} failed with exit code {result.returncode}: {result.stderr}")
                return None
            
            if "IMPORT_SUCCESS" not in result.stdout:
                self._log_failure(f"{mode} missing IMPORT_SUCCESS marker")
                return None
            
            return elapsed_ms
            
        except subprocess.TimeoutExpired:
            self._log_failure(f"{mode} timeout after {TIMEOUT_SECS}s")
            return None
        except Exception as e:
            self._log_failure(f"{mode} error: {e}")
            return None
    
    def benchmark(self) -> Optional[Dict]:
        """Run full benchmark suite."""
        results = {
            "package": self.package_name,
            "cpython_ms": [],
            "velo_cold_ms": [],
            "velo_zygote_ms": [],
            "status": "success"
        }
        
        # Warmup for Zygote
        if self.run_test("velo_zygote") is None:
            results["status"] = "warmup_failed"
            return results
        
        for i in range(ITERATIONS):
            # CPython
            cpython_time = self.run_test("cpython")
            if cpython_time is None:
                results["status"] = "cpython_failed"
                break
            results["cpython_ms"].append(cpython_time)
            
            # Velo Cold
            velo_cold_time = self.run_test("velo_cold")
            if velo_cold_time is None:
                results["status"] = "velo_cold_failed"
                break
            results["velo_cold_ms"].append(velo_cold_time)
            
            # Velo Zygote
            zygote_time = self.run_test("velo_zygote")
            if zygote_time is None:
                results["status"] = "velo_zygote_failed"
                break
            results["velo_zygote_ms"].append(zygote_time)
        
        return results
    
    def cleanup(self):
        """Remove project directory."""
        if not self.keep_env and self.project_dir.exists():
            shutil.rmtree(self.project_dir)
    
    def _log_failure(self, message: str):
        """Log failure to failures log."""
        with open(FAILURES_LOG, "a") as f:
            f.write(f"[{self.package_name}] {message}\n")


def load_package_list() -> List[str]:
    """Load package list from JSON file."""
    if not LIST_FILE.exists():
        print(f"❌ Package list not found at {LIST_FILE}")
        print(f"   Run: python3 scripts/refresh_top100.py")
        sys.exit(1)
    
    with open(LIST_FILE) as f:
        data = json.load(f)
    return data["packages"]


def calculate_stats(times: List[float]) -> Dict:
    """Calculate statistics from timing data."""
    if not times:
        return {"mean": 0, "min": 0, "max": 0}
    
    import statistics
    return {
        "mean": statistics.mean(times),
        "min": min(times),
        "max": max(times),
        "stdev": statistics.stdev(times) if len(times) > 1 else 0
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark top 100 Python packages with Velo")
    parser.add_argument("--limit", type=int, default=100, help="Number of packages to test")
    parser.add_argument("--keep-envs", action="store_true", help="Keep .venv directories after test")
    parser.add_argument("--package", type=str, help="Test single package only")
    args = parser.parse_args()
    
    # Verify Velo binary exists
    if not VELO_BIN.exists():
        print(f"❌ Velo binary not found at {VELO_BIN}")
        print(f"   Build it first: cargo build --release")
        sys.exit(1)
    
    # Setup directories
    BENCHMARKS_DIR.mkdir(exist_ok=True)
    TOP100_DIR.mkdir(exist_ok=True)
    
    # Clear failures log
    if FAILURES_LOG.exists():
        FAILURES_LOG.unlink()
    
    # Load package list
    if args.package:
        packages = [args.package]
    else:
        packages = load_package_list()[:args.limit]
    
    print(f"🚀 Starting benchmark for {len(packages)} packages")
    print(f"   Timeout: {TIMEOUT_SECS}s per test")
    print(f"   Iterations: {ITERATIONS}")
    print()
    
    all_results = []
    success_count = 0
    
    for idx, pkg in enumerate(packages, 1):
        print(f"[{idx}/{len(packages)}] {pkg}...", end=" ", flush=True)
        
        bench = PackageBenchmark(pkg, keep_env=args.keep_envs)
        
        if not bench.setup():
            print("❌ Setup failed")
            continue
        
        result = bench.benchmark()
        bench.cleanup()
        
        if result and result["status"] == "success":
            stats = {
                "cpython": calculate_stats(result["cpython_ms"]),
                "velo_zygote": calculate_stats(result["velo_zygote_ms"])
            }
            speedup = stats["cpython"]["mean"] / stats["velo_zygote"]["mean"] if stats["velo_zygote"]["mean"] > 0 else 0
            
            print(f"✅ {stats['cpython']['mean']:.0f}ms → {stats['velo_zygote']['mean']:.0f}ms ({speedup:.1f}x)")
            success_count += 1
        else:
            print(f"❌ {result['status'] if result else 'unknown'}")
        
        all_results.append(result)
    
    # Save results
    output_data = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_packages": len(packages),
        "success_count": success_count,
        "pass_rate": success_count / len(packages) * 100,
        "results": all_results
    }
    
    with open(RESULTS_FILE, "w") as f:
        json.dump(output_data, f, indent=2)
    
    print()
    print(f"📊 Results: {success_count}/{len(packages)} passed ({output_data['pass_rate']:.1f}%)")
    print(f"   Saved to: {RESULTS_FILE}")
    
    if FAILURES_LOG.exists():
        print(f"   Failures: {FAILURES_LOG}")
    
    # Check against acceptance criteria (90% pass rate)
    if output_data["pass_rate"] < 90:
        print()
        print(f"⚠️  Warning: Pass rate below 90% threshold")
        sys.exit(1)


if __name__ == "__main__":
    main()
