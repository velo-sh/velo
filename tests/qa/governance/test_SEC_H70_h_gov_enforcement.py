import os
import sys
import subprocess
import shutil
import tempfile
import unittest
import struct
from pathlib import Path

# SOP Ritual 11.2: Hostile Hygiene - Strict Initialization
# SOP Ritual 70: Heartbeat Governance Enforcement Probe

VELO_BIN = os.path.abspath("./target/release/velo")

class TestHGovEnforcement(unittest.TestCase):
    """
    Hostile Audit of SOP-004 (H-Gov) Invariants.
    Verifies that optimizations fail-fast in Dev and fail-safe in Prod.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="hgov_test_")
        self.work_dir = Path(self.tmp_dir)
        
        # Create a simple script
        self.script_file = self.work_dir / "simple.py"
        self.script_file.write_text("import os; print('HEARTBEAT_ACK', flush=True)\n")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def run_velo(self, env_vars, args):
        env = os.environ.copy()
        env.update(env_vars)
        # Ensure we don't pick up local dev config unless intended
        env["VELO_IS_ZYGOTE"] = "0"
        
        return subprocess.run(
            [VELO_BIN] + args,
            env=env,
            cwd=self.tmp_dir,
            capture_output=True,
            text=True
        )

    def test_SEC_H70_ritual_70_1_signal_format(self):
        """Verify Ritual 70.1: Audit Signal Structure and ANSI Colors"""
        res = self.run_velo(
            {"VELO_ENV": "prod", "VELO_ZYGOTE_SOCKET": "/tmp/non_existent_dir/fail.sock"},
            ["run", "--zygote", "simple.py"]
        )
        
        stderr = res.stderr
        if res.returncode != 0:
            print(f"DEBUG: Prod fallback failed with RC={res.returncode}")
            print(f"DEBUG: STDERR: {stderr}")
            self.assertEqual(res.returncode, 0, "Prod mode must succeed via fallback")
        
        # Check Structured Signal components
        # We use re.escape and allow for ANSI codes
        self.assertTrue(any("H-GOV AUDIT:" in line for line in stderr.splitlines()), 
                        f"H-GOV AUDIT: signal missing from stderr:\n{stderr}")
        self.assertIn("Impact:", stderr)
        self.assertIn("Healing:", stderr)
        
        # ANSI check: \x1b[ is the CSI (Control Sequence Introducer)
        self.assertIn("\x1b[", stderr, "Output should contain ANSI color codes")
        
        print("\n[HOSTILE] Ritual 70.1 PASSED: Audit signals are compliant.")

    def test_SEC_H70_ritual_70_2_zygote_fallback(self):
        """Verify Ritual 70.2: Zygote Fallback Boundary (Dev vs Prod)"""
        
        # 1. Dev Mode (Strict)
        res_dev = self.run_velo(
            {"VELO_ENV": "dev", "VELO_ZYGOTE_SOCKET": "/tmp/non_existent_dir/fail.sock"},
            ["run", "--zygote", "simple.py"]
        )
        if res_dev.returncode == 0:
            print(f"DEBUG: Dev mode incorrectly returned 0!")
            print(f"DEBUG: STDERR: {res_dev.stderr}")
            print(f"DEBUG: STDOUT: {res_dev.stdout}")
        
        self.assertNotEqual(res_dev.returncode, 0, "Dev mode must FAIL-FAST (RC != 0)")
        self.assertIn("H-GOV CRITICAL:", res_dev.stderr)
        
        # 2. Prod Mode (Relaxed)
        res_prod = self.run_velo(
            {"VELO_ENV": "prod", "VELO_ZYGOTE_SOCKET": "/tmp/non_existent_dir/fail.sock"},
            ["run", "--zygote", "simple.py"]
        )
        self.assertEqual(res_prod.returncode, 0, "Prod mode must FAIL-SAFE (RC == 0)")
        self.assertIn("HEARTBEAT_ACK", res_prod.stdout)
        
        print("\n[HOSTILE] Ritual 70.2 PASSED: Zygote fallback honors boundaries.")

    def test_SEC_H70_ritual_70_3_shm_fallback(self):
        """Verify Ritual 70.3: SHM Fallback (Mangled Header Probe)"""
        
        shm_file = self.work_dir / "mangled.safetensors"
        # Mangled header: length > file size
        shm_file.write_bytes(struct.pack("<Q", 1000000) + b'{"data": [0, 1024]}')
        
        # 1. Dev Mode (Strict) - Should crash
        res_dev = self.run_velo(
            {"VELO_ENV": "dev"},
            ["run", "--shm", "mangled.safetensors", "simple.py"]
        )
        self.assertNotEqual(res_dev.returncode, 0, "Dev mode should crash on SHM error")
        
        # 2. Prod Mode (Relaxed) - Should fallback to disk
        res_prod = self.run_velo(
            {"VELO_ENV": "prod"},
            ["run", "--shm", "mangled.safetensors", "simple.py"]
        )
        
        if res_prod.returncode != 0:
            print(f"\n🚨 [H-GOV DEFECT] SHM creation failure causes crash in PROD! RC={res_prod.returncode}")
            print(f"STDERR: {res_prod.stderr}")
            # We fail the test to report the defect
            self.fail("SHM failure must fallback to standard execution in Prod mode")
        
        self.assertIn("H-GOV AUDIT", res_prod.stderr)
        print("\n[HOSTILE] Ritual 70.3 PASSED: SHM fallback gracefully degrades in Prod.")

    def test_SEC_H70_chaos_env_fail_closed(self):
        """Verify Environmental Fail-Closed: Unknown VELO_ENV should be strict"""
        
        res = self.run_velo(
            {"VELO_ENV": "chaos", "VELO_ZYGOTE_SOCKET": "/tmp/non_existent_dir/fail.sock"},
            ["run", "--zygote", "simple.py"]
        )
        
        if res.returncode == 0:
            print(f"DEBUG: Chaos env incorrectly returned 0!")
            print(f"DEBUG: STDERR: {res.stderr}")
        
        self.assertNotEqual(res.returncode, 0, "Unknown VELO_ENV must be strict (RC != 0)")
        self.assertIn("H-GOV CRITICAL:", res.stderr)
        
        print("\n[HOSTILE] Environment Isolation PASSED: Unknown VELO_ENV is strict.")

if __name__ == "__main__":
    unittest.main()
