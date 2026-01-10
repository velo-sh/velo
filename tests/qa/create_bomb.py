import struct
import marshal
import sys
from pathlib import Path


def create_bomb_bundle(output_path: Path, depth: int = 1000):
    # 1. Create deeply nested object
    obj = "x"
    for _ in range(depth):
        obj = (obj,)

    # 2. Marshal it
    payload = marshal.dumps(obj)

    # 3. Build a minimal Velo bundle header
    # Magic (4) + Version (4) + ModuleCount (4) + IndexOffset (8) + Hash (32) + Padding...
    # total header = 128

    magic = b"VELO"
    version = struct.pack("<I", 1)
    module_count = struct.pack("<I", 1)

    index_offset_val = 128 + len(payload)
    index_offset = struct.pack("<Q", index_offset_val)

    # Placeholder hash (will be calculated later if needed, but Rust checks hash first)
    # Actually, verify_blake3 is called BEFORE check_marshal_depth.
    # So I need a valid hash.

    header_prefix = magic + version + module_count + index_offset

    # Create the data stream
    # Identity Prefix (20) + Hash (32) + Padding (76) + Payload + Index

    dummy_hash = b"\x00" * 32
    padding = b"\x00" * 76

    # Bundle = [Prefix(20)] + [Hash(32)] + [Padding(76)] + [Payload] + [Index]

    # Index Entry: name_len(2) + name + offset(8) + size(8) + hash(32) + is_pkg(1)
    name = b"bomb"
    name_len = struct.pack("<H", len(name))
    m_offset = struct.pack("<Q", 128)
    m_size = struct.pack("<Q", len(payload))
    m_hash = b"\x00" * 32
    is_pkg = b"\x00"

    index = name_len + name + m_offset + m_size + m_hash + is_pkg

    bundle_data = bytearray(header_prefix + dummy_hash + padding + payload + index)

    # Calculate Global Hash (H-1)
    import hashlib

    try:
        from blake3 import blake3

        hasher = blake3()
    except ImportError:
        hasher = hashlib.sha256()

    hasher.update(bundle_data[0:20])
    hasher.update(bundle_data[52:])
    actual_hash = hasher.digest()

    bundle_data[20:52] = actual_hash

    output_path.write_bytes(bundle_data)
    print(f"Created bomb bundle at {output_path} (depth={depth})")


if __name__ == "__main__":
    create_bomb_bundle(Path("bomb.veloc"), 1000)
