import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

# SOP Ritual 11.2: Hostile Hygiene - Strict Initialization
# SOP Ritual 70: Heartbeat Governance Enforcement Probe

from pathlib import Path

repo_root = Path(__file__).parents[4]
VELO_BIN = str((repo_root / "target" / "release" / "velo").resolve())
if not Path(VELO_BIN).exists():
    VELO_BIN = str((repo_root / "target" / "debug" / "velo").resolve())


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
        # Force colors for signal verification (Ritual 70.1)
        env["CLICOLOR_FORCE"] = "1"
        env["FORCE_COLOR"] = "1"

        return subprocess.run([VELO_BIN] + args, env=env, cwd=self.tmp_dir, capture_output=True, text=True)

    def test_SEC_H70_ritual_70_1_signal_format(self):
        """Verify Ritual 70.1: Audit Signal Structure and ANSI Colors"""
        res = self.run_velo(
            {
                "VELO_ENV": "prod",
                "VELO_ZYGOTE_SOCKET": "/tmp/non_existent_dir/fail.sock",
            },
            ["run", "--zygote", "simple.py"],
        )

        stderr = res.stderr
        if res.returncode != 0:
            print(f"DEBUG: Prod fallback failed with RC={res.returncode}")
            print(f"DEBUG: STDERR: {stderr}")
            self.assertEqual(res.returncode, 0, "Prod mode must succeed via fallback")

        # Check Structured Signal components
        # We use re.escape and allow for ANSI codes
        self.assertTrue(
            any("H-GOV AUDIT:" in line for line in stderr.splitlines()),
            f"H-GOV AUDIT: signal missing from stderr:\n{stderr}",
        )
        self.assertIn("Impact:", stderr)
        self.assertIn("Healing:", stderr)

        # ANSI check: \x1b[ is the CSI (Control Sequence Introducer)
        # We need to make sure the binary is actually outputting them
        self.assertIn(
            "\x1b[",
            stderr,
            "Output should contain ANSI color codes (forced via CLICOLOR_FORCE)",
        )

        print("\n[HOSTILE] Ritual 70.1 PASSED: Audit signals are compliant.")

    def test_SEC_H70_ritual_70_2_zygote_fallback(self):
        """Verify Ritual 70.2: Zygote Fallback Boundary (Dev vs Prod)"""

        # 1. Dev Mode (Strict)
        res_dev = self.run_velo(
            {
                "VELO_ENV": "dev",
                "VELO_ZYGOTE_SOCKET": "/tmp/non_existent_dir/fail.sock",
            },
            ["run", "--zygote", "simple.py"],
        )
        if res_dev.returncode == 0:
            print("DEBUG: Dev mode incorrectly returned 0!")
            print(f"DEBUG: STDERR: {res_dev.stderr}")
            print(f"DEBUG: STDOUT: {res_dev.stdout}")

        self.assertNotEqual(res_dev.returncode, 0, "Dev mode must FAIL-FAST (RC != 0)")
        self.assertIn("H-GOV CRITICAL:", res_dev.stderr)

        # 2. Prod Mode (Relaxed)
        res_prod = self.run_velo(
            {
                "VELO_ENV": "prod",
                "VELO_ZYGOTE_SOCKET": "/tmp/non_existent_dir/fail.sock",
            },
            ["run", "--zygote", "simple.py"],
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
        res_dev = self.run_velo({"VELO_ENV": "dev"}, ["run", "--shm", "mangled.safetensors", "simple.py"])
        self.assertNotEqual(res_dev.returncode, 0, "Dev mode should crash on SHM error")

        # 2. Prod Mode (Relaxed) - Should fallback to disk
        res_prod = self.run_velo({"VELO_ENV": "prod"}, ["run", "--shm", "mangled.safetensors", "simple.py"])

        if res_prod.returncode != 0:
            print(f"\n🚨 [H-GOV DEFECT] SHM creation failure causes crash in PROD! RC={res_prod.returncode}")
            print(f"STDERR: {res_prod.stderr}")
            # We fail the test to report the defect
            self.fail("SHM failure must fallback to standard execution in Prod mode")

        self.assertIn("H-GOV AUDIT", res_prod.stderr)
        print("\n[HOSTILE] Ritual 70.3 PASSED: SHM fallback gracefully degrades in Prod.")

    def test_SEC_H70_ritual_70_4_fast_loader_fallback(self):
        """Verify Ritual 70.4: Fast Loader Fallback (Corrupted Bundle)"""

        # Create a corrupted bundle.veloc
        bundle_file = self.work_dir / "bundle.veloc"
        bundle_file.write_text("NOT_A_VALID_BUNDLE")

        # Prod Mode: Should fallback to normal imports
        res = self.run_velo({"VELO_ENV": "prod"}, ["run", "--fast", "simple.py"])

        # PROBE: run_with_fast_loader uses '?' during canonicalize/verify
        if res.returncode != 0:
            print(f"\n🚨 [H-GOV DEFECT] Fast Loader failure causes crash in PROD! RC={res.returncode}")
            print(f"STDERR: {res.stderr}")
            self.fail("Fast Loader failure must fallback to standard execution in Prod mode")

        self.assertIn("HEARTBEAT_ACK", res.stdout)
        print("\n[HOSTILE] Ritual 70.4 PASSED: Fast Loader fallback is functional.")

    def test_SEC_H70_ritual_70_5_invalid_shm_path(self):
        """Verify Ritual 70.5: Validation Boundary (Non-existent SHM)"""

        # 1. Dev Mode (Strict) - Should crash early
        res_dev = self.run_velo(
            {"VELO_ENV": "dev"},
            ["run", "--shm", "/tmp/non_existent_path_999.safetensors", "simple.py"],
        )
        self.assertNotEqual(res_dev.returncode, 0)

        # 2. Prod Mode (Relaxed) - Should fallback
        res_prod = self.run_velo(
            {"VELO_ENV": "prod"},
            ["run", "--shm", "/tmp/non_existent_path_999.safetensors", "simple.py"],
        )

        if res_prod.returncode != 0:
            print(f"\n🚨 [H-GOV DEFECT] Invalid SHM path causes crash in PROD! RC={res_prod.returncode}")
            print(f"STDERR: {res_prod.stderr}")
            self.fail("Invalid SHM path must fallback to standard execution in Prod mode")

        print("\n[HOSTILE] Ritual 70.5 PASSED: Invalid SHM path handles gracefully.")

    def test_SEC_H70_chaos_env_fail_closed(self):
        """Verify Environmental Fail-Closed: Unknown VELO_ENV should be strict"""

        res = self.run_velo(
            {
                "VELO_ENV": "chaos",
                "VELO_ZYGOTE_SOCKET": "/tmp/non_existent_dir/fail.sock",
            },
            ["run", "--zygote", "simple.py"],
        )

        if res.returncode == 0:
            print("DEBUG: Chaos env incorrectly returned 0!")
            print(f"DEBUG: STDERR: {res.stderr}")

        self.assertNotEqual(res.returncode, 0, "Unknown VELO_ENV must be strict (RC != 0)")
        self.assertIn("H-GOV CRITICAL:", res.stderr)

        print("\n[HOSTILE] Environment Isolation PASSED: Unknown VELO_ENV is strict.")

    def test_SEC_H70_ritual_70_7_analyze_shm_fallback(self):
        """Verify Ritual 70.7: Analyze SHM Fallback (Architectural Debt Probe)"""

        shm_file = self.work_dir / "mangled_analyze.safetensors"
        # Mangled header: length > file size
        shm_file.write_bytes(struct.pack("<Q", 1000000) + b'{"data": [0, 1024]}')

        # Prod Mode: Should NOT crash
        res = self.run_velo({"VELO_ENV": "prod"}, ["analyze", "--shm", "mangled_analyze.safetensors", "simple.py"])

        if res.returncode != 0:
            print(f"\n🚨 [H-GOV DEFECT] Analyze SHM failure causes crash in PROD! RC={res.returncode}")
            print(f"STDERR: {res.stderr}")
            self.fail("Analyze SHM failure must be handled by H-Gov in Prod mode")

        print("\n[HOSTILE] Ritual 70.7 PASSED: Analyze SHM fallback is functional.")

    def test_SEC_H70_ritual_70_8_serve_respawn_fallback(self):
        """Verify Ritual 70.8: Serve Respawn Fallback (SEC-H78)"""

        # Scenario: Start serve, kill Zygote, then kill a worker.
        # Prod mode supervisor should NOT bail when respawn fails.

        # We start serve in a background thread or non-blocking way
        # Since we are in a test, we can use a shorter timeout
        os.environ["VELO_ENV"] = "prod"
        os.environ["VELO_FAIL_FAST_LIMIT"] = "2"  # Faster failure for testing

        # We need a dummy app
        self.script_file.write_text("def app(scope, receive, send): pass\n")

        # Start Zygote first to ensure it's available
        subprocess.run([VELO_BIN, "debug", "zygote"], capture_output=True)

        # Find Zygote socket
        socket_path = Path("/tmp/velo-zygote.sock")
        if socket_path.exists():
            socket_path.unlink()
        socket_path.touch()  # Create a fake stale socket to ensure Zygote start fails

        res = self.run_velo(
            {"VELO_ENV": "prod"},
            [
                "serve",
                "--zygote",
                "--host",
                "127.0.0.1",
                "--port",
                "19998",
                "--workers",
                "1",
                "--dry-run",
                "simple:app",
            ],
        )

        # Probe: If Zygote fails to start, supervisor must report fallback
        # Current implementation uses 'Continuing without Zygote optimization'
        if "Continuing without Zygote optimization" not in res.stderr:
            print(f"\n🚨 [H-GOV DEFECT] Serve failed to report Zygote fallback! RC={res.returncode}")
            print(f"STDERR: {res.stderr}")
            self.fail("Serve must report Zygote fallback in Prod")

        self.assertEqual(res.returncode, 0)
        print("\n[HOSTILE] Ritual 70.8 PASSED: Serve handles initial Zygote failure.")

    def test_SEC_H70_ritual_70_9_analyze_zygote_fallback(self):
        """Verify Ritual 70.9: Analyze Zygote Fallback (SEC-H79)"""

        # Scenario: Zygote is dead, analyze should fallback to cold analysis
        socket_path = Path("/tmp/velo-zygote.sock")
        if socket_path.exists():
            socket_path.unlink()

        # We can't easily force Zygote start failure without breaking permissions
        # because the launcher is quite robust.
        # But we can check if it uses the bubble operator for Zygote::start()
        # PROBE: Current analyze.rs line 429 uses .context(...)?

        # Let's try to pass an invalid preload but that's hard to trigger from CLI.
        # Let's use a non-existent socket directory if possible?

        res = self.run_velo(
            {"VELO_ENV": "prod", "VELO_ZYGOTE_SOCKET": "/non_existent_dir/fail.sock"}, ["analyze", "simple.py"]
        )

        if res.returncode != 0:
            print(f"\n🚨 [H-GOV DEFECT] Analyze Zygote failure causes crash! RC={res.returncode}")
            print(f"STDERR: {res.stderr}")
            self.fail("Analyze must fallback to cold analysis if Zygote fails")

        print("\n[HOSTILE] Ritual 70.9 PASSED: Analyze handles Zygote failure.")

    def test_SEC_H70_ritual_70_10_fast_loader_setup_fallback(self):
        """Verify Ritual 70.10: Fast Loader Setup Fallback"""

        # Scenario: Break temp dir creation in run --fast
        # We point TMPDIR to a non-existent location

        res = self.run_velo(
            {"VELO_ENV": "prod", "TMPDIR": "/tmp/non_existent_dir_12345"}, ["run", "--fast", "simple.py"]
        )

        if res.returncode != 0:
            print(f"\n🚨 [H-GOV DEFECT] Fast Loader setup failure causes crash! RC={res.returncode}")
            print(f"STDERR: {res.stderr}")
            # Current run_with_fast_loader line 501 uses tempfile::tempdir()?
            self.fail("Fast Loader setup failure must fallback to disk in Prod")

        print("\n[HOSTILE] Ritual 70.10 PASSED: Fast Loader handles setup failure.")


if __name__ == "__main__":
    unittest.main()
