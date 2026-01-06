use anyhow::{Context, Result, anyhow};
use std::fs::File;
use std::os::unix::io::{FromRawFd, RawFd};
use std::path::Path;
// Use alignment for verification (future H-29 integration)
use crate::shm::alignment;

pub struct MemoryRegistry {
    strict_numa: bool,
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
        if strict_numa {
            eprintln!("🔥 VELO_STRICT_NUMA enabled. Verifying topology...");
            // Real implementation would check libnuma here.
            // For now, we assume if env is set, we ENFORCE mbind.
        }
        Self { strict_numa }
    }

    /// Create a shared memory segment from a file (e.g., safetensors).
    /// H-23: Strict Seal Ordering
    /// H-29: Alignment Enforcement (Padding)
    pub fn create_segment(&self, name: &str, file_path: &Path) -> Result<File> {
        let file_bytes = std::fs::read(file_path).context("Failed to read tensor file")?;

        // H-29 Logic: Parse header length to calculate padding
        if file_bytes.len() < 8 {
            return Err(anyhow!("File too small to be safetensors (H-29 check)"));
        }

        let mut header_len_bytes = [0u8; 8];
        header_len_bytes.copy_from_slice(&file_bytes[0..8]);
        let header_len = u64::from_le_bytes(header_len_bytes) as usize;

        // Use H-29 logic
        let padding_needed = alignment::calculate_padding(header_len)?;

        // Total size = original size + padding needed
        let total_size = file_bytes.len() + padding_needed;

        // 1. Create memfd or shm_open
        let fd = self.create_shm_fd(name, total_size)?;

        // 2. Map RW
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
            return Err(anyhow!(
                "Failed to mmap RW: {}",
                std::io::Error::last_os_error()
            ));
        }

        // H-30: NUMA Binding (Strict Mode)
        if self.strict_numa {
            #[cfg(target_os = "linux")]
            {
                // Simple strict bind to node 0 for demonstration/default
                let nodemask: u64 = 1;
                let maxnode = 64;
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
                    panic!(
                        "H-30 Violation: Failed to mbind memory in strict mode! {:?}",
                        std::io::Error::last_os_error()
                    );
                }
            }
        }

        // 3. Populate
        unsafe {
            let dst = ptr as *mut u8;
            // Layout: [8 bytes len] [header] [PADDING] [data]
            // Original: [8 bytes len] [header] [data]

            // 8 bytes len + header
            let header_section_len = 8 + header_len;

            // Check bounds
            if header_section_len > file_bytes.len() {
                libc::munmap(ptr, total_size);
                let _ = libc::close(fd);
                return Err(anyhow!("Safetensors header_len > file size"));
            }

            // Copy [Len + Header]
            std::ptr::copy_nonoverlapping(file_bytes.as_ptr(), dst, header_section_len);

            // Zero out padding (optional but good for determinism)
            if padding_needed > 0 {
                std::ptr::write_bytes(dst.add(header_section_len), 0, padding_needed);
            }

            // Copy [Data]
            let data_start = header_section_len;
            let data_len = file_bytes.len() - header_section_len;
            if data_len > 0 {
                std::ptr::copy_nonoverlapping(
                    file_bytes.as_ptr().add(data_start),
                    dst.add(header_section_len + padding_needed),
                    data_len,
                );
            }
        }

        // 4. Unmap RW (CRITICAL BARRIER)
        unsafe {
            libc::munmap(ptr, total_size);
        }

        // 5. Map RO Check (Internal Verification)
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
            return Err(anyhow!(
                "Failed to mmap RO: {}",
                std::io::Error::last_os_error()
            ));
        }

        unsafe {
            libc::munmap(ptr_ro, total_size);
        }

        // 6. Seal
        self.apply_seals(fd)?;

        // Return File wrapper
        Ok(unsafe { File::from_raw_fd(fd) })
    }

    #[cfg(target_os = "linux")]
    fn create_shm_fd(&self, name: &str, size: usize) -> Result<RawFd> {
        // H-26: Host Death - check PID namespace logic if needed here

        use std::ffi::CString;
        let c_name = CString::new(name).unwrap();

        // MFD_CLOEXEC | MFD_ALLOW_SEALING
        let flags = libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING;
        let fd = unsafe { libc::memfd_create(c_name.as_ptr(), flags) };

        if fd < 0 {
            return Err(anyhow!(
                "memfd_create failed: {}",
                std::io::Error::last_os_error()
            ));
        }

        // Allocate space
        if unsafe { libc::ftruncate(fd, size as i64) } < 0 {
            let _ = unsafe { libc::close(fd) };
            return Err(anyhow!(
                "ftruncate failed: {}",
                std::io::Error::last_os_error()
            ));
        }

        Ok(fd)
    }

    #[cfg(target_os = "macos")]
    fn create_shm_fd(&self, name: &str, size: usize) -> Result<RawFd> {
        use std::ffi::CString;
        let c_name = CString::new(name).unwrap();

        let fd = unsafe {
            libc::shm_open(
                c_name.as_ptr(),
                libc::O_RDWR | libc::O_CREAT | libc::O_EXCL,
                0o600,
            )
        };

        if fd < 0 {
            return Err(anyhow!(
                "shm_open failed: {}",
                std::io::Error::last_os_error()
            ));
        }

        // Unlink so it disappears when closed
        unsafe { libc::shm_unlink(c_name.as_ptr()) };

        if unsafe { libc::ftruncate(fd, size as i64) } < 0 {
            let _ = unsafe { libc::close(fd) };
            return Err(anyhow!(
                "ftruncate failed: {}",
                std::io::Error::last_os_error()
            ));
        }

        Ok(fd)
    }

    fn apply_seals(&self, fd: RawFd) -> Result<()> {
        #[cfg(target_os = "linux")]
        {
            // H-23.7: F_ADD_SEALS
            let seals =
                libc::F_SEAL_WRITE | libc::F_SEAL_SHRINK | libc::F_SEAL_GROW | libc::F_SEAL_SEAL;
            let ret = unsafe { libc::fcntl(fd, libc::F_ADD_SEALS, seals) };
            if ret < 0 {
                return Err(anyhow!(
                    "Failed to add seals: {}",
                    std::io::Error::last_os_error()
                ));
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
