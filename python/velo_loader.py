"""
Velo Fast Loader - Python Import Hook

RFC-0006 Phase 5.0.2: VeloBundle + VeloFinder + VeloLoader

This module provides:
- VeloBundle: Memory-efficient bundle loading with BLAKE3 verification
- VeloFinder: MetaPathFinder for import hook registration
- VeloLoader: Loader with fallback and __path__ support

Usage:
    from velo_loader import VeloBundle, install_hook
    
    bundle = VeloBundle(Path("bundle.veloc"))
    bundle.open()
    install_hook(bundle)
    
    import my_module  # Served from bundle
"""

import importlib.abc
import importlib.machinery
import marshal
import struct
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    import blake3 as blake3_module
    HAS_BLAKE3 = True
except ImportError:
    HAS_BLAKE3 = False
    import hashlib

# Bundle format constants (must match Rust implementation)
MAGIC = b"VELO"
VERSION = 1
MAX_BUNDLE_SIZE = 256 * 1024 * 1024  # 256MB security limit

# RFC-0006 §3.5: Marshal Recursion Limit (AUDIT-012)
# Prevents Stack Overflow attacks via deeply nested bytecode
MARSHAL_RECURSION_LIMIT = 1000


def safe_marshal_loads(data: bytes) -> object:
    """
    Load marshalled data with recursion depth protection.
    
    RFC-0006 §3.5: Deeply nested bytecode can cause Stack Overflow.
    This function temporarily lowers the recursion limit during marshal.loads().
    """
    import sys
    old_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(MARSHAL_RECURSION_LIMIT)
        return marshal.loads(data)
    finally:
        sys.setrecursionlimit(old_limit)


class ModuleEntry:
    """Module entry from bundle index"""
    
    __slots__ = ('name', 'offset', 'size', 'hash', 'is_package')
    
    def __init__(self, name: str, offset: int, size: int, 
                 hash_bytes: bytes, is_package: bool = False):
        self.name = name
        self.offset = offset
        self.size = size
        self.hash = hash_bytes
        self.is_package = is_package


class VeloBundle:
    """
    Velo bundle (.veloc) reader with BLAKE3 verification
    
    RFC-0006 Section 2.7: Single read + memoryview (no mmap for Phase 5.0)
    
    Security:
    - 256MB size limit (DoS prevention)
    - BLAKE3 verification per module
    - Atomic read before any parsing
    """
    
    def __init__(self, path: Path):
        self.path = path
        self.data: Optional[bytes] = None
        self.view: Optional[memoryview] = None
        self.index: Dict[str, ModuleEntry] = {}
        self._content_hash: Optional[bytes] = None
        self._index_offset: int = 0
    
    def open(self) -> None:
        """
        Load bundle into memory (atomic read)
        
        RFC-0006 Section 3.1: Read → Verify → Load sequence
        """
        # Security: Size check before read
        file_size = self.path.stat().st_size
        if file_size > MAX_BUNDLE_SIZE:
            raise ValueError(
                f"Bundle too large: {file_size} bytes > {MAX_BUNDLE_SIZE} bytes"
            )
        
        # Atomic read entire file
        self.data = self.path.read_bytes()
        self.view = memoryview(self.data)
        
        # Parse and verify
        self._read_header()
        self._verify_content_hash()
    
    def close(self) -> None:
        """Release resources"""
        if self.view:
            self.view.release()
        self.data = None
        self.view = None
        self.index.clear()
    
    def _read_header(self) -> None:
        """Parse bundle header and module index"""
        if len(self.data) < 20:
            raise ValueError("Bundle too small")
        
        # Verify magic
        magic = bytes(self.view[:4])
        if magic != MAGIC:
            raise ValueError(f"Invalid bundle magic: {magic!r}")
        
        # Read header fields
        version, module_count, index_offset = struct.unpack(
            "<IIQ", bytes(self.view[4:20])
        )
        
        if version != VERSION:
            raise ValueError(f"Unsupported bundle version: {version}")
        
        # Store index offset for hash verification
        self._index_offset = index_offset
        
        # Read content hash (bytes 20-52)
        self._content_hash = bytes(self.view[20:52])
        
        # Parse module index
        pos = index_offset
        for _ in range(module_count):
            entry = self._read_index_entry(pos)
            self.index[entry.name] = entry
            # Calculate next entry position
            name_len = struct.unpack("<H", bytes(self.view[pos:pos+2]))[0]
            pos += 2 + name_len + 8 + 8 + 32 + 1  # name_len + name + offset + size + hash + is_pkg
    
    def _read_index_entry(self, pos: int) -> ModuleEntry:
        """Read a single module entry from index"""
        # Read name length and name
        name_len = struct.unpack("<H", bytes(self.view[pos:pos+2]))[0]
        pos += 2
        name = bytes(self.view[pos:pos+name_len]).decode("utf-8")
        pos += name_len
        
        # Read offset, size
        offset, size = struct.unpack("<QQ", bytes(self.view[pos:pos+16]))
        pos += 16
        
        # Read BLAKE3 hash
        hash_bytes = bytes(self.view[pos:pos+32])
        pos += 32
        
        # Read is_package flag
        is_package = bool(self.view[pos])
        
        return ModuleEntry(name, offset, size, hash_bytes, is_package)
    
    def _verify_content_hash(self) -> None:
        """
        Verify bundle integrity using BLAKE3
        
        RFC-0006 Section 3.4: Unified BLAKE3 Verification
        """
        if self._content_hash is None:
            return
        
        # Hash data section only (from header end to index offset)
        # Builder hashes data_section which ends at index_offset
        data_section = bytes(self.view[128:self._index_offset])
        
        if HAS_BLAKE3:
            actual = blake3_module.blake3(data_section).digest()
        else:
            # Fallback to SHA-256 if blake3 not installed
            actual = hashlib.sha256(data_section).digest()
        
        if actual != self._content_hash:
            raise ValueError("Bundle content hash verification failed")
    
    def get_code(self, name: str) -> Optional[bytes]:
        """
        Get marshalled bytecode for a module
        
        Returns None if module not in bundle (triggers fallback)
        """
        if name not in self.index:
            return None
        
        entry = self.index[name]
        return bytes(self.view[entry.offset:entry.offset + entry.size])
    
    def verify_module(self, name: str, data: bytes) -> bool:
        """
        Verify module integrity using BLAKE3
        
        Called before marshal.loads() for security
        """
        if name not in self.index:
            return False
        
        entry = self.index[name]
        
        if HAS_BLAKE3:
            actual = blake3_module.blake3(data).digest()
        else:
            actual = hashlib.sha256(data).digest()
        
        return actual == entry.hash
    
    def __contains__(self, name: str) -> bool:
        return name in self.index
    
    def __len__(self) -> int:
        return len(self.index)


class VeloFinder(importlib.abc.MetaPathFinder):
    """
    Import hook that finds modules in Velo bundle
    
    RFC-0006 Section 2.9: Fallback Mechanism
    - Returns ModuleSpec for bundled modules
    - Returns None for non-bundled (fallback to standard import)
    """
    
    def __init__(self, bundle: VeloBundle, project_root: Optional[Path] = None):
        self.bundle = bundle
        self.project_root = project_root or Path.cwd()
    
    def find_spec(self, fullname: str, path, target=None):
        """Find module spec for import"""
        if fullname not in self.bundle:
            return None  # Fallback to standard import
        
        entry = self.bundle.index[fullname]
        
        return importlib.machinery.ModuleSpec(
            fullname,
            VeloLoader(self.bundle, fullname, self.project_root),
            is_package=entry.is_package,
            origin=f"<velo-bundle:{self.bundle.path}:{fullname}>"
        )


class VeloLoader(importlib.abc.Loader):
    """
    Loader that loads modules from Velo bundle
    
    RFC-0006 Section 5 (Handover):
    - BLAKE3 verification before marshal.loads()
    - Set __file__ to original source path
    - Handle __path__ for packages (disk plugin support)
    """
    
    def __init__(self, bundle: VeloBundle, name: str, 
                 project_root: Optional[Path] = None):
        self.bundle = bundle
        self.name = name
        self.project_root = project_root or Path.cwd()
    
    def create_module(self, spec):
        """Use default module creation"""
        return None
    
    def exec_module(self, module) -> None:
        """Execute module code from bundle"""
        # Get marshalled bytecode
        code_data = self.bundle.get_code(self.name)
        if code_data is None:
            raise ImportError(f"Cannot find {self.name} in bundle")
        
        # BLAKE3 verification before marshal.loads()
        # RFC-0006 Section 3.1: Mandatory security check
        if not self.bundle.verify_module(self.name, code_data):
            raise ImportError(
                f"Module {self.name} failed integrity verification"
            )
        
        # Load code object with recursion protection
        # RFC-0006 §3.5: Use safe_marshal_loads() to prevent stack overflow
        code = safe_marshal_loads(code_data)
        
        # Set __file__ to original source path
        # RFC-0006: Point to real file for debugging/tracebacks
        module.__file__ = self._get_original_path()
        
        # Handle __path__ for packages
        # RFC-0006 Section 5: Allow disk plugins to be discovered
        entry = self.bundle.index[self.name]
        if entry.is_package:
            self._setup_package_path(module)
        
        # Execute module code
        exec(code, module.__dict__)
    
    def _get_original_path(self) -> str:
        """Get original source file path for __file__"""
        # Convert module name to path
        parts = self.name.split(".")
        
        # Try common patterns
        for suffix in [".py", "/__init__.py"]:
            candidate = self.project_root / Path(*parts).with_suffix("").parent / (parts[-1] + suffix)
            if candidate.exists():
                return str(candidate)
        
        # Fallback: virtual path
        return f"<velo-bundle:{self.bundle.path}:{self.name}>"
    
    def _setup_package_path(self, module) -> None:
        """
        Set up __path__ for package modules
        
        RFC-0006 Section 5: Allow disk extensions (plugins) to be found
        """
        if not hasattr(module, "__path__"):
            module.__path__ = []
        
        # Find package directory on disk
        parts = self.name.split(".")
        disk_path = self.project_root / Path(*parts)
        
        if disk_path.is_dir() and str(disk_path) not in module.__path__:
            module.__path__.append(str(disk_path))


def install_hook(bundle: VeloBundle, 
                 project_root: Optional[Path] = None) -> VeloFinder:
    """
    Install Velo import hook at sys.meta_path[0]
    
    Returns the finder instance for later removal if needed.
    """
    finder = VeloFinder(bundle, project_root)
    sys.meta_path.insert(0, finder)
    return finder


def uninstall_hook(finder: VeloFinder) -> None:
    """Remove Velo import hook"""
    if finder in sys.meta_path:
        sys.meta_path.remove(finder)


# Convenience function for velo run --fast
def activate_fast_mode(bundle_path: Path, 
                       project_root: Optional[Path] = None) -> VeloBundle:
    """
    Activate fast loader mode
    
    Called from sitecustomize.py injected by velo run --fast
    """
    bundle = VeloBundle(bundle_path)
    bundle.open()
    install_hook(bundle, project_root)
    return bundle


if __name__ == "__main__":
    # Simple test
    import sys
    if len(sys.argv) < 2:
        print("Usage: python velo_loader.py <bundle.veloc>")
        sys.exit(1)
    
    bundle_path = Path(sys.argv[1])
    bundle = VeloBundle(bundle_path)
    bundle.open()
    
    print(f"Bundle: {bundle_path}")
    print(f"Modules: {len(bundle)}")
    for name, entry in bundle.index.items():
        pkg = " [pkg]" if entry.is_package else ""
        print(f"  - {name}: {entry.size} bytes @ {entry.offset}{pkg}")
    
    bundle.close()
