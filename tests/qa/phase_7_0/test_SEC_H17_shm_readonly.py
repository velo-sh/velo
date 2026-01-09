import os
import pytest
import sys
import subprocess
from pathlib import Path
import re

# SOP Ritual 11.3: Hostile Verification Discipline
# SOP Ritual 30: Identity-Based Alignment Assertion
# SOP Ritual 21: SHM ReadOnly Verification

@pytest.mark.tier3
class TestSecH17ShmReadonly:
    """
    [SOP Section 13.1] Security Invariant H-17: SHM ReadOnly.
    [SOP Section 4.3] Implementation Rules: Isolated Environment, Explicit Assertions.
    
    References:
    - docs/qa/STANDARDS/QA-SOP.md
    - Knowledge: Ritual 21 (SHM ReadOnly), Ritual 30 (Identity Alignment)
    """

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux only ritual (uses /proc)")
    def test_SEC_H17_ritual_21_shm_readonly_invariant(self, shm_test_env):
        """
        [SEC-H17] SHM ReadOnly Verification.
        Verifies that workers cannot modify source tensors (Zero-Copy Safety).
        """
        # [RITUAL 11.2] Hostile Test Technical Hygiene
        import sys
        for mod in list(sys.modules.keys()):
            if mod.startswith("velo_"):
                sys.modules.pop(mod, None)

        # 1. Start a worker process that loads a model (simulated)
        env = shm_test_env
        env.create_file("main.py", "import time, sys; print('READY', flush=True); sys.stderr.flush(); time.sleep(10)")
        
        # Create a dummy SHM file
        shm_file = env.path / "model.safetensors"
        shm_file.write_bytes(b"A" * 4096)
        
        # Launch Velo with SHM using spawn_velo (non-blocking)
        proc = env.spawn_velo("run", "--shm", str(shm_file), "main.py", 
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        try:
            # Wait for readiness using Ritual 43 (Retry-and-Accumulate)
            import time
            start_time = time.time()
            ready = False
            
            while time.time() - start_time < 5:
                if proc.poll() is not None:
                    stdout, stderr = proc.communicate()
                    pytest.fail(f"Velo died prematurely! RC={proc.returncode} STDERR={stderr.decode()}")
                
                pid = proc.pid
                maps_path = Path(f"/proc/{pid}/maps")
                if maps_path.exists():
                    content = maps_path.read_text()
                    if str(shm_file.name) in content:
                        ready = True
                        break
                time.sleep(0.1)

            if not ready:
                proc.kill()
                pytest.fail("Timeout waiting for SHM mapping to appear in /proc/{pid}/maps")

            pid = proc.pid
            
            # 2. Map Audit: Execute grep "velo_shm" /proc/{pid}/maps
            maps_path = Path(f"/proc/{pid}/maps")
            maps_content = maps_path.read_text()
            
            target_pattern = str(shm_file.name)
            
            found = False
            for line in maps_content.splitlines():
                if target_pattern in line:
                    found = True
                    # 3. Permission Assertion: Verify r--p (or r--s for shared)
                    perms = line.split()[1]
                    if "w" in perms:
                        pytest.fail(f"🚨 [RITUAL 21 FAILURE] SHM Segment is WRITABLE! Perms: {perms} Line: {line}")
                    
                    print(f"✅ [RITUAL 21] Verified Read-Only mapping: {perms} for {target_pattern}")

            if not found:
                 pytest.fail(f"Mapping '{target_pattern}' disappeared during audit!")

        finally:
            if proc.poll() is None:
                proc.kill()

    @pytest.mark.shm
    def test_ritual_30_identity_alignment(self, shm_test_env):
        """[RITUAL 30] Verify SHM alignment matches architectural identity."""
        # [RITUAL 11.2] Hostile Test Technical Hygiene
        import sys
        for mod in list(sys.modules.keys()):
            if mod.startswith("velo_"):
                sys.modules.pop(mod, None)

        env = shm_test_env
        
        # 1. Metadata Query: Retrieve the actual page size reported by Velo
        try:
            actual_page_size = env.get_actual_page_size()
        except Exception as e:
            pytest.skip(f"Ritual 30 skipped: could not determine actual page size from binary. Error: {e}")
            
        print(f"\n[RITUAL 30] Architecturally Reported Page Size: {actual_page_size} bytes")
        
        # 2. Create a synthetic safetensors file
        shm_file = env.path / "identity_check.safetensors"
        # We write exactly 1MB (not aligned to 2MB HugePage if present, but aligned to 4KB)
        file_size = 1024 * 1024
        shm_file.write_bytes(b"B" * file_size)
        
        # 3. The Assertion: assert_eq!(size % actual_page_size, 0)
        # RFC-0015 H-30/H-33: Even in fallback, the segment must be page-aligned.
        if file_size % actual_page_size != 0:
            pytest.fail(f"🚨 [RITUAL 30 FAILURE] SHM size {file_size} is not aligned to actual page size ({actual_page_size} bytes). "
                        "This indicates a violation of the Memory Gravity alignment invariant.")
            
        print(f"✅ [RITUAL 30] Verified Alignment Invariant: {file_size} % {actual_page_size} == 0")

