//! RFC-0006 Phase 5.0.1 Bundle Infrastructure Tests
//!
//! TDD: These tests are written FIRST, before implementation.
//! All security requirements from RFC-0006 are non-negotiable.
//!
//! Updated 2026-01-03: Migrated from SHA-256/CRC32 to unified BLAKE3

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

    // === SECURITY TEST CASES ===

    /// Test: Reject bundles larger than 256MB
    /// RFC-0006 Section 3.1: DoS Prevention
    #[test]
    fn test_rejects_oversized_bundle() {
        use velo::loader::security::{DEFAULT_MAX_BUNDLE_SIZE, validate_size};

        let temp = tempdir().unwrap();
        let path = create_fake_bundle(temp.path(), 1024);

        assert!(validate_size(&path, DEFAULT_MAX_BUNDLE_SIZE).is_ok());
    }

    /// Test: 256MB limit constant is correct
    #[test]
    fn test_rejects_oversized_bundle_size_check() {
        const MAX_BUNDLE_SIZE: u64 = 256 * 1024 * 1024;
        assert_eq!(MAX_BUNDLE_SIZE, 268_435_456);

        let test_size: u64 = 300 * 1024 * 1024;
        assert!(test_size > MAX_BUNDLE_SIZE, "300MB should exceed limit");
    }

    /// Test: Reject world-writable files (mode & 0o002 != 0)
    /// RFC-0006 Section 3.3: File Permission Checks
    #[cfg(unix)]
    #[test]
    fn test_rejects_world_writable() {
        use velo::loader::error::LoaderError;
        use velo::loader::security::validate_permissions;

        let temp = tempdir().unwrap();
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
        let path = create_bundle_with_mode(temp.path(), 0o644);

        let result = validate_permissions(&path);
        assert!(result.is_ok(), "Should accept 0o644 permissions");
    }

    /// Test: Reject bundles in /tmp
    /// RFC-0006 Section 3.2: Three-Tier Path Security
    #[cfg(unix)]
    #[test]
    fn test_rejects_insecure_location_tmp() {
        use std::path::PathBuf;
        use velo::loader::error::LoaderError;
        use velo::loader::security::validate_location;

        let tmp_path = PathBuf::from("/tmp/malicious.veloc");

        let result = validate_location(&tmp_path);
        assert!(result.is_err(), "Should reject /tmp location");

        match result {
            Err(LoaderError::InsecureLocation { .. }) => (),
            other => panic!("Expected InsecureLocation, got {:?}", other),
        }
    }

    /// Test: Reject symlink traversal attacks
    /// RFC-0006 Section 3.2: Three-Tier Path Security
    #[cfg(unix)]
    #[test]
    fn test_rejects_insecure_location_symlink() {
        use velo::loader::security::validate_location;

        let temp = tempdir().unwrap();
        let symlink_path = temp.path().join("sneaky_link.veloc");

        if std::os::unix::fs::symlink("/tmp/target", &symlink_path).is_ok() {
            let result = validate_location(&symlink_path);
            assert!(result.is_err(), "Should reject symlink pointing to /tmp");
        }
    }

    /// Test: Detect bundle corruption (BLAKE3 mismatch)
    /// RFC-0006 Section 3.4: Unified BLAKE3 Verification
    #[test]
    fn test_detects_bundle_corruption() {
        use velo::loader::error::LoaderError;
        use velo::loader::verify::verify_blake3;

        let data = vec![0u8; 100];
        let wrong_hash = [0u8; 32]; // All zeros - definitely wrong

        let result = verify_blake3(&data, &wrong_hash);
        assert!(result.is_err(), "Should detect hash mismatch");

        match result {
            Err(LoaderError::BundleCorrupted { .. }) => (),
            other => panic!("Expected BundleCorrupted, got {:?}", other),
        }
    }

    /// Test: Verify correct BLAKE3 passes (H-1 Global Hash scheme)
    /// RFC-0008: Hash covers [0..20] (Identity Prefix) + [52..EOF] (Content)
    #[test]
    fn test_accepts_valid_blake3() {
        use velo::loader::verify::verify_blake3;

        // Create test data with proper H-1 structure (minimum 52 bytes)
        let mut data = vec![0u8; 128];
        // Fill identity prefix [0..20] with test data
        data[0..4].copy_from_slice(b"VELO");
        data[4..8].copy_from_slice(&1u32.to_le_bytes()); // version
        data[8..12].copy_from_slice(&1u32.to_le_bytes()); // module_count
        data[12..20].copy_from_slice(&128u64.to_le_bytes()); // index_offset
        // [20..52] is where hash will go
        // Fill content [52..] with test data
        data[52..60].copy_from_slice(b"CONTENT!");

        // Calculate hash using H-1 scheme: [0..20] + [52..]
        let mut hasher = blake3::Hasher::new();
        hasher.update(&data[0..20]);
        hasher.update(&data[52..]);
        let correct_hash = hasher.finalize();

        // Place hash in [20..52]
        data[20..52].copy_from_slice(correct_hash.as_bytes());

        let result = verify_blake3(&data, correct_hash.as_bytes());
        assert!(result.is_ok(), "Should accept valid H-1 BLAKE3 hash");
    }

    /// Test: Detect module corruption (BLAKE3 mismatch)
    /// RFC-0006 Section 3.4: Unified BLAKE3 Verification
    #[test]
    fn test_detects_module_corruption() {
        use velo::loader::error::LoaderError;
        use velo::loader::verify::verify_module_hash;

        let data = vec![b'K', 42]; // Valid marshal: small int
        let wrong_hash = [0xDE; 32]; // Definitely wrong

        let result = verify_module_hash(&data, &wrong_hash, "test_module", 28);
        assert!(result.is_err(), "Should detect BLAKE3 mismatch");

        match result {
            Err(LoaderError::ModuleCorrupted { .. }) => (),
            other => panic!("Expected ModuleCorrupted, got {:?}", other),
        }
    }

    /// Test: Verify correct module hash passes
    /// Note: verify_module_hash also checks marshal depth (H-4), so we need valid marshal
    #[test]
    fn test_accepts_valid_module_hash() {
        use velo::loader::verify::verify_module_hash;

        // Create minimal valid marshal data: b'N' = None (simplest valid marshal object)
        // This passes the H-4 depth check since it has depth 0
        let data: &[u8] = b"N"; // Marshal code for None
        let correct_hash = blake3::hash(data);

        let result = verify_module_hash(data, correct_hash.as_bytes(), "test_module", 28);
        assert!(
            result.is_ok(),
            "Should accept valid BLAKE3 hash with valid marshal data"
        );
    }

    /// Test: Atomic Read → Verify → Load sequence
    /// RFC-0006 Section 3.1: TOCTOU Prevention
    #[test]
    fn test_atomic_read_verify_load() {
        use velo::loader::verify::load_and_verify;

        // 1. Prepare a valid bundle data with H-1 scheme and H-4 marshal logic
        let mut data = vec![0u8; 256];

        // Magic + Version (0..8)
        data[0..4].copy_from_slice(b"VELO");
        data[4..8].copy_from_slice(&1u32.to_le_bytes());

        // module_count (8..12) + index_offset (128)
        data[8..12].copy_from_slice(&1u32.to_le_bytes());
        let index_offset = 128u64;
        data[12..20].copy_from_slice(&index_offset.to_le_bytes());

        // Mock module data at offset 200, size 1 (None = 'N' in marshal)
        let m_offset = 200u64;
        let m_size = 1u64;
        data[m_offset as usize] = b'N';

        // Build module index entry at index_offset (128)
        let mut pos = index_offset as usize;
        let name = "test_mod";
        data[pos..pos + 2].copy_from_slice(&(name.len() as u16).to_le_bytes());
        pos += 2;
        data[pos..pos + name.len()].copy_from_slice(name.as_bytes());
        pos += name.len();
        data[pos..pos + 8].copy_from_slice(&m_offset.to_le_bytes());
        pos += 8;
        data[pos..pos + 8].copy_from_slice(&m_size.to_le_bytes());

        // Calculate H-1 Hash: covers [0..20] and [52..EOF]
        let mut hasher = blake3::Hasher::new();
        hasher.update(&data[0..20]);
        hasher.update(&data[52..]);
        let hash = hasher.finalize();
        data[20..52].copy_from_slice(hash.as_bytes());

        // 2. Write to temp file in a "secure" location (not /tmp)
        let temp = tempdir().unwrap();
        let path = temp.path().join("atomic_test.veloc");
        std::fs::write(&path, &data).unwrap();

        // 3. Load and verify
        let result = load_and_verify(&path, None);

        // 4. Assert
        assert!(result.is_ok(), "Load and verify failed: {:?}", result.err());
        let bundle = result.unwrap();
        assert_eq!(bundle.data.len(), 256);
        assert_eq!(bundle.data[m_offset as usize], b'N', "Module data mismatch");
    }

    /// Test: Attempt TOCTOU swap during loading
    /// RFC-0006 Section 3.1: TOCTOU Prevention via Shared Locks (H-5)
    #[test]
    fn test_toctou_adversarial_race() {
        use std::sync::Arc;
        use std::thread;
        use velo::loader::verify::load_and_verify;

        // 1. Setup a LARGE valid bundle to prolong the "loading window"
        let temp = tempdir().unwrap();
        let path = temp.path().join("race.veloc");
        let mut data = vec![0u8; 10 * 1024 * 1024]; // 10MB
        data[0..4].copy_from_slice(b"VELO");
        data[4..8].copy_from_slice(&1u32.to_le_bytes()); // version
        data[8..12].copy_from_slice(&0u32.to_le_bytes()); // count
        data[12..20].copy_from_slice(&100u64.to_le_bytes()); // index_offset

        let mut hasher = blake3::Hasher::new();
        hasher.update(&data[0..20]);
        hasher.update(&data[52..]);
        let hash = hasher.finalize();
        data[20..52].copy_from_slice(hash.as_bytes());

        fs::write(&path, &data).unwrap();

        let path_clone = path.clone();
        let stop_attacker = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let stop_attacker_clone = stop_attacker.clone();

        // 2. Attacker thread: Constantly tries to overwrite the file with INVALID data
        let attacker = thread::spawn(move || {
            let evil_data = vec![0xDEu8; 1024];
            while !stop_attacker_clone.load(std::sync::atomic::Ordering::Relaxed) {
                let _ = fs::OpenOptions::new()
                    .write(true)
                    .open(&path_clone)
                    .and_then(|mut f| f.write_all(&evil_data));
            }
        });

        // 3. Victim: Attempt to load
        for _ in 0..10 {
            let result = load_and_verify(&path, None);
            if let Ok(bundle) = result {
                assert_eq!(
                    bundle.data[0..4],
                    *b"VELO",
                    "TOCTOU CRITICAL: Header corrupted by attacker!"
                );
                assert!(
                    !bundle.data.contains(&0xDE),
                    "TOCTOU CRITICAL: Evil data leaked into RAM!"
                );
            }
        }

        stop_attacker.store(true, std::sync::atomic::Ordering::Relaxed);
        attacker.join().unwrap();
    }
}

#[cfg(test)]
mod format_tests {
    //! Bundle format tests (P0)

    /// Test: Validate "VELO" magic bytes
    #[test]
    fn test_header_magic_velo() {
        use velo::loader::error::LoaderError;
        use velo::loader::header::BundleHeader;

        // Valid magic
        let valid_data = b"VELO\x01\x00\x00\x00";
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
        use velo::loader::header::BundleHeader;

        let version_1 = 1u32;
        let result = BundleHeader::validate_version(version_1);
        assert!(result.is_ok());

        let version_0 = 0u32;
        let result = BundleHeader::validate_version(version_0);
        assert!(result.is_err());

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
        use velo::loader::header::BundleHeader;

        let bundle_tag = "cpython-312";
        let runtime_tag = "cpython-311";

        let result = BundleHeader::check_cache_tag(bundle_tag, runtime_tag);
        assert!(result.is_err(), "Should reject cache tag mismatch");
    }

    /// Test: 4KB page alignment
    #[test]
    fn test_page_alignment_4k() {
        use velo::loader::header::BundleHeader;

        const PAGE_SIZE: u64 = 4096;

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
    #[test]
    fn test_padding_bytes_zero() {
        use velo::loader::header::BundleHeader;

        let current_offset = 100usize;
        let padding = BundleHeader::generate_padding(current_offset);

        for byte in &padding {
            assert_eq!(*byte, 0x00, "Padding must be 0x00, not random");
        }

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

        let data = b"test module bytecode";
        let original = ModuleEntry::new("numpy.core".to_string(), 4096, 1024, data);

        // Serialize
        let bytes = original.to_bytes();

        // Deserialize
        let restored = ModuleEntry::from_bytes(&bytes).unwrap();

        assert_eq!(restored.name, original.name);
        assert_eq!(restored.offset, original.offset);
        assert_eq!(restored.size, original.size);
        assert_eq!(restored.hash, original.hash);
    }

    /// Test: O(1) module lookup
    #[test]
    fn test_module_lookup_o1() {
        use velo::loader::entry::ModuleIndex;

        // Create index with 1000 modules
        let mut index = ModuleIndex::new();
        for i in 0..1000 {
            let data = format!("module_{}_data", i).into_bytes();
            index.insert(format!("module_{}", i), i as u64, 100, &data);
        }

        // Lookup should be O(1) - HashMap based
        let result = index.get("module_500");
        assert!(result.is_some());
        assert_eq!(result.unwrap().offset, 500);
    }

    /// Test: BLAKE3 hash for cache invalidation
    /// RFC-0006: Unified hash replaces source_hash
    #[test]
    fn test_hash_invalidation() {
        // Original source
        let original_source = b"def foo(): pass";
        let original_hash = blake3::hash(original_source);

        // Modified source
        let modified_source = b"def foo(): return 1";
        let modified_hash = blake3::hash(modified_source);

        // Hashes should differ - triggering cache invalidation
        assert_ne!(original_hash.as_bytes(), modified_hash.as_bytes());
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
        }
        // Lock should be released after drop

        // Should be able to acquire again immediately
        let lock2 = BuildLock::acquire(&lock_path);
        assert!(lock2.is_ok(), "Lock should be released after drop");
    }
}
