from __future__ import annotations
"""
Velo QA Test Harness
====================
Core test infrastructure for adversarial QA testing.

Usage:
    python -m pytest tests/qa/ -v
"""

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Test configuration
VELO_BINARY = Path(__file__).parent.parent.parent / "target" / "release" / "velo"
PROJECT_ROOT = Path(__file__).parent.parent.parent


@dataclass
class VeloTestResult:
    """Result of a velo command execution."""
    returncode: int
    stdout: str
    stderr: str
    duration_ms: float
    command: list[str]
    
    @property
    def success(self) -> bool:
        return self.returncode == 0
    
    def __repr__(self) -> str:
        status = "✅" if self.success else "❌"
        return f"{status} VeloTestResult(rc={self.returncode}, {self.duration_ms:.1f}ms)"


@dataclass
class VeloTestEnv:
    """Isolated test environment with project structure."""
    temp_dir: tempfile.TemporaryDirectory = field(default_factory=lambda: tempfile.TemporaryDirectory())
    
    @property
    def path(self) -> Path:
        return Path(self.temp_dir.name)
    
    @property
    def venv_path(self) -> Path:
        return self.path / ".venv"
    
    @property
    def cache_path(self) -> Path:
        return self.path / ".velo_cache"
    
    @property
    def cache_file(self) -> Path:
        return self.cache_path / "env.rkyv"
    
    def create_venv(self, python: str = "python3") -> None:
        """Create a minimal virtual environment."""
        subprocess.run(
            [python, "-m", "venv", str(self.venv_path)],
            check=True,
            capture_output=True
        )
    
    def create_uv_lock(self, content: str = "# test uv.lock\nversion = 1\n") -> None:
        """Create a uv.lock file for fingerprinting."""
        (self.path / "uv.lock").write_text(content)
    
    def create_script(self, name: str = "test.py", content: str = "print('OK')") -> Path:
        """Create a Python test script."""
        script_path = self.path / name
        script_path.write_text(content)
        return script_path
    
    def corrupt_cache(self, corruption_type: str = "random") -> None:
        """Corrupt the cache file in various ways."""
        self.cache_path.mkdir(parents=True, exist_ok=True)
        
        if corruption_type == "random":
            self.cache_file.write_bytes(os.urandom(256))
        elif corruption_type == "truncated":
            self.cache_file.write_bytes(os.urandom(10))
        elif corruption_type == "empty":
            self.cache_file.write_bytes(b"")
        elif corruption_type == "huge":
            # 10MB of zeros
            self.cache_file.write_bytes(b"\x00" * 10_000_000)
        elif corruption_type == "partial_json":
            self.cache_file.write_bytes(b'{"incomplete":')
    
    def make_cache_readonly(self) -> None:
        """Make cache directory read-only."""
        self.cache_path.mkdir(parents=True, exist_ok=True)
        os.chmod(self.cache_path, 0o444)
    
    def cleanup(self) -> None:
        """Clean up temporary directory."""
        # Restore permissions first
        if self.cache_path.exists():
            try:
                os.chmod(self.cache_path, 0o755)
            except:
                pass
        self.temp_dir.cleanup()


def run_velo(
    args: list[str],
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    timeout: float = 30.0
) -> VeloTestResult:
    """
    Execute velo with given arguments and return structured result.
    
    Args:
        args: Command arguments (without 'velo' itself)
        cwd: Working directory
        env: Environment variables (merged with os.environ)
        timeout: Maximum execution time in seconds (auto-scaled for CI)
    
    Returns:
        VeloTestResult with execution details
        
    Note:
        Timeout is automatically scaled by VELO_TIMEOUT_MULTIPLIER for CI.
        Default multiplier is 1.0 (local) or 3.0 (CI/GitHub Actions).
    """
    if not VELO_BINARY.exists():
        raise FileNotFoundError(
            f"Velo binary not found at {VELO_BINARY}. "
            f"Run 'cargo build --release' first."
        )
    
    # Apply CI timeout multiplier
    multiplier = float(os.environ.get("VELO_TIMEOUT_MULTIPLIER", "1.0"))
    scaled_timeout = timeout * multiplier
    
    cmd = [str(VELO_BINARY)] + args
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    
    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=full_env,
            capture_output=True,
            timeout=scaled_timeout
        )
        duration_ms = (time.perf_counter() - start) * 1000
        
        # Handle potential binary output with errors='replace'
        try:
            stdout = result.stdout.decode('utf-8', errors='replace')
            stderr = result.stderr.decode('utf-8', errors='replace')
        except AttributeError:
            stdout = result.stdout if isinstance(result.stdout, str) else str(result.stdout)
            stderr = result.stderr if isinstance(result.stderr, str) else str(result.stderr)
        
        return VeloTestResult(
            returncode=result.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            command=cmd
        )
    except subprocess.TimeoutExpired:
        duration_ms = (time.perf_counter() - start) * 1000
        return VeloTestResult(
            returncode=-1,
            stdout="",
            stderr=f"TIMEOUT after {scaled_timeout}s (base={timeout}s, multiplier={multiplier})",
            duration_ms=duration_ms,
            command=cmd
        )



def assert_velo_fails_gracefully(result: VeloTestResult, expected_in_stderr: str = "") -> None:
    """Assert that velo failed but without crashing (panic)."""
    # Check for Rust panic indicators
    panic_indicators = [
        "panic",
        "thread 'main' panicked",
        "RUST_BACKTRACE",
        "stack backtrace:",
    ]
    
    for indicator in panic_indicators:
        assert indicator.lower() not in result.stderr.lower(), \
            f"Velo panicked! Found '{indicator}' in stderr:\n{result.stderr}"
    
    if expected_in_stderr:
        assert expected_in_stderr.lower() in result.stderr.lower(), \
            f"Expected '{expected_in_stderr}' in stderr, got:\n{result.stderr}"


def assert_no_crash(result: VeloTestResult) -> None:
    """Assert that velo did not crash (may succeed or fail gracefully)."""
    crash_indicators = [
        "panic",
        "SIGSEGV",
        "SIGABRT",
        "Segmentation fault",
        "core dumped",
    ]
    
    combined_output = result.stdout + result.stderr
    for indicator in crash_indicators:
        assert indicator.lower() not in combined_output.lower(), \
            f"Velo crashed! Found '{indicator}' in output:\n{combined_output}"
