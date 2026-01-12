#!/usr/bin/env python3
"""
Velo Top 100 Benchmark Runner (RFC-0013 v2)

Executes benchmarks defined in benchmarks/top100/<category>/<package>/benchmark.toml
"""


from __future__ import annotations
import argparse

import json
import logging
import platform
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Try to import velo.zygote components
# Assuming velo is in PYTHONPATH or installed
sys.path.append(str(Path(__file__).parent.parent.parent.parent / "velo_zygote"))

# Try to import tomllib (Python 3.11+) or tomli
try:
    import tomllib as toml
except ImportError:
    try:
        import tomli as toml
    except ImportError:
        sys.exit(
            "Error: 'tomllib' (Python 3.11+) or 'tomli' is required. Please install it."
        )

# Constants
ROOT_DIR = Path(__file__).parent.parent.parent.parent
BENCHMARKS_DIR = ROOT_DIR / "benchmarks" / "top100"
SHARED_VENV_DIR = (BENCHMARKS_DIR / ".shared_venv").resolve()
RESULTS_FILE = BENCHMARKS_DIR / "top100_v2_results.json"
VELO_BIN = (ROOT_DIR / "target/release/velo").resolve()

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("runner")


class BenchmarkRunner:
    def __init__(
        self,
        limit: int | None = None,
        keep_env: bool = False,
        target_pkg: str | None = None,
        runs: int = 3,
        drop_cache: bool = False,
        use_zygote: bool = False,
    ):
        self.limit = limit
        self.keep_env = keep_env
        self.target_pkg = (
            [target_pkg] if isinstance(target_pkg, str) else (target_pkg or [])
        )
        self.runs = runs
        self.drop_cache = drop_cache
        self.use_zygote = use_zygote
        self.fleet_mode = False
        self.zygote_process = None
        self.env = os.environ.copy()

        if self.use_zygote:
            if platform.system() not in ["Linux", "Darwin"]:
                logger.error("❌ Zygote mode is only supported on Linux/macOS.")
                sys.exit(1)

        self.results = []
        self.success_count = 0
        self.fail_count = 0

        # logger.info("✅ BenchmarkRunner Initialized.")

    def _ensure_zygote_running(self):
        """Initial bootstrap (optional, as run_benchmark restarts it)."""
        self._start_zygote(["json", "os", "sys"])

    def _start_zygote(self, preload_modules: list[str] | None = None):
        """Explicitly start the Master Zygote."""
        if not VELO_BIN.exists():
            logger.error(f"❌ Velo binary not found at {VELO_BIN}. Build it first!")
            sys.exit(1)

        # Determine environment
        if SHARED_VENV_DIR.exists():
            self.env["VIRTUAL_ENV"] = str(SHARED_VENV_DIR.resolve())
            raw_python = (SHARED_VENV_DIR / "bin" / "python").resolve()
            self.env["VELO_PYTHON"] = str(raw_python)
            self.env["PYTHONPATH"] = (
                str(ROOT_DIR.resolve()) + ":" + self.env.get("PYTHONPATH", "")
            )
            self.env["PATH"] = (
                str((SHARED_VENV_DIR / "bin").resolve())
                + os.pathsep
                + self.env.get("PATH", "")
            )

            # macOS Fork Safety & Compatibility (RFC-0014 Fix)
            # macOS Fork Safety & Compatibility (RFC-0014 Fix)
            self.env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
            self.mpl_cache_dir = tempfile.mkdtemp(prefix="velo_mpl_")
            self.env["MPLCONFIGDIR"] = self.mpl_cache_dir

        cmd = [str(VELO_BIN), "zygote", "start"]
        if preload_modules:
            cmd.extend(["--preload", ",".join(preload_modules)])

        self.zygote_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            cwd=BENCHMARKS_DIR,
        )

        # ✅ Poll until Zygote is fully ready (IPC handshake, not just socket exists)
        if not self._wait_for_zygote_ready(timeout=60):
            if self.zygote_process.poll() is not None:
                out, err = self.zygote_process.communicate()
                logger.error(
                    f"❌ Zygote exited early with code {self.zygote_process.returncode}"
                )
                logger.error(f"   Stdout: {out}")
                logger.error(f"   Stderr: {err}")
            raise RuntimeError("Zygote failed to become ready within 60s")

    def _wait_for_zygote_ready(self, timeout: int = 60) -> bool:
        """Poll until Zygote is fully initialized and preloading is complete."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                result = subprocess.run(
                    [str(VELO_BIN), "zygote", "status"],
                    capture_output=True,
                    timeout=2,
                    text=True,
                    env=self.env,
                    cwd=BENCHMARKS_DIR,
                )
                if result.returncode == 0:
                    stdout = result.stdout.lower()
                    if "running" in stdout and (
                        "preload: ready" in stdout or "preload: none" in stdout
                    ):
                        return True
                    if time.time() - start > 10:  # Only log if it's taking too long
                        logger.info(
                            f"   ⌛ Waiting for Zygote... Current Status: {stdout.strip()}"
                        )
                else:
                    if time.time() - start > 5:
                        logger.warning(
                            f"   ⚠️ Zygote status check failed (RC={result.returncode}): {result.stderr.strip()}"
                        )
            except subprocess.TimeoutExpired:
                pass
            time.sleep(0.2)
        return False

    def __del__(self):
        """Cleanup Zygote."""
        self._clean_zygote()

    def _clean_zygote(self):
        """Stop Zygote and ensure socket is removed to prevent Stale Socket detection."""
        # 1. Try polite stop via CLI
        subprocess.run([str(VELO_BIN), "zygote", "stop"], capture_output=True)

        # 2. Kill local process backing it if we own it
        if hasattr(self, "zygote_process") and self.zygote_process:
            if self.zygote_process.poll() is None:
                self.zygote_process.terminate()
                try:
                    self.zygote_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.zygote_process.kill()

        if (
            hasattr(self, "mpl_cache_dir")
            and self.mpl_cache_dir
            and os.path.exists(self.mpl_cache_dir)
        ):
            shutil.rmtree(self.mpl_cache_dir, ignore_errors=True)

    def discover(self) -> list[Path]:
        """Find all benchmark.toml files."""
        candidates = list(BENCHMARKS_DIR.glob("*/*/benchmark.toml"))
        # Sort by category then package
        candidates.sort(key=lambda p: (p.parent.parent.name, p.parent.name))
        if self.target_pkg:
            candidates = [p for p in candidates if p.parent.name in self.target_pkg]
        elif self.limit:
            candidates = candidates[: self.limit]

        return candidates

    def run_command(
        self, cmd: list[str], cwd: Path, timeout: int, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess:
        """Run a command with timeout."""
        return subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env
        )

    def measure(
        self,
        cmd: list[str],
        cwd: Path,
        timeout: int,
        runs: int = 3,
        warmup_runs: int = 0,
        drop_cache: bool = False,
        env: dict[str, str] | None = None,
    ) -> list[float]:
        """Measure execution time of a command."""
        times = []

        # Warmup (discard results)
        for _ in range(warmup_runs):
            try:
                subprocess.run(
                    cmd, cwd=cwd, capture_output=True, timeout=timeout, env=env
                )
            except subprocess.TimeoutExpired:
                pass

        # Measurement
        for i in range(runs):
            if drop_cache:
                print(f"      ❄️  Dropping Cache (Run {i+1})...", end="\r")
                subprocess.run(
                    [
                        sys.executable,
                        str(ROOT_DIR / "benchmarks/top100/_runner/drop_cache.py"),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            # 🔍 DEBUG: Log exact command being executed
            logger.info(f"      CMD: {' '.join(cmd)}")
            start = time.perf_counter()

            try:
                env_size = sum(len(k) + len(v) for k, v in env.items()) if env else 0
                logger.info(f"      ENV SIZE: {env_size} chars")
                proc = self.run_command(cmd, cwd, timeout, env=env)
                duration = (time.perf_counter() - start) * 1000

                # 🔍 DEBUG: Log individual run times to diagnose cold starts
                logger.info(f"      Run {i+1}/{runs}: {duration:.1f}ms")

                if proc.returncode != 0:
                    raise RuntimeError(
                        f"Exit code {proc.returncode} | STDERR: {proc.stderr} | STDOUT: {proc.stdout}"
                    )

                times.append(duration)
            except subprocess.TimeoutExpired:
                raise TimeoutError(f"Timeout after {timeout}s")

        return times

    def ensure_builder_deps(self, pkg_dir: Path):
        """Ensure bundle builder dependencies (blake3) are installed."""
        if (
            self.run_command(["uv", "pip", "install", "blake3"], pkg_dir, 60).returncode
            != 0
        ):
            # In Shared Mode without write access, this might fail.
            # We assume Shared Venv has blake3.
            # Just warn if fail.
            logger.warning(
                "Failed to install builder deps (blake3). Assuming present in environment."
            )

    def build_bundle(self, pkg_dir: Path):
        """Build .veloc bundle for the project."""
        builder_script = ROOT_DIR / "python" / "bundle_builder.py"
        if not builder_script.exists():
            raise FileNotFoundError("bundle_builder.py not found")

        venv_python = pkg_dir / ".venv" / "bin" / "python"
        if not venv_python.exists() and SHARED_VENV_DIR.exists():
            venv_python = SHARED_VENV_DIR / "bin" / "python"

        cmd = [str(venv_python), str(builder_script), str(pkg_dir)]
        proc = self.run_command(cmd, pkg_dir, 60)
        if proc.returncode != 0:
            raise RuntimeError(f"Bundle build failed: {proc.stderr}")

    def inject_preload(self, pkg_dir: Path, modules: list[str]):
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

            pattern = r"\[tool\.velo\][^\[]*"
            replacement = f"[tool.velo]\npreload = {json.dumps(modules)}\n"
            new_content = re.sub(pattern, replacement, existing_content)
        else:
            # Append new [tool.velo] section
            new_content = (
                existing_content.rstrip()
                + f"\n\n[tool.velo]\npreload = {json.dumps(modules)}\n"
            )

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
            using_shared_env = self.use_zygote and SHARED_VENV_DIR.exists()
            venv_dir = pkg_dir / ".venv"

            env = os.environ.copy()

            if using_shared_env:
                venv_dir = SHARED_VENV_DIR
                # Inherit all critical Zygote environment settings (RFC-0014 Fix)
                for k, v in self.env.items():
                    env[k] = v
            else:
                # Standard Mode: Clean and Recreate
                if venv_dir.exists():
                    shutil.rmtree(venv_dir)

            # logger.info(f"   Debug: Shared={using_shared_env}, VenvDir={venv_dir}")

            # 1. Install Project & Deps (Skip if Shared)
            install_pkg = config.get("meta", {}).get("package", pkg_name)

            if not using_shared_env:
                if self.run_command(["uv", "venv"], pkg_dir, 30).returncode != 0:
                    raise RuntimeError("Failed to create venv")

                pkgs = install_pkg.split()
                install_cmd = ["uv", "pip", "install"] + pkgs
                if self.run_command(install_cmd, pkg_dir, 120).returncode != 0:
                    raise RuntimeError("Install failed")
            else:
                pass  # Already installed in shared venv

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
                "status": "PASS",
            }

            # Command Construction Helpers
            def get_cmd(mode: str):
                if not is_python_script:
                    return None

                # Base args
                velo_args = ["--"] + args if args else []
                script_args = args if args else []

                if mode == "cpython":
                    if local_script.exists():
                        return [str(python_bin), str(target_path)] + script_args
                    else:
                        return [str(target_path)] + script_args

                elif mode == "velo_zero":
                    if self.use_zygote:
                        return [
                            str(VELO_BIN),
                            "run",
                            "--zygote",
                            str(target_path),
                        ] + velo_args
                    else:
                        return [str(VELO_BIN), "run", str(target_path)] + velo_args
                elif mode == "velo_bundle":
                    return [
                        str(VELO_BIN),
                        "run",
                        "--zygote",
                        "--fast",
                        str(target_path),
                    ] + velo_args
                elif mode == "velo_instant":
                    return [
                        str(VELO_BIN),
                        "run",
                        "--zygote",
                        "--fast",
                        str(target_path),
                    ] + velo_args
                return None

            # === Execution Matrix ===
            if self.fleet_mode:
                # Use current warm Zygote, only measure L4
                l4_times = self.measure(
                    get_cmd("velo_instant"),
                    pkg_dir,
                    timeout,
                    runs=self.runs,
                    warmup_runs=2,
                    env=env,
                )
                results["L4_instant"] = statistics.mean(l4_times)
                results["status"] = "PASS (FLEET)"
            else:
                # === L1: CPython (Baseline) ===
                l1_times = self.measure(
                    get_cmd("cpython"),
                    pkg_dir,
                    timeout,
                    runs=self.runs,
                    warmup_runs=1,
                    drop_cache=self.drop_cache,
                    env=env,
                )
                results["L1_cpython"] = statistics.mean(l1_times)

                # === L2: Velo Zero (Zygote Only) ===
                self._clean_zygote()
                self._start_zygote([])
                l2_times = self.measure(
                    get_cmd("velo_zero"),
                    pkg_dir,
                    timeout,
                    runs=self.runs,
                    warmup_runs=1,
                    env=env,
                )
                results["L2_velo_zero"] = statistics.mean(l2_times)

                # === L3: Velo Bundle ===
                self.build_bundle(pkg_dir)
                l3_times = self.measure(
                    get_cmd("velo_bundle"),
                    pkg_dir,
                    timeout,
                    runs=self.runs,
                    warmup_runs=1,
                    env=env,
                )
                results["L3_bundle"] = statistics.mean(l3_times)

                # === L4: Instant ===
                if preload_modules:
                    self.inject_preload(pkg_dir, preload_modules)
                    self._clean_zygote()
                    self._start_zygote(preload_modules)
                    l4_times = self.measure(
                        get_cmd("velo_instant"),
                        pkg_dir,
                        timeout,
                        runs=self.runs,
                        warmup_runs=5,
                        env=env,
                    )
                    results["L4_instant"] = statistics.mean(l4_times)
                else:
                    results["L4_instant"] = results["L3_bundle"]

            self.results.append(results)
            self.success_count += 1

            # Logging
            l1, l2 = results["L1_cpython"], results["L2_velo_zero"]
            l3, l4 = results["L3_bundle"], results["L4_instant"]

            def safe_div(a, b):
                return a / b if b > 0 else 0.0

            if self.fleet_mode:
                logger.info(f"   ✅ PASS | L4 (Fleet): {l4:.1f}ms 🚀")
            else:
                logger.info(
                    f"   ✅ PASS | L1: {l1:.1f}ms | L2: {l2:.1f}ms (x{safe_div(l1,l2):.1f}) | L3: {l3:.1f}ms | L4: {l4:.1f}ms (x{safe_div(l1,l4):.1f} 🚀)"
                )

        except Exception as e:
            logger.error(f"   ❌ FAIL: {e}")
            self.results.append(
                {
                    "package": pkg_name,
                    "category": category,
                    "status": "FAIL",
                    "error": str(e),
                }
            )
            self.fail_count += 1
        finally:
            if not self.keep_env:
                # IMPORTANT: Never delete Shared Venv
                if not (self.use_zygote and SHARED_VENV_DIR.exists()):
                    if (pkg_dir / ".venv").exists():
                        shutil.rmtree(pkg_dir / ".venv")

                if (pkg_dir / ".velo_cache").exists():
                    shutil.rmtree(pkg_dir / ".velo_cache")
                if (pkg_dir / "pyproject.toml").exists():
                    (pkg_dir / "pyproject.toml").unlink()
                for b in pkg_dir.glob("*.veloc"):
                    b.unlink()

    def save_report(self):
        """Save results to JSON."""
        sys_info = {
            "os": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        report = {
            "system": sys_info,
            "summary": {
                "total": self.success_count + self.fail_count,
                "passed": self.success_count,
                "failed": self.fail_count,
            },
            "results": self.results,
        }

        with open(RESULTS_FILE, "w") as f:
            json.dump(report, f, indent=2)

        logger.info(f"\n📊 Report saved to {RESULTS_FILE}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Limit number of benchmarks")
    parser.add_argument("--keep-env", action="store_true", help="Don't clean venvs")
    parser.add_argument(
        "--package", type=str, action="append", help="Run specific package"
    )
    parser.add_argument("--runs", type=int, default=3, help="Number of runs per level")
    parser.add_argument(
        "--drop-cache", action="store_true", help="Drop OS page cache before L1 runs"
    )
    parser.add_argument(
        "--use-zygote", action="store_true", help="Use Zygote for acceleration"
    )
    parser.add_argument(
        "--fleet", action="store_true", help="Run in Fleet Mode (one Zygote for all)"
    )
    args = parser.parse_args()

    if not VELO_BIN.exists():
        sys.exit(f"❌ Velo binary not found at {VELO_BIN}. Build it first!")

    runner = BenchmarkRunner(
        limit=args.limit,
        keep_env=args.keep_env,
        target_pkg=args.package,
        runs=args.runs,
        drop_cache=args.drop_cache,
        use_zygote=args.use_zygote,
    )
    configs = runner.discover()
    logger.info(f"Found {len(configs)} benchmarks.")

    if getattr(args, "fleet", False):
        runner.fleet_mode = True
        # Preload the most common heavy lifters for the whole fleet
        # RFC-0014: On macOS, preloading anything beyond core modules risk objc-fork-safety crashes.
        # We use a minimal set on Darwin and a broader set on Linux.
        if platform.system() == "Darwin":
            mega_preload = ["json", "os", "sys"]
        else:
            mega_preload = [
                "json",
                "os",
                "sys",
                "requests",
                "urllib3",
                "pydantic",
                "aiohttp",
                "numpy",
            ]
        logger.info(
            f"🚀 Starting Mega-Zygote Fleet (Preload: {len(mega_preload)} modules)..."
        )
        runner._clean_zygote()
        runner._start_zygote(mega_preload)
        logger.info("✅ Fleet Zygote Warm.")
    elif args.use_zygote:
        # Standard Zygote start for non-fleet mode
        runner._start_zygote(["json", "os", "sys"])
        logger.info("✅ Master Zygote Ready.")

    for cfg in configs:
        runner.run_benchmark(cfg)

    runner.save_report()


if __name__ == "__main__":
    main()
