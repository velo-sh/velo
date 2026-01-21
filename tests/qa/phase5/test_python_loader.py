from __future__ import annotations

"""
Phase 5.0 Fast Loader: Python Loader Unit Tests

Tests for the Python implementation:
- VeloBundle (velo_loader.py)
- VeloBundleBuilder (bundle_builder.py)

These supplement the architect's tests with additional security/edge cases.
"""

import marshal
import struct
import sys
from pathlib import Path

import pytest

# Add python/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "python"))

from bundle_builder import HEADER_SIZE, VeloBundleBuilder
from velo_loader import MAGIC, MAX_BUNDLE_SIZE, VeloBundle, VeloFinder


class TestBundleSecurity:
    """
    Security tests for VeloBundle

    RFC-0006 §3.1: Size limits
    RFC-0006 §3.4: Integrity verification
    """

    @pytest.mark.security
    def test_bundle_magic_validation(self, tmp_path):
        """
        SEC-PY-001: Invalid magic is rejected
        """
        # Create fake bundle with wrong magic
        fake_bundle = tmp_path / "bad_magic.veloc"

        with open(fake_bundle, "wb") as f:
            f.write(b"EVIL")  # Wrong magic
            f.write(b"\x00" * 124)  # Padding

        bundle = VeloBundle(fake_bundle)

        with pytest.raises(ValueError, match="Invalid bundle magic"):
            bundle.open()

    @pytest.mark.security
    def test_bundle_version_validation(self, tmp_path):
        """
        SEC-PY-002: Unsupported version is rejected
        """
        # Create bundle with future version
        fake_bundle = tmp_path / "bad_version.veloc"

        with open(fake_bundle, "wb") as f:
            f.write(MAGIC)
            f.write(struct.pack("<I", 999))  # Future version
            f.write(struct.pack("<I", 0))  # module_count
            f.write(struct.pack("<Q", 128))  # index_offset
            f.write(b"\x00" * (128 - 20))  # Padding

        bundle = VeloBundle(fake_bundle)

        with pytest.raises(ValueError, match="Unsupported bundle version"):
            bundle.open()

    @pytest.mark.security
    def test_max_bundle_size_constant(self):
        """
        SEC-PY-003: MAX_BUNDLE_SIZE is 256MB
        """
        assert MAX_BUNDLE_SIZE == 256 * 1024 * 1024
        assert MAX_BUNDLE_SIZE == 268_435_456

    @pytest.mark.security
    def test_bundle_too_small_rejected(self, tmp_path):
        """
        SEC-PY-004: Truncated bundle is rejected
        """
        small_bundle = tmp_path / "small.veloc"
        small_bundle.write_bytes(b"VELO" + b"\x00" * 10)  # Only 14 bytes

        bundle = VeloBundle(small_bundle)

        with pytest.raises(ValueError, match="too small"):
            bundle.open()

    @pytest.mark.security
    def test_module_hash_verification(self, tmp_path):
        """
        SEC-PY-005: Module hash tampering is detected
        """
        # Build valid bundle
        builder = VeloBundleBuilder()
        code = compile("x = 1", "<test>", "exec")
        builder.add_code("mymodule", marshal.dumps(code))

        bundle_path = tmp_path / "test.veloc"
        builder.build(bundle_path)

        # Load and verify
        bundle = VeloBundle(bundle_path)
        bundle.open()

        code_data = bundle.get_code("mymodule")

        # Original should verify
        assert bundle.verify_module("mymodule", code_data)

        # Tampered should fail
        tampered = code_data[:-1] + bytes([code_data[-1] ^ 0xFF])
        assert not bundle.verify_module("mymodule", tampered)

        bundle.close()


class TestBundleBuilder:
    """
    Tests for VeloBundleBuilder
    """

    def test_header_size_constant(self):
        """
        BUILDER-001: Header is 128 bytes
        """
        assert HEADER_SIZE == 128

    def test_empty_bundle_rejected(self, tmp_path):
        """
        BUILDER-002: Empty bundle (0 modules) is rejected
        """
        builder = VeloBundleBuilder()

        with pytest.raises(ValueError, match="No modules"):
            builder.build(tmp_path / "empty.veloc")

    def test_package_flag_preserved(self, tmp_path):
        """
        BUILDER-003: is_package flag is preserved
        """
        builder = VeloBundleBuilder()

        # Add package
        code_pkg = compile("PKG = True", "<test>", "exec")
        builder.add_code("mypackage", marshal.dumps(code_pkg), is_package=True)

        # Add module
        code_mod = compile("MOD = True", "<test>", "exec")
        builder.add_code("mymodule", marshal.dumps(code_mod), is_package=False)

        output = tmp_path / "pkg_test.veloc"
        builder.build(output)

        # Verify
        bundle = VeloBundle(output)
        bundle.open()

        assert bundle.index["mypackage"].is_package is True
        assert bundle.index["mymodule"].is_package is False

        bundle.close()


class TestVeloFinder:
    """
    Tests for import hook
    """

    def test_fallback_to_stdlib(self, tmp_path):
        """
        FINDER-001: Non-bundled stdlib modules use fallback
        """
        # Create minimal bundle
        builder = VeloBundleBuilder()
        code = compile("x = 1", "<test>", "exec")
        builder.add_code("custom_only", marshal.dumps(code))

        bundle_path = tmp_path / "minimal.veloc"
        builder.build(bundle_path)

        bundle = VeloBundle(bundle_path)
        bundle.open()

        finder = VeloFinder(bundle)

        # Bundled module returns spec
        spec = finder.find_spec("custom_only", None)
        assert spec is not None

        # stdlib returns None (triggers fallback)
        spec = finder.find_spec("json", None)
        assert spec is None

        spec = finder.find_spec("os", None)
        assert spec is None

        bundle.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
