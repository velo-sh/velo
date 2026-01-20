import struct
from pathlib import Path

import pytest


@pytest.mark.tier0
@pytest.mark.shm
class TestCoreContract:
    """
    L0: Core Contract Tests (TITANIUM MODE).
    Verifies that the MemoryRegistry correctly handles and reports errors
    for invalid inputs and RFC violations.
    """

    def test_L0_error_invalid_name(self, shm_test_env):
        """Verify that an invalid name triggers an error."""
        env = shm_test_env
        try:
            result = env.run_velo("run", "dummy.py", "--shm-name", "invalid\0name")
            # Velo should catch this or the syscall should fail
            assert "InvalidName" in result.stderr or result.returncode != 0
        except ValueError as e:
            if "embedded null byte" in str(e):
                pytest.skip("Python subprocess doesn't support NUL bytes (blocked at test harness level)")
            raise e

    def test_L0_error_missing_file(self, shm_test_env):
        """Verify that a missing source file triggers InvalidSourceFile."""
        env = shm_test_env
        env.create_file("main.py", "print('hello')")
        # Attempt to analyze a non-existent file with SHM
        result = env.run_velo("analyze", "--shm", "non_existent_file.safetensors", "main.py")
        assert "InvalidSourceFile" in result.stderr or "No such file" in result.stderr

    def test_L0_cli_shm_flag_missing_analyze(self, shm_test_env):
        """
        [PROSECUTOR] Verify that 'analyze --shm' is recognized.
        RFC-0015 CLI Integration.
        """
        env = shm_test_env
        result = env.run_velo("analyze", "--help")
        if "--shm" not in result.stdout:
            pytest.fail("REGRESSION: --shm flag DELETED from 'analyze' command! (Finding 004)")

    def test_L0_cli_shm_flag_missing_run(self, shm_test_env):
        """
        [PROSECUTOR] Verify that 'run --shm' is recognized.
        RFC-0015 CLI Integration.
        """
        env = shm_test_env
        result = env.run_velo("run", "--help")
        if "--shm" not in result.stdout:
            pytest.fail("REGRESSION: --shm flag DELETED from 'run' command! (Finding 004)")

    def test_L0_error_header_too_large(self, shm_test_env):
        """
        [PROSECUTOR] Verify that a file with a massive header length header fails.
        H-22: Offset Validation
        """
        env = shm_test_env
        env.create_file("main.py", "print('hello')")
        bad_file = env.path / "massive_header.safetensors"
        # Write 8 bytes indicating 1PB header
        with open(bad_file, "wb") as f:
            f.write(struct.pack("<Q", 1024 * 1024 * 1024 * 1024 * 1024))

        # We try to use --shm if it exists, otherwise we'll fail the CLI test anyway
        result = env.run_velo("analyze", "--shm", str(bad_file), "main.py")

        if "Unknown option: --shm" in result.stderr:
            pytest.skip("CLI flag missing, covered by CLI tests")

        if "HeaderParseFailed" not in result.stderr and "InvalidSourceFile" not in result.stderr:
            pytest.fail("REGRESSION: Velo failed to validate safetensors header length (H-22 Violation)")

    def test_L0_h20_hugepage_erasure(self, shm_test_env):
        """
        [PROSECUTOR] Verify if the binary even contains HugePage capability code.
        H-20: MAP_HUGETLB usage.
        """
        # Fix: use path relative to the test file
        root_dir = Path(__file__).parents[4]
        registry_path = root_dir / "src/shm/registry.rs"
        content = registry_path.read_text()
        if "MAP_HUGETLB" not in content:
            pytest.fail("REGRESSION: H-20 HugePage support (MAP_HUGETLB) is MISSING from implementation! (Finding 002)")

    def test_L0_h20_hugepage_integrity(self, shm_test_env):
        """
        [PROSECUTOR] Verify that MFD_HUGETLB is used for memfd creation.
        H-20: HugePage Support.
        """
        root_dir = Path(__file__).parents[4]
        registry_path = root_dir / "src/shm/registry.rs"
        content = registry_path.read_text()

        has_mfd = "MFD_HUGETLB" in content

        if not has_mfd:
            pytest.fail("REGRESSION: H-20 HugePage support (MFD_HUGETLB) is MISSING! This is a TITANIUM Requirement.")

    def test_L0_alignment_integrity(self, shm_test_env):
        """
        [PROSECUTOR] Verify that data with odd header length triggers H-29 logic.
        """
        env = shm_test_env
        env.create_file("main.py", "print('hello')")
        header = b'{"t":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}'
        header_len = len(header)

        test_file = env.path / "unaligned.safetensors"
        with open(test_file, "wb") as f:
            f.write(struct.pack("<Q", header_len))
            f.write(header)
            f.write(b"\x00\x00\x00\x00")

        result = env.run_velo("analyze", "--shm", str(test_file), "main.py")

        if "Unknown option: --shm" in result.stderr:
            pytest.skip("CLI flag missing, covered by CLI tests")

        if "⚠️ H-29 Alignment Warning" in result.stderr:
            pytest.fail(
                "REGRESSION: H-29 Padding logic is BROKEN! (Simulation warning detected instead of enforcement)"
            )
