import os
import subprocess
from pathlib import Path

from .conftest_utils import VeloTestEnv, get_repo_root, get_velo_binary


def test_l2_003_syntax_error_fast_fail():
    """Regression test: Ensure Zygote fails fast on syntax errors instead of hanging."""
    root = get_repo_root()
    velo_binary = get_velo_binary()

    env = VeloTestEnv(root, velo_binary)
    # Create a broken app
    env.create_app("broken.py", "def broken(\n")

    # Explicitly set log path for debugging
    zy_log = Path(env.home) / "zygote.log"
    env.env["VELO_ZYGOTE_LOG"] = str(zy_log)

    # Run with Zygote enabled.
    # Previously this would hang for 360s (default zygote timeout).
    # We set a 30s timeout for the subprocess call. It SHOULD fail in < 5s.
    try:
        print("\n[FORENSIC] Running velo serve with broken:app...")
        result = env.run_velo("serve", "broken:app", env={"VELO_ZYGOTE_PRELOAD": "1"}, timeout=30)
        print(f"[FORENSIC] Return code: {result.returncode}")
        print(f"[FORENSIC] Stderr: {result.stderr}")
        assert result.returncode != 0
        assert "error" in result.stderr.lower() or "syntax" in result.stderr.lower()
    except subprocess.TimeoutExpired as e:
        # Diagnostic: Dump Zygote log if it hung
        print("\n[FORENSIC] TIMEOUT EXPIRED")
        if e.stdout:
            print(f"Stdout: {e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout}")
        if e.stderr:
            print(f"Stderr: {e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr}")

        log_content = zy_log.read_text() if zy_log.exists() else "Log not found"
        print(f"\n--- Zygote Log ({zy_log}) ---\n{log_content}\n-----------------")

        # Check for zombie processes
        subprocess.run(["ps", "-ax", "-o", "pid=,ppid=,command=", "-g", str(os.getpgid(0))], check=False)

        assert False, "Regression: velo serve hung while starting with a syntax error in Zygote mode"
    except Exception as e:
        print(f"\n[FORENSIC] UNEXPECTED ERROR: {e}")
        raise


def test_rkyv_security_version():
    """Regression test: Ensure rkyv version is >= 0.8.14 (RUSTSEC-2026-0001)."""
    repo_root = get_repo_root()
    cargo_lock = repo_root / "Cargo.lock"

    if not cargo_lock.exists():
        return  # Skip if no lock file (unlikely in CI)

    lock_content = cargo_lock.read_text()

    # Search for rkyv entry
    import re

    # Match:
    # [[package]]
    # name = "rkyv"
    # version = "0.8.14"
    rkyv_match = re.search(r'\[\[package\]\]\s+name = "rkyv"\s+version = "([^"]+)"', lock_content)
    if rkyv_match:
        version = rkyv_match.group(1)
        v_parts = [int(p) for p in version.split(".")]
        # Minimum safe version: 0.8.14
        assert (
            v_parts[0] > 0
            or (v_parts[0] == 0 and v_parts[1] > 8)
            or (v_parts[0] == 0 and v_parts[1] == 8 and v_parts[2] >= 14)
        ), f"Vulnerable rkyv version detected: {version}. Minimum safe version is 0.8.14"


def test_protocol_crate_has_tests():
    """Regression test: Ensure velo-protocol has working tests (avoiding 0-test CI failure)."""
    repo_root = get_repo_root()

    # Run cargo test on the protocol crate
    result = subprocess.run(["cargo", "test", "-p", "velo-protocol"], cwd=repo_root, capture_output=True, text=True)

    # Assert it passed and actually ran tests
    assert result.returncode == 0
    assert "running 1 test" in result.stdout or "running 1 test" in result.stderr
    assert "test result: ok. 1 passed" in result.stdout or "test result: ok. 1 passed" in result.stderr


def test_ci_matrix_naming_smoke():
    """Regression test: Ensure binary name is 'velo' as expected by CI matrix."""
    velo_binary = get_velo_binary()
    assert os.path.basename(velo_binary) == "velo"

    # Check help output to confirm it's the right binary
    result = subprocess.run([velo_binary, "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "high-performance python runtime" in result.stdout.lower()
