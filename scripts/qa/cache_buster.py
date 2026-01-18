#!/usr/bin/env python3
"""
Velo Cache-Buster Utility
Attempts to evict OS Page Cache and Python bytecode caches to ensure 'Cold Start' metrics.
"""
import os
import shutil
import time
from pathlib import Path

def purge_python_cache(root_dir: Path):
    print(f"🧹 Purging Python bytecode caches in {root_dir}...")
    for p in root_dir.rglob("__pycache__"):
        if p.is_dir():
            shutil.rmtree(p)
    for p in root_dir.rglob("*.pyc"):
        p.unlink()
    print("✅ Bytecode purged.")

def displace_page_cache():
    """
    Attempts to displace OS Page Cache by allocating and writing a large block of RAM.
    This forces the OS to evict file-backed pages.
    """
    print("🌀 Displacing OS Page Cache (this may take a moment)...")
    # Allocate ~2GB of randomized data to prevent decompression optimizations
    try:
        size_gb = 2
        block = bytearray(os.urandom(size_gb * 1024 * 1024 * 1024))
        # Access the block to ensure it's actually paged in
        _sum = sum(block[::1024*1024])
        del block
        time.sleep(1) # Allow OS to settle
        print(f"✅ Displaced ~{size_gb}GB of memory.")
    except MemoryError:
        print("⚠️ Not enough RAM to displace 2GB, skipping RAM pressure.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=str, help="Path to clean bytecode from")
    args = parser.parse_args()
    
    purge_python_cache(Path(args.path))
    displace_page_cache()
