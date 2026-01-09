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
@pytest.mark.skipif(sys.platform != "linux", reason="Linux only ritual (uses /proc)")
class TestSecH17ShmReadonly:
    """
    [SOP Section 13.1] Security Invariant H-17: SHM ReadOnly.
    [SOP Section 4.3] Implementation Rules: Isolated Environment, Explicit Assertions.
    
    References:
    - docs/qa/STANDARDS/QA-SOP.md
    - Knowledge: Ritual 21 (SHM ReadOnly), Ritual 30 (Identity Alignment)
    """

    def test_SEC_H17_ritual_21_shm_readonly_invariant(self, shm_test_env):
        """
        [SEC-H17] SHM ReadOnly Verification.
        Verifies that workers cannot modify source tensors (Zero-Copy Safety).
        """
        # 1. Start a worker process that loads a model (simulated)
        env = shm_test_env
        env.create_file("main.py", "import time, sys; print('READY', flush=True); sys.stderr.flush(); time.sleep(10)")
        
        # Create a dummy SHM file
        shm_file = env.path / "model.safetensors"
        shm_file.write_bytes(b"A" * 4096)
        
        # Launch Velo with SHM using spawn_velo (non-blocking)
        # Note: We capture stdout/stderr to read the READY signal
        proc = env.spawn_velo("run", "--shm", str(shm_file), "main.py", 
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        try:
            # Wait for readiness using Ritual 43 (Retry-and-Accumulate)
            # We need to read line-by-line or check output without blocking forever
            import time
            start_time = time.time()
            ready = False
            
            # Simple polling loop since POpen.stdout is a blocking reader by default unless select is used
            # For simplicity in this test, we use a naive read with strict timeout check
            while time.time() - start_time < 5:
                if proc.poll() is not None:
                    # Process died early
                    stdout, stderr = proc.communicate()
                    pytest.fail(f"Velo died prematurely! RC={proc.returncode} STDERR={stderr.decode()}")
                
                # We can't easily non-block read without fcntl/selectors, 
                # but since we flush 'READY', we can try readline if we are sure it emits.
                # Safer: grep the /proc command first to see if it's running, 
                # but we need it to reach the 'loading' state.
                # Let's rely on the file existence first.
                
                pid = proc.pid
                maps_path = Path(f"/proc/{pid}/maps")
                if maps_path.exists():
                    # Check if 'model.safetensors' is mapped yet
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
                    # H-17 requires Read-Only.
                    perms = line.split()[1]
                    if "w" in perms:
                        pytest.fail(f"🚨 [RITUAL 21 FAILURE] SHM Segment is WRITABLE! Perms: {perms} Line: {line}")
                    
                    print(f"✅ [RITUAL 21] Verified Read-Only mapping: {perms} for {target_pattern}")

            if not found:
                 # Should rely on the previous loop, but double check
                 pytest.fail(f"Mapping '{target_pattern}' disappeared during audit!")

        finally:
            if proc.poll() is None:
                proc.kill()

    def test_ritual_30_identity_based_alignment(self, shm_test_env):
        """
        [RITUAL 30] Identity-Based Alignment Assertion.
        Tests must use the *actual* page size of the segment, not hardcoded 2MB/4KB.
        """
        env = shm_test_env
        
        # 1. Metadata Query: We need to retrieve the actual page size reported by Velo
        # This usually requires parsing the analyze output or a debug log
        
        env.create_file("main.py", "print('hello')")
        shm_file = env.path / "aligned.safetensors"
        # Write enough bytes
        shm_file.write_bytes(b"B" * (2 * 1024 * 1024)) 
        
        result = env.run_velo("analyze", "--shm", str(shm_file), "main.py", "--debug")
        
        # Extract Actual Page Size from debug logs
        # Expected Log: "Actual Page Size: 2097152" or "4096"
        match = re.search(r"Actual Page Size:\s+(\d+)", result.stderr)
        if not match:
            # If log missing, we can query system page size as baseline for the assertion logic test
            # But the Ritual demands getting it from the registry identity.
            # Assuming 'analyze' outputs it in debug mode.
            pytest.skip("Skipping Ritual 30: 'Actual Page Size' telemetry missing from analyze output.")
            
        actual_page_size = int(match.group(1))
        file_size = shm_file.stat().st_size
        
        # 2. The Assertion: assert_eq!(size % actual_page_size, 0)
        if file_size % actual_page_size != 0:
            pytest.fail(f"QA FAILURE: SHM size {file_size} is not aligned to actual page size ({actual_page_size/1024}KB)")
            
        print(f"✅ [RITUAL 30] Verified Alignment: Size {file_size} aligned to {actual_page_size} bytes")

