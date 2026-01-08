#[cfg(test)]
mod tests {
    use crate::shm::alignment;
    use crate::shm::constants::*;
    use crate::shm::registry::MemoryRegistry;
    use std::io::Write;
    use tempfile::NamedTempFile;

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
}
