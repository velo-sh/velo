"""
Velo Bundle Builder

RFC-0006 Phase 5.0.2: Build .veloc bundles from Python projects

Usage:
    from bundle_builder import VeloBundleBuilder
    
    builder = VeloBundleBuilder()
    builder.add_module("mymodule", code_bytes, hash_bytes)
    builder.build(Path("bundle.veloc"))
"""

import marshal
import struct
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import blake3 as blake3_module

    HAS_BLAKE3 = True
except ImportError:
    HAS_BLAKE3 = False
    import hashlib

# Bundle format constants
MAGIC = b"VELO"
VERSION = 1
HEADER_SIZE = 128  # Fixed header size for alignment


class ModuleData:
    """Module data for bundle building"""

    __slots__ = ("name", "code", "hash", "is_package")

    def __init__(self, name: str, code: bytes, is_package: bool = False):
        self.name = name
        self.code = code
        self.is_package = is_package

        # Compute BLAKE3 hash
        if HAS_BLAKE3:
            self.hash = blake3_module.blake3(code).digest()
        else:
            self.hash = hashlib.sha256(code).digest()


class VeloBundleBuilder:
    """
    Builds Velo bundles (.veloc) from Python modules

    Bundle format:
    - Header (128 bytes, padded)
    - Data section (module bytecodes, 4KB aligned)
    - Index section (module entries)
    """

    def __init__(self):
        self.modules: List[ModuleData] = []

    def add_pyc(self, name: str, pyc_path: Path, is_package: bool = False) -> None:
        """Add a .pyc file to the bundle"""
        with open(pyc_path, "rb") as f:
            # Skip .pyc header (16 bytes in Python 3.7+)
            f.seek(16)
            code_data = f.read()

        self.modules.append(ModuleData(name, code_data, is_package))

    def add_source(
        self, name: str, source_path: Path, is_package: bool = False, optimize: int = 0
    ) -> None:
        """Add a .py source file (compiles to bytecode)"""
        source = source_path.read_text(encoding="utf-8")
        code = compile(source, str(source_path), "exec", optimize=optimize)
        code_data = marshal.dumps(code)

        self.modules.append(ModuleData(name, code_data, is_package))

    def add_code(self, name: str, code_data: bytes, is_package: bool = False) -> None:
        """Add raw marshalled bytecode"""
        self.modules.append(ModuleData(name, code_data, is_package))

    def build(self, output_path: Path) -> None:
        """Build the bundle file"""
        if not self.modules:
            raise ValueError("No modules to bundle")

        # 1. Build data section and module offsets
        data_section = bytearray()
        module_offsets: list[tuple[ModuleData, int]] = []

        for mod in self.modules:
            file_offset = HEADER_SIZE + len(data_section)
            module_offsets.append((mod, file_offset))
            data_section.extend(mod.code)

            # Align to 4KB boundary
            padding = (4096 - (len(data_section) % 4096)) % 4096
            data_section.extend(b"\x00" * padding)

        # 2. Build index section
        index_buffer = bytearray()
        for mod, offset in module_offsets:
            name_bytes = mod.name.encode("utf-8")
            index_buffer.extend(struct.pack("<H", len(name_bytes)))
            index_buffer.extend(name_bytes)
            index_buffer.extend(struct.pack("<QQ", offset, len(mod.code)))
            index_buffer.extend(mod.hash)
            index_buffer.extend(struct.pack("<B", int(mod.is_package)))

        # 3. RFC-0009: Integration of Static Graph (Section 4)
        # We call the Rust 'velo graph generate' command to get Section 4
        graph_section = bytearray()
        graph_offset = 0

        # Try to find 'velo' binary and run it if possible
        # (For production this would be handled by the velo binary itself)
        import subprocess
        import tempfile
        import os

        velo_bin = os.environ.get("VELO_BIN", "velo")
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # We assume current directory set to project_dir in caller
            # Or we pass it. For now use cwd.
            subprocess.run(
                [velo_bin, "graph", "generate", ".", "--output", tmp_path],
                check=True,
                capture_output=True,
            )
            if os.path.exists(tmp_path):
                graph_section = open(tmp_path, "rb").read()
                os.unlink(tmp_path)

                # Align Section 4 to 4KB (RFC-0009 §2.1)
                graph_padding = (4096 - (len(data_section) % 4096)) % 4096
                # Wait, Section 4 starts after Data Section.
                # So the FILE offset must be 4KB aligned.
                graph_offset = HEADER_SIZE + len(data_section) + graph_padding
        except Exception as e:
            print(f"⚠️  Graph generation failed: {e}")
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        index_offset = (
            (graph_offset + len(graph_section))
            if graph_section
            else (HEADER_SIZE + len(data_section))
        )

        # 4. Construct Header components for H-1 Global Hash
        # Prefix (0..20): MAGIC, VERSION, MODULE_COUNT, INDEX_OFFSET
        header_prefix = bytearray()
        header_prefix.extend(MAGIC)  # 0..4
        header_prefix.extend(struct.pack("<I", VERSION))  # 4..8
        header_prefix.extend(struct.pack("<I", len(self.modules)))  # 8..12
        header_prefix.extend(struct.pack("<Q", index_offset))  # 12..20

        # Header padding (20..128)
        # Bytes 20..52: Content Hash (placeholders)
        # Bytes 52..60: Hash Algo + padding
        # Bytes 60..68: Graph Offset (RFC-0009)
        header_padding = bytearray(HEADER_SIZE - 20)
        if graph_offset:
            struct.pack_into("<Q", header_padding, 60 - 20, graph_offset)

        # RFC-0009 v2.0: Dynamic Security Header Offset
        struct.pack_into("<B", header_padding, 68 - 20, 28)  # 28 for Python 3.11/3.12

        # 5. Compute Global Hash (H-1): Cover Prefix + Padding + Data + Graph + Index
        hasher = None
        if HAS_BLAKE3:
            hasher = blake3_module.blake3()
        else:
            import hashlib

            hasher = hashlib.sha256()

        hasher.update(header_prefix)
        # RFC-0008 H-1: Skip 20..52 (hash slot)
        hasher.update(header_padding[32:])
        hasher.update(data_section)
        if graph_section:
            hasher.update(b"\x00" * graph_padding)
            hasher.update(graph_section)
        hasher.update(index_buffer)
        content_hash = hasher.digest()

        # 6. Write bundle
        with open(output_path, "wb") as f:
            f.write(header_prefix)  # 0..20
            f.write(content_hash)  # 20..52
            f.write(header_padding[32:])  # 52..128
            f.write(data_section)  # 128..graph_offset/index_offset
            if graph_section:
                f.write(b"\x00" * graph_padding)
                f.write(graph_section)
            f.write(index_buffer)  # index_offset..EOF

        print(f"✅ Bundle created: {output_path}")
        print(f"   Modules: {len(self.modules)}")
        print(f"   Size: {output_path.stat().st_size} bytes")


def build_from_project(
    project_dir: Path, output_path: Optional[Path] = None, optimize: int = 0
) -> Path:
    """
    Build a bundle from a Python project directory

    Scans for .py files and compiles them to a bundle.
    """
    if output_path is None:
        output_path = project_dir / "bundle.veloc"

    builder = VeloBundleBuilder()

    # Find all .py files
    for py_file in project_dir.rglob("*.py"):
        # Skip __pycache__ and hidden directories
        if "__pycache__" in str(py_file) or any(
            p.startswith(".") for p in py_file.parts
        ):
            continue

        # Convert path to module name
        rel_path = py_file.relative_to(project_dir)
        parts = list(rel_path.parts)

        if parts[-1] == "__init__.py":
            # Package
            module_name = ".".join(parts[:-1])
            is_package = True
        else:
            # Regular module
            module_name = ".".join(parts[:-1] + [parts[-1].removesuffix(".py")])
            is_package = False

        if module_name:
            builder.add_source(module_name, py_file, is_package, optimize)

    builder.build(output_path)
    return output_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python bundle_builder.py <project_dir> [output.veloc]")
        sys.exit(1)

    project_dir = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    build_from_project(project_dir, output_path)
