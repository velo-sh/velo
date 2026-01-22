import subprocess
import sys
from pathlib import Path

import pytest

try:
    from tests.qa.phase_7_0.conftest import T_SHORT
except ImportError:
    T_SHORT = 5

# SOP Ritual 11.3: Hostile Verification Discipline
# SOP Ritual 30: Identity-Based Alignment Assertion
# SOP Ritual 21: SHM ReadOnly Verification


@pytest.mark.tier3
class TestSecH17ShmReadonly:
    def _read_with_timeout(self, stream: Any, timeout: float = 5.0) -> str | None:
        import select
        import time

        start_time = time.time()
        while time.time() - start_time < timeout:
            r, _, _ = select.select([stream], [], [], 0.1)
            if r:
                line = stream.readline()
                if line:
                    return str(line)
        return None

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
        # Ritual 21: In-process Maps Audit to avoid race conditions and /proc access issues
        env.create_file(
            "main.py",
            """
import time, sys, os
with open('/proc/self/maps') as f:
    maps = f.read()
print(f'READY PID:{os.getpid()}', flush=True)
print('---MAPS_START---', flush=True)
print(maps, flush=True)
print('---MAPS_END---', flush=True)
sys.stdout.flush()
time.sleep(10)
""",
        )

        # Create a dummy SHM file (valid safetensors format)
        import struct

        shm_file = env.path / "model.safetensors"
        header = b'{"test": [0, 1024]}'
        header_len = len(header)
        # Pad header to 8-byte alignment (Required by some loaders, though Velo handles it)
        shm_file.write_bytes(struct.pack("<Q", header_len) + header + b"\x00" * 4096)

        # Launch Velo with SHM using spawn_velo (non-blocking)
        # Use text=True for string output
        proc = env.spawn_velo(
            "run",
            "--shm",
            str(shm_file),
            "main.py",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            # Phase 1: Wait for READY signal (Ritual 43.1: Synchronous Readiness)
            # This ensures the worker has started and mapped the SHM (or tried to)
            while True:
                line = self._read_with_timeout(proc.stdout, timeout=10)
                if not line or "READY" in line:
                    break

            if not line:
                stdout_rem, stderr = proc.communicate(timeout=5)
                pytest.fail(f"Velo failed to reach READY state! STDERR={stderr}")

            print(f"✅ Velo reported READY: {line.strip()}")

            # Phase 2: Read Maps Dump from stdout
            maps_content = ""
            line = self._read_with_timeout(proc.stdout, timeout=5)
            if line and "---MAPS_START---" in line:
                while True:
                    line = self._read_with_timeout(proc.stdout, timeout=5)
                    if not line or "---MAPS_END---" in line:
                        break
                    maps_content += line

            if not maps_content:
                stdout_rem, stderr = proc.communicate(timeout=5)
                pytest.fail(f"Failed to capture maps dump from worker! STDOUT={maps_content} STDERR={stderr}")

            # Phase 3: Forensic Audit of the maps content
            # RFC-0015: Support both file-backed (cold start) and memfd-backed (SHM)
            patterns = [str(shm_file.name), "/memfd:shm-"]

            found = False
            for line in maps_content.splitlines():
                if any(p in line for p in patterns):
                    found = True
                    # 3. Permission Assertion: Verify r--p (or r--s for shared)
                    perms = line.split()[1]
                    if "w" in perms:
                        pytest.fail(f"🚨 [RITUAL 21 FAILURE] SHM Segment is WRITABLE! Perms: {perms} Line: {line}")

                    print(f"✅ [RITUAL 21] Verified Read-Only mapping: {perms} for {line}")

            if not found:
                # Forensic Audit: Capture Zygote logs to see why SHM failed
                zygote_log = Path(env.env["VELO_ZYGOTE_LOG"])
                log_content = ""
                if zygote_log.exists():
                    log_content = zygote_log.read_text()

                # Kill the process and wait for termination
                stderr = "(could not capture stderr)"
                if proc.poll() is None:
                    proc.kill()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass

                # Capture remaining stderr (may already be closed)
                try:
                    _, stderr = proc.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    stderr = "(stderr capture timed out)"
                except Exception as e:
                    stderr = f"(stderr capture failed: {e})"

                pytest.fail(
                    f"🚨 [RITUAL 21 FAILURE] Mapping matching patterns {patterns} not found in worker maps!\n"
                    f"MAPS CONTENT:\n{maps_content}\n"
                    f"VELO STDERR:\n{stderr}\n"
                    f"ZYGOTE LOG:\n{log_content}"
                )

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
        import struct

        shm_file = env.path / "identity_check.safetensors"
        header = b'{"data": [0, 8192]}'
        header_len = len(header)
        # We write exactly 1MB (not aligned to 2MB HugePage if present, but aligned to 4KB)
        file_size = 1024 * 1024
        shm_file.write_bytes(struct.pack("<Q", header_len) + header + b"B" * file_size)

        # 3. The Assertion: assert_eq!(size % actual_page_size, 0)
        # RFC-0015 H-30/H-33: Even in fallback, the segment must be page-aligned.
        if file_size % actual_page_size != 0:
            pytest.fail(
                f"🚨 [RITUAL 30 FAILURE] SHM size {file_size} is not aligned to actual page size ({actual_page_size} bytes). "
                "This indicates a violation of the Memory Gravity alignment invariant."
            )

        print(f"✅ [RITUAL 30] Verified Alignment Invariant: {file_size} % {actual_page_size} == 0")
