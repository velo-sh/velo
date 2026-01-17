import sys
from pathlib import Path
from typing import Any

# ============================================================================
# MessagePack Import with Pure Python Fallback (ADV-3)
# ============================================================================
_USING_PURE_PYTHON_MSGPACK = False

try:
    # 1. Try high-performance C extension first
    import msgpack

    if not hasattr(msgpack, "packb"):
        raise ImportError("msgpack installed but packb missing")

    def packer(msg: dict[str, Any]) -> bytes:
        return bytes(msgpack.packb(msg, use_bin_type=True))

    def unpacker(data: bytes) -> Any:
        return msgpack.unpackb(data, raw=False)


except (ImportError, OSError, AttributeError):
    # 2. Fallback to vendored Pure Python implementation
    _fallback_loaded = False

    # Search paths for vendored umsgpack.py
    _search_paths = [
        # Relative to this file: velo_zygote/serializer.py -> python/velo/_vendor
        Path(__file__).parent.parent / "python" / "velo" / "_vendor",
        # If running from project root
        Path.cwd() / "python" / "velo" / "_vendor",
        # If installed as package
        Path(__file__).parent / "_vendor",
    ]

    for _vendor_path in _search_paths:
        if (_vendor_path / "umsgpack.py").exists():
            if str(_vendor_path) not in sys.path:
                sys.path.insert(0, str(_vendor_path))
            try:
                import umsgpack

                # Only log if running as main process to avoid noise
                # sys.stderr.write("[Velo] ⚠️  Warning: fast 'msgpack' extension failed to load. Using pure Python fallback.\n")

                def packer(msg: dict[str, Any]) -> bytes:
                    return bytes(umsgpack.packb(msg))

                def unpacker(data: bytes) -> Any:
                    return umsgpack.unpackb(data)

                _USING_PURE_PYTHON_MSGPACK = True
                _fallback_loaded = True
                break
            except ImportError:
                continue

    if not _fallback_loaded:
        # Define dummy functions that raise error when called,
        # allowing module to import but failing at runtime if used
        def packer(msg: dict[str, Any]) -> bytes:
            raise ImportError("msgpack not installed and fallback umsgpack not found")

        def unpacker(data: bytes) -> Any:
            raise ImportError("msgpack not installed and fallback umsgpack not found")
