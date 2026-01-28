#!/usr/bin/env python3
"""
Velo Fast Loader Prototype

This script demonstrates:
1. Building a bundle from multiple .pyc files
2. Loading modules from mmap'd bundle via import hook
3. Benchmarking I/O reduction

Usage:
    python prototype_fast_loader.py build <project_dir>  # Create bundle
    python prototype_fast_loader.py run <entry_point>    # Run with bundle
    python prototype_fast_loader.py benchmark            # Compare performance
"""

import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import marshal
import mmap
import struct
import sys
import time
from pathlib import Path

# Bundle format constants
MAGIC = b"VELO"
VERSION = 1


class VeloBundle:
    """Represents a Velo bundle (.veloc file)"""

    def __init__(self, path: Path):
        self.path = path
        self.mm: mmap.mmap | None = None
        self.index: dict[str, tuple[int, int, bytes]] = {}  # name -> (offset, size, hash)
        self._fd = None

    def open(self):
        """Memory-map the bundle file"""
        self._fd = open(self.path, "rb")
        self.mm = mmap.mmap(self._fd.fileno(), 0, access=mmap.ACCESS_READ)
        self._read_header()

    def close(self):
        if self.mm:
            self.mm.close()
        if self._fd:
            self._fd.close()

    def _read_header(self):
        """Parse bundle header and index"""
        # Read magic
        magic = self.mm[:4]
        if magic != MAGIC:
            raise ValueError(f"Invalid bundle magic: {magic}")

        # Read version and module count
        version, module_count, index_offset = struct.unpack("<IIQ", self.mm[4:20])

        if version != VERSION:
            raise ValueError(f"Unsupported bundle version: {version}")

        # Read index
        pos = index_offset
        for _ in range(module_count):
            # Read name length and name
            name_len = struct.unpack("<H", self.mm[pos : pos + 2])[0]
            pos += 2
            name = self.mm[pos : pos + name_len].decode("utf-8")
            pos += name_len

            # Read offset, size, hash
            offset, size = struct.unpack("<QQ", self.mm[pos : pos + 16])
            pos += 16
            code_hash = bytes(self.mm[pos : pos + 32])
            pos += 32

            self.index[name] = (offset, size, code_hash)

    def get_code(self, name: str) -> bytes | None:
        """Get marshalled code for a module"""
        if name not in self.index:
            return None
        offset, size, _ = self.index[name]
        return bytes(self.mm[offset : offset + size])

    def __contains__(self, name: str) -> bool:
        return name in self.index


class VeloBundleBuilder:
    """Builds a Velo bundle from .pyc files"""

    def __init__(self):
        self.modules: dict[str, bytes] = {}  # name -> marshalled code

    def add_pyc(self, name: str, pyc_path: Path):
        """Add a .pyc file to the bundle"""
        with open(pyc_path, "rb") as f:
            # Skip .pyc header (16 bytes in Python 3.7+)
            f.seek(16)
            code_data = f.read()
            self.modules[name] = code_data

    def add_module(self, name: str, code_data: bytes):
        """Add raw marshalled code"""
        self.modules[name] = code_data

    def build(self, output_path: Path):
        """Write the bundle to a file"""
        # Calculate data section
        data_offset = 20  # Header size
        module_data = []
        index_entries = []

        current_offset = data_offset
        for name, code in self.modules.items():
            code_hash = hashlib.sha256(code).digest()
            index_entries.append((name, current_offset, len(code), code_hash))
            module_data.append(code)
            current_offset += len(code)

        index_offset = current_offset

        with open(output_path, "wb") as f:
            # Write header
            f.write(MAGIC)
            f.write(struct.pack("<IIQ", VERSION, len(self.modules), index_offset))

            # Write data section
            for code in module_data:
                f.write(code)

            # Write index
            for name, offset, size, code_hash in index_entries:
                name_bytes = name.encode("utf-8")
                f.write(struct.pack("<H", len(name_bytes)))
                f.write(name_bytes)
                f.write(struct.pack("<QQ", offset, size))
                f.write(code_hash)

        print(f"✅ Bundle created: {output_path}")
        print(f"   Modules: {len(self.modules)}")
        print(f"   Size: {output_path.stat().st_size} bytes")


class VeloFinder(importlib.abc.MetaPathFinder):
    """Import hook that finds modules in Velo bundle"""

    def __init__(self, bundle: VeloBundle):
        self.bundle = bundle

    def find_spec(self, fullname, path, target=None):
        if fullname in self.bundle:
            return importlib.machinery.ModuleSpec(fullname, VeloLoader(self.bundle, fullname), is_package=False)
        return None


class VeloLoader(importlib.abc.Loader):
    """Loader that loads modules from Velo bundle"""

    def __init__(self, bundle: VeloBundle, name: str):
        self.bundle = bundle
        self.name = name

    def create_module(self, spec):
        return None  # Use default module creation

    def exec_module(self, module):
        code_data = self.bundle.get_code(self.name)
        if code_data is None:
            raise ImportError(f"Cannot find {self.name} in bundle")

        code = marshal.loads(code_data)
        exec(code, module.__dict__)


def install_hook(bundle: VeloBundle):
    """Install the Velo import hook"""
    finder = VeloFinder(bundle)
    sys.meta_path.insert(0, finder)
    return finder


def benchmark_import(module_name: str, iterations: int = 10):
    """Benchmark import performance"""
    times = []

    for _ in range(iterations):
        # Clear module cache
        if module_name in sys.modules:
            del sys.modules[module_name]

        start = time.perf_counter()
        __import__(module_name)
        end = time.perf_counter()
        times.append((end - start) * 1000)

    avg = sum(times) / len(times)
    return avg


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "build":
        # Build bundle from a directory
        if len(sys.argv) < 3:
            print("Usage: prototype_fast_loader.py build <project_dir>")
            sys.exit(1)

        project_dir = Path(sys.argv[2])
        builder = VeloBundleBuilder()

        # Find all .pyc files
        pycache = project_dir / "__pycache__"
        if pycache.exists():
            for pyc in pycache.glob("*.pyc"):
                # Extract module name from filename
                # Format: module.cpython-312.pyc
                name = pyc.stem.rsplit(".", 1)[0]
                builder.add_pyc(name, pyc)

        output = project_dir / "bundle.veloc"
        builder.build(output)

    elif cmd == "info":
        # Show bundle info
        if len(sys.argv) < 3:
            print("Usage: prototype_fast_loader.py info <bundle.veloc>")
            sys.exit(1)

        bundle_path = Path(sys.argv[2])
        bundle = VeloBundle(bundle_path)
        bundle.open()

        print(f"Bundle: {bundle_path}")
        print(f"Modules: {len(bundle.index)}")
        for name, (offset, size, _) in bundle.index.items():
            print(f"  - {name}: {size} bytes @ offset {offset}")

        bundle.close()

    elif cmd == "benchmark":
        # Simple I/O benchmark
        print("🔬 Benchmarking I/O patterns...")

        # Create test files
        test_dir = Path("/tmp/velo_benchmark")
        test_dir.mkdir(exist_ok=True)

        n_files = 100
        file_size = 10 * 1024  # 10KB each

        # Create N small files
        for i in range(n_files):
            (test_dir / f"module_{i}.pyc").write_bytes(b"x" * file_size)

        # Create 1 big file
        (test_dir / "bundle.veloc").write_bytes(b"x" * (n_files * file_size))

        # Benchmark: read N files
        start = time.perf_counter()
        for i in range(n_files):
            with open(test_dir / f"module_{i}.pyc", "rb") as f:
                _ = f.read()
        time_n_files = (time.perf_counter() - start) * 1000

        # Benchmark: mmap 1 file
        start = time.perf_counter()
        with open(test_dir / "bundle.veloc", "rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            # Simulate reading N modules from mmap
            for i in range(n_files):
                _ = bytes(mm[i * file_size : (i + 1) * file_size])
            mm.close()
        time_1_mmap = (time.perf_counter() - start) * 1000

        print(f"\n📊 Results ({n_files} modules, {file_size // 1024}KB each):")
        print(f"   Read {n_files} files:  {time_n_files:.2f}ms")
        print(f"   mmap 1 bundle:     {time_1_mmap:.2f}ms")
        print(f"   Speedup:           {time_n_files / time_1_mmap:.1f}x")

        # Cleanup
        import shutil

        shutil.rmtree(test_dir)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
