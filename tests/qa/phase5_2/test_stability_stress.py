"""
Velo QA: Stability & Security Stress Tests (Dev Accountability Suite)
======================================================================
QA Team Audit Date: 2026-01-03
Developer Delivery: 08af068 (phase-5.1/zygote-optimization)

**PURPOSE**: These tests formally document and PROVE critical bugs and
security vulnerabilities in the Developer's delivery. They serve as
"Iron Gates" that MUST PASS before any merge is considered.

**BUGS DOCUMENTED**:
- BUG-51-001: --zygote flag ignores --fast, bypassing all Phase 5 security.
- BUG-51-002: H-4 Marshal Bomb bypass - sys.setrecursionlimit is IGNORED.

**VERDICT**: REJECTED. Dev must fix before re-submission.
"""


import pytest
import subprocess
import os
import sys
import marshal
import struct
from pathlib import Path

# Add python/ to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "python"))
from bundle_builder import VeloBundleBuilder

@pytest.fixture
def velo_binary():
    cargo_path = Path(__file__).parent.parent.parent.parent / "target" / "release" / "velo"
    if cargo_path.exists():
        return str(cargo_path)
    debug_path = Path(__file__).parent.parent.parent.parent / "target" / "debug" / "velo"
    if debug_path.exists():
        return str(debug_path)
    pytest.skip("velo binary not found")


def test_stress_001_marshal_bomb(tmp_path, velo_binary):
    """
    STRESS-SEC-001: Marshal Bomb Protection
    
    Create a bundle where bytecode is nested 1000 levels deep manually.
    Verify that velo_loader.py (recursion limit 500) catches this.
    """
    # Manually construct a 1000-level nested list [ [ [ ... ] ] ]
    # 0x5b = '[', 0x01 0x00 0x00 0x00 = size 1, 0x4e = 'N' (None)
    bomb_data = b'\x5b\x01\x00\x00\x00' * 1000 + b'\x4e'
    
    # Build a bundle containing this "bomb"
    bundle_path = tmp_path / "bundle.veloc"
    builder = VeloBundleBuilder()
    builder.add_code("bomb_module", bomb_data)
    builder.build(bundle_path)
    
    # Run velo with --fast
    main_py = tmp_path / "main.py"
    main_py.write_text("import bomb_module")
    
    # We expect an error, but not a crash
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent.parent / "python")
    
    result = subprocess.run(
        [velo_binary, "run", "--fast", str(main_py)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True
    )
    
    # The Rust-level StructuralGuard should catch this BEFORE Python sees it
    # Expected output: "Insecure bundle: Marshal recursion limit exceeded (max 500)"
    assert ("Marshal recursion limit exceeded" in result.stderr or
            "InsecureBundle" in result.stderr or
            "RecursionError" in result.stderr), \
        f"H-4 Guard did not trigger. stdout={result.stdout!r}, stderr={result.stderr!r}"
           
    # Ensure it didn't segfault
    assert result.returncode != -11
 

def test_bug_001_zygote_fast_conflict(tmp_path, velo_binary):
    """
    BUG-51-001: Zygote-Fast Flag Incompatibility
    
    This test verifies that --zygote and --fast work together or fail explicitly.
    Currently, Zygote ignores --fast.
    """
    main_py = tmp_path / "main.py"
    main_py.write_text("import sys; print('Fast Loader Active' if 'velo_loader' in sys.modules else 'Standard Loader')")
    
    # Build a bundle first
    from bundle_builder import build_from_project
    build_from_project(tmp_path)
    
    # IMPORTANT: Stop and restart Zygote to ensure updated Python code is loaded
    subprocess.run([velo_binary, "zygote", "stop"], capture_output=True)
    subprocess.run([velo_binary, "zygote", "start"], capture_output=True)
    
    # Run with both flags
    result = subprocess.run(
        [velo_binary, "run", "--zygote", "--fast", str(main_py)],
        cwd=tmp_path,
        capture_output=True,
        text=True
    )
    
    # Current behavior (BUG): It says "Standard Loader" because Zygote doesn't load the bundle
    # If it was fixed, it should say "Fast Loader Active"
    print(f"DEBUG stdout: {result.stdout}")
    print(f"DEBUG stderr: {result.stderr}")
    print(f"DEBUG returncode: {result.returncode}")
    
    if "Standard Loader" in result.stdout:
        pytest.fail("BUG-51-001: --zygote ignored --fast flag. Fast loader not active in Zygote worker.")
    
    assert "Fast Loader Active" in result.stdout
