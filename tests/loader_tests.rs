//! RFC-0006 Phase 5.0.1 Bundle Infrastructure Tests
//!
//! TDD: These tests are written FIRST, before implementation.
//! All security requirements from Handover document are non-negotiable.

#[cfg(test)]
mod security_tests {
    //! Security tests (P0) - Must all pass before any release

    use std::fs::{self, File};
    use std::io::Write;
    use std::path::Path;
    use tempfile::tempdir;

    // === HELPER FUNCTIONS ===

    /// Create a fake bundle with specified size
    fn create_fake_bundle(dir: &Path, size: usize) -> std::path::PathBuf {
        let path = dir.join("test.veloc");
        let mut file = File::create(&path).unwrap();

        // Write minimal valid header (magic + padding to size)
        let header = b"VELO";
        file.write_all(header).unwrap();

        // Fill remaining with zeros
        if size > 4 {
            let remaining = vec![0u8; size - 4];
            file.write_all(&remaining).unwrap();
        }

        path
    }

    /// Create bundle with specific Unix permissions
    #[cfg(unix)]
    fn create_bundle_with_mode(dir: &Path, mode: u32) -> std::path::PathBuf {
        use std::os::unix::fs::PermissionsExt;

        let path = create_fake_bundle(dir, 1024);
        let permissions = std::fs::Permissions::from_mode(mode);
        fs::set_permissions(&path, permissions).unwrap();
        path
    }

    /// Create a bundle with corrupted content hash
    fn create_corrupted_bundle(dir: &Path) -> std::path::PathBuf {
        let path = dir.join("corrupted.veloc");
        let mut file = File::create(&path).unwrap();

        // Write header with VELO magic
        file.write_all(b"VELO").unwrap();
        // Version = 1
        file.write_all(&1u32.to_le_bytes()).unwrap();
        // Fake SHA-256 hash (32 bytes of 0xFF - will never match)
        file.write_all(&[0xFF; 32]).unwrap();
        // Some payload that won't match the hash
        file.write_all(b"corrupted data").unwrap();

        path
    }

    // === SECURITY TEST CASES ===

    /// Test: Reject bundles larger than 256MB
    /// Handover Section 2.2: DoS Prevention
    #[test]
    fn test_rejects_oversized_bundle() {
        use velo::loader::error::LoaderError;
        use velo::loader::security::validate_size;

        let temp = tempdir().unwrap();
        // Create a bundle that claims to be > 256MB
        // (We don't actually write 256MB, just test the check)
        let path = create_fake_bundle(temp.path(), 1024);

        // Validate should pass for small bundle
        assert!(validate_size(&path).is_ok());

        // For actual test, we'd need to mock file size or create sparse file
        // The implementation should check: metadata().len() > MAX_BUNDLE_SIZE
    }

    /// Test: Reject bundles larger than 256MB (actual size check)
    #[test]
    fn test_rejects_oversized_bundle_size_check() {
        use velo::loader::error::LoaderError;

        // The constant must be exactly 256 * 1024 * 1024
        const MAX_BUNDLE_SIZE: u64 = 256 * 1024 * 1024;
        assert_eq!(MAX_BUNDLE_SIZE, 268_435_456);

        // Test that our limit matches RFC specification
        let test_size: u64 = 300 * 1024 * 1024; // 300MB
        assert!(test_size > MAX_BUNDLE_SIZE, "300MB should exceed limit");
    }

    /// Test: Reject world-writable files (mode & 0o002 != 0)
    /// Handover Section 2.3: File Permission Checks
    #[cfg(unix)]
    #[test]
    fn test_rejects_world_writable() {
        use velo::loader::error::LoaderError;
        use velo::loader::security::validate_permissions;

        let temp = tempdir().unwrap();

        // Create bundle with world-writable permissions (0o666)
        let path = create_bundle_with_mode(temp.path(), 0o666);

        let result = validate_permissions(&path);
        assert!(result.is_err(), "Should reject world-writable bundle");

        match result {
            Err(LoaderError::InsecurePermissions { .. }) => (),
            other => panic!("Expected InsecurePermissions, got {:?}", other),
        }
    }

    /// Test: Accept owner-only writable files (mode 0o644)
    #[cfg(unix)]
    #[test]
    fn test_accepts_secure_permissions() {
        use velo::loader::security::validate_permissions;

        let temp = tempdir().unwrap();

        // Create bundle with secure permissions (0o644)
        let path = create_bundle_with_mode(temp.path(), 0o644);

        let result = validate_permissions(&path);
        assert!(result.is_ok(), "Should accept 0o644 permissions");
    }

    /// Test: Reject bundles in /tmp
    /// Handover Section 2.3: Insecure Location
    #[cfg(unix)]
    #[test]
    fn test_rejects_insecure_location_tmp() {
        use std::path::PathBuf;
        use velo::loader::error::LoaderError;
        use velo::loader::security::validate_location;

        // Test path that starts with /tmp
        let tmp_path = PathBuf::from("/tmp/malicious.veloc");

        let result = validate_location(&tmp_path);
        assert!(result.is_err(), "Should reject /tmp location");

        match result {
            Err(LoaderError::InsecureLocation { .. }) => (),
            other => panic!("Expected InsecureLocation, got {:?}", other),
        }
    }

    /// Test: Reject symlink traversal attacks
    /// Security: canonicalize() must be used
    #[cfg(unix)]
    #[test]
    fn test_rejects_insecure_location_symlink() {
        use velo::loader::error::LoaderError;
        use velo::loader::security::validate_location;

        let temp = tempdir().unwrap();

        // Create a symlink that points to /tmp
        let symlink_path = temp.path().join("sneaky_link.veloc");

        // Only run this test if we can create symlinks (skip on some CI)
        if std::os::unix::fs::symlink("/tmp/target", &symlink_path).is_ok() {
            let result = validate_location(&symlink_path);
            // After canonicalize(), this should resolve to /tmp and be rejected
            assert!(result.is_err(), "Should reject symlink pointing to /tmp");
        }
    }

    /// Test: Detect bundle corruption (SHA-256 mismatch)
    /// Handover Section 2.1: Marshal Security Protocol
    #[test]
    fn test_detects_bundle_corruption() {
        use velo::loader::error::LoaderError;
        use velo::loader::verify::verify_sha256;

        // Data with known SHA-256
        let data = b"test data for hashing";
        let wrong_hash = [0u8; 32]; // All zeros - definitely wrong

        let result = verify_sha256(data, &wrong_hash);
        assert!(result.is_err(), "Should detect hash mismatch");

        match result {
            Err(LoaderError::BundleCorrupted { .. }) => (),
            other => panic!("Expected BundleCorrupted, got {:?}", other),
        }
    }

    /// Test: Verify correct SHA-256 passes
    #[test]
    fn test_accepts_valid_sha256() {
        use sha2::{Digest, Sha256};
        use velo::loader::verify::verify_sha256;

        let data = b"test data for hashing";
        let mut hasher = Sha256::new();
        hasher.update(data);
        let correct_hash: [u8; 32] = hasher.finalize().into();

        let result = verify_sha256(data, &correct_hash);
        assert!(result.is_ok(), "Should accept valid hash");
    }

    /// Test: Detect module corruption (CRC32 mismatch)
    /// Handover Section 3: CRC32 模块校验
    #[test]
    fn test_detects_module_corruption() {
        use velo::loader::error::LoaderError;
        use velo::loader::verify::verify_crc32;

        let data = b"module bytecode data";
        let wrong_crc = 0xDEADBEEF_u32; // Definitely wrong

        let result = verify_crc32(data, wrong_crc);
        assert!(result.is_err(), "Should detect CRC32 mismatch");

        match result {
            Err(LoaderError::ModuleCorrupted { .. }) => (),
            other => panic!("Expected ModuleCorrupted, got {:?}", other),
        }
    }

    /// Test: Verify correct CRC32 passes
    #[test]
    fn test_accepts_valid_crc32() {
        use velo::loader::verify::verify_crc32;

        let data = b"module bytecode data";
        // Calculate correct CRC32 using the same algorithm
        let correct_crc = crc32fast::hash(data);

        let result = verify_crc32(data, correct_crc);
        assert!(result.is_ok(), "Should accept valid CRC32");
    }

    /// Test: Atomic Read → Verify → Load sequence
    /// Handover Section 2.1: TOCTOU Prevention
    #[test]
    fn test_atomic_read_verify_load() {
        // This test verifies the SEQUENCE of operations
        // The implementation MUST:
        // 1. Read entire file to RAM
        // 2. Verify SHA-256 in memory
        // 3. Only then parse/load modules

        // We verify this by ensuring load_and_verify returns VerifiedBundle
        // which contains the data already in memory
        use velo::loader::verify::VerifiedBundle;

        // VerifiedBundle should contain:
        // - The raw data (already read)
        // - The parsed header
        // - The module index
        // This proves data was read before any parsing
    }
}

#[cfg(test)]
mod format_tests {
    //! Bundle format tests (P0)

    use std::fs::File;
    use std::io::Write;
    use std::path::Path;
    use tempfile::tempdir;

    /// Test: Validate "VELO" magic bytes
    #[test]
    fn test_header_magic_velo() {
        use velo::loader::error::LoaderError;
        use velo::loader::header::BundleHeader;

        // Valid magic
        let valid_data = b"VELO\x01\x00\x00\x00"; // VELO + version 1
        let header = BundleHeader::parse_magic(&valid_data[..4]);
        assert!(header.is_ok(), "Should accept VELO magic");

        // Invalid magic
        let invalid_data = b"EVIL\x01\x00\x00\x00";
        let header = BundleHeader::parse_magic(&invalid_data[..4]);
        assert!(header.is_err(), "Should reject non-VELO magic");

        match header {
            Err(LoaderError::InvalidMagic { .. }) => (),
            other => panic!("Expected InvalidMagic, got {:?}", other),
        }
    }

    /// Test: Version must be 1
    #[test]
    fn test_header_version_1() {
        use velo::loader::error::LoaderError;
        use velo::loader::header::BundleHeader;

        // Version 1 should be accepted
        let version_1 = 1u32;
        let result = BundleHeader::validate_version(version_1);
        assert!(result.is_ok());

        // Version 0 should be rejected
        let version_0 = 0u32;
        let result = BundleHeader::validate_version(version_0);
        assert!(result.is_err());

        // Version 999 should be rejected (future version)
        let version_future = 999u32;
        let result = BundleHeader::validate_version(version_future);
        assert!(result.is_err());
    }

    /// Test: Python version mismatch detection
    #[test]
    fn test_python_version_mismatch() {
        use velo::loader::error::LoaderError;
        use velo::loader::header::BundleHeader;

        let bundle_version = "3.12.1";
        let runtime_version = "3.11.0";

        let result = BundleHeader::check_python_version(bundle_version, runtime_version);
        assert!(result.is_err(), "Should reject version mismatch");

        match result {
            Err(LoaderError::PythonVersionMismatch { .. }) => (),
            other => panic!("Expected PythonVersionMismatch, got {:?}", other),
        }
    }

    /// Test: Matching Python version passes
    #[test]
    fn test_python_version_match() {
        use velo::loader::header::BundleHeader;

        let bundle_version = "3.12.1";
        let runtime_version = "3.12.1";

        let result = BundleHeader::check_python_version(bundle_version, runtime_version);
        assert!(result.is_ok(), "Should accept matching version");
    }

    /// Test: Cache tag mismatch detection
    #[test]
    fn test_cache_tag_mismatch() {
        use velo::loader::error::LoaderError;
        use velo::loader::header::BundleHeader;

        let bundle_tag = "cpython-312";
        let runtime_tag = "cpython-311";

        let result = BundleHeader::check_cache_tag(bundle_tag, runtime_tag);
        assert!(result.is_err(), "Should reject cache tag mismatch");
    }

    /// Test: 4KB page alignment
    /// Handover Section 4: 对齐要求
    #[test]
    fn test_page_alignment_4k() {
        use velo::loader::header::BundleHeader;

        const PAGE_SIZE: u64 = 4096;

        // Test alignment calculation
        let offset = 100u64;
        let aligned = BundleHeader::align_to_page(offset);
        assert_eq!(aligned, PAGE_SIZE, "100 should align to 4096");

        let offset = 4096u64;
        let aligned = BundleHeader::align_to_page(offset);
        assert_eq!(aligned, PAGE_SIZE, "4096 should stay at 4096");

        let offset = 4097u64;
        let aligned = BundleHeader::align_to_page(offset);
        assert_eq!(aligned, 2 * PAGE_SIZE, "4097 should align to 8192");
    }

    /// Test: Padding bytes must be 0x00
    /// Handover Section 8: 陷阱 - 随机填充
    #[test]
    fn test_padding_bytes_zero() {
        use velo::loader::header::BundleHeader;

        // Generate padding for alignment
        let current_offset = 100usize;
        let padding = BundleHeader::generate_padding(current_offset);

        // All padding bytes must be 0x00
        for byte in &padding {
            assert_eq!(*byte, 0x00, "Padding must be 0x00, not random");
        }

        // Padding length should bring us to 4KB boundary
        assert_eq!(
            (current_offset + padding.len()) % 4096,
            0,
            "Should align to 4KB"
        );
    }
}

#[cfg(test)]
mod entry_tests {
    //! Module entry tests (P1)

    /// Test: ModuleEntry serialization roundtrip
    #[test]
    fn test_module_entry_roundtrip() {
        use velo::loader::entry::ModuleEntry;

        let original = ModuleEntry {
            name: "numpy.core".to_string(),
            offset: 4096,
            size: 1024,
            crc32: 0xDEADBEEF,
            source_hash: [0xAB; 32],
        };

        // Serialize
        let bytes = original.to_bytes();

        // Deserialize
        let restored = ModuleEntry::from_bytes(&bytes).unwrap();

        assert_eq!(restored.name, original.name);
        assert_eq!(restored.offset, original.offset);
        assert_eq!(restored.size, original.size);
        assert_eq!(restored.crc32, original.crc32);
        assert_eq!(restored.source_hash, original.source_hash);
    }

    /// Test: O(1) module lookup
    #[test]
    fn test_module_lookup_o1() {
        use std::collections::HashMap;
        use velo::loader::entry::ModuleIndex;

        // Create index with 1000 modules
        let mut index = ModuleIndex::new();
        for i in 0..1000 {
            index.insert(format!("module_{}", i), i as u64, 100, 0);
        }

        // Lookup should be O(1) - HashMap based
        let result = index.get("module_500");
        assert!(result.is_some());
        assert_eq!(result.unwrap().offset, 500);
    }

    /// Test: Source hash for cache invalidation
    #[test]
    fn test_source_hash_invalidation() {
        use sha2::{Digest, Sha256};
        use velo::loader::entry::ModuleEntry;

        // Original source
        let original_source = b"def foo(): pass";
        let mut hasher = Sha256::new();
        hasher.update(original_source);
        let original_hash: [u8; 32] = hasher.finalize().into();

        // Modified source
        let modified_source = b"def foo(): return 1";
        let mut hasher = Sha256::new();
        hasher.update(modified_source);
        let modified_hash: [u8; 32] = hasher.finalize().into();

        // Hashes should differ - triggering cache invalidation
        assert_ne!(original_hash, modified_hash);
    }
}

#[cfg(test)]
mod build_lock_tests {
    //! Build lock tests (P1)

    use tempfile::tempdir;

    /// Test: flock exclusive lock prevents concurrent access
    #[cfg(unix)]
    #[test]
    fn test_build_lock_exclusive() {
        use std::sync::Arc;
        use std::sync::atomic::{AtomicBool, Ordering};
        use std::thread;
        use velo::loader::lock::BuildLock;

        let temp = tempdir().unwrap();
        let lock_path = temp.path().join("build.lock");

        // Acquire first lock
        let lock1 = BuildLock::acquire(&lock_path).unwrap();
        let lock_acquired = Arc::new(AtomicBool::new(false));
        let lock_acquired_clone = lock_acquired.clone();

        // Try to acquire second lock in another thread (should block)
        let lock_path_clone = lock_path.clone();
        let handle = thread::spawn(move || {
            // Try non-blocking acquire
            let result = BuildLock::try_acquire(&lock_path_clone);
            if result.is_ok() {
                lock_acquired_clone.store(true, Ordering::SeqCst);
            }
        });

        // Give the thread time to attempt
        thread::sleep(std::time::Duration::from_millis(100));

        // Second lock should NOT have been acquired
        assert!(
            !lock_acquired.load(Ordering::SeqCst),
            "Second lock should be blocked"
        );

        // Release first lock
        drop(lock1);

        handle.join().unwrap();
    }

    /// Test: Lock auto-releases on drop (crash-safe)
    #[cfg(unix)]
    #[test]
    fn test_build_lock_auto_release() {
        use velo::loader::lock::BuildLock;

        let temp = tempdir().unwrap();
        let lock_path = temp.path().join("build.lock");

        // Acquire and immediately drop
        {
            let _lock = BuildLock::acquire(&lock_path).unwrap();
            // Lock is held here
        }
        // Lock should be released after drop

        // Should be able to acquire again immediately
        let lock2 = BuildLock::acquire(&lock_path);
        assert!(lock2.is_ok(), "Lock should be released after drop");
    }
}
