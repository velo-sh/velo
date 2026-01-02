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
    
    __slots__ = ('name', 'code', 'hash', 'is_package')
    
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
    
    def add_source(self, name: str, source_path: Path, 
                   is_package: bool = False, optimize: int = 0) -> None:
        """Add a .py source file (compiles to bytecode)"""
        source = source_path.read_text(encoding="utf-8")
        code = compile(source, str(source_path), "exec", optimize=optimize)
        code_data = marshal.dumps(code)
        
        self.modules.append(ModuleData(name, code_data, is_package))
    
    def add_code(self, name: str, code_data: bytes, 
                 is_package: bool = False) -> None:
        """Add raw marshalled bytecode"""
        self.modules.append(ModuleData(name, code_data, is_package))
    
    def build(self, output_path: Path) -> None:
        """Build the bundle file"""
        if not self.modules:
            raise ValueError("No modules to bundle")
        
        # Build data section first, then calculate offsets
        data_section = bytearray()
        module_offsets: list[tuple[ModuleData, int]] = []  # (module, offset_in_file)
        
        for mod in self.modules:
            # Offset in file = HEADER_SIZE + current position in data_section
            file_offset = HEADER_SIZE + len(data_section)
            module_offsets.append((mod, file_offset))
            
            data_section.extend(mod.code)
            
            # Align to 4KB boundary
            padding = (4096 - (len(data_section) % 4096)) % 4096
            data_section.extend(b'\x00' * padding)
        
        # Index starts after data section
        index_offset = HEADER_SIZE + len(data_section)
        
        # Calculate content hash of data section
        if HAS_BLAKE3:
            content_hash = blake3_module.blake3(bytes(data_section)).digest()
        else:
            content_hash = hashlib.sha256(bytes(data_section)).digest()
        
        # Write bundle
        with open(output_path, "wb") as f:
            # Write header
            f.write(MAGIC)                                          # 4 bytes
            f.write(struct.pack("<I", VERSION))                     # 4 bytes
            f.write(struct.pack("<I", len(self.modules)))           # 4 bytes
            f.write(struct.pack("<Q", index_offset))                # 8 bytes
            f.write(content_hash)                                   # 32 bytes
            # Pad header to 128 bytes
            f.write(b'\x00' * (HEADER_SIZE - f.tell()))
            
            # Write data section
            f.write(data_section)
            
            # Write index
            for mod, offset in module_offsets:
                name_bytes = mod.name.encode("utf-8")
                f.write(struct.pack("<H", len(name_bytes)))         # 2 bytes
                f.write(name_bytes)                                 # variable
                f.write(struct.pack("<QQ", offset, len(mod.code)))  # 16 bytes
                f.write(mod.hash)                                   # 32 bytes
                f.write(struct.pack("<B", int(mod.is_package)))     # 1 byte
        
        print(f"✅ Bundle created: {output_path}")
        print(f"   Modules: {len(self.modules)}")
        print(f"   Size: {output_path.stat().st_size} bytes")


def build_from_project(project_dir: Path, output_path: Optional[Path] = None,
                       optimize: int = 0) -> Path:
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
        if "__pycache__" in str(py_file) or any(p.startswith(".") for p in py_file.parts):
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
