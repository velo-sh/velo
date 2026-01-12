#[cfg(target_os = "linux")]
use crate::common::governance::{GovernanceSignal, SignalComponent};
use crate::config::VeloConfig;
use crate::shm::alignment;
use crate::shm::constants::*;
use crate::shm::error::MemoryError;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::os::fd::{AsRawFd, FromRawFd, RawFd};
use std::path::Path;

/// TITANIUM: Segment Metadata for RFC-0015 (Memory Gravity)
#[derive(Debug)]
pub struct ShmSegment {
    pub file: File,
    pub actual_page_size: usize,
}

pub struct MemoryRegistry {
    pub config: VeloConfig,
    #[allow(dead_code)]
    strict_numa: bool,
    #[allow(dead_code)] // Used only on Linux in mbind()
    numa_mask: u64,
}

impl Default for MemoryRegistry {
    fn default() -> Self {
        Self::new(VeloConfig::default())
    }
}

impl MemoryRegistry {
    pub fn new(config: VeloConfig) -> Self {
        // H-30: Strict NUMA Check
        let strict_numa = std::env::var(ENV_STRICT_NUMA).unwrap_or_default() == "1";
        // H-32: Configurable NUMA mask (defaults to node 0)
        let numa_mask: u64 = std::env::var(ENV_NUMA_MASK)
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(DEFAULT_NUMA_MASK);

        Self {
            config,
            strict_numa,
            numa_mask,
        }
    }

    pub fn validate_source(file_path: &Path) -> Result<u64, MemoryError> {
        let mut file =
            File::open(file_path).map_err(|e| MemoryError::InvalidSourceFile(e.to_string()))?;
        let metadata = file
            .metadata()
            .map_err(|e| MemoryError::InvalidSourceFile(e.to_string()))?;

        if !metadata.is_file() {
            return Err(MemoryError::InvalidSourceFile(
                "Source is not a file".to_string(),
            ));
        }

        let file_size = metadata.len() as usize;

        if file_size < HEADER_LEN_SIZE {
            return Err(MemoryError::InvalidSourceFile(
                "File too small to be safetensors (H-29 check)".to_string(),
            ));
        }

        let mut header_len_bytes = [0u8; HEADER_LEN_SIZE];
        file.read_exact(&mut header_len_bytes)
            .map_err(|e| MemoryError::HeaderParseFailed(e.to_string()))?;
        let header_len = u64::from_le_bytes(header_len_bytes) as usize;

        // DEF-70-004: Early Validation - Check if header_len is physically possible
        if (HEADER_LEN_SIZE + header_len) > file_size {
            return Err(MemoryError::HeaderParseFailed(format!(
                "Header length ({}) + Prefix ({}) exceeds file size ({})",
                header_len, HEADER_LEN_SIZE, file_size
            )));
        }

        // Use H-29 logic
        let padding_needed = alignment::calculate_padding(header_len)?;

        // Return total size for create_segment to use
        Ok((file_size + padding_needed) as u64)
    }

    pub fn create_segment(
        &self,
        name: &str,
        source_path: &Path,
    ) -> Result<ShmSegment, MemoryError> {
        let size = Self::validate_source(source_path)?;
        let prefer_huge = true; // RFC-0015: Scheme B always prefers HugePages

        // 1. Create SHM FD
        #[allow(unused_mut)]
        let (mut fd, mut _is_huge) = self.create_shm_fd(name, size as usize, prefer_huge)?;

        // We need to re-read header len for population
        let mut file =
            File::open(source_path).map_err(|e| MemoryError::InvalidSourceFile(e.to_string()))?;
        let mut header_len_bytes = [0u8; HEADER_LEN_SIZE];
        file.read_exact(&mut header_len_bytes)
            .map_err(|e| MemoryError::HeaderParseFailed(e.to_string()))?;
        let header_len = u64::from_le_bytes(header_len_bytes) as usize;
        let padding_needed = alignment::calculate_padding(header_len)?;

        // DEF-70-004: Protection against 1PB allocation DoS/Deadlock
        if size > MAX_SHM_SIZE as u64 {
            return Err(MemoryError::InvalidSourceFile(format!(
                "SHM size exceeds safety limit of 1TB: {} bytes",
                size
            )));
        }

        // 2. Map RW
        // SECURITY: mmap is used to create a shared memory mapping for the registry.
        // We use PROT_READ | PROT_WRITE for population and later munmap/mmap RO for isolation.
        // H-20: Conditional MAP_HUGETLB. Only use if the FD effectively supports it (MFD_HUGETLB).
        #[allow(unused_mut)]
        let mut flags = libc::MAP_SHARED;
        #[cfg(target_os = "linux")]
        if _is_huge {
            flags |= linux::MAP_HUGETLB;
        }

        #[allow(unused_mut)]
        let mut ptr = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                size as usize,
                libc::PROT_READ | libc::PROT_WRITE,
                flags,
                fd,
                0,
            )
        };

        // H-20: Robust Fallback for HugePage mmap failure (ENOMEM)
        #[cfg(target_os = "linux")]
        if ptr == libc::MAP_FAILED
            && _is_huge
            && std::io::Error::last_os_error().raw_os_error() == Some(libc::ENOMEM)
        {
            let signal = GovernanceSignal::new(
                SignalComponent::MemoryGravity,
                "HugePages mmap failed (ENOMEM)",
                "Sub-optimal performance (Standard 4KB Page fallback)",
                "Verify hugepage availability: 'grep HugePages /proc/meminfo' and 'nr_hugepages' sysctl.",
            );

            if self.config.strict_optimizations {
                let _ = unsafe { libc::close(fd) };
                return Err(MemoryError::MmapFailed(signal.format_critical()));
            }

            signal.report_audit();

            unsafe { libc::close(fd) };
            let (new_fd, new_is_huge) = self.create_shm_fd(name, size as usize, false)?;
            fd = new_fd;
            _is_huge = new_is_huge;
            ptr = unsafe {
                libc::mmap(
                    std::ptr::null_mut(),
                    size as usize,
                    libc::PROT_READ | libc::PROT_WRITE,
                    libc::MAP_SHARED,
                    fd,
                    0,
                )
            };
        }

        if ptr == libc::MAP_FAILED {
            let _ = unsafe { libc::close(fd) };
            return Err(MemoryError::MmapFailed(format!(
                "Failed to mmap RW: {}",
                std::io::Error::last_os_error()
            )));
        }

        // Calculate page_size AFTER potential fallback to ensure accuracy
        let page_size = if _is_huge {
            HUGE_PAGE_SIZE
        } else {
            unsafe { libc::sysconf(libc::_SC_PAGESIZE) as usize }
        };

        // H-30: NUMA Binding (Strict Mode)
        // DEF-70-004: Only attempt strict mbind if we successfully allocated HugePages.
        // Strict mbind on standard 4KB pages in Docker/Container environments causes kernel hangs.
        #[cfg(target_os = "linux")]
        if self.strict_numa {
            let nodemask = self.numa_mask;
            let maxnode = 64; // Simple fallback
            if _is_huge {
                // H-32: Use configurable NUMA mask instead of hardcoded node 0
                // SECURITY: mbind is used to enforce NUMA affinity in strict mode (H-30).
                // This prevents cross-node latency by pinning memory to the configured nodes.
                // Using raw syscall to avoid libc version compatibility issues.
                let ret = unsafe {
                    libc::syscall(
                        libc::SYS_mbind,
                        ptr,
                        size as libc::c_ulong,
                        linux::MPOL_BIND,
                        &nodemask as *const u64,
                        maxnode,
                        linux::MPOL_MF_STRICT,
                    )
                };
                if ret < 0 {
                    let _ = unsafe { libc::munmap(ptr, size as usize) };
                    let _ = unsafe { libc::close(fd) };
                    return Err(MemoryError::NumaBindFailed(format!(
                        "H-30 Violation: mbind failed with mask 0x{:x}: {:?}",
                        nodemask,
                        std::io::Error::last_os_error()
                    )));
                }
            } else {
                // Fallback path (Standard Pages): Skip strict mbind to avoid Deadlock
                let signal = GovernanceSignal::new(
                    SignalComponent::NumaAffinity,
                    "Skipping strict mbind on standard pages (H-30)",
                    "Potential cross-node latency (NUMA Affinity loss)",
                    "Enable HugePages to safely support strict NUMA binding in containerized environments.",
                );

                if self.config.strict_optimizations {
                    let _ = unsafe { libc::munmap(ptr, size as usize) };
                    let _ = unsafe { libc::close(fd) };
                    return Err(MemoryError::NumaBindFailed(signal.format_critical()));
                }

                signal.report_audit();
            }
        }

        // 3. Populate (Zero-Copy Optimization)
        // HPC Critique: Avoid reading into Vec<u8> buffer. Map source file directly.
        {
            // Reset file pointer after header read
            file.seek(SeekFrom::Start(0))
                .map_err(|e| MemoryError::InvalidSourceFile(format!("Seek reset: {}", e)))?;
            let src_file = file;
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
                    src_file.as_raw_fd(),
                    0,
                )
            };
            if src_ptr == libc::MAP_FAILED {
                let _ = unsafe { libc::munmap(ptr, size as usize) };
                let _ = unsafe { libc::close(fd) };
                return Err(MemoryError::MmapFailed(format!(
                    "Failed to mmap source file: {}",
                    std::io::Error::last_os_error()
                )));
            }

            // Map the entire segment as writable for population
            // SECURITY: Copying from source-mmap to shm-mmap. Guaranteed disjoint memory regions.
            // Bounds checked via header_len and file size.
            unsafe {
                let header_section_len = HEADER_LEN_SIZE + header_len;
                if header_section_len > src_size {
                    libc::munmap(src_ptr, src_size);
                    libc::munmap(ptr, size as usize);
                    let _ = libc::close(fd);
                    return Err(MemoryError::HeaderParseFailed(
                        "Safetensors header_len > file size".to_string(),
                    ));
                }

                // Copy [Len + Header]
                std::ptr::copy_nonoverlapping(
                    src_ptr as *const u8,
                    ptr as *mut u8,
                    header_section_len,
                );

                // Zero out padding (H-29 alignment)
                if padding_needed > 0 {
                    std::ptr::write_bytes(
                        (ptr as *mut u8).add(header_section_len),
                        0,
                        padding_needed,
                    );
                }

                // Copy Body (after padding)
                let body_offset_src = header_section_len;
                let body_offset_dst = header_section_len + padding_needed;
                let body_len = src_size - header_section_len;

                if body_offset_dst + body_len > size as usize {
                    libc::munmap(src_ptr, src_size);
                    libc::munmap(ptr, size as usize);
                    let _ = libc::close(fd);
                    return Err(MemoryError::ResizeFailed(
                        "Logic error: Segment overflow during population".to_string(),
                    ));
                }

                std::ptr::copy_nonoverlapping(
                    (src_ptr as *const u8).add(body_offset_src),
                    (ptr as *mut u8).add(body_offset_dst),
                    body_len,
                );

                libc::munmap(src_ptr, src_size);
            }
        }

        // 4. Unmap RW
        // SECURITY: Unmapping the RW pointer before returning or sealing.
        // On Linux, F_SEAL_WRITE requires no active writable mappings.
        unsafe {
            libc::munmap(ptr, size as usize);
        }

        // 5. Apply Seals (Linux specific)
        self.apply_seals(fd)?;

        // 6. Verify (RO)
        // SECURITY: Temporary RO mapping to verify integrity.
        let verify_ptr = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                size as usize,
                libc::PROT_READ,
                libc::MAP_SHARED,
                fd,
                0,
            )
        };

        if verify_ptr == libc::MAP_FAILED {
            let _ = unsafe { libc::close(fd) };
            return Err(MemoryError::MmapFailed(format!(
                "Failed to mmap verified RO: {}",
                std::io::Error::last_os_error()
            )));
        }

        // Cleanup verify mapping
        // SECURITY: Unmapping verification pointer.
        unsafe {
            libc::munmap(verify_ptr, size as usize);
        }

        // 7. Success
        // SECURITY: from_raw_fd is safe here as the FD was just created and validated by this process.
        Ok(ShmSegment {
            file: unsafe { File::from_raw_fd(fd) },
            actual_page_size: page_size,
        })
    }

    #[cfg(target_os = "linux")]
    fn create_shm_fd(
        &self,
        name: &str,
        size: usize,
        prefer_huge: bool,
    ) -> Result<(RawFd, bool), MemoryError> {
        use std::ffi::CString;
        let c_name = CString::new(name).map_err(|e| MemoryError::InvalidName(e.to_string()))?;

        // SECURITY: memfd_create is used for secure, anonymous shared memory on Linux.
        // MFD_CLOEXEC: Close on exec to prevent leak to children.
        // MFD_ALLOW_SEALING: Required for H-23 (F_ADD_SEALS).
        // H-20: Helper for HugePages attempt
        let try_create = |flags: u32| -> i64 {
            unsafe {
                libc::syscall(
                    libc::SYS_memfd_create,
                    c_name.as_ptr(),
                    libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING | flags,
                )
            }
        };

        // H-20: Optimistic HugePages Attempt (MFD_HUGETLB)
        // We try with hugepages first if preferred.
        let mut fd = if prefer_huge {
            try_create(linux::MFD_HUGETLB)
        } else {
            -1
        };
        let mut is_huge = fd >= 0;

        if fd >= 0 {
            // H-20: Alignment Requirement (Verified Logic)
            // Use the shared alignment helper to ensure we meet valid HugePage boundaries.
            let aligned_size = alignment::align_to_huge_page(size);

            // Attempt to size with the aligned size.
            // If this fails even with aligned size, then HugePages are likely fundamentally broken
            // (e.g. not mounted, insufficient pool, or quota exceeded).
            if unsafe { libc::ftruncate(fd as RawFd, aligned_size as i64) } < 0 {
                let err = std::io::Error::last_os_error();
                unsafe { libc::close(fd as RawFd) };
                fd = -1;
                eprintln!(
                    "⚠️ H-20 Warning: HugePages ftruncate failed ({} for aligned size {}), falling back to standard 4KB pages.",
                    err, aligned_size
                );
            }
        }

        if fd < 0 {
            // Fallback to standard 4KB pages
            // This path is taken if:
            // 1. MFD_HUGETLB failed (not supported/disabled)
            // 2. ftruncate failed (quota exceeded, etc)
            if prefer_huge {
                eprintln!(
                    "⚠️ H-20 Warning: HugePages unavailable, falling back to standard 4KB pages."
                );
            }
            fd = try_create(0);
            is_huge = false;

            #[cfg(target_os = "linux")]
            let page_size = unsafe { libc::sysconf(libc::_SC_PAGESIZE) as usize };
            #[cfg(not(target_os = "linux"))]
            let page_size = 4096;

            let aligned_size = alignment::align_up(size, page_size);

            if fd >= 0 && unsafe { libc::ftruncate(fd as RawFd, aligned_size as i64) } < 0 {
                let err = std::io::Error::last_os_error();
                unsafe { libc::close(fd as RawFd) };
                return Err(MemoryError::ResizeFailed(format!(
                    "ftruncate failed on standard page: {}",
                    err
                )));
            }
        }

        let fd = fd as RawFd;

        if fd < 0 {
            return Err(MemoryError::SegmentCreationFailed(format!(
                "memfd_create failed: {}",
                std::io::Error::last_os_error()
            )));
        }

        // Seals are applied later by caller via apply_seals() to allow mapping first
        Ok((fd, is_huge))
    }

    #[cfg(target_os = "macos")]
    fn create_shm_fd(
        &self,
        name: &str,
        size: usize,
        _prefer_huge: bool,
    ) -> Result<(RawFd, bool), MemoryError> {
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

        Ok((fd, false))
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
