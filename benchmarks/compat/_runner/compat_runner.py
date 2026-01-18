#!/usr/bin/env python3
"""
Velo Compatibility Test Runner

Runs package test suites under both CPython and Velo Zygote to verify runtime compatibility.
Part of RFC-0013 Top 100 Baseline infrastructure.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# Try to import tomllib (Python 3.11+) or tomli
try:
    import tomllib as toml
except ImportError:
    try:
        import tomli as toml
    except ImportError:
        sys.exit("Error: 'tomllib' (Python 3.11+) or 'tomli' is required.")

# Constants
ROOT_DIR = Path(__file__).parent.parent.parent.parent
BENCHMARKS_DIR = ROOT_DIR / "benchmarks" / "compat"
SHARED_VENV_DIR = (BENCHMARKS_DIR / ".shared_venv").resolve()
COMPAT_RESULTS_FILE = BENCHMARKS_DIR / "compat_results.json"
COMPAT_REPORT_FILE = BENCHMARKS_DIR / "COMPAT_REPORT.md"
VELO_BIN_ENV = os.environ.get("VELO_BIN")
if VELO_BIN_ENV:
    VELO_BIN = Path(VELO_BIN_ENV).resolve()
else:
    VELO_BIN = (ROOT_DIR / "target/release/velo").resolve()

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("compat_runner")


@dataclass
class TestResult:
    """Result of a single test run."""
    package: str
    category: str
    tier: int
    runtime: str  # "cpython" or "velo"
    exit_code: int
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_sec: float = 0.0
    error_message: str = ""
    report: dict[str, Any] = field(default_factory=dict)
    
    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped + self.errors
    
    @property
    def status(self) -> str:
        if self.exit_code == 0:
            return "PASS"
        elif self.exit_code == -1:
            return "TIMEOUT"
        elif self.exit_code == -2:
            return "SKIP"
        else:
            return "FAIL"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dict, excluding potentially large report data for basic results."""
        d = asdict(self)
        if "report" in d:
             # Keep only summary in basic dict to avoid massive JSON files
             summary = d["report"].get("summary", {})
             d["report_summary"] = summary
             del d["report"]
        return d


@dataclass
class CompatResult:
    """Comparison result between CPython and Velo."""
    package: str
    category: str
    tier: int
    cpython: TestResult
    velo: TestResult
    new_failures: int = 0  # Tests that pass in CPython but fail in Velo
    verdict: str = "UNKNOWN"
    known_failures: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "package": self.package,
            "category": self.category,
            "tier": self.tier,
            "verdict": self.verdict,
            "new_failures": self.new_failures,
            "cpython": self.cpython.to_dict(),
            "velo": self.velo.to_dict(),
        }
    
    def compute_verdict(self) -> None:
        """Determine compatibility verdict."""
        if self.cpython.status == "SKIP" or self.velo.status == "SKIP":
            self.verdict = "SKIP"
            return
        if self.cpython.status == "TIMEOUT" or self.velo.status == "TIMEOUT":
            self.verdict = "TIMEOUT"
            return
            
        # [NEW] Handle known failures masking
        # We look at the actual nodeids in the Velo report
        v_failed_nodes = set()
        if self.velo.report and "tests" in self.velo.report:
            for t in self.velo.report["tests"]:
                if t["outcome"] == "failed":
                    v_failed_nodes.add(t["nodeid"])
        
        # Calculate real regressions (failures not in CPython and not in known_failures)
        cp_failed_nodes = set()
        if self.cpython.report and "tests" in self.cpython.report:
            for t in self.cpython.report["tests"]:
                if t["outcome"] == "failed":
                    cp_failed_nodes.add(t["nodeid"])
        
        real_regressions = []
        for node in v_failed_nodes:
            if node in cp_failed_nodes:
                continue # Both failed, compatible
            
            # Mask if it's a known failure (by substring or full match)
            is_known = False
            for kf in self.known_failures:
                if kf in node:
                    is_known = True
                    break
            
            if not is_known:
                real_regressions.append(node)
        
        if len(real_regressions) > 0:
            self.new_failures = len(real_regressions)
            self.verdict = "REGRESSION"
        elif self.cpython.total == 0 or self.velo.total == 0:
            # If nothing was collected by either, it's a discovery failure, not compatibility
            self.verdict = "DISCOVERY_FAILED"
        elif self.velo.status == "PASS" and self.cpython.status == "PASS":
            self.verdict = "COMPATIBLE"
        elif len(real_regressions) == 0:
            self.verdict = "COMPATIBLE"
        else:
            self.verdict = "UNKNOWN"


class CompatRunner:
    """Compatibility test runner."""
    
    def __init__(
        self,
        tier: int = 1,
        parallel: int = 1,
        target_pkg: str | None = None,
        timeout: int = 600,
        report_name: str | None = None,
        tier_only: bool = False,
        category: str | None = None,
    ):
        self.tier = tier
        self.tier_only = tier_only
        self.parallel = parallel
        self.target_pkg = target_pkg
        self.target_category = category
        self.default_timeout = timeout
        self.report_name = report_name
        self.results: list[CompatResult] = []
        self.env = os.environ.copy()
        
        # Setup shared environment
        if SHARED_VENV_DIR.exists():
            self.env["VIRTUAL_ENV"] = str(SHARED_VENV_DIR)
            self.env["VELO_PYTHON"] = str(SHARED_VENV_DIR / "bin" / "python")
            
            # [CRITICAL] Scrub host PYTHONPATH to prevent leakage into Zygote
            # We want a pure environment containing only shared venv and project
            host_venv_marker = f"{ROOT_DIR}/.venv"
            pythonpath = os.environ.get("PYTHONPATH", "")
            clean_pp = []
            for p in pythonpath.split(os.pathsep):
                if p and host_venv_marker not in os.path.abspath(p):
                    clean_pp.append(p)
            self.env["PYTHONPATH"] = os.pathsep.join(clean_pp)
            
            # Clean PATH as well
            path = os.environ.get("PATH", "")
            clean_path = [str(SHARED_VENV_DIR / "bin")]
            for p in path.split(os.pathsep):
                if p and host_venv_marker not in os.path.abspath(p):
                    clean_path.append(p)
            self.env["PATH"] = os.pathsep.join(clean_path)

            # Force Velo to trust the shared venv and workspace
            self.env["VELO_SECURITY_TRUSTED_PREFIXES"] = f"/usr,/bin,/sbin,/lib,/private/var/folders,{ROOT_DIR},{os.environ.get('HOME', '')}"
            self.env["VELO_TEST_MODE"] = "1"
            # macOS fork safety
            self.env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

    
    def discover(self) -> list[Path]:
        """Find all compat.toml files."""
        candidates = list(BENCHMARKS_DIR.glob("*/*/compat.toml"))
        candidates.sort(key=lambda p: (p.parent.parent.name, p.parent.name))
        
        if self.target_pkg:
            target_pkgs = [p.strip() for p in self.target_pkg.split(",")]
            candidates = [p for p in candidates if p.parent.name in target_pkgs]
        
        if self.target_category:
            candidates = [p for p in candidates if p.parent.parent.name == self.target_category]
        
        # Filter by tier (only if not specific package targeted)
        if not self.target_pkg:
            # Filter by tier
            filtered = []
            for c in candidates:
                try:
                    with open(c, "rb") as f:
                        config = toml.load(f)
                    pkg_tier = config.get("meta", {}).get("tier", 3)
                    if self.tier_only:
                        if pkg_tier == self.tier:
                            filtered.append(c)
                    elif pkg_tier <= self.tier:
                        filtered.append(c)
                except Exception:
                    continue
            candidates = filtered
        
        return candidates
    
    def _clone_repo(self, git_repo: str, git_ref: str, pkg_dir: Path, enable_submodules: bool = True) -> Path:
        """Clone a git repository for testing."""
        repo_dir = pkg_dir / ".test_repo"
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        
        logger.info(f"   📥 Cloning {git_repo}@{git_ref}...")
        # Use environment to prevent interactive prompts on macOS
        git_env = os.environ.copy()
        git_env["GIT_TERMINAL_PROMPT"] = "0"
        git_env["GIT_ASKPASS"] = "true"
        subprocess.check_call(
            ["git", "clone", "--depth", "1", "--branch", git_ref, git_repo, str(repo_dir)],
            cwd=pkg_dir,
            env=git_env,
        )
        
        # [FIX] Initialize submodules (required for httptools -> llhttp)
        if (repo_dir / ".gitmodules").exists() and enable_submodules:
            logger.info(f"   📥 Initializing submodules...")
            subprocess.run(
                ["git", "submodule", "update", "--init", "--recursive", "--depth", "1"],
                cwd=repo_dir,
                env=git_env,
                capture_output=True,
            )
        return repo_dir
    
    def _run_pytest(
        self,
        package: str,
        runtime: str,
        pytest_args: list[str],
        timeout: int,
        cwd: Path,
        source: str = "pyargs",
        test_path: str | None = None,
        run_cmd: list[str] | None = None,
        sys_path_strategy: str = "source",
    ) -> TestResult:
        """Run pytest and collect results."""
        result = TestResult(
            package=package,
            category="",
            tier=0,
            runtime=runtime,
            exit_code=0,
        )
        
        # Build command based on source type
        if source == "pyargs":
            base_args = ["--pyargs", package]
        elif source == "git" and test_path:
            # Run tests from cloned repo
            # [CRITICAL] Use absolute path to the specific test directory inside the repo
            target_dir = (cwd / test_path).resolve()
            base_args = [str(target_dir)]
        else:
            base_args = [str(cwd.resolve())]
        
        # Always use JSON report for parsing
        json_report = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        json_report.close()
        
        pytest_args_full = [
            *base_args,
            *pytest_args,
            f"--json-report",
            f"--json-report-file={json_report.name}",
        ]
        
        wrapper_script = None
        
        if run_cmd:
             # Custom entry point (e.g. Django runtests.py)
            logger.info(f"   🐛 Custom Command: {' '.join(run_cmd)}")
            
            if runtime == "cpython":
                cmd = list(run_cmd)  # e.g. ["python", "tests/runtests.py", ...]
            else:  # velo
                # Velo needs a wrapper script to execute custom commands with arguments
                # Strip 'python' prefix if present
                velo_cmd = list(run_cmd)
                if velo_cmd[0] == "python" or velo_cmd[0] == "python3":
                    velo_cmd = velo_cmd[1:]
                
                # Create wrapper script that executes the command
                wrapper_script = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", delete=False
                )
                
                # Prepare environment injection
                env_to_inject = getattr(self, "run_env", self.env)
                # Add extended timeout for large test suites
                env_to_inject['VELO_ZYGOTE_SOCKET_TIMEOUT'] = '600'  # 10 minutes
                env_json = json.dumps(env_to_inject)
                project_abs_path = cwd.resolve()
                
                # Build the command to execute
                cmd_str = json.dumps(velo_cmd)
                
                wrapper_script.write(f"""import sys
import os
import json
import subprocess

# Inject environment variables
env_to_inject = {env_json}
os.environ.update(env_to_inject)

# Change to project directory
os.chdir("{project_abs_path}")

# Execute the custom command
cmd = {cmd_str}
sys.exit(subprocess.call(cmd))
""")
                wrapper_script.close()
                cmd = [str(VELO_BIN), "run", "--zygote", wrapper_script.name]
                
        elif runtime == "cpython":
            pytest_cmd = ["-m", "pytest", *pytest_args_full]
            cmd = [str(SHARED_VENV_DIR / "bin" / "python"), *pytest_cmd]
        else:  # velo
            # Velo run expects a script file, not -m pytest
            # Create a temporary wrapper script that embeds the arguments
            wrapper_script = tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            )
            # We pass args explicitly to pytest.main()
            args_str = json.dumps(pytest_args_full)
            site_pkgs = SHARED_VENV_DIR / "lib" / "python3.11" / "site-packages"
            project_abs_path = cwd.resolve()
            
            # Prepare environment variables for injection
            env_to_inject = getattr(self, "run_env", self.env)
            env_json = json.dumps(env_to_inject)
            
            # --- Path Strategy Logic ---
            if sys_path_strategy == "installed":
                # Prioritize site-packages (fixed cryptography case)
                path_logic = f"""
new_path = []
new_path.append(os.path.abspath(shared_site_pkgs))
src_dir = os.path.join(project_root, "src")
if os.path.exists(src_dir):
    new_path.append(os.path.abspath(src_dir))
new_path.append(os.path.abspath(project_root))
"""
            else:
                # Default: Prioritize source (fixed certifi case)
                path_logic = f"""
new_path = []
src_dir = os.path.join(project_root, "src")
if os.path.exists(src_dir):
    new_path.append(os.path.abspath(src_dir))
new_path.append(os.path.abspath(project_root))
new_path.append(os.path.abspath(shared_site_pkgs))
"""
            
            wrapper_script.write(f"""import sys
import os
import json

# --- ENVIRONMENT INJECTION ---
# Inject required environment variables before importing anything
# This is critical for Django settings discovery.
env_to_inject = {env_json}
os.environ.update(env_to_inject)

# --- ENVIRONMENT ISOLATION SHIELD ---
# Hardcoded project path to avoid CWD confusion in Zygote
project_root = "{project_abs_path}"
shared_site_pkgs = "{site_pkgs}"

{path_logic}

# 3. Add stdlib and other non-host-venv paths
host_venv_marker = "{ROOT_DIR}/.venv"
for p in sys.path:
    p_abs = os.path.abspath(p)
    # Scrub host venv site-packages (prioritizing shared venv)
    if host_venv_marker in p_abs and shared_site_pkgs not in p_abs:
        continue
    if p_abs not in new_path:
        new_path.append(p_abs)

sys.path = new_path

import pytest

if __name__ == "__main__":
    args = {args_str}
    
    # [CRITICAL] Ensure the worker is in the project root
    # Velo Zygote may be running in the Velo root, but tests expect the cloned repo.
    os.chdir(project_root)
    
    # Force pytest to use the current cloned repo as rootdir
    # to avoid discovery leakage into parent directories (Velo root).
    if "--rootdir" not in args:
        args.extend(["--rootdir", project_root])
    
        
    sys.exit(pytest.main(args))
""")
            wrapper_script.close()
            cmd = [str(VELO_BIN), "run", "--zygote", wrapper_script.name]
        
        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=getattr(self, "run_env", self.env),
            )
            result.exit_code = proc.returncode
            result.duration_sec = time.time() - start
            if runtime == "velo" and wrapper_script:
                try:
                    os.unlink(wrapper_script.name)
                except OSError:
                    pass
            
            if proc.returncode != 0:
                # Capture some output for debugging
                error_output = ""
                if proc.stdout:
                    error_output += f"\nSTDOUT:\n{proc.stdout[:1000]}"
                if proc.stderr:
                    error_output += f"\nSTDERR:\n{proc.stderr[:1000]}"
                result.error_message = error_output
            
            # Parse JSON report
            if Path(json_report.name).exists():
                try:
                    with open(json_report.name, "r") as f:
                        result.report = json.load(f)
                        summary = result.report.get("summary", {})
                        result.passed = summary.get("passed", 0)
                        result.failed = summary.get("failed", 0)
                        result.skipped = summary.get("skipped", 0)
                        result.errors = summary.get("error", 0)
                except Exception as e:
                    logger.warning(f"   ⚠️  Failed to parse JSON report: {e}")
                    error_output = f"JSON Parse Error: {e}"
                    if proc.stdout:
                        error_output += f"\nSTDOUT TAIL:\n{proc.stdout[-2000:]}"
                    if proc.stderr:
                        error_output += f"\nSTDERR TAIL:\n{proc.stderr[-2000:]}"
                    result.error_message = error_output
                finally:
                    try:
                        os.unlink(json_report.name)
                    except:
                        pass
            else:
                logger.warning(f"   ⚠️  JSON report not found: {json_report.name}")
                error_output = "JSON Report Not Found"
                if proc.stdout:
                    error_output += f"\nSTDOUT TAIL:\n{proc.stdout[-2000:]}"
                if proc.stderr:
                    error_output += f"\nSTDERR TAIL:\n{proc.stderr[-2000:]}"
                result.error_message = error_output
            
            if proc.returncode != 0 and result.total == 0:
                result.error_message = (proc.stdout or "") + (proc.stderr or "")
                result.error_message = result.error_message[:2000]
            
            # If we used a custom command and exited 0, but have no JSON report,
            # we count this as 1 pass (at package level)
            if run_cmd and result.total == 0:
                 if result.exit_code == 0:
                     result.passed = 1
                     result.status = "PASS"
                 else:
                     result.failed = 1
                
        except subprocess.TimeoutExpired:
            result.exit_code = -1
            result.duration_sec = timeout
            result.error_message = f"Timeout after {timeout}s"
        except Exception as e:
            result.exit_code = -2
            result.error_message = str(e)
        finally:
            Path(json_report.name).unlink(missing_ok=True)
        
        return result
    
    def run_compat_test(self, config_path: Path) -> CompatResult:
        """Run compatibility test for a single package."""
        pkg_dir = config_path.parent
        category = pkg_dir.parent.name
        pkg_name = pkg_dir.name
        
        logger.info(f"🔍 [{category}/{pkg_name}] Starting compatibility test...")
        
        try:
            with open(config_path, "rb") as f:
                config = toml.load(f)
            
            meta = config.get("meta", {})
            compat = config.get("compat", {})
            
            # Load environment variables from config if present
            run_env = self.env.copy()
            for k, v in compat.get("env", {}).items():
                run_env[k] = v
            
            # [CRITICAL] Map sys_path_strategy to VELO_ZYGOTE_PATH_STRATEGY
            sys_path_strategy = compat.get("sys_path_strategy")
            if sys_path_strategy:
                run_env["VELO_ZYGOTE_PATH_STRATEGY"] = sys_path_strategy
                logger.info(f"   🚩 Setting VELO_ZYGOTE_PATH_STRATEGY={sys_path_strategy}")
            
            # Setup runner with specific env
            self.run_env = run_env

            tier = meta.get("tier", 3)
            source = compat.get("source", "pyargs")
            git_repo = compat.get("git_repo", "")
            git_ref = compat.get("git_ref", "main")
            test_path = compat.get("test_path", "tests")
            
            pytest_args = compat.get("pytest_args", [])
            pytest_args = compat.get("pytest_args", [])
            timeout = compat.get("timeout", self.default_timeout)
            test_deps = compat.get("test_dependencies", [])
            run_cmd = compat.get("run_cmd") # optional list[str]
            
            # Handle git source - clone repo first
            test_cwd = pkg_dir
            actual_test_path = None
            pyproject_file = None
            pyproject_bak = None
            self.source_dir_orig = None
            self.source_dir_bak = None
            
            if source == "git" and git_repo:
                repo_dir = self._clone_repo(git_repo, git_ref, pkg_dir, compat.get("enable_submodules", True))
                
                # Determine CWD for running tests
                run_cwd_strategy = compat.get("run_cwd_strategy", "repo")
                if run_cwd_strategy == "parent":
                    test_cwd = repo_dir.parent
                else:
                    test_cwd = repo_dir
                actual_test_path = test_path
                
                # Install the cloned package into the shared venv
                # Standard install (not editable) ensures the package stays in site-packages
                # even if .test_repo is removed later.
                logger.info(f"   📦 Installing package {meta.get('package')} into shared venv...")
                subprocess.run(
                    ["uv", "pip", "install", "."],
                    cwd=repo_dir,
                    capture_output=True,
                    env=self.env,
                )
                
                # [FIX] Velo auto-detects pyproject.toml and tries to use uv --frozen.
                # This often fails in third-party repos. We hide it from Velo
                # but we'll try to let pytest use it if needed (though pytest 
                # usually finds it even if renamed via command line or if we are careful).
                pyproject_file = repo_dir / "pyproject.toml"
                if pyproject_file.exists():
                    pyproject_bak = repo_dir / "pyproject_velo_backup.toml"
                    pyproject_file.rename(pyproject_bak)
                    logger.info(f"   🙈 Hiding pyproject.toml from Velo (keeping as .toml for pytest)")
                
                # [FIX] Ensure no problematic backports shadow stdlib
                # These are often re-installed as transitive dependencies by 'uv pip install'
                # [CRITICAL] uv pip uninstall does NOT support -y. Removing it fix the silent failure.
                # [NOTE] Keeping 'six' because it's required by the 'case' plugin.
                subprocess.run(
                    [
                        "uv", "pip", "uninstall", 
                        "argparse", "ipaddress", "traceback2", "unittest2",
                        "--python", str(SHARED_VENV_DIR / "bin" / "python")
                    ],
                    env=self.env, capture_output=True, check=False
                )

                # [FIX] For 'installed' strategy, rename the local source folder
                # to prevent it from shadowing the installed version in site-packages,
                # which causes ModuleNotFoundError in subprocesses if versions differ.
                self.source_dir_orig = None
                self.source_dir_bak = None
                if sys_path_strategy == "installed":
                    source_dir_path = repo_dir / pkg_name
                    if source_dir_path.exists() and source_dir_path.is_dir():
                        self.source_dir_orig = source_dir_path
                        self.source_dir_bak = source_dir_path.parent / f"{source_dir_path.name}_hidden_by_runner"
                        source_dir_path.rename(self.source_dir_bak)
                        logger.info(f"   🙈 Hiding local source {pkg_name}/ to force use of installed version")
                        
                        # [FIX] If test_path was inside the hidden source dir, update it
                        if actual_test_path and (actual_test_path == pkg_name or actual_test_path.startswith(f"{pkg_name}/")):
                            old_path = actual_test_path
                            actual_test_path = actual_test_path.replace(pkg_name, f"{pkg_name}_hidden_by_runner", 1)
                            logger.info(f"   🧪 Adjusted test_path: {old_path} -> {actual_test_path}")

            # [FIX] Isolated Zygote Socket for Parallel Safety
            # Give each worker a unique socket and PID file to avoid stomping
            import os
            worker_id = os.getpid() # For serial
            if self.parallel > 1:
                from threading import current_thread
                worker_id = f"{os.getpid()}_{current_thread().name}"
            
            socket_path = pkg_dir / f".velo_zygote_{worker_id}.sock"
            pid_file = pkg_dir / f".velo_zygote_{worker_id}.pid"
            run_env["VELO_SOCKET"] = str(socket_path)
            run_env["VELO_PID_FILE"] = str(pid_file)

            # Stop any existing Zygote to ensure clean environment for EACH package
            subprocess.run([str(VELO_BIN), "zygote", "stop"], capture_output=True, env=run_env)
            # Give it a moment to clean up
            time.sleep(1)
            # Start fresh Zygote with the FULL environment (including compat.toml env vars)
            # [CRITICAL] Start in test_cwd so "source" strategy can see the code or installed package
            logger.info(f"   🚀 Starting fresh Velo Zygote in {test_cwd.name} (Socket: {socket_path.name})...")
            subprocess.run([str(VELO_BIN), "zygote", "start"], capture_output=True, env=run_env, cwd=test_cwd)
            time.sleep(2)
            
            # Install test dependencies if needed
            if test_deps:
                logger.info(f"   📦 Installing test deps: {test_deps}")
                subprocess.run(
                    ["uv", "pip", "install", *test_deps],
                    cwd=test_cwd,
                    capture_output=True,
                    env=self.env,
                )
            
            # Prepare environment variables for injection (already in run_env, but keep as backup)
            self.run_env = run_env

            # Run CPython baseline
            logger.info(f"   🐍 Running CPython baseline...")
            
            # [CRITICAL] Create an isolated pytest.ini if no config exists
            # This prevents pytest from scanning parent directories (Velo root)
            isolated_ini = test_cwd / "pytest.ini"
            if not isolated_ini.exists() and not pyproject_bak:
                with open(isolated_ini, "w") as f:
                    f.write("[pytest]\nnorecursedirs = .git .venv benchmarks tests/qa\n")
                    # For Django, we might need to satisfy pytest-django's discovery
                    if pkg_name == "django":
                        f.write("django_find_project = false\n")
                logger.info(f"   🛡️  Created isolated pytest.ini")
            
            # For Django specifically, create a dummy manage.py if it's missing in tests
            if pkg_name == "django" and not (test_cwd / "manage.py").exists():
                with open(test_cwd / "manage.py", "w") as f:
                    f.write("# dummy")

            # If we hid pyproject.toml, tell pytest to use it
            cp_args = list(pytest_args)
            if pyproject_bak:
                cp_args.extend(["-c", str(pyproject_bak)])
            elif isolated_ini.exists():
                cp_args.extend(["-c", str(isolated_ini)])
            else:
                cp_args.extend(["-c", "/dev/null"])
            
            cpython_result = self._run_pytest(
                package=pkg_name,
                runtime="cpython",
                pytest_args=cp_args,
                timeout=timeout,
                cwd=test_cwd,
                source=source,
                test_path=actual_test_path,
                run_cmd=run_cmd,
                sys_path_strategy=compat.get("sys_path_strategy", "source"),
            )
            cpython_result.category = category
            cpython_result.tier = tier
            
            # Run Velo Zygote
            logger.info(f"   ⚡ Running Velo Zygote...")
            # Velo will see NO pyproject.toml, so it will just use VELO_PYTHON
            # But we tell pytest to use our backup config
            v_args = list(pytest_args)
            if pyproject_bak:
                v_args.extend(["-c", str(pyproject_bak)])
            elif isolated_ini.exists():
                v_args.extend(["-c", str(isolated_ini)])
            else:
                v_args.extend(["-c", "/dev/null"])
            
            velo_result = self._run_pytest(
                package=pkg_name,
                runtime="velo",
                pytest_args=v_args,
                timeout=timeout,
                cwd=test_cwd,
                source=source,
                test_path=actual_test_path,
                run_cmd=run_cmd,
                sys_path_strategy=compat.get("sys_path_strategy", "source"),
            )
            velo_result.category = category
            velo_result.tier = tier
            
            # Restore pyproject.toml
            if pyproject_bak and pyproject_bak.exists():
                pyproject_bak.rename(pyproject_file)
            
            # Restore local source if hidden
            if self.source_dir_bak and self.source_dir_bak.exists():
                self.source_dir_bak.rename(self.source_dir_orig)
                logger.info(f"   👀 Restored local source {pkg_name}/")
            
            # Compare results
            compat_result = CompatResult(
                package=pkg_name,
                category=category,
                tier=tier,
                cpython=cpython_result,
                velo=velo_result,
                known_failures=compat.get("known_failures", []),
            )
            compat_result.compute_verdict()
            
            # Log result
            verdict_emoji = {
                "COMPATIBLE": "✅",
                "REGRESSION": "❌",
                "TIMEOUT": "⏱️",
                "SKIP": "⏭️",
            }.get(compat_result.verdict, "❓")
            
            logger.info(
                f"   {verdict_emoji} {compat_result.verdict} | "
                f"CPython: {cpython_result.passed}/{cpython_result.total} | "
                f"Velo: {velo_result.passed}/{velo_result.total}"
            )
            
            return compat_result
            
        except Exception as e:
            logger.error(f"   ❌ Error: {e}")
            # Return error result
            error_result = TestResult(
                package=pkg_name,
                category=category,
                tier=0,
                runtime="error",
                exit_code=-2,
                error_message=str(e),
            )
            return CompatResult(
                package=pkg_name,
                category=category,
                tier=0,
                cpython=error_result,
                velo=error_result,
                verdict="ERROR",
            )
    
    def run_all(self) -> list[CompatResult]:
        """Run all discovered compatibility tests."""
        config_paths = self.discover()
        if not config_paths:
            logger.warning("⚠️ No compatibility tests found.")
            return []
        
        logger.info(f"📋 Found {len(config_paths)} packages for Tier <= {self.tier}")
        
        results = []
        if self.parallel > 1:
            from concurrent.futures import ThreadPoolExecutor
            from threading import Lock
            logger.info(f"🚀 Running with {self.parallel} parallel workers...")
            report_lock = Lock()
            
            def run_and_save(path):
                res = self.run_compat_test(path)
                with report_lock:
                    results.append(res)
                    self.results = list(results) # snapshot
                    self.save_report()
                return res
                
            with ThreadPoolExecutor(max_workers=self.parallel) as executor:
                list(executor.map(run_and_save, config_paths))
        else:
            for config_path in config_paths:
                try:
                    # Clear pytest cache before each run to avoid metadata leakage
                    repo_dir = config_path.parent / ".test_repo"
                    if repo_dir.exists():
                        cache_dir = repo_dir / ".pytest_cache"
                        if cache_dir.exists():
                            shutil.rmtree(cache_dir)
                    
                    res = self.run_compat_test(config_path)
                    results.append(res)
                    self.results = results
                    self.save_report() # Partial save
                except Exception as e:
                    logger.error(f"   ❌ Fatal error running {config_path}: {e}")
        
        self.results = results
        return results
    
    def save_report(self) -> None:
        """Save results to JSON and Markdown."""
        suffix = f"_{self.report_name}" if self.report_name else ""
        results_file = BENCHMARKS_DIR / f"compat_results{suffix}.json"
        report_file = BENCHMARKS_DIR / f"COMPAT_REPORT{suffix}.md"

        # JSON report
        json_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "system": {
                "os": platform.system(),
                "python": platform.python_version(),
                "velo": str(VELO_BIN),
            },
            "summary": {
                "total": len(self.results),
                "compatible": sum(1 for r in self.results if r.verdict == "COMPATIBLE"),
                "regression": sum(1 for r in self.results if r.verdict == "REGRESSION"),
                "timeout": sum(1 for r in self.results if r.verdict == "TIMEOUT"),
                "skip": sum(1 for r in self.results if r.verdict == "SKIP"),
            },
            "results": [
                {
                    "package": r.package,
                    "category": r.category,
                    "tier": r.tier,
                    "verdict": r.verdict,
                    "new_failures": r.new_failures,
                    "cpython": asdict(r.cpython),
                    "velo": asdict(r.velo),
                }
                for r in self.results
            ],
        }
        
        with open(results_file, "w") as f:
            json.dump(json_data, f, indent=2)
        
        logger.info(f"\n📊 JSON report saved to {results_file}")
        
        # Markdown report
        md_lines = [
            f"# Velo Compatibility Report {self.report_name if self.report_name else ''}",
            "",
            f"> Generated: {json_data['timestamp']}",
            "",
            "## Summary",
            "",
            f"| Metric | Count |",
            f"|:---|:---|",
            f"| **Compatible** | {json_data['summary']['compatible']} |",
            f"| **Regression** | {json_data['summary']['regression']} |",
            f"| **Timeout** | {json_data['summary']['timeout']} |",
            f"| **Skip** | {json_data['summary']['skip']} |",
            "",
            "## Results",
            "",
            "| Package | Category | Tier | Verdict | CPython | Velo |",
            "|:---|:---|:---|:---|:---|:---|",
        ]
        
        for r in sorted(self.results, key=lambda x: (x.tier, x.category, x.package)):
            verdict_emoji = {"COMPATIBLE": "✅", "REGRESSION": "❌", "TIMEOUT": "⏱️", "SKIP": "⏭️"}.get(r.verdict, "❓")
            md_lines.append(
                f"| {r.package} | {r.category} | {r.tier} | {verdict_emoji} {r.verdict} | "
                f"{r.cpython.passed}/{r.cpython.total} | {r.velo.passed}/{r.velo.total} |"
            )
        
        with open(report_file, "w") as f:
            f.write("\n".join(md_lines))
        
        logger.info(f"📄 Markdown report saved to {report_file}")


def main():
    parser = argparse.ArgumentParser(description="Velo Compatibility Test Runner")
    parser.add_argument("--tier", type=int, default=1, choices=[1, 2, 3],
                        help="Maximum tier to test (1=必测, 2=核心, 3=扩展)")
    parser.add_argument("--tier-only", action="store_true",
                        help="Only test packages belonging exactly to the specified tier")
    parser.add_argument("--parallel", type=int, default=1,
                        help="Number of parallel workers")
    parser.add_argument("--package", type=str,
                        help="Test specific package only")
    parser.add_argument("--category", type=str,
                        help="Run specific category (cli, library, web)")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Default timeout per package (seconds)")
    parser.add_argument("--report-name", type=str, default=None,
                        help="Suffix for report filenames (e.g. 'tier2' -> COMPAT_REPORT_tier2.md)")
    parser.add_argument("--all", action="store_true", help="Run all tiers (equivalent to --tier 3)")

    args = parser.parse_args()
    
    if args.all:
        args.tier = 3
    
    if not VELO_BIN.exists():
        sys.exit(f"❌ Velo binary not found at {VELO_BIN}. Build it first!")
    
    if not SHARED_VENV_DIR.exists():
        sys.exit(f"❌ Shared venv not found at {SHARED_VENV_DIR}. Run setup_shared_env.py first!")
    
    runner = CompatRunner(
        tier=args.tier,
        parallel=args.parallel,
        target_pkg=args.package,
        timeout=args.timeout,
        report_name=args.report_name,
        tier_only=args.tier_only,
        category=args.category,
    )
    
    try:
        runner.run_all()
        runner.save_report()
    finally:
        # Final cleanup
        subprocess.run([str(VELO_BIN), "zygote", "stop"], capture_output=True)
    
    # Print summary
    compatible = sum(1 for r in runner.results if r.verdict == "COMPATIBLE")
    total = len(runner.results)
    logger.info(f"\n🎯 Compatibility: {compatible}/{total} ({100*compatible/total:.1f}%)" if total else "\n⚠️ No tests run")


if __name__ == "__main__":
    main()
