"""
Phase 7.0 Memory Gravity Test Fixtures

QA-SOP Reference: §4.1
RFC Reference: RFC-0015 (Memory Gravity)

This module provides shared fixtures for testing Memory Gravity SHM infrastructure.
Follows main branch patterns for CI-aware timeout scaling.
"""

import os
import sys
import pytest
import platform
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Generator
from dataclasses import dataclass

# Import CI-aware timeout constants from parent conftest (main branch pattern)
# These are automatically scaled for CI environments (3x multiplier)
try:
    from tests.qa.conftest import (
        T_SHORT,      # 5s local, 15s CI
        T_MEDIUM,     # 15s local, 45s CI
        T_LONG,       # 60s local, 180s CI
        ci_timeout,   # Function to scale custom timeouts
        TIMEOUT_MULTIPLIER,
    )
except ImportError:
    # Fallback for standalone execution
    T_SHORT = 5
    T_MEDIUM = 15
    T_LONG = 60
    TIMEOUT_MULTIPLIER = 1.0
    def ci_timeout(base: float) -> float:
        return base


# =============================================================================
# Platform Detection
# =============================================================================

IS_LINUX = platform.system() == "Linux"
IS_MACOS = platform.system() == "Darwin"

# Skip decorators for platform-specific tests
skip_unless_linux = pytest.mark.skipif(
    not IS_LINUX,
    reason="Test requires Linux (memfd_create, F_SEAL support)"
)

skip_on_macos_security = pytest.mark.skipif(
    IS_MACOS,
    reason="macOS has no kernel-level sealing protection (RFC-0015 §3.4)"
)

skip_on_macos_numa = pytest.mark.skipif(
    IS_MACOS,
    reason="macOS is single-NUMA-node (RFC-0015 §4.7)"
)

skip_on_macos_hugepages = pytest.mark.skipif(
    IS_MACOS,
    reason="macOS has no HugePages support (RFC-0015 §3.4)"
)

skip_on_macos_pid_namespace = pytest.mark.skipif(
    IS_MACOS,
    reason="macOS has no PID namespace support (RFC-0015 §4.4)"
)


# =============================================================================
# Fixtures
# =============================================================================

@dataclass
class VeloTestEnv:
    """Test environment for Memory Gravity tests."""
    path: Path
    velo_binary: Optional[Path]
    python_path: Path
    
    def run_velo(self, *args, timeout: float = None, **kwargs) -> subprocess.CompletedProcess:
        """Run velo command in the test environment.
        
        Uses T_MEDIUM (15s local, 45s CI) as default timeout.
        """
        if self.velo_binary is None:
            pytest.skip("Velo binary not found")
        
        if timeout is None:
            timeout = T_MEDIUM
        
        cmd = [str(self.velo_binary)] + list(args)
        return subprocess.run(
            cmd,
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout,
            **kwargs
        )
    
    def run_python(self, script: str, timeout: float = None) -> subprocess.CompletedProcess:
        """Run a Python script in the test environment.
        
        Uses T_MEDIUM (15s local, 45s CI) as default timeout.
        """
        if timeout is None:
            timeout = T_MEDIUM
            
        script_path = self.path / "_test_script.py"
        script_path.write_text(script)
        
        return subprocess.run(
            [str(self.python_path), str(script_path)],
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout
        )
    
    def create_file(self, name: str, content: str) -> Path:
        """Create a file in the test environment."""
        file_path = self.path / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return file_path


def find_velo_binary() -> Optional[Path]:
    """Find the velo binary in standard locations."""
    # Search order: release > debug > PATH
    cwd = Path.cwd()
    candidates = [
        cwd / "target" / "release" / "velo",
        cwd / "target" / "debug" / "velo",
    ]
    
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    
    # Try PATH
    result = subprocess.run(["which", "velo"], capture_output=True, text=True)
    if result.returncode == 0:
        return Path(result.stdout.strip())
    
    return None


@pytest.fixture
def isolated_env(tmp_path: Path) -> Generator[VeloTestEnv, None, None]:
    """
    Create an isolated test environment for Memory Gravity tests.
    
    Per QA-SOP §7.3: Each test gets a fresh, isolated environment.
    """
    velo_binary = find_velo_binary()
    python_path = Path(sys.executable)
    
    env = VeloTestEnv(
        path=tmp_path,
        velo_binary=velo_binary,
        python_path=python_path
    )
    
    yield env
    
    # Cleanup is handled by pytest's tmp_path fixture


@pytest.fixture
def shm_test_env(isolated_env: VeloTestEnv) -> Generator[VeloTestEnv, None, None]:
    """
    Extended environment for SHM-specific tests.
    
    Includes additional setup for Memory Gravity testing.
    """
    # Create a minimal safetensors-like test file
    test_data_dir = isolated_env.path / "test_data"
    test_data_dir.mkdir(exist_ok=True)
    
    yield isolated_env


# =============================================================================
# Test Markers
# =============================================================================

def pytest_configure(config):
    """Register custom markers for Memory Gravity tests."""
    config.addinivalue_line(
        "markers", "tier0: Tier 0 - Core Functionality (MUST PASS)"
    )
    config.addinivalue_line(
        "markers", "tier1: Tier 1 - Core Benchmarks (Cold Start, Time to Token)"
    )
    config.addinivalue_line(
        "markers", "tier2: Tier 2 - Scalability & Stability"
    )
    config.addinivalue_line(
        "markers", "tier3: Tier 3 - Security (MUST PASS)"
    )
    config.addinivalue_line(
        "markers", "tier4: Tier 4 - HFT Performance"
    )
    config.addinivalue_line(
        "markers", "shm: Memory Gravity SHM tests"
    )
    config.addinivalue_line(
        "markers", "security: Security invariant tests"
    )
    config.addinivalue_line(
        "markers", "linux_only: Tests that require Linux"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests with velo binary"
    )


# =============================================================================
# Utility Functions
# =============================================================================

def get_process_rss_kb(pid: int) -> int:
    """Get Resident Set Size of a process in KB."""
    if IS_LINUX:
        try:
            with open(f"/proc/{pid}/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1])
        except (FileNotFoundError, PermissionError):
            pass
    elif IS_MACOS:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    return 0


def get_process_numa_node(pid: int) -> Optional[int]:
    """Get the NUMA node of a process (Linux only)."""
    if not IS_LINUX:
        return None
    
    try:
        result = subprocess.run(
            ["numactl", "--hardware"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return None
        
        # Parse numa_maps for the process
        numa_maps_path = f"/proc/{pid}/numa_maps"
        if os.path.exists(numa_maps_path):
            with open(numa_maps_path, "r") as f:
                content = f.read()
                # Simple heuristic: find most common node
                if "N0=" in content:
                    return 0
                elif "N1=" in content:
                    return 1
    except (FileNotFoundError, PermissionError, subprocess.SubprocessError):
        pass
    
    return None


def create_synthetic_safetensors(path: Path, header_length: int, tensor_size: int = 1024) -> None:
    """
    Create a synthetic safetensors file with specified header length.
    
    Used for testing H-29 alignment guarantee.
    """
    import json
    import struct
    
    # Create minimal metadata
    metadata = {
        "tensor_0": {
            "dtype": "F32",
            "shape": [tensor_size // 4],
            "data_offsets": [0, tensor_size]
        }
    }
    
    # Serialize to JSON
    json_str = json.dumps(metadata)
    
    # Pad to desired header length
    current_len = len(json_str.encode("utf-8"))
    if current_len < header_length:
        padding = " " * (header_length - current_len)
        json_str = json_str[:-1] + padding + "}"
    
    header_bytes = json_str.encode("utf-8")
    
    # Write file: u64 header_len + header + tensor data
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(header_bytes)))
        f.write(header_bytes)
        f.write(b"\x00" * tensor_size)


def check_alignment(mmap_base: int, offset: int, alignment: int = 64) -> bool:
    """Check if tensor offset is properly aligned."""
    effective_address = mmap_base + offset
    return (effective_address % alignment) == 0
