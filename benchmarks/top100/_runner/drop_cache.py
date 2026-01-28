import os
import sys
import tempfile


def drop_cache():
    # Detect System RAM
    try:
        total_ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, AttributeError):
        # Fallback to 16GB if detection fails
        total_ram = 16 * 1024 * 1024 * 1024

    # Target: 1.2x RAM to ensure full eviction (LRU saturation)
    # But cap at 32GB to avoid excessive wear/time on massive workstations unless needed
    target_size = int(total_ram * 1.2)

    # Safety cap: If machine has >64GB RAM, writing 80GB is too slow for a quick benchmark.
    # 32GB I/O pressure is usually enough to flush active working sets of common libraries.
    # Users can edit this if they really need to burn 128GB.
    if target_size > 32 * 1024 * 1024 * 1024:
        target_size = 32 * 1024 * 1024 * 1024

    FILE_SIZE = target_size
    CHUNK_SIZE = 64 * 1024 * 1024  # 64MB chunks for faster throughput
    temp_path = os.path.join(tempfile.gettempdir(), "velo_cache_buster.bin")

    print(
        f"I/O Pressure: Writing/Reading {FILE_SIZE / 1024**3:.1f} GB (System RAM: {total_ram / 1024**3:.1f} GB) to {temp_path}..."
    )

    try:
        # Write
        with open(temp_path, "wb") as f:
            bytes_written = 0
            # Random-ish data to avoid deduplication/compression quirks?
            # os.urandom is slow. Just use zeros or sequence.
            # Zeros might be sparse-files? Safe to use bytearray([1]) * CHUNK_SIZE
            data = bytearray(os.urandom(1024)) * (CHUNK_SIZE // 1024)

            while bytes_written < FILE_SIZE:
                f.write(data)
                bytes_written += len(data)
                sys.stdout.write(f"\r  Writing: {bytes_written / 1024**3:.1f} GB")
                sys.stdout.flush()

        # Read (Force into Page Cache)
        with open(temp_path, "rb") as f:
            bytes_read = 0
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                bytes_read += len(chunk)
                sys.stdout.write(f"\r  Reading: {bytes_read / 1024**3:.1f} GB")
                sys.stdout.flush()

    except Exception as e:
        print(f"\nError: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            print("\n  Cleaned up.")


if __name__ == "__main__":
    drop_cache()
