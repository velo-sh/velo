"""
Velo QA: Fingerprint Attack Tests (FP-xxx)
==========================================
Adversarial tests targeting uv.lock fingerprinting.

These tests attempt to BREAK fingerprinting by:
- Malicious uv.lock files (symlinks, directories, huge files)
- Race conditions during fingerprint computation
- Permission issues

Goal: Velo should handle fingerprint edge cases gracefully.
"""

import os
import pytest
import threading
import time
from pathlib import Path

from test_harness import (
    VeloTestEnv,
    run_velo,
    assert_no_crash,
)


class TestFingerprintATTACKS:
    """FP-001 to FP-004: Malicious uv.lock tests."""

    def test_fp_001_uv_lock_is_symlink_to_dev_random(self):
        """FP-001: uv.lock as symlink to /dev/random should be handled."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_script()
            
            # Create symlink to /dev/random (infinite random data)
            uv_lock = env.path / "uv.lock"
            uv_lock.symlink_to("/dev/urandom")
            
            # Should not hang forever trying to hash infinite data
            result = run_velo(["run", "test.py"], cwd=env.path, timeout=5)
            assert_no_crash(result)
        finally:
            env.cleanup()

    def test_fp_002_uv_lock_is_directory(self):
        """FP-002: uv.lock as directory should be handled."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_script()
            
            # Create directory at uv.lock path
            uv_lock = env.path / "uv.lock"
            uv_lock.mkdir()
            
            result = run_velo(["run", "test.py"], cwd=env.path)
            assert_no_crash(result)
            # Should work without fingerprinting or fail gracefully
        finally:
            env.cleanup()

    def test_fp_003_huge_uv_lock(self):
        """FP-003: 10MB uv.lock should be handled without memory issues."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_script()
            
            # Create 10MB uv.lock
            uv_lock = env.path / "uv.lock"
            uv_lock.write_bytes(b"x" * 10_000_000)
            
            result = run_velo(["run", "test.py"], cwd=env.path, timeout=10)
            assert_no_crash(result)
            # Should succeed - hashing 10MB is fine
        finally:
            env.cleanup()

    def test_fp_004_binary_uv_lock(self):
        """FP-004: Binary content in uv.lock should still hash correctly."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_script()
            
            # Write binary content
            uv_lock = env.path / "uv.lock"
            uv_lock.write_bytes(os.urandom(1000))
            
            result = run_velo(["run", "test.py"], cwd=env.path)
            assert_no_crash(result)
            assert result.success
        finally:
            env.cleanup()


class TestFingerprintPERMISSIONS:
    """FP-006: Permission tests."""

    def test_fp_006_uv_lock_no_permissions(self):
        """FP-006: Unreadable uv.lock should be handled."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_script()
            
            # Create uv.lock with no permissions
            uv_lock = env.path / "uv.lock"
            uv_lock.write_text("version = 1")
            uv_lock.chmod(0o000)
            
            result = run_velo(["run", "test.py"], cwd=env.path)
            assert_no_crash(result)
            # Should work without fingerprinting
            
            # Restore permissions for cleanup
            uv_lock.chmod(0o644)
        finally:
            env.cleanup()


class TestFingerprintRACE:
    """FP-005: Race condition tests."""

    def test_fp_005_uv_lock_changes_during_read(self):
        """FP-005: uv.lock changing during fingerprint should not cause issues."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()
            
            # Continuously modify uv.lock while running velo
            stop_flag = threading.Event()
            
            def modify_uv_lock():
                counter = 0
                while not stop_flag.is_set():
                    try:
                        (env.path / "uv.lock").write_text(f"version = {counter}\n")
                        counter += 1
                        time.sleep(0.01)
                    except:
                        pass
            
            modifier_thread = threading.Thread(target=modify_uv_lock)
            modifier_thread.start()
            
            try:
                # Run velo multiple times during modification
                for _ in range(3):
                    result = run_velo(["run", "test.py"], cwd=env.path)
                    assert_no_crash(result)
            finally:
                stop_flag.set()
                modifier_thread.join()
        finally:
            env.cleanup()


class TestFingerprintMISSING:
    """Test behavior without uv.lock."""

    def test_no_uv_lock_still_works(self):
        """Velo should work without uv.lock (no fingerprinting)."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_script()
            # Note: NOT creating uv.lock
            
            result = run_velo(["run", "test.py"], cwd=env.path)
            assert_no_crash(result)
            assert result.success, "Should work without uv.lock"
        finally:
            env.cleanup()
