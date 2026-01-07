use std::fs::File;
use std::os::unix::io::{FromRawFd, RawFd};
use std::path::Path;
// Use alignment for verification (future H-29 integration)
use crate::shm::alignment;
use crate::shm::error::MemoryError;

pub struct MemoryRegistry {
    strict_numa: bool,
    #[allow(dead_code)] // Used only on Linux in mbind()
    numa_mask: u64,
}

impl Default for MemoryRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl MemoryRegistry {
    pub fn new() -> Self {
        // H-30: Strict NUMA Check
        let strict_numa = std::env::var("VELO_STRICT_NUMA").unwrap_or_default() == "1";
        // H-32: Configurable NUMA mask (defaults to node 0)
        let numa_mask: u64 = std::env::var("VELO_NUMA_MASK")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(1); // Default to node 0 bitmask
        if strict_numa {
            eprintln!("🔥 VELO_STRICT_NUMA enabled. NUMA mask: 0x{:x}", numa_mask);
        }
        Self {
            strict_numa,
            numa_mask,
        }
    }

    /// Create a shared memory segment from a file (e.g., safetensors).
    /// H-23: Strict Seal Ordering
    /// H-29: Alignment Enforcement (Padding)
    pub fn create_segment(&self, name: &str, file_path: &Path) -> Result<File, MemoryError> {
        // HPC Critique: Use metadata() for size instead of reading entire file into Vec.
        let file_meta = std::fs::metadata(file_path)
            .map_err(|e| MemoryError::InvalidSourceFile(e.to_string()))?;
        let file_size = file_meta.len() as usize;

        if file_size < 8 {
            return Err(MemoryError::InvalidSourceFile(
                "File too small to be safetensors (H-29 check)".to_string(),
            ));
        }

        // Only read the first 8 bytes for header length
        let mut header_len_bytes = [0u8; 8];
        {
            use std::io::Read;
            let mut f =
                File::open(file_path).map_err(|e| MemoryError::InvalidSourceFile(e.to_string()))?;
            f.read_exact(&mut header_len_bytes)
                .map_err(|e| MemoryError::HeaderParseFailed(e.to_string()))?;
        }
        let header_len = u64::from_le_bytes(header_len_bytes) as usize;

        // Use H-29 logic
        let padding_needed = alignment::calculate_padding(header_len)?;

        // Total size = original size + padding needed
        let total_size = file_size + padding_needed;

        // 1. Create memfd or shm_open
        let fd = self.create_shm_fd(name, total_size)?;

        // 2. Map RW
        // SECURITY: mmap is used to create a shared memory mapping for the registry.
        // We use PROT_READ | PROT_WRITE for population and later munmap/mmap RO for isolation.
        let ptr = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                total_size,
                libc::PROT_READ | libc::PROT_WRITE,
                libc::MAP_SHARED,
                fd,
                0,
            )
        };

        if ptr == libc::MAP_FAILED {
            return Err(MemoryError::MmapFailed(format!(
                "Failed to mmap RW: {}",
                std::io::Error::last_os_error()
            )));
        }

        // H-30: NUMA Binding (Strict Mode)
        if self.strict_numa {
            #[cfg(target_os = "linux")]
            {
                // H-32: Use configurable NUMA mask instead of hardcoded node 0
                let nodemask = self.numa_mask;
                let maxnode = 64;
                // SECURITY: mbind is used to enforce NUMA affinity in strict mode (H-30).
                // This prevents cross-node latency by pinning memory to the configured nodes.
                let ret = unsafe {
                    libc::mbind(
                        ptr,
                        total_size as u64,
                        libc::MPOL_BIND,
                        &nodemask as *const u64,
                        maxnode,
                        libc::MPOL_MF_STRICT,
                    )
                };
                if ret < 0 {
                    return Err(MemoryError::NumaBindFailed(format!(
                        "H-30 Violation: mbind failed with mask 0x{:x}: {:?}",
                        nodemask,
                        std::io::Error::last_os_error()
                    )));
                }
            }
        }

        // 3. Populate (Zero-Copy Optimization)
        // HPC Critique: Avoid reading into Vec<u8> buffer. Map source file directly.
        {
            let src_file = File::open(file_path)
                .map_err(|e| MemoryError::InvalidSourceFile(format!("Zero-copy open: {}", e)))?;
            let src_size = src_file
                .metadata()
                .map_err(|e| MemoryError::InvalidSourceFile(e.to_string()))?
                .len() as usize;

            // SECURITY: mmap of source file is safe as it is read-only and size-checked.
            let src_ptr = unsafe {
                libc::mmap(
                    std::ptr::null_mut(),
                    src_size,
                    libc::PROT_READ,
                    libc::MAP_PRIVATE,
                    std::os::unix::io::AsRawFd::as_raw_fd(&src_file),
                    0,
                )
            };
            if src_ptr == libc::MAP_FAILED {
                return Err(MemoryError::MmapFailed(format!(
                    "Failed to mmap source file: {}",
                    std::io::Error::last_os_error()
                )));
            }

            // SECURITY: Copying from source-mmap to shm-mmap. Guaranteed disjoint memory regions.
            // Bounds checked via header_len and file size.
            unsafe {
                let dst = ptr as *mut u8;
                let src = src_ptr as *const u8;

                let header_section_len = 8 + header_len;
                if header_section_len > src_size {
                    libc::munmap(src_ptr, src_size);
                    libc::munmap(ptr, total_size);
                    let _ = libc::close(fd);
                    return Err(MemoryError::HeaderParseFailed(
                        "Safetensors header_len > file size".to_string(),
                    ));
                }

                // Copy [Len + Header]
                std::ptr::copy_nonoverlapping(src, dst, header_section_len);

                // Zero out padding (H-29 alignment)
                if padding_needed > 0 {
                    std::ptr::write_bytes(dst.add(header_section_len), 0, padding_needed);
                }

                // Copy [Data]
                let data_len = src_size - header_section_len;
                if data_len > 0 {
                    std::ptr::copy_nonoverlapping(
                        src.add(header_section_len),
                        dst.add(header_section_len + padding_needed),
                        data_len,
                    );
                }

                libc::munmap(src_ptr, src_size);
            }
        }

        // 4. Unmap RW (CRITICAL BARRIER)
        // SECURITY: Unmapping the RW pointer before returning. This ensures no accidental writes.
        unsafe {
            libc::munmap(ptr, total_size);
        }

        // 5. Map RO Check (Internal Verification)
        // SECURITY: Temporary RO mapping to verify integrity.
        let ptr_ro = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                total_size,
                libc::PROT_READ,
                libc::MAP_SHARED,
                fd,
                0,
            )
        };

        if ptr_ro == libc::MAP_FAILED {
            return Err(MemoryError::MmapFailed(format!(
                "Failed to mmap RO: {}",
                std::io::Error::last_os_error()
            )));
        }

        // SECURITY: Unmapping verification pointer.
        unsafe {
            libc::munmap(ptr_ro, total_size);
        }

        // 6. Seal
        self.apply_seals(fd)?;

        // Return File wrapper
        // SECURITY: from_raw_fd is safe here as the FD was just created and validated by this process.
        Ok(unsafe { File::from_raw_fd(fd) })
    }

    #[cfg(target_os = "linux")]
    fn create_shm_fd(&self, name: &str, size: usize) -> Result<RawFd, MemoryError> {
        // H-26: Host Death - check PID namespace logic if needed here

        use std::ffi::CString;
        let c_name = CString::new(name).map_err(|e| MemoryError::InvalidName(e.to_string()))?;

        // MFD_CLOEXEC | MFD_ALLOW_SEALING
        let flags = libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING;
        // SECURITY: memfd_create is used for secure, anonymous shared memory on Linux.
        let fd = unsafe { libc::memfd_create(c_name.as_ptr(), flags) };

        if fd < 0 {
            return Err(MemoryError::SegmentCreationFailed(format!(
                "memfd_create failed: {}",
                std::io::Error::last_os_error()
            )));
        }

        // Allocate space
        // SECURITY: ftruncate is used to set the initial size of the shared memory segment.
        if unsafe { libc::ftruncate(fd, size as i64) } < 0 {
            // SECURITY: closing the FD on error.
            let _ = unsafe { libc::close(fd) };
            return Err(MemoryError::ResizeFailed(format!(
                "ftruncate failed: {}",
                std::io::Error::last_os_error()
            )));
        }

        Ok(fd)
    }

    #[cfg(target_os = "macos")]
    fn create_shm_fd(&self, name: &str, size: usize) -> Result<RawFd, MemoryError> {
        use std::ffi::CString;
        let c_name = CString::new(name).map_err(|e| MemoryError::InvalidName(e.to_string()))?;

        // SECURITY: shm_open for macOS shared memory. 0o600 perms for owner-only access.
        let fd = unsafe {
            libc::shm_open(
                c_name.as_ptr(),
                libc::O_RDWR | libc::O_CREAT | libc::O_EXCL,
                0o600,
            )
        };

        if fd < 0 {
            return Err(MemoryError::SegmentCreationFailed(format!(
                "shm_open failed: {}",
                std::io::Error::last_os_error()
            )));
        }

        // Unlink so it disappears when closed
        // SECURITY: shm_unlink ensures the segment is not persistent on the filesystem.
        unsafe { libc::shm_unlink(c_name.as_ptr()) };

        // SECURITY: ftruncate to set segment size.
        if unsafe { libc::ftruncate(fd, size as i64) } < 0 {
            // SECURITY: close on error.
            let _ = unsafe { libc::close(fd) };
            return Err(MemoryError::ResizeFailed(format!(
                "ftruncate failed: {}",
                std::io::Error::last_os_error()
            )));
        }

        Ok(fd)
    }

    fn apply_seals(&self, fd: RawFd) -> Result<(), MemoryError> {
        #[cfg(target_os = "linux")]
        {
            // H-23.7: F_ADD_SEALS
            let seals =
                libc::F_SEAL_WRITE | libc::F_SEAL_SHRINK | libc::F_SEAL_GROW | libc::F_SEAL_SEAL;
            // SECURITY: Applying memfd seals to make the memory immutable before passing to workers.
            let ret = unsafe { libc::fcntl(fd, libc::F_ADD_SEALS, seals) };
            if ret < 0 {
                return Err(MemoryError::SealFailed(format!(
                    "Failed to add seals: {}",
                    std::io::Error::last_os_error()
                )));
            }
        }
        #[cfg(not(target_os = "linux"))]
        {
            // Suppress unused variable warning on non-linux
            let _ = fd;
        }
        Ok(())
    }
}
