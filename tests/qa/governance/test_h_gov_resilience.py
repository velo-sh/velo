import subprocess
import os
import sys
from pathlib import Path

VELO_BIN = "./target/release/velo"
TEST_ST = "tests/qa/governance/test.safetensors"
SIMPLE_PY = "tests/qa/governance/simple.py"

def run_velo(env, args):
    """Run Velo with specific environment and arguments."""
    full_env = os.environ.copy()
    full_env.update(env)
    
    result = subprocess.run(
        [VELO_BIN] + args,
        env=full_env,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"--- FAILURE DETAILS ---")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
    return result

def test_h_gov_resilience():
    print("🚀 Starting H-Gov Chaos Verification Ritual...")
    
    # 1. CI/Dev Mode: Strict Optimization (Zygote Failure)
    print("\n[Scenario 1] VELO_ENV=dev (Strict) + Zygote Force-Fail")
    res1 = run_velo(
        {"VELO_ENV": "dev", "VELO_ZYGOTE_SOCKET": "/tmp/non_existent_dir/fail.sock"},
        ["run", "--zygote", SIMPLE_PY]
    )
    assert res1.returncode != 0
    assert "H-GOV CRITICAL" in res1.stderr
    assert "Zygote/IPC" in res1.stderr
    print("✅ Verified: Strict mode correctly blocks fallback.")

    # 2. Prod Mode: Relaxed Optimization (Zygote Failure)
    print("\n[Scenario 2] VELO_ENV=prod (Relaxed) + Zygote Force-Fail")
    res2 = run_velo(
        {"VELO_ENV": "prod", "VELO_ZYGOTE_SOCKET": "/tmp/non_existent_dir/fail.sock"},
        ["run", "--zygote", SIMPLE_PY]
    )
    assert res2.returncode == 0
    assert "H-GOV AUDIT" in res2.stderr
    assert "Success" in res2.stdout
    print("✅ Verified: Prod mode gracefully degrades with audit signal.")

    # 3. CI/Dev Mode: Strict Memory Gravity (HugePages Failure - simulated via malformed socket dir or similar)
    # Note: On macOS, HugePages isn't as easy to trigger/fail via ENOMEM, 
    # but we can verify the 'SHM mode requested but Zygote protocol failed' which is now part of the H-Gov logic.
    print("\n[Scenario 3] VELO_ENV=dev (Strict) + SHM + Zygote Force-Fail")
    res3 = run_velo(
        {"VELO_ENV": "dev", "VELO_ZYGOTE_SOCKET": "/tmp/non_existent_dir/fail.sock"},
        ["run", "--shm", TEST_ST, SIMPLE_PY]
    )
    assert res3.returncode != 0
    assert "H-GOV CRITICAL" in res3.stderr
    assert "Note: Fallback is blocked (strict_optimizations=true)" in res3.stderr
    print("✅ Verified: Strict SHM mode correctly blocks fallback.")

    # 4. Prod Mode: Relaxed Memory Gravity (SHM Creation Failure)
    print("\n[Scenario 4] VELO_ENV=prod (Relaxed) + SHM Creation Failure")
    # Passing a directory instead of a file to trigger open error
    res4 = run_velo(
        {"VELO_ENV": "prod"},
        ["run", "--shm", "tests/qa/governance", SIMPLE_PY]
    )
    assert res4.returncode == 0
    assert "H-GOV AUDIT" in res4.stderr
    assert "MemoryGravity/SHM" in res4.stderr
    assert "SHM Segment creation failed" in res4.stderr
    assert "Success" in res4.stdout
    print("✅ Verified: Prod mode gracefully degrades on SHM creation failure.")

    print("\n✨ H-Gov Chaos Verification Ritual Completed Successfully!")

if __name__ == "__main__":
    test_h_gov_resilience()
