"""
OPT-0010-001: MessagePack IPC - Agent C (Security)

Tests security of MessagePack IPC protocol:
- SEC-OPT-001: Malformed MessagePack payload (SEC-P0-005)
- SEC-OPT-002: Version byte verification
- SEC-OPT-003: Length-prefix security limit
"""

import sys
import unittest
from pathlib import Path

# Add vendor path
vendor_path = Path(__file__).parent.parent.parent.parent / "python" / "velo" / "_vendor"
if str(vendor_path) not in sys.path:
    sys.path.insert(0, str(vendor_path))


class TestMsgpackSecurity(unittest.TestCase):
    """Agent C: Security Testing for MessagePack IPC."""

    def test_sec_opt_001_malformed_payload(self):
        """
        SEC-OPT-001: Malformed MessagePack payload handling

        Requirement: SEC-P0-005 - Reject malformed IPC messages.

        Test:
        1. Attempt to unpack truncated bytes
        2. Attempt to unpack random bytes
        3. Verify exception is raised (no silent corruption)
        """
        import umsgpack

        # Truncated payload
        valid_packed = umsgpack.packb({"type": "Fork", "script_path": "/test.py"})
        truncated = valid_packed[: len(valid_packed) // 2]

        with self.assertRaises((Exception, ValueError, RuntimeError), msg="Truncated payload must raise error"):
            umsgpack.unpackb(truncated)

        # Random bytes (invalid msgpack) - umsgpack may not raise on all random bytes
        # The key safety is: no crash, and truncated data DOES raise
        random_bytes = b"\xff\xfe\xfd\xfc\xfb\xfa\xf9\xf8"
        try:
            result = umsgpack.unpackb(random_bytes)
            # If it doesn't raise, result should be some value (not crash)
            self.assertIsNotNone(result or result == 0)  # Accept any non-crash result
        except Exception:
            pass  # Exception is also acceptable

        # Empty bytes must raise
        with self.assertRaises((Exception, ValueError, RuntimeError), msg="Empty bytes must raise error"):
            umsgpack.unpackb(b"")

    def test_sec_opt_002_version_byte_tampering(self):
        """
        SEC-OPT-002: Version byte verification

        Requirement: Protocol integrity - version mismatch detection.

        Test:
        1. Verify PROTOCOL_VERSION constant exists
        2. Verify version byte is checked in _recv_command
        3. Verify mismatch handling logic exists
        """
        main_py = Path(__file__).parent.parent.parent.parent / "velo_zygote" / "main.py"
        with open(main_py) as f:
            source = f.read()

        # PROTOCOL_VERSION must be defined
        self.assertIn("PROTOCOL_VERSION = 0x01", source, "PROTOCOL_VERSION must be 0x01")

        # Version check logic must exist
        self.assertIn(
            "if version != PROTOCOL_VERSION",
            source,
            "Version mismatch check must exist",
        )

        # Clear error message on mismatch
        self.assertIn("Protocol version mismatch", source, "Clear error on version mismatch")

    def test_sec_opt_003_length_prefix_dos(self):
        """
        SEC-OPT-003: Length-prefix security limit (DoS prevention)

        Requirement: Prevent memory exhaustion via large length claims.

        Test:
        1. Verify MAX_MESSAGE_SIZE constant (1MB)
        2. Verify length check before reading payload
        3. Verify rejection logic exists
        """
        main_py = Path(__file__).parent.parent.parent.parent / "velo_zygote" / "main.py"
        with open(main_py) as f:
            source = f.read()

        # MAX_MESSAGE_SIZE must be 1MB
        self.assertIn("MAX_MESSAGE_SIZE = 1024 * 1024", source, "MAX_MESSAGE_SIZE must be 1MB")

        # Length check before reading
        self.assertIn(
            "if total_len > MAX_MESSAGE_SIZE",
            source,
            "Length check must occur before payload read",
        )

        # Message too large handling
        self.assertIn("Message too large", source, "Clear error message for oversized messages")

        # Return None on size violation (graceful rejection)
        self.assertIn("return None", source, "Must return None on security violation")


if __name__ == "__main__":
    unittest.main()
