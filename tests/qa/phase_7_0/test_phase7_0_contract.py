import pytest
import os
import struct
from pathlib import Path

@pytest.mark.tier0
@pytest.mark.shm
class TestCoreContract:
    """
    L0: Core Contract Tests (TITANIUM MODE).
    Verifies that the MemoryRegistry correctly handles and reports errors 
    for invalid inputs and RFC violations.
    """

    def test_L0_error_invalid_name(self, shm_test_env):
        """Verify that an invalid name (with NUL) triggers an error."""
        env = shm_test_env
        # We can't easily trigger this from Python if Velo cleans it, 
        # but let's try passing a name that might cause issues.
        # RFC-0015 H-33: Typed Error Disciplines
        result = env.run_velo("run", "dummy.py", "--shm-name", "invalid\0name")
        # Velo should catch this or the syscall should fail
        assert "InvalidName" in result.stderr or result.returncode != 0

    def test_L0_error_missing_file(self, shm_test_env):
        """Verify that a missing source file triggers InvalidSourceFile."""
        env = shm_test_env
        # Attempt to analyze a non-existent file with SHM
        result = env.run_velo("analyze", "--shm", "non_existent_file.safetensors")
        assert "InvalidSourceFile" in result.stderr or "No such file" in result.stderr

    def test_L0_error_header_too_large(self, shm_test_env):
        """
        [PROSECUTOR] Verify that a file with a massive header length header fails.
        H-22: Offset Validation
        """
        env = shm_test_env
        bad_file = env.path / "massive_header.safetensors"
        # Write 8 bytes indicating 1PB header
        with open(bad_file, "wb") as f:
            f.write(struct.pack("<Q", 1024 * 1024 * 1024 * 1024 * 1024))
        
        result = env.run_velo("analyze", "--shm", str(bad_file))
        
        # CURRENT REGRESSION: The dev code just does a single copy of 'metadata.len()'
        # based on the file size, and doesn't even READ the header length (line 52).
        # This test SHOULD fail if it doesn't find HeaderParseFailed or similar.
        if "HeaderParseFailed" not in result.stderr and "InvalidSourceFile" not in result.stderr:
            pytest.fail("REGRESSION: Velo failed to validate safetensors header length (H-22 Violation)")

    def test_L0_alignment_integrity(self, shm_test_env):
        """
        [PROSECUTOR] Verify that data with odd header length triggers H-29 logic.
        """
        env = shm_test_env
        # 1 byte header -> needs 55 bytes padding
        header = b'{"t":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}'
        header_len = len(header)
        
        test_file = env.path / "unaligned.safetensors"
        with open(test_file, "wb") as f:
            f.write(struct.pack("<Q", header_len))
            f.write(header)
            f.write(b"\x00\x00\x00\x00") # 4 bytes data
            
        # Run analyze
        result = env.run_velo("analyze", "--shm", str(test_file))
        
        # In a TITANIUM implementation, this should either work (with padding) 
        # OR fail if the file is truly malformed. 
        # But here we want to check if the implementation ADMITTED it didn't align.
        # Developer log warning check (from finding 001)
        if "⚠️ H-29 Alignment Warning" in result.stderr:
            pytest.fail("REGRESSION: H-29 Padding logic is missing! (Simulation warning detected)")
