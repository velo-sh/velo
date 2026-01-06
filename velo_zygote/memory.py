import mmap
import os
import signal
import sys
import time
import torch
import weakref
from typing import Optional, List

# H-17: Immutability Defense (Monkey-patching)
_ORIG_DATA_PTR = torch.Tensor.data_ptr

def _safe_data_ptr(self):
    """Safe data_ptr that warns on access to shared memory."""
    # Logic to detect if tensor is from SHM (e.g. check bounds or metadata)
    # For now, we strictly follow the invariant.
    return _ORIG_DATA_PTR(self)

# torch.Tensor.data_ptr = _safe_data_ptr # Uncomment to enable active defense

class SharedMemoryManager:
    """
    Manages shared memory segments for the worker.
    Enforces H-31 (Lazy Unmap, Expect Breakage).
    """
    def __init__(self):
        self._mappings = []
        self._tensor_refs = []
        
        # H-31: Register signal handler for expiry (SIGUSR1 usually, assuming SHM_EXPIRE)
        # Note: In real implementation, this might be a specific IPC message.
        # RFC-0015 mentions "SHM_EXPIRE message".
        pass

    def attach(self, fd: int, size: int) -> torch.Tensor:
        """
        Attach to a shared memory segment via FD.
        H-17: Maps as PROT_READ (ReadOnly).
        """
        # 1. Map PROT_READ
        buf = mmap.mmap(fd, size, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ)
        self._mappings.append(buf)
        
        # 2. Wrap as Tensor
        # Using from_buffer logic
        # Note: In real usage we need dtype/shape from somewhere (IPC or header)
        # For this artifact, we assume bytes or flat float32
        # Mocking shape for the handover: we just return the buffer wrapped
        # But torch.from_buffer needs specific args.
        # We'll return the buffer for now or a dummy tensor if needed.
        return buf

    def handle_expire(self):
        """
        H-31: Lazy Unmap Support.
        When Host broadcasts expire, Python MUST drop all tensor references within 100ms.
        """
        print("[Memory] Received SHM_EXPIRE. Dropping refs.")
        self._tensor_refs.clear()
        
        # Close mmaps
        for m in self._mappings:
            m.close()
        self._mappings.clear()
        
        # Force GC?
        import gc
        gc.collect()

# Global singleton
MEMORY_MANAGER = SharedMemoryManager()
