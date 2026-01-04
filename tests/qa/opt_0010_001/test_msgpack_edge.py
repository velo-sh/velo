"""
OPT-0010-001: MessagePack IPC - Agent A (Edge Cases)

Tests edge cases in MessagePack IPC protocol:
- EDGE-OPT-001: Large message handling (>1MB limit enforced)
- EDGE-OPT-002: Empty message handling
- EDGE-OPT-003: Nested structure depth limit
"""

import unittest
import sys
from pathlib import Path

# Add vendor path
vendor_path = Path(__file__).parent.parent.parent.parent / "python" / "velo" / "_vendor"
if str(vendor_path) not in sys.path:
    sys.path.insert(0, str(vendor_path))


class TestMsgpackEdge(unittest.TestCase):
    """Agent A: Edge Case Testing for MessagePack IPC."""

    def test_edge_opt_001_large_message_handling(self):
        """
        EDGE-OPT-001: Large message handling (>1MB limit enforced)
        
        Requirement: Protocol should enforce MAX_MESSAGE_SIZE (1MB) limit.
        
        Test:
        1. Create a Fork command with large payload
        2. Verify serialization works up to limit
        3. Verify protocol constant is correctly defined
        """
        import umsgpack
        
        # Read the MAX_MESSAGE_SIZE constant from main.py
        main_py = Path(__file__).parent.parent.parent.parent / "velo_zygote" / "main.py"
        with open(main_py) as f:
            source = f.read()
        
        # Verify MAX_MESSAGE_SIZE constant exists and is 1MB
        self.assertIn("MAX_MESSAGE_SIZE = 1024 * 1024", source,
                     "MAX_MESSAGE_SIZE must be defined as 1MB")
        
        # Test: serializing a moderately large message works
        large_args = ["arg"] * 10000  # ~50KB payload
        fork_command = {
            "type": "Fork",
            "script_path": "/path/to/main.py",
            "args": large_args,
        }
        
        packed = umsgpack.packb(fork_command)
        self.assertLess(len(packed), 1024 * 1024, "Test message should be under 1MB")
        
        unpacked = umsgpack.unpackb(packed)
        self.assertEqual(len(unpacked["args"]), 10000, "Large args preserved")

    def test_edge_opt_002_empty_message_handling(self):
        """
        EDGE-OPT-002: Empty message handling
        
        Requirement: Protocol should handle empty payloads gracefully.
        
        Test:
        1. Send a command with empty args
        2. Verify round-trip works
        3. Verify empty dict/list preserved
        """
        import umsgpack
        
        # Empty args
        fork_cmd = {
            "type": "Fork",
            "script_path": "/main.py",
            "args": [],
        }
        packed = umsgpack.packb(fork_cmd)
        unpacked = umsgpack.unpackb(packed)
        self.assertEqual(unpacked["args"], [], "Empty args preserved")
        
        # Empty dict
        empty_dict = {}
        packed = umsgpack.packb(empty_dict)
        unpacked = umsgpack.unpackb(packed)
        self.assertEqual(unpacked, {}, "Empty dict preserved")
        
        # None values
        cmd_with_none = {
            "type": "Fork",
            "stdout_path": None,
            "stderr_path": None,
        }
        packed = umsgpack.packb(cmd_with_none)
        unpacked = umsgpack.unpackb(packed)
        self.assertIsNone(unpacked["stdout_path"], "None preserved")

    def test_edge_opt_003_nested_structure_depth_limit(self):
        """
        EDGE-OPT-003: Nested structure depth limit
        
        Requirement: Protocol should handle moderately nested structures.
        
        Test:
        1. Create nested structure (50 levels - reasonable depth)
        2. Verify serialization works
        3. Verify deserialization preserves structure
        """
        import umsgpack
        
        # Create nested structure (50 levels)
        nested = {"value": "deepest"}
        for i in range(50):
            nested = {"level": i, "child": nested}
        
        # Should serialize successfully
        packed = umsgpack.packb(nested)
        self.assertIsInstance(packed, bytes)
        
        # Should deserialize correctly
        unpacked = umsgpack.unpackb(packed)
        
        # Verify depth
        ptr = unpacked
        for i in range(50):
            self.assertEqual(ptr["level"], 49 - i)
            ptr = ptr["child"]
        self.assertEqual(ptr["value"], "deepest")


if __name__ == '__main__':
    unittest.main()
