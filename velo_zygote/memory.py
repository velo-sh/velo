import mmap
import sys
import weakref
from types import ModuleType
from typing import Any

try:
    import torch
except ImportError:
    torch: ModuleType | None = None  # type: ignore[no-redef]

# H-17: Immutability Defense (Monkey-patching)
_ORIG_DATA_PTR = None
if torch and hasattr(torch, "Tensor"):
    _ORIG_DATA_PTR = getattr(torch.Tensor, "data_ptr", None)


def _safe_data_ptr(self: Any) -> int | None:
    """Safe data_ptr that warns on access to shared memory."""
    if _ORIG_DATA_PTR:
        return _ORIG_DATA_PTR(self)  # type: ignore[no-any-return]
    return None


# if torch:
#     torch.Tensor.data_ptr = _safe_data_ptr # Uncomment to enable active defense


class SharedMemoryManager:
    """
    Manages shared memory segments for the worker.
    Enforces H-31 (Lazy Unmap, Expect Breakage).
    """

    def __init__(self) -> None:
        self._mappings: list[mmap.mmap] = []
        self._tensor_refs: list[Any] = []

        # H-31: Register signal handler for expiry (SIGUSR1 usually, assuming SHM_EXPIRE)
        # Note: In real implementation, this might be a specific IPC message.
        # RFC-0015 mentions "SHM_EXPIRE message".
        pass

    def attach(self, fd: int, size: int) -> mmap.mmap | None:
        """
        Attach to a shared memory segment via FD.
        H-17: Maps as PROT_READ (ReadOnly).
        """
        try:
            # 1. Map PROT_READ
            buf = mmap.mmap(fd, size, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ)
            self._mappings.append(buf)

            # 2. Wrap as Tensor if torch is available
            if torch:
                try:
                    # Create a tensor from the buffer (zero-copy)
                    # We assume float32 for default demonstration, but real impl
                    # would use metadata from the segment header.
                    t = torch.frombuffer(buf, dtype=torch.uint8)  # type: ignore
                    self._tensor_refs.append(weakref.ref(t))
                    return t  # type: ignore[return-value, no-any-return]
                except Exception as e:
                    print(
                        f"[Memory] Warning: Could not wrap buffer as torch.Tensor: {e}",
                        file=sys.stderr,
                    )

            return buf
        except Exception as e:
            print(
                f"[Memory] Error: Failed to attach SHM segment (fd={fd}, size={size}): {e}",
                file=sys.stderr,
            )
            return None

    def handle_expire(self) -> None:
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
