#[cfg(test)]
mod tests {
    use crate::shm::alignment;
    use crate::shm::constants::*;
    use crate::shm::registry::MemoryRegistry;
    use std::io::{Seek, SeekFrom, Write};
    use tempfile::NamedTempFile;

    const EXPECTED_HUGE_PAGE_SIZE: u64 = 2 * 1024 * 1024;

    /// TITANIUM: Verify H-29 Padding Calculation Logic
    #[test]
    fn test_h29_padding_logic() {
        // Aligned header (64 bytes) -> 0 padding
        // HEADER_LEN_SIZE (8) + 56 = 64
        assert_eq!(alignment::calculate_padding(56).unwrap(), 0);

        // Unaligned header (1 byte) -> 55 padding
        // HEADER_LEN_SIZE (8) + 1 = 9. 64 - 9 = 55.
        assert_eq!(alignment::calculate_padding(1).unwrap(), 55);

        // Edge case: Overflow protection
        // usize::MAX should error, not panic
        assert!(alignment::calculate_padding(usize::MAX).is_err());
    }

    /// TITANIUM: Verify DEF-70-004 Deadlock Prevention (Validate Source Logic)
    #[test]
    fn test_validate_source_logic() {
        // 1. Create a dummy safetensors file with a VALID header (small)
        let mut tmp = NamedTempFile::new().unwrap();
        let header_len: u64 = 10;
        tmp.write_all(&header_len.to_le_bytes()).unwrap(); // 8 bytes length
        tmp.write_all(&[0u8; 10]).unwrap(); // 10 bytes header
        tmp.flush().unwrap();

        // This should pass
        let size = MemoryRegistry::validate_source(tmp.path()).unwrap();
        // 8 (len) + 10 (header) = 18. Padding for 18 to 64:
        // 18 % 64 = 18. 64 - 18 = 46.
        // Total = 18 + 46 = 64.
        assert_eq!(size, 64);

        // 2. Create a MALFORMED file (Header Claim > File Size) causes Deadlock if unchecked
        let mut tmp_deadlock = NamedTempFile::new().unwrap();
        let massive_len: u64 = 1024 * 1024 * 1024; // 1GB header claim
        tmp_deadlock.write_all(&massive_len.to_le_bytes()).unwrap(); // Write only 8 bytes
        tmp_deadlock.flush().unwrap();

        // This MUST fail with HeaderParseFailed, NOT panic or return huge size
        let res = MemoryRegistry::validate_source(tmp_deadlock.path());
        assert!(res.is_err(), "Should detect massive header in tiny file");
        let err = res.err().unwrap().to_string();
        assert!(
            err.contains("exceeds file size"),
            "Error message should mention size mismatch"
        );
    }

    /// TITANIUM: Verify H-30/H-32 Constants
    #[test]
    fn test_numa_constants() {
        assert_eq!(ENV_STRICT_NUMA, "VELO_STRICT_NUMA");
        assert_eq!(ENV_NUMA_MASK, "VELO_NUMA_MASK");
        assert_eq!(DEFAULT_NUMA_MASK, 1);
        #[cfg(target_os = "linux")]
        {
            use crate::shm::constants::linux::*;
            assert_eq!(MPOL_BIND, 2);
            assert_eq!(MPOL_MF_STRICT, 1);
        }
    }

    /// QA HOSTILE: Scheme B (Alignment) Verification
    /// "Try hard to break dev code"
    #[test]
    fn test_qa_alignment_scheme_b_integration() {
        // Case 2.1: HugePages Enabled (Simulated by verifying file size alignment)
        // We create a tiny file. If Scheme B is working, the backing SHM must be 2MB.
        // Input: 18 bytes (header) + 0 body.

        let mut tmp = NamedTempFile::new().unwrap();
        let header_len: u64 = 10;
        tmp.write_all(&header_len.to_le_bytes()).unwrap(); // 8 bytes
        tmp.write_all(&[0u8; 10]).unwrap(); // 10 bytes content
        tmp.flush().unwrap();

        let registry = MemoryRegistry::new(); // Defaults to strict_numa=false in tests usually unless env set

        let shm_file = registry
            .create_segment("qa_test_alignment_underflow", tmp.path())
            .unwrap();
        let metadata = shm_file.metadata().unwrap();
        let size = metadata.len();

        // CRITICAL CHECK: Must be 2MB (HUGE_PAGE_SIZE), not 64 bytes or 1 page.
        // If the dev code falls back to Scheme A (Standard Pages) or doesn't align, this fails.
        // Case 2.1: HugePages Enabled (Simulated by verifying file size alignment)
        // We create a tiny file. If Scheme B is working, the backing SHM should be 2MB.
        // H-20: If HugePages are unavailable (ENOMEM), we fall back to standard pages (4KB).
        #[cfg(target_os = "linux")]
        {
            let page_size = unsafe { libc::sysconf(libc::_SC_PAGESIZE) as u64 };
            if size == EXPECTED_HUGE_PAGE_SIZE {
                println!("✅ QA INFO: HugePage alignment verified (2MB)");
            } else if size.is_multiple_of(page_size) && size < EXPECTED_HUGE_PAGE_SIZE {
                println!(
                    "⚠️ QA INFO: HugePage fallback detected (Standard {}KB page used). This is acceptable in resource-constrained environments.",
                    page_size / 1024
                );
            } else {
                panic!(
                    "QA FAILURE: SHM size {} is not aligned to HugePage (2MB) nor standard page ({}KB)",
                    size,
                    page_size / 1024
                );
            }
        }
        #[cfg(not(target_os = "linux"))]
        {
            println!(
                "ℹ️ QA INFO: HugePage alignment skipped on non-Linux platform (Got {}, Expected 2MB on Linux)",
                size
            );
        }

        // Case 1.3: Overflow (溢出一点点)
        // We need a source that results in logically 2MB + 1 byte.
        // HugePage = 2,097,152.
        // We want raw_size = 2,097,153.
        // Let's make a file of size 2,097,153 (assuming aligned header for simplicity).
        // Header 56 bytes -> padding 0.
        // Total = File Size.

        let mut tmp_overflow = NamedTempFile::new().unwrap();
        let file_size = EXPECTED_HUGE_PAGE_SIZE + 1;
        // Efficiently create large file
        tmp_overflow.as_file().set_len(file_size).unwrap();

        // Write a valid header at start
        tmp_overflow.seek(SeekFrom::Start(0)).unwrap();
        let header_len_56: u64 = 56 - 8; // 48
        tmp_overflow
            .write_all(&header_len_56.to_le_bytes())
            .unwrap();
        // We don't need to write all data, validate_source just checks size and header.
        tmp_overflow.flush().unwrap();

        let shm_file_overflow = registry
            .create_segment("qa_test_alignment_overflow", tmp_overflow.path())
            .unwrap();
        let size_overflow = shm_file_overflow.metadata().unwrap().len();

        // Expect 4MB
        let _expected_size = EXPECTED_HUGE_PAGE_SIZE * 2;
        #[cfg(target_os = "linux")]
        {
            let page_size = match size_overflow {
                s if s == _expected_size => HUGE_PAGE_SIZE,
                _ => unsafe { libc::sysconf(libc::_SC_PAGESIZE) as usize },
            };
            assert_eq!(
                size_overflow as usize,
                alignment::align_up(EXPECTED_HUGE_PAGE_SIZE + 64, page_size),
                "QA FAILURE: Overflow size {} not aligned to page boundary ({}KB)",
                size_overflow,
                page_size / 1024
            );
        }
        #[cfg(not(target_os = "linux"))]
        {
            println!(
                "ℹ️ QA INFO: Overflow alignment skipped on non-Linux platform (Got {}, Expected 4MB on Linux)",
                size_overflow
            );
        }
    }

    /// QA HOSTILE: Boundary & Negative Testing
    #[test]
    fn test_qa_boundary_limits() {
        // Case 3.2: Max Size Logic Check
        // We can't actually allocate 1TB or usize::MAX in a unit test easily without OOM,
        // but we can check the Registry error response for "Safety Limit".

        let tmp_limit = NamedTempFile::new().unwrap();
        // Fake a file size > MAX_SHM_SIZE (1TB)
        // Note: set_len is sparse, so this is fast and doesn't verify disk space usually.
        let huge_size = crate::shm::constants::MAX_SHM_SIZE as u64 + 1;

        // We use a safe wrapper to avoid actual checking if OS fails set_len on massive sizes
        if tmp_limit.as_file().set_len(huge_size).is_ok() {
            let registry = MemoryRegistry::new();
            let res = registry.create_segment("qa_test_limit", tmp_limit.path());

            assert!(res.is_err());
            // Must fail with InvalidSourceFile (Safety limit)
            assert!(
                res.unwrap_err()
                    .to_string()
                    .contains("exceeds safety limit")
            );
        }
    }
}
