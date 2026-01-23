"""
Linux Syscall Helper Module

Expert Recommendation #3: Use architecture-agnostic syscall numbers.

This module provides architecture-agnostic access to Linux syscalls
for Memory Gravity testing.
"""

import ctypes
import ctypes.util
import os
import platform
from typing import Any


def get_memfd_create_syscall_number() -> int:
    """
    Get the memfd_create syscall number for the current architecture.

    Architecture mapping:
    - x86_64: 319
    - aarch64 (ARM64): 279
    - i386 (x86): 356
    - arm (32-bit): 385

    Returns syscall number or -1 if unsupported.
    """
    machine = platform.machine().lower()

    syscall_map = {
        "x86_64": 319,
        "amd64": 319,
        "aarch64": 279,
        "arm64": 279,
        "i386": 356,
        "i686": 356,
        "arm": 385,
        "armv7l": 385,
    }

    return syscall_map.get(machine, -1)


def get_libc() -> Any:
    """Load libc with errno support."""
    return ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)


# Constants for memfd_create
MFD_CLOEXEC = 0x0001
MFD_ALLOW_SEALING = 0x0002
MFD_HUGETLB = 0x0004

# Seal flags (these are architecture-independent, defined in fcntl.h)
F_ADD_SEALS = 1033
F_GET_SEALS = 1034
F_SEAL_SEAL = 0x0001
F_SEAL_SHRINK = 0x0002
F_SEAL_GROW = 0x0004
F_SEAL_WRITE = 0x0008

# mmap protection flags
PROT_NONE = 0x0
PROT_READ = 0x1
PROT_WRITE = 0x2
PROT_EXEC = 0x4


def memfd_create(name: bytes, flags: int) -> int:
    """
    Create an anonymous file in memory using memfd_create.

    Returns file descriptor or -1 on error.
    """
    libc = get_libc()
    syscall_nr = get_memfd_create_syscall_number()

    if syscall_nr < 0:
        return -1

    return int(libc.syscall(syscall_nr, name, flags))


def check_writable_vmas_robust(fd: int) -> tuple[bool | None, str]:
    """
    Check /proc/self/maps for writable VMAs pointing to a file.

    Expert Recommendation #4: Improve /proc/maps parsing robustness.

    Uses multiple parsing strategies:
    1. Primary: Parse by inode matching
    2. Fallback: Parse by memfd name in pathname
    3. Safety: Graceful degradation on parse errors

    Returns: (has_writable: bool | None, details: str)
    """
    try:
        stat_info = os.fstat(fd)
        target_inode = stat_info.st_ino
        target_dev = stat_info.st_dev
    except OSError as e:
        return None, f"fstat failed: {e}"

    try:
        with open("/proc/self/maps") as f:
            for line in f:
                try:
                    # Parse VMA line format:
                    # address perms offset dev inode pathname
                    # Example:
                    # 7f1234-7f1300 rw-p 00000000 00:05 12345 /memfd:test (deleted)

                    parts = line.split(None, 5)  # Split into max 6 parts
                    if len(parts) < 5:
                        continue

                    address_range = parts[0]
                    perms = parts[1]
                    offset = parts[2]
                    dev = parts[3]
                    inode_str = parts[4]
                    pathname = parts[5].strip() if len(parts) > 5 else ""

                    # Parse inode
                    try:
                        line_inode = int(inode_str)
                    except ValueError:
                        continue

                    # Check if this VMA matches our fd
                    if line_inode == target_inode:
                        # Check for write permission (second char of perms)
                        if len(perms) >= 2 and perms[1] == "w":
                            return True, f"Writable VMA found: {line.strip()}"

                    # Fallback: Check for memfd pattern in pathname
                    if "memfd:" in pathname and line_inode > 0:
                        if len(perms) >= 2 and perms[1] == "w":
                            # Could be our memfd - check inode
                            if line_inode == target_inode:
                                return True, f"Writable memfd VMA: {line.strip()}"

                except (ValueError, IndexError):
                    # Skip malformed lines
                    continue

        return False, "No writable VMAs found for this fd"

    except FileNotFoundError:
        return None, "/proc/self/maps not available"
    except PermissionError:
        return None, "Permission denied reading /proc/self/maps"
    except Exception as e:
        return None, f"Unexpected error: {e}"


def is_ptrace_available() -> bool:
    """Check if ptrace syscall is available (for testing)."""
    try:
        libc = get_libc()
        # PTRACE_TRACEME = 0, should return 0 on success, -1 on error
        # Note: This will fail if already being traced
        result = libc.ptrace(0, 0, 0, 0)
        return True  # If we get here, ptrace is available
    except (OSError, AttributeError):
        return False
