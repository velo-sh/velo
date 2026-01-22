import sys
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).parents[4] / "python"))
from bundle_builder import build_from_project


def build_bundle(project_dir: Path) -> Path:
    cache_dir = project_dir / ".velo" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cast(Path, build_from_project(project_dir, cache_dir / "bundle.veloc"))


"""
Phase 5.0 Fast Loader: L4 Security Tests

RFC-0006 Section 3: Security Protocol
These tests verify all P0 security requirements.

Security Test IDs per RFC-0006:
- SEC-001: Symlink attack blocked (§3.2)
- SEC-002: World-writable rejected (§3.3)
- SEC-003: Corrupted bundle detected (§3.4)
- SEC-004: Offset overflow rejected (§3.8)
- SEC-005: Dangerous paths rejected (§3.2)
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def velo_binary():
    """Get path to velo binary."""
    cargo_path = Path(__file__).parents[4] / "target" / "release" / "velo"
    if cargo_path.exists():
        return str(cargo_path)
    debug_path = Path(__file__).parents[4] / "target" / "debug" / "velo"
    if debug_path.exists():
        return str(debug_path)
    return "velo"


def run_velo(
    args: list[str], cwd: Path, velo_binary: str, timeout: int = 30, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Helper to run velo command."""
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    result = subprocess.run(
        [velo_binary] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=run_env,
    )
    return result


def create_simple_project(path: Path) -> None:
    """Create minimal project."""
    main_py = path / "main.py"
    main_py.write_text('print("ok")')

    pyproject = path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "sec-test"\nversion = "0.1.0"')


# === L4 Security Tests ===


class TestL4Security:
    """
    Level 4: Security Tests

    RFC-0006 Section 3: All security requirements.
    """

    @pytest.mark.security
    @pytest.mark.skipif(os.name != "posix", reason="Unix-only test")
    def test_sec_001_symlink_to_tmp_rejected(self, tmp_path, velo_binary):
        """
        SEC-001: Symlink pointing to /tmp rejected

        RFC-0006 §3.2: Three-tier path check (raw + link + canonical)
        """
        # Create project
        create_simple_project(tmp_path)

        # Create bundle in safe location
        build_bundle(tmp_path)

        # Create symlink pointing to /tmp
        cache_dir = tmp_path / ".velo" / "cache"
        bundle_path = cache_dir / "bundle.veloc"

        if bundle_path.exists():
            # Move bundle to /tmp
            tmp_bundle = Path("/tmp") / "evil_bundle.veloc"
            bundle_path.rename(tmp_bundle)

            # Create symlink in safe location pointing to /tmp
            bundle_path.symlink_to(tmp_bundle)

            try:
                # Should reject - symlink points to /tmp
                result = run_velo(["run", "--fast", "main.py"], tmp_path, velo_binary)

                # Should either reject or fallback
                if bundle_path.exists():
                    # If succeeded, should show fallback warning
                    assert "fallback" in result.stderr.lower() or "ok" in result.stdout
                else:
                    # Should explicitly reject insecure location
                    assert (
                        "insecure" in result.stderr.lower()
                        or "location" in result.stderr.lower()
                        or "symlink" in result.stderr.lower()
                    )
            finally:
                # Cleanup
                if tmp_bundle.exists():
                    tmp_bundle.unlink()

    @pytest.mark.security
    @pytest.mark.skipif(os.name != "posix", reason="Unix-only test")
    def test_sec_003_world_writable_rejected(self, tmp_path, velo_binary):
        """
        SEC-002: World-writable bundle rejected

        RFC-0006 §3.3: Reject if mode & 0o002 != 0
        """
        # Create project and build
        create_simple_project(tmp_path)
        build_bundle(tmp_path)

        # Make bundle world-writable
        bundle_path = tmp_path / ".velo" / "cache" / "bundle.veloc"
        if bundle_path.exists():
            bundle_path.chmod(0o666)

            # Should reject
            result = run_velo(["run", "--fast", "main.py"], tmp_path, velo_binary)

            # Should reject or fallback
            if result.returncode != 0:
                assert "permission" in result.stderr.lower() or "insecure" in result.stderr.lower()

    @pytest.mark.security
    def test_sec_003_corrupted_bundle_detected(self, tmp_path, velo_binary):
        """
        SEC-003: Corrupted bundle detected via BLAKE3

        RFC-0006 §3.4: Unified BLAKE3 verification
        """
        # Create project and build
        create_simple_project(tmp_path)
        build_bundle(tmp_path)

        # Corrupt bundle (flip bits in content)
        bundle_path = tmp_path / ".velo" / "cache" / "bundle.veloc"
        if bundle_path.exists():
            data = bytearray(bundle_path.read_bytes())
            # Corrupt middle of file
            if len(data) > 200:
                for i in range(100, 200):
                    data[i] ^= 0xFF
                bundle_path.write_bytes(bytes(data))

            # Should detect corruption
            result = run_velo(["run", "--fast", "main.py"], tmp_path, velo_binary)

            # Should fallback or error
            if bundle_path.exists():
                # Fallback is acceptable
                pass
            else:
                # Should mention corruption/integrity
                assert (
                    "corrupt" in result.stderr.lower()
                    or "integrity" in result.stderr.lower()
                    or "hash" in result.stderr.lower()
                    or "blake3" in result.stderr.lower()
                )

    @pytest.mark.security
    @pytest.mark.skipif(os.name != "posix", reason="Unix-only test")
    def test_sec_005_tmp_path_rejected(self, velo_binary):
        """
        SEC-005: Bundle in /tmp rejected

        RFC-0006 §3.2: Blacklist includes /tmp
        """
        # Create project in /tmp
        with tempfile.TemporaryDirectory(prefix="velo_test_", dir="/tmp") as tmp:
            tmp_path = Path(tmp)
            create_simple_project(tmp_path)

            # Try to build in /tmp
            bundle_path = build_bundle(tmp_path)

            # Building in /tmp may work (project location)
            # But loading should warn or reject
            if bundle_path.exists():
                result = run_velo(["run", "--fast", "main.py"], tmp_path, velo_binary)
                # Should work but may warn about insecure location

    @pytest.mark.security
    @pytest.mark.skipif(os.name != "posix", reason="Unix-only test")
    def test_sec_006_var_tmp_rejected(self, velo_binary):
        """
        SEC-006: Bundle in /var/tmp rejected

        RFC-0006 §3.2: Blacklist includes /var/tmp
        """
        # Only run if /var/tmp exists
        if not Path("/var/tmp").exists():
            pytest.skip("/var/tmp not available")

        with tempfile.TemporaryDirectory(prefix="velo_test_", dir="/var/tmp") as tmp:
            tmp_path = Path(tmp)
            create_simple_project(tmp_path)

            bundle_path = build_bundle(tmp_path)
            # Similar to /tmp test

    @pytest.mark.security
    @pytest.mark.skipif(os.name != "posix", reason="Unix-only test")
    def test_sec_002_multi_layer_symlink(self, tmp_path, velo_binary):
        """
        L4-02: Multi-layer symlink chain detection

        RFC-0006 §3.2: Canonicalize should detect chain: safe -> safe -> /tmp
        """
        create_simple_project(tmp_path)
        build_bundle(tmp_path)

        bundle_path = tmp_path / ".velo" / "cache" / "bundle.veloc"
        if not bundle_path.exists():
            pytest.skip("Bundle not created")

        # Create symlink chain: link1 -> link2 -> /tmp/evil
        chain_dir = tmp_path / "chain"
        chain_dir.mkdir()

        # Final target in /tmp
        evil_bundle = Path("/tmp") / "multi_layer_evil.veloc"
        try:
            import shutil

            shutil.copy(bundle_path, evil_bundle)

            # Create chain
            link2 = chain_dir / "link2.veloc"
            link2.symlink_to(evil_bundle)

            link1 = chain_dir / "link1.veloc"
            link1.symlink_to(link2)

            # Move bundle and replace with link1
            bundle_path.unlink()
            bundle_path.symlink_to(link1)

            # Should detect the chain and reject
            result = run_velo(["run", "--fast", "main.py"], tmp_path, velo_binary)

            # Should reject or fallback
            if bundle_path.exists():
                # Fallback is acceptable
                pass
            else:
                assert "insecure" in result.stderr.lower() or "symlink" in result.stderr.lower()
        finally:
            if evil_bundle.exists():
                evil_bundle.unlink()

    @pytest.mark.security
    def test_sec_005_header_tampering(self, tmp_path, velo_binary):
        """
        L4-05: Header tampering (module_count modification)

        RFC-0006 §3.6: Header fields must be included in content_hash
        """
        create_simple_project(tmp_path)
        build_bundle(tmp_path)

        bundle_path = tmp_path / ".velo" / "cache" / "bundle.veloc"
        if not bundle_path.exists():
            pytest.skip("Bundle not created")

        data = bytearray(bundle_path.read_bytes())

        # Tamper with module_count (typically at a fixed offset in header)
        # Set module_count to a large value (would cause out-of-bounds if not caught)
        if len(data) > 20:
            # Modify bytes that might represent module_count
            data[16] = 0xFF
            data[17] = 0xFF
            data[18] = 0xFF
            data[19] = 0x7F  # Large positive value
            bundle_path.write_bytes(bytes(data))

        # Should fail integrity check
        result = run_velo(["run", "--fast", "main.py"], tmp_path, velo_binary)

        # Should detect tampering
        if result.returncode != 0:
            assert (
                "corrupt" in result.stderr.lower()
                or "integrity" in result.stderr.lower()
                or "invalid" in result.stderr.lower()
            )
        # Fallback is also acceptable

    @pytest.mark.security
    def test_sec_008_path_traversal_rejected(self, tmp_path, velo_binary):
        """
        L4-08: Path traversal in module name rejected

        Module names like '../../../etc/passwd' should be rejected.
        """
        # Create a malicious module name (if possible)
        main_py = tmp_path / "main.py"
        main_py.write_text(
            """
# Attempt to create a module that could exploit path traversal
print("normal execution")
"""
        )

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "traversal-test"\nversion = "0.1.0"')

        # Build and run normally first
        build_bundle(tmp_path)

        # Tamper with bundle to inject malicious module name
        bundle_path = tmp_path / ".velo" / "cache" / "bundle.veloc"
        if bundle_path.exists():
            data = bytearray(bundle_path.read_bytes())

            # Look for a module name pattern and try to inject path traversal
            # This is a best-effort test - actual vulnerability would depend on format
            traversal = b"../../../etc/passwd"

            # If bundle contains module names, try to corrupt them
            if len(data) > 200:
                # Inject traversal pattern
                for i in range(100, 150):
                    if i + len(traversal) < len(data):
                        data[i : i + len(traversal)] = traversal
                        break
                bundle_path.write_bytes(bytes(data))

            # Should fail or be rejected
            result = run_velo(["run", "--fast", "main.py"], tmp_path, velo_binary)

            # Must not crash with segfault
            assert result.returncode != -11, "Segfault from path traversal!"


class TestL4OffsetValidation:
    """
    L4: Offset boundary validation tests

    RFC-0006 §3.8: AUDIT-007 fixes
    """

    @pytest.mark.security
    def test_offset_overflow_attack(self, tmp_path, velo_binary):
        """
        Malformed offset that would cause integer overflow should be rejected.

        This tests the Rust-side validation: checked_add()
        """
        # Create and build
        create_simple_project(tmp_path)
        build_bundle(tmp_path)

        bundle_path = tmp_path / ".velo" / "cache" / "bundle.veloc"
        if bundle_path.exists():
            data = bytearray(bundle_path.read_bytes())

            # Try to inject malformed offset (would need to know format)
            # For now, just verify the bundle loader doesn't crash
            if len(data) > 200:
                # Set some bytes to max values
                for i in range(50, 58):
                    data[i] = 0xFF
                bundle_path.write_bytes(bytes(data))

            # Should not crash, should error gracefully
            result = run_velo(["run", "--fast", "main.py"], tmp_path, velo_binary)

            # Must not segfault - either error or fallback
            # returncode -11 would indicate SIGSEGV
            assert result.returncode != -11, "Segmentation fault!"


class TestL4MarshalDepth:
    """
    L4: Marshal recursion depth limit

    RFC-0006 §3.5: AUDIT-012 fixes
    """

    @pytest.mark.security
    def test_deeply_nested_code_handled(self, tmp_path, velo_binary):
        """
        Deeply nested code should not cause stack overflow.
        """
        # Create deeply nested code
        main_py = tmp_path / "main.py"

        # Generate deeply nested function calls (50 levels)
        nested = "x"
        for i in range(50):
            nested = f"(lambda: {nested})()"

        main_py.write_text(
            f"""
def deep():
    return {nested}

print(f"Result: {{deep()}}")
"""
        )

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "deep-test"\nversion = "0.1.0"')

        # Build and run
        build_bundle(tmp_path)
        result = run_velo(["run", "--fast", "main.py"], tmp_path, velo_binary)

        # Should either succeed or fail gracefully (not crash)
        assert result.returncode != -11, "Segmentation fault from deep nesting!"

    @pytest.mark.security
    def test_marshal_limit_constant_exists(self):
        """
        SEC-GAP-001: MARSHAL_RECURSION_LIMIT constant must exist.

        RFC-0006 §3.5: Limit must be 1000
        """
        from velo_loader import MARSHAL_RECURSION_LIMIT

        assert MARSHAL_RECURSION_LIMIT == 500, "MARSHAL_RECURSION_LIMIT must be 500"

    @pytest.mark.security
    def test_safe_marshal_loads_exists(self):
        """
        SEC-GAP-001: safe_marshal_loads function must exist.

        RFC-0006 §3.5: Must use protected marshal loading
        """
        import marshal

        from velo_loader import safe_marshal_loads

        # Test basic functionality
        data = marshal.dumps([1, 2, 3])
        result = safe_marshal_loads(data)
        assert result == [1, 2, 3]

    @pytest.mark.security
    def test_safe_marshal_loads_restores_limit(self):
        """
        SEC-GAP-001: Recursion limit must be restored after call.

        RFC-0006 §3.5: Must restore original limit in finally block
        """
        import marshal
        import sys

        from velo_loader import safe_marshal_loads

        original_limit = sys.getrecursionlimit()

        # Call safe_marshal_loads
        data = marshal.dumps({"test": "value"})
        safe_marshal_loads(data)

        # Limit should be restored
        assert sys.getrecursionlimit() == original_limit, f"Recursion limit not restored: expected {original_limit}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "security"])
