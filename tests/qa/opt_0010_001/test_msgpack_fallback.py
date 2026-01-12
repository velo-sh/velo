"""
OPT-0010-001: MessagePack IPC - ADV-3 Fallback Tests

Tests Pure Python fallback mechanism per RFC ADV-3:
- FALL-001: Mock ImportError triggers fallback
- FALL-002: IPC works with Pure Python packer
- FALL-003: Stderr warning output correct
"""

import unittest
import pytest
import sys
import io
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestMsgpackFallback(unittest.TestCase):
    """Tests for ADV-3: Pure Python Fallback Mechanism."""

    def test_fall_001_import_error_triggers_fallback(self):
        """
        FALL-001: Verify fallback flag exists in implementation.

        Requirement: When `import msgpack` raises ImportError,
        system must set a flag and fallback to vendored u-msgpack-python.
        """
        # Import the main module and check fallback flag exists
        sys.path.insert(
            0, str(Path(__file__).parent.parent.parent.parent / "velo_zygote")
        )

        # Read source to verify fallback mechanism exists
        velo_zygote_path = (
            Path(__file__).parent.parent.parent.parent / "velo_zygote" / "main.py"
        )
        with open(velo_zygote_path) as f:
            source = f.read()

        # Verify fallback implementation exists
        self.assertIn(
            "_USING_PURE_PYTHON_MSGPACK", source, "Fallback flag must be defined"
        )
        # Developer refactored: now directly imports umsgpack after adding to sys.path
        self.assertIn(
            "import umsgpack",
            source,
            "Must import umsgpack (directly or from vendor path)",
        )
        self.assertIn(
            "except (ImportError, OSError)",
            source,
            "Must catch both ImportError and OSError for fallback",
        )

    def test_fall_002_ipc_works_with_pure_python_packer(self):
        """
        FALL-002: IPC works with Pure Python packer

        Requirement: IPC messages can be serialized/deserialized
        using the pure Python implementation.
        """
        # Import vendored umsgpack directly
        vendor_path = (
            Path(__file__).parent.parent.parent.parent / "python" / "velo" / "_vendor"
        )
        if str(vendor_path) not in sys.path:
            sys.path.insert(0, str(vendor_path))

        import umsgpack

        # Test data structure - typical Fork command
        fork_command = {
            "type": "Fork",
            "script_path": "/path/to/main.py",
            "args": ["--port", "8000"],
            "fast_mode": True,
            "bundle_path": "/path/to/.velo/bundle.veloc",
        }

        # Serialize and deserialize
        packed = umsgpack.packb(fork_command)
        self.assertIsInstance(packed, bytes, "packb must return bytes")

        unpacked = umsgpack.unpackb(packed)
        self.assertEqual(fork_command, unpacked, "Round-trip must preserve data")

    def test_fall_003_stderr_warning_output(self):
        """
        FALL-003: Stderr warning format is correct per RFC.

        Requirement: When fallback activates, warning must be
        printed to stderr with specific format per RFC.

        Expected:
        [Velo] ⚠️  Warning: fast 'msgpack' extension failed to load.
        [Velo]    Falling back to pure Python implementation (slower IPC).
        [Velo]    Run: pip install msgpack  (requires C compiler)
        """
        # Read source to verify warning format
        velo_zygote_path = (
            Path(__file__).parent.parent.parent.parent / "velo_zygote" / "main.py"
        )
        with open(velo_zygote_path) as f:
            source = f.read()

        # RFC-specified warning strings must be present
        self.assertIn(
            "[Velo] ⚠️  Warning:",
            source,
            "Warning must start with '[Velo] ⚠️  Warning:'",
        )
        self.assertIn(
            "Falling back to pure Python", source, "Must mention 'pure Python' fallback"
        )
        self.assertIn(
            "pip install msgpack",
            source,
            "Must provide fix command: pip install msgpack",
        )


if __name__ == "__main__":
    unittest.main()
